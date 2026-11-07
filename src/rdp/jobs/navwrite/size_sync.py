"""平台自动同步大小（worker 领域层，M1.5-17）。

统计侧只保存计划和提交作业；本作业经通用流水线持锁写入，不访问存储根。
复用指纹、JSON 读取和前后像，不另建锁、日志或撤回机制。
"""

from collections.abc import Callable
from datetime import date
from functools import partial
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from rdp.accounts.types import Role
from rdp.infra.db.connection import session_scope
from rdp.infra.diagnostics import DefectError
from rdp.jobs.datasets import _io
from rdp.jobs.datasets._size_text import replace_size_text
from rdp.jobs.datasets._sizing_types import SizeDataset
from rdp.jobs.datasets.catalog import SIZING_TYPE
from rdp.jobs.execution import ExecutionContext
from rdp.jobs.navwrite._create_plan import image
from rdp.jobs.navwrite.errors import nav_input_error
from rdp.jobs.navwrite.jsonio import load_navigation_json
from rdp.jobs.navwrite.models import (
    NavOperation,
    NavPreview,
    NavWritePlan,
    PlanReport,
    PreviewState,
    WriteFileStep,
)
from rdp.jobs.navwrite.pipeline import NavWriteDependencies, run_write_plan
from rdp.jobs.navwrite.preview_state import diff_preview_state
from rdp.jobs.navwrite.previews import preview_path, read_preview, write_preview
from rdp.jobs.records import find_job
from rdp.jobs.registry import JobDefinition
from rdp.jobs.types import RecoveryMode

# 工单约定的持久化类型键；与人工编辑共用 edit_dataset_fields 变更记录。
SIZE_SYNC_TYPE = "nav_size_sync"


class SizeSyncParameters(BaseModel):
    """自动写入只携带已发布统计的计划编号，避免把大计划塞进作业参数。

    Attributes:
        model_config: 冻结、拒绝额外字段，不回显输入。
        sizing_job_id: 生成计划的统计作业编号，严格正整数。
    """

    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)
    sizing_job_id: int = Field(strict=True, ge=1)


def build_size_sync_definition(dependencies: NavWriteDependencies | None) -> JobDefinition:
    """登记平台自动大小写入作业。

    Args:
        dependencies: worker 写入依赖；Web 传 None，只登记类型。

    Returns:
        无 GPU、并发1、写导航层、中断后回滚的作业定义。

    Raises:
        无。

    Side Effects:
        无；不读取导航或提交作业。

    Time Semantics:
        启动时登记，执行时遵循现有写锁等待预算。
    """
    return JobDefinition(
        SIZE_SYNC_TYPE,
        "同步数据集大小",
        SizeSyncParameters,
        RecoveryMode.INTERRUPT,
        partial(_execute, dependencies),
        writes_navigation=True,
        submission_role=Role.ADMINISTRATOR,
    )


def plan_size_update(
    deps: NavWriteDependencies,
    dataset: SizeDataset,
    size_bytes: int,
    local_date: date,
    checkpoint: Callable[[], None],
) -> NavWritePlan | None:
    """以统计时的指纹构造只改第4项的计划，不写导航层。

    Args:
        deps: worker 写入依赖，此处只读导航根。
        dataset: 完整统计的数据集及统计前指纹。
        size_bytes: 规范入口完整统计值，非负整数字节。
        local_date: 统计完成时按调度时区换算的本地日期。
        checkpoint: 每个文件和读块的取消检查。

    Returns:
        规范信息及格式副本的写入计划；大小相同或没有唯一规范入口/第4项时为 None。

    Raises:
        OSError: 读取失败或文件已变化，由统计作业跳过此数据集。
        InputError: 信息 JSON 非法，不能生成写入计划。
        JobCancelledError: checkpoint 收到取消。
        WorkerStoppingError: checkpoint 收到停止。

    Side Effects:
        无；只读受限导航文件，不访问存储根。

    Time Semantics:
        完整统计之后调用，不持写锁；前像必须与统计指纹一致，索引发布成功才提交计划，执行时在锁内复核。
    """
    canonical = [entry for entry in dataset.entries if entry.canonical]
    if len(canonical) != 1:
        return None
    original = _read_information(deps, dataset, canonical[0].path, checkpoint)
    load_navigation_json(original)
    after = replace_size_text(original, size_bytes, local_date)
    if after is None:
        return None
    steps: list[WriteFileStep] = []
    for entry in dataset.entries:
        before = _read_information(deps, dataset, entry.path, checkpoint)
        if before != after:
            steps.append(
                WriteFileStep(
                    path=str(Path(entry.path) / "数据集信息.json"),
                    before=image(before),
                    after=image(after),
                    after_content=after.decode("utf-8"),
                )
            )
    return NavWritePlan(
        operation=NavOperation.EDIT_DATASET_FIELDS,
        dataset_ids=(dataset.dataset_id,),
        steps=tuple(steps),
        state=PreviewState(
            nav_root=str(deps.rescan.nav_root), datasets=(dataset.fingerprint,), new_dataset=None
        ),
    )


