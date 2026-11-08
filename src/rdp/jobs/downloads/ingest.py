"""下载数据集的 worker 入库入口（领域层，M2-05、ADR 0006/0008）。

手动预览只读，确认后同根不覆盖改名，再复用 M1 写入流水线。移动恢复记录位于状态目录，
不改来源格式、不改 M1 契约；文件系统隔离、JSON、互斥和进程回收均复用现有能力或标准库。
"""

import gzip
import json
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime
from functools import partial
from pathlib import Path
from typing import cast

from rdp.accounts.types import Role
from rdp.infra.config import StorageRootConfig
from rdp.infra.db.connection import session_scope
from rdp.infra.diagnostics import DefectError
from rdp.infra.state import StatePaths
from rdp.infra.storage import StorageAccessChecker
from rdp.jobs.datasets.types import JsonObject
from rdp.jobs.downloads._ingest_access import access, check_files, check_root, committed
from rdp.jobs.downloads._ingest_build import CreationFacts, build_creation
from rdp.jobs.downloads._ingest_receipt import Receipt, atomic_bytes, atomic_json, read_receipt
from rdp.jobs.downloads.coordination import download_guard
from rdp.jobs.downloads.ingest_models import (
    INGEST_APPLY_TYPE,
    INGEST_PREVIEW_TYPE,
    IngestParameters,
)
from rdp.jobs.downloads.job import DownloadParameters, request_from_parameters
from rdp.jobs.downloads.plan import (
    RepositoryRevision,
    _target_parts,  # pyright: ignore[reportPrivateUsage]  # 理由：工单要求复用现有 target_subdir 规则，保持旧契约。
    staging_path,
)
from rdp.jobs.execution import ExecutionContext
from rdp.jobs.navwrite._create_plan import image
from rdp.jobs.navwrite._create_read import Target
from rdp.jobs.navwrite._ingest_creation import with_ingest_date
from rdp.jobs.navwrite.create_models import FormatEntrySelection, validate_entry_name
from rdp.jobs.navwrite.errors import nav_input_error
from rdp.jobs.navwrite.jobs import NavApplyParameters, PreviewBuild, run_preview
from rdp.jobs.navwrite.jsonio import dump_navigation_json
from rdp.jobs.navwrite.marker import is_navigation_write_blocked
from rdp.jobs.navwrite.models import NavPreview, Step, WriteFileStep
from rdp.jobs.navwrite.pipeline import NavWriteDependencies, run_write_plan
from rdp.jobs.navwrite.previews import preview_path, read_preview
from rdp.jobs.navwrite.provenance import ActorStamp
from rdp.jobs.outcome import JobOutcome
from rdp.jobs.records import find_job
from rdp.jobs.registry import JobDefinition
from rdp.jobs.types import ExecutionMode, JobProgress, JobRecord, JobState, RecoveryMode


def _time(value: datetime | None) -> str | None:
    """领域时间已由数据库层统一成 UTC；保持来源格式的秒级 Z 文本。"""
    return value.strftime("%Y-%m-%dT%H:%M:%SZ") if value is not None else None


def _download(deps: NavWriteDependencies, job_id: int) -> tuple[JobRecord, Receipt]:
    """不从客户端接收仓库身份，只读取成功下载和它实际执行的固定回执。"""
    with session_scope(deps.rescan.engine, read_only=True) as session:
        record = find_job(session, job_id)
    if (
        record.type_name != "download"
        or record.state is not JobState.COMPLETED
        or record.summary is None
        or record.summary.outcome is not JobOutcome.SUCCEEDED
        or record.parameters.get("repo_type") != "dataset"
    ):
        raise nav_input_error(
            "DOWNLOAD_INGEST",
            "仅成功的数据集下载可入库",
            objects=(("download_job_id", str(job_id)),),
        )
    receipt = read_receipt(deps.paths, job_id)
    if DownloadParameters.model_validate(record.parameters) != receipt.parameters:
        raise nav_input_error("DOWNLOAD_INGEST", "下载回执与作业参数不一致")
    return record, receipt


