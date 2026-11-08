"""转换检查与入库 worker 作业；复用 M1 预览、写入事务和 M2 不覆盖移动恢复。

检查只写报告和预览，自动触发由作业终态事务完成；确认作业持暂存锁执行已保存计划。
"""

import gzip
import json
from functools import partial
from typing import cast

from rdp.accounts.types import Role
from rdp.infra.db.connection import session_scope
from rdp.infra.diagnostics import DefectError
from rdp.jobs.conversion import _ingest_build, _ingest_read
from rdp.jobs.conversion.check_models import CheckReport, IngestCheckResult
from rdp.jobs.conversion.ingest_models import APPLY_TYPE, CHECK_TYPE, ConversionIngestParameters
from rdp.jobs.datasets.types import JsonObject
from rdp.jobs.downloads._ingest_access import access, check_root
from rdp.jobs.downloads._ingest_receipt import atomic_bytes, atomic_json
from rdp.jobs.downloads.coordination import download_guard
from rdp.jobs.downloads.ingest import _rollback_move  # pyright: ignore[reportPrivateUsage] # 理由：复用M2已提交判定与回滚失败保留记录的恢复语义。
from rdp.jobs.execution import ExecutionContext
from rdp.jobs.navwrite._ingest_creation import with_ingest_date
from rdp.jobs.navwrite.errors import nav_input_error
from rdp.jobs.navwrite.jobs import NavApplyParameters, run_preview
from rdp.jobs.navwrite.pipeline import NavWriteDependencies, run_write_plan
from rdp.jobs.navwrite.previews import preview_path, read_preview
from rdp.jobs.outcome import JobOutcome
from rdp.jobs.records import find_job
from rdp.jobs.registry import JobDefinition
from rdp.jobs.types import JobProgress, JobState, RecoveryMode


def _execute_check(deps: NavWriteDependencies | None, context: ExecutionContext) -> None:
    """RESTART 重跑四层检查和预览；所有成功收尾使用同一份报告。"""
    if deps is None or not isinstance(context.parameters, ConversionIngestParameters):
        raise DefectError()
    parameters = context.parameters
    with download_guard(deps.paths.root, context):
        value = _ingest_read.conversion(deps, parameters.conversion_job_id)
        if deps.rescan.storage is None:
            raise DefectError()
        check_root(value.root, deps.rescan.storage, context.reporter.check_cancelled)
        facts = _ingest_read.inspect(value)
        facts["checked_at"] = context.clock.now().strftime("%Y-%m-%dT%H:%M:%SZ")
        report = CheckReport.model_validate(facts["report"])
        _report(context, facts, report, ready=False)
        ready = False
        if report.result != "不通过":
            preview = run_preview(
                context,
                deps,
                lambda checkpoint: _ingest_build.build(deps, parameters, value, facts, checkpoint),
            )
            ready = (
                parameters.automatic
                and report.result == "通过"
                and not preview.parameters["default_occupied"]
            )
        _report(context, facts, report, ready=ready)


def _report(
    context: ExecutionContext, facts: JsonObject, report: CheckReport, *, ready: bool
) -> None:
    """报告独立于导航预览是否成功；自动就绪只在计划保存后发布。"""
    if not isinstance(context.parameters, ConversionIngestParameters):
        raise DefectError()
    context.reporter.report(
        JobProgress(
            stage_index=1,
            stage_count=1,
            stage_name="入库检查",
            done=1,
            total=1,
            unit="产物",
            warning_count=report.warning_count,
            failed_items=int(report.result == "不通过"),
            total_items=1,
            ingest_check=IngestCheckResult(
                conversion_job_id=context.parameters.conversion_job_id,
                report=report,
                size_bytes=int(str(facts["size_bytes"]))
                if facts["size_bytes"] is not None
                else None,
                automatic_ready=ready,
            ),
        )
    )