def submit_size_sync(
    context: ExecutionContext, deps: NavWriteDependencies, plans: list[NavWritePlan]
) -> None:
    """保存已发布统计的合并计划，并提交至多一个自动写入作业。

    Args:
        context: 统计作业上下文，其编号作为计划编号。
        deps: 状态布局和作业服务。
        plans: 本次需要更新的数据集计划，按统计遍历顺序，可空。

    Returns:
        无；空计划不提交。

    Raises:
        ExternalError: 保存计划或提交队列失败，已发布统计不回滚。
        ConflictError: 队列数据库锁竞争。
        InputError: 队列参数或计划非法。

    Side Effects:
        替换本统计作业的计划文件，以系统身份提交 nav_size_sync 并记录提交审计。
        不写导航层；提交失败留下计划，可随下次统计重算。

    Time Semantics:
        全部统计发布之后调用；不持写锁、不等待写入完成。
    """
    if not plans:
        return
    plan = NavWritePlan(
        operation=NavOperation.EDIT_DATASET_FIELDS,
        dataset_ids=tuple(identifier for plan in plans for identifier in plan.dataset_ids),
        steps=tuple(step for plan in plans for step in plan.steps),
        state=PreviewState(
            nav_root=str(deps.rescan.nav_root),
            datasets=tuple(item for plan in plans for item in plan.state.datasets),
            new_dataset=None,
        ),
    )
    preview = NavPreview(
        preview_job_id=context.job_id,
        created_at=context.clock.now(),
        parameters={},
        plan=plan,
        report=_report(len(plan.steps)),
    )
    preview_path(deps.paths, context.job_id).unlink(missing_ok=True)
    write_preview(deps.paths, preview)
    deps.service.submit_system(
        SIZE_SYNC_TYPE, {"sizing_job_id": context.job_id}, now=context.clock.now()
    )


def _execute(deps: NavWriteDependencies | None, context: ExecutionContext) -> None:
    """读取统计计划直接执行；自动计划不要求人工预览作业成功结束。"""
    if deps is None or not isinstance(context.parameters, SizeSyncParameters):
        raise DefectError()
    with session_scope(deps.rescan.engine, read_only=True) as session:
        source = find_job(session, context.parameters.sizing_job_id)
    # 只接受统计生成的内部计划，不能把人工预览编号当作无需确认的入口。
    if source.type_name != SIZING_TYPE:
        raise nav_input_error("NAV_SIZE_SYNC", "自动大小计划必须来自统计作业")
    preview = read_preview(deps.paths, source.job_id)
    if preview.plan.state.nav_root != str(deps.rescan.nav_root):
        raise DefectError()
    run_write_plan(context, deps, preview, prepare_locked=partial(_unchanged, context))


def _unchanged(context: ExecutionContext, preview: NavPreview) -> NavPreview:
    """写锁内剔除已变化的数据集，保留原步骤和原前像；不以新状态覆盖统计时状态。"""
    plan = preview.plan
    differences = diff_preview_state(Path(plan.state.nav_root), plan.state, checkpoint=lambda: None)
    changed = {item.dataset_id for item in differences}
    datasets = tuple(item for item in plan.state.datasets if item.dataset_id not in changed)
    paths = {
        str(Path(entry.path) / "数据集信息.json") for item in datasets for entry in item.entries
    }
    steps = tuple(step for step in plan.steps if step.path in paths)
    if changed:
        context.log.write_line(
            "大小同步跳过已变化数据集：" + "、".join(sorted(str(item) for item in changed)),
            now=context.clock.now(),
        )
    filtered = plan.model_copy(
        update={
            "dataset_ids": tuple(item.dataset_id for item in datasets),
            "steps": steps,
            "state": plan.state.model_copy(update={"datasets": datasets}),
        }
    )
    return preview.model_copy(update={"plan": filtered, "report": _report(len(steps))})


def _report(files: int) -> PlanReport:
    """自动计划的摘要只包含实际步骤计数，不伪装人工预览确认。"""
    return PlanReport(
        file_count=files,
        link_count=0,
        directory_count=0,
        field_counts=(),
        listed_changes=(),
        listed_total=0,
        checks=(),
        notices=(),
    )


def _read_information(
    deps: NavWriteDependencies,
    dataset: SizeDataset,
    entry_path: str,
    checkpoint: Callable[[], None],
) -> bytes:
    """通过已有不跟随软链接的有界读取，核对统计时的文件哈希。"""
    fingerprint = next(entry for entry in dataset.fingerprint.entries if entry.path == entry_path)
    expected = next(item for item in fingerprint.json_files if item.name == "数据集信息.json")
    with _io.directory(deps.rescan.nav_root / entry_path) as descriptor:
        content = _io.read_file(descriptor, "数据集信息.json", checkpoint)
    if image(content).sha256 != expected.sha256:
        raise OSError("数据集信息在统计期间变化")
    return content