def _paths(
    deps: NavWriteDependencies, receipt: Receipt, parameters: IngestParameters
) -> tuple[StorageRootConfig, str, str]:
    """解析同一可写根的安全相对路径；正式目录不能留在暂存或嵌入原目录。"""
    roots = [
        item
        for item in deps.rescan.roots
        if item.name == receipt.parameters.storage_root and item.writable
    ]
    if len(roots) != 1 or deps.rescan.storage is None:
        raise nav_input_error("DOWNLOAD_INGEST", "只允许已登记可写存储根")
    root = roots[0]
    request = request_from_parameters(receipt.parameters)
    revision = RepositoryRevision(receipt.commit, False, False, False)
    stage = str(staging_path(root, request, revision).relative_to(root.path))
    target = parameters.target_subdir or f"下载/{request.repo_id}@{receipt.commit[:12]}"
    parts = _target_parts(target)
    if parts[0] == "暂存":
        raise nav_input_error("DOWNLOAD_INGEST", "正式位置必须在暂存目录之外")
    return root, stage, "/".join(parts)


def build_ingest_preview(
    dependencies: NavWriteDependencies,
    parameters: IngestParameters,
    stamp: ActorStamp,
    *,
    checkpoint: Callable[[], None],
) -> PreviewBuild:
    """检查成功下载并构造正式位置的新数据集计划，不提前移动目录。

    Args:
        dependencies: worker 依赖，含绝对导航根、登记根与超时检查器。
        parameters: 正整数下载编号，以及可选安全名称、同根相对位置和格式选择。
        stamp: 当前预览提交人的可信 UTC 印记。
        checkpoint: 取消与停止检查点，检查前后调用。

    Returns:
        同一份 M1 创建计划和报告；参数中保存解析后的名字、位置和 14 项。

    Raises:
        InputError: 下载未成功、回执缺失、文件缺失或大小错误、不是 LeRobot、目标占用或输入不安全。
        ExternalError: 根离线、文件系统超时或导航读取失败。
        ConflictError: 构造期间导航层状态变化。
        JobCancelledError: 检查点收到取消。
        WorkerStoppingError: 检查点收到停止。
        DefectError: worker 缺存储检查器或依赖不一致。

    Side Effects:
        无（只读状态回执、作业、导航和存储；隔离子进程退出时回收）。

    Time Semantics:
        挂载检查采用登记预算；文件检查子进程最多 30 秒；不重新访问远端。
    """
    record, receipt = _download(dependencies, parameters.download_job_id)
    root, stage, target = _paths(dependencies, receipt, parameters)
    checker = dependencies.rescan.storage
    if checker is None:
        raise DefectError()
    check_root(root, checker, checkpoint)
    facts = check_files(dependencies.paths, parameters.download_job_id, root, stage, target)
    checkpoint()
    metadata = cast(JsonObject, facts["metadata"])
    version = validate_entry_name(str(metadata["codebase_version"]).removeprefix("v"))
    normalized = IngestParameters(
        download_job_id=parameters.download_job_id,
        dataset_name=parameters.dataset_name or receipt.parameters.repo_id.split("/")[-1],
        target_subdir=target,
        format_entries=parameters.format_entries
        if parameters.format_entries is not None
        else (FormatEntrySelection(format="lerobot", version=version),),
    )
    build = build_creation(
        dependencies,
        normalized,
        CreationFacts(
            receipt,
            facts,
            Target(str(root.path / target), "directory", "lerobot", version, "meta_info"),
            stamp,
            (_time(record.started_at), _time(record.ended_at)),
        ),
        checkpoint,
    )
    return replace(
        build,
        parameters={
            **build.parameters,
            "move": {
                "storage_root": root.name,
                "stage": stage,
                "target": target,
                "dev": facts["dev"],
                "ino": facts["ino"],
            },
        },
    )


def _execute_preview(deps: NavWriteDependencies | None, context: ExecutionContext) -> None:
    """由真实作业身份生成来源印记，保存 worker 的完整预览。"""
    if deps is None or not isinstance(context.parameters, IngestParameters):
        raise DefectError()
    with session_scope(deps.rescan.engine, read_only=True) as session:
        actor = find_job(session, context.job_id).submitted_by
    stamp = ActorStamp(
        kind="人工标注",
        account_id=actor.account_id,
        account_name=actor.name,
        at=_time(context.clock.now()) or "",
    )
    with download_guard(deps.paths.root, context):
        parameters = context.parameters
        run_preview(
            context,
            deps,
            lambda checkpoint: build_ingest_preview(deps, parameters, stamp, checkpoint=checkpoint),
        )
    context.reporter.report(
        JobProgress(
            stage_index=1,
            stage_count=1,
            stage_name="入库预览",
            done=1,
            total=1,
            unit="预览",
            total_items=1,
            failed_items=0,
            warning_count=0,
        )
    )