def _execute_apply(deps: NavWriteDependencies | None, context: ExecutionContext) -> None:
    """在暂存锁内复核已确认预览，以M2持久移动记录覆盖整个导航事务。"""
    if deps is None or not isinstance(context.parameters, NavApplyParameters):
        raise DefectError()
    with download_guard(deps.paths.root, context):
        identifier = context.parameters.preview_job_id
        preview = read_preview(deps.paths, identifier)
        with session_scope(deps.rescan.engine, read_only=True) as session:
            record = find_job(session, identifier)
        if (
            record.type_name != CHECK_TYPE
            or record.state is not JobState.COMPLETED
            or record.summary is None
            or record.summary.outcome
            not in (JobOutcome.SUCCEEDED, JobOutcome.SUCCEEDED_WITH_WARNINGS)
        ):
            raise nav_input_error("CONVERSION_INGEST", "请先完成通过或有警告的入库预览")
        if CheckReport.model_validate(preview.parameters["check"]).result == "不通过":
            raise nav_input_error("CONVERSION_INGEST", "检查不通过，不能入库")
        parameters = ConversionIngestParameters.model_validate(preview.parameters["input"])
        value = _ingest_read.conversion(deps, parameters.conversion_job_id)
        _apply_plan(deps, context, value, cast(JsonObject, preview.parameters["move"]))


def _apply_plan(
    deps: NavWriteDependencies,
    context: ExecutionContext,
    value: _ingest_read.Conversion,
    move: JsonObject,
) -> None:
    """先持久化移动意图，失败复用导航提交事实决定退回还是保留。"""
    if deps.rescan.storage is None or not isinstance(context.parameters, NavApplyParameters):
        raise DefectError()
    check_root(value.root, deps.rescan.storage, context.reporter.check_cancelled)
    stage, target = str(move["stage"]), str(move["target"])
    facts = access("probe", value.root, stage, target, deps.paths.root)
    if facts["target_exists"] or (facts["dev"], facts["ino"]) != (move["dev"], move["ino"]):
        raise nav_input_error("CONVERSION_INGEST", "目标已占用或暂存目录被替换，请重新预览")
    marker = deps.paths.root / "download-ingest-moves" / f"{context.job_id}.json"
    atomic_json(marker, json.dumps(move))
    try:
        access("move", value.root, stage, target, marker)
        identifier = context.parameters.preview_job_id
        finalized = with_ingest_date(read_preview(deps.paths, identifier), context.clock.now())
        atomic_bytes(
            preview_path(deps.paths, identifier),
            gzip.compress(finalized.model_dump_json().encode(), mtime=0),
        )
        run_write_plan(context, deps, identifier)
    except BaseException:
        _rollback_move(deps, context.job_id, (value.root, stage, target), marker)
        raise
    marker.unlink()


def build_ingest_definitions(
    dependencies: NavWriteDependencies | None,
) -> tuple[JobDefinition, ...]:
    """登记转换入库检查与确认作业。

    Args:
        dependencies: worker 导航和存储能力；Web 仅校验参数时传 None。

    Returns:
        检查 RESTART、入库 INTERRUPT 两个类型，入库受导航写门禁保护。

    Raises:
        无。

    Side Effects:
        只构造类型定义，不访问存储或提交作业。

    Time Semantics:
        启动期调用；检查限时300秒，移动和恢复各限时30秒。
    """
    return (
        JobDefinition(
            CHECK_TYPE,
            "转换入库检查",
            ConversionIngestParameters,
            RecoveryMode.RESTART,
            partial(_execute_check, dependencies),
            submission_role=Role.MEMBER,
        ),
        JobDefinition(
            APPLY_TYPE,
            "转换入库",
            NavApplyParameters,
            RecoveryMode.INTERRUPT,
            partial(_execute_apply, dependencies),
            submission_role=Role.ADMINISTRATOR,
            writes_navigation=True,
        ),
    )