def _finalize(preview: NavPreview, context: ExecutionContext, started_at: str) -> NavPreview:
    """仅补执行时才能知道的入库编号和核验时刻，业务计划和用户选择保持原样。"""
    steps: list[Step] = []
    for step in preview.plan.steps:
        if step.op == "write_file" and step.path.endswith("/来源.json"):
            payload = cast(JsonObject, json.loads(step.after_content))
            lineage = cast(list[JsonObject], payload["lineage"])[0]
            values = cast(JsonObject, lineage["parameters"])
            values.update(
                {"ingest_job_id": context.job_id, "ingest_started_at": _time(context.clock.now())}
            )
            lineage["job_id"] = context.job_id
            lineage["started_at"] = started_at
            # 终点是数据目录已就位、准备写入导航的时刻；来源文件随同一次事务提交。
            lineage["finished_at"] = _time(context.clock.now())
            cast(JsonObject, lineage["ingest_check"])["checked_at"] = _time(context.clock.now())
            content = dump_navigation_json(payload)
            step = WriteFileStep(
                path=step.path,
                before=step.before,
                after=image(content),
                after_content=content.decode(),
            )
        steps.append(step)
    return with_ingest_date(
        preview.model_copy(
            update={"plan": preview.plan.model_copy(update={"steps": tuple(steps)})}
        ),
        context.clock.now(),
    )


def _rollback_move(
    deps: NavWriteDependencies,
    job_id: int,
    locations: tuple[StorageRootConfig, str, str],
    marker: Path,
) -> None:
    """导航已提交就保留正式目录；回滚失败则保留移动意图与目录供启动恢复。"""
    if not committed(deps.paths, job_id):
        with session_scope(deps.rescan.engine, read_only=True) as session:
            blocked = is_navigation_write_blocked(session)
        if blocked:
            from rdp.jobs.navwrite.errors import nav_external_error

            raise nav_external_error(
                "DOWNLOAD_INGEST_RECOVERY", "导航层回滚失败，保留正式目录和移动记录"
            )
        root, stage, target = locations
        access("restore", root, stage, target, marker)
    marker.unlink()


def execute_ingest_apply(
    dependencies: NavWriteDependencies | None, context: ExecutionContext
) -> None:
    """不覆盖改名暂存目录并执行已确认的 M1 创建计划，写失败则退回目录。

    Args:
        dependencies: worker 写入依赖；Web 登记时为 None。
        context: NavApplyParameters 的 FRESH 上下文；编号为实际入库作业编号。

    Returns:
        无；作业结果仍由框架按进度和诊断计算。

    Raises:
        DefectError: 缺依赖、上下文参数或执行模式不匹配。
        InputError: 预览未成功、回执不合约、目录被占用或清单检查失败。
        ExternalError: 存储超时、改名或导航写入失败；恢复记录保留供启动恢复。
        ConflictError: M1 写锁内发现预览已过期。
        JobCancelledError: 等锁或检查时取消。
        WorkerStoppingError: worker 停止；已移动目录有持久恢复记录。

    Side Effects:
        只在同一登记可写根内移动新数据，M1 负责导航日志、回滚、索引和统计。
        导航写入失败时不覆盖地退回暂存；已提交的导航不因后续失败退回。

    Time Semantics:
        暂存锁最多等待 30 秒，移动和恢复各最多 30 秒；导航锁预算沿用 M1。
        血缘起点为执行开始，终点为目录就位、准备提交导航的 UTC 时刻。
    """
    if (
        dependencies is None
        or not isinstance(context.parameters, NavApplyParameters)
        or context.mode is not ExecutionMode.FRESH
    ):
        raise DefectError()
    deps = dependencies
    started_at = _time(context.clock.now()) or ""
    identifier = context.parameters.preview_job_id
    with download_guard(deps.paths.root, context):
        preview = read_preview(deps.paths, identifier)
        with session_scope(deps.rescan.engine, read_only=True) as session:
            record = find_job(session, identifier)
        if (
            record.type_name != INGEST_PREVIEW_TYPE
            or record.state is not JobState.COMPLETED
            or record.summary is None
            or record.summary.outcome is not JobOutcome.SUCCEEDED
        ):
            problem = nav_input_error("DOWNLOAD_INGEST", "请先完成入库预览")
            raise problem
        parameters = IngestParameters.model_validate(preview.parameters["input"])
        _, receipt = _download(deps, parameters.download_job_id)
        root, stage, target = _paths(deps, receipt, parameters)
        checker = deps.rescan.storage
        if checker is None:
            raise DefectError()
        check_root(root, checker, context.reporter.check_cancelled)
        facts = check_files(deps.paths, parameters.download_job_id, root, stage, target)
        context.reporter.check_cancelled()
        marker = deps.paths.root / "download-ingest-moves" / f"{context.job_id}.json"
        move = cast(JsonObject, preview.parameters["move"])
        if (facts["dev"], facts["ino"]) != (move["dev"], move["ino"]):
            problem = nav_input_error("DOWNLOAD_INGEST", "暂存目录在预览后被替换，请重新预览")
            raise problem
        atomic_json(marker, json.dumps(move))
        try:
            access("move", root, stage, target, marker)
            # 只补执行编号和起止时间；用户确认的业务计划不重新计算。
            finalized = _finalize(preview, context, started_at)
            atomic_bytes(
                preview_path(deps.paths, identifier),
                gzip.compress(finalized.model_dump_json().encode(), mtime=0),
            )
            run_write_plan(context, deps, identifier)
        except BaseException:
            _rollback_move(deps, context.job_id, (root, stage, target), marker)
            raise
        marker.unlink()


def build_ingest_definitions(
    dependencies: NavWriteDependencies | None,
) -> tuple[JobDefinition, ...]:
    """登记下载入库的只读预览和受导航写门禁保护的确认作业。

    Args:
        dependencies: worker 写入依赖，Web 为 None，仅登记参数校验。

    Returns:
        两个定义：预览 RESTART，确认 INTERRUPT；确认标记 writes_navigation=True。

    Raises:
        无。

    Side Effects:
        无；不访问配置、数据库或存储。

    Time Semantics:
        启动登记时构造，不自动执行。
    """
    return (
        JobDefinition(
            INGEST_PREVIEW_TYPE,
            "预览下载入库",
            IngestParameters,
            RecoveryMode.RESTART,
            partial(_execute_preview, dependencies),
            submission_role=Role.MEMBER,
        ),
        JobDefinition(
            INGEST_APPLY_TYPE,
            "下载入库",
            NavApplyParameters,
            RecoveryMode.INTERRUPT,
            partial(execute_ingest_apply, dependencies),
            submission_role=Role.ADMINISTRATOR,
            writes_navigation=True,
        ),
    )


def recover_ingest_moves(
    paths: StatePaths, roots: tuple[StorageRootConfig, ...], checker: StorageAccessChecker
) -> None:
    """在 M1 导航恢复之后恢复尚未完成的下载改名。

    Args:
        paths: worker 状态目录，含移动意图与 M1 永久变更记录。
        roots: 当前登记的存储根，不接受历史记录授权新增写路径。
        checker: 当前挂载身份与可写许可检查器。

    Returns:
        无；全部移动记录已经安全收尾。

    Raises:
        InputError: 历史根不再登记为可写或恢复内容不合约。
        ExternalError: 根离线、恢复超时或目录身份冲突；保留记录并阻止 worker 开始领取。

    Side Effects:
        未提交的目录退回暂存；已提交的目录保留正式位置；成功删除对应移动记录。

    Time Semantics:
        启动时单次运行，各次文件系统操作最多 30 秒；必须先完成 M1 导航日志恢复。
    """
    for marker in sorted((paths.root / "download-ingest-moves").glob("*.json")):
        if not committed(paths, int(marker.stem)):
            move = cast(JsonObject, json.loads(marker.read_bytes()))
            matching = [
                root for root in roots if root.name == move["storage_root"] and root.writable
            ]
            if len(matching) != 1:
                problem = nav_input_error("DOWNLOAD_INGEST_RECOVERY", "恢复所需存储根不再可写")
                raise problem
            root = matching[0]
            check_root(root, checker, lambda: None)
            access("restore", root, str(move["stage"]), str(move["target"]), marker)
        marker.unlink()
