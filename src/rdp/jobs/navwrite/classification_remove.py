"""批量删除分类值的 worker 预览（领域层，M1.5-16、ADR 0009）。

只修改原始信息对象的一个顶层键，复用 jsonio、指纹、差异报告及通用写入流水线。
格式信息整份同步规范副本；不改来源、原始路径、子任务文件，不访问原始数据。
"""

from collections.abc import Callable
from functools import partial

from rdp.accounts.types import Role
from rdp.infra.diagnostics import DefectError
from rdp.jobs.datasets.reading import discover_entries, scene_values
from rdp.jobs.datasets.types import EntryLocation, View
from rdp.jobs.execution import ExecutionContext
from rdp.jobs.navwrite import _create_plan as plans
from rdp.jobs.navwrite import _create_read as reads
from rdp.jobs.navwrite._field_diff import differences
from rdp.jobs.navwrite.classification_parameters import (
    CLASSIFICATION_REMOVE_PREVIEW_TYPE,
    ClassificationRemoveParameters,
)
from rdp.jobs.navwrite.classification_read import classification_dataset_ids
from rdp.jobs.navwrite.errors import nav_conflict_error, nav_input_error
from rdp.jobs.navwrite.jobs import PreviewBuild, run_preview
from rdp.jobs.navwrite.jsonio import dump_navigation_json
from rdp.jobs.navwrite.models import (
    CheckNote,
    CheckScope,
    NavOperation,
    NavWritePlan,
    PlanReport,
    PreviewState,
    WriteFileStep,
)
from rdp.jobs.navwrite.pipeline import NavWriteDependencies
from rdp.jobs.navwrite.preview_state import capture_preview_state, verify_preview_state
from rdp.jobs.registry import JobDefinition
from rdp.jobs.types import RecoveryMode


def build_classification_remove_definition(
    dependencies: NavWriteDependencies | None,
) -> JobDefinition:
    """登记与字段编辑相同成员权限的分类删除预览。

    Args:
        dependencies: worker 完整依赖；Web 传 None，只登记参数及权限。

    Returns:
        可重跑、并发 1、无 GPU 且不持导航写锁的预览定义。

    Raises:
        无。

    Side Effects:
        无；构造时不读取导航层或数据库。

    Time Semantics:
        启动期登记；预览由 worker 执行，确认由 nav_write_apply 持锁复核。
    """
    return JobDefinition(
        CLASSIFICATION_REMOVE_PREVIEW_TYPE,
        "预览删除场景或任务值",
        ClassificationRemoveParameters,
        RecoveryMode.RESTART,
        partial(_execute, dependencies),
        submission_role=Role.MEMBER,
    )


def _execute(deps: NavWriteDependencies | None, context: ExecutionContext) -> None:
    """复用公共预览入口持久化计划，依赖或参数装配错误为平台缺陷。"""
    if deps is None or not isinstance(context.parameters, ClassificationRemoveParameters):
        raise DefectError()
    run_preview(context, deps, partial(_build, deps, context.parameters))


def _build(
    deps: NavWriteDependencies,
    parameters: ClassificationRemoveParameters,
    checkpoint: Callable[[], None],
) -> PreviewBuild:
    """重新发现使用范围，以同一份指纹约束原文读取和副本同步。"""
    nav = deps.rescan.nav_root
    ids = classification_dataset_ids(nav, parameters, checkpoint=checkpoint)
    state = capture_preview_state(nav, ids, None, checkpoint=checkpoint)
    locations = discover_entries(nav).entries
    steps: list[WriteFileStep] = []
    originals: dict[str, bytes] = {}
    for dataset in state.datasets:
        paths = {entry.path for entry in dataset.entries}
        entries = [location for location in locations if str(location.path) in paths]
        changes, before = _dataset(deps, parameters, state, entries, checkpoint)
        steps.extend(changes)
        originals.update(before)
    listed, total = differences(steps, originals, checkpoint)
    verify_preview_state(nav, state, checkpoint=checkpoint)
    return PreviewBuild(
        NavWritePlan(
            operation=NavOperation.EDIT_DATASET_FIELDS,
            dataset_ids=ids,
            steps=tuple(steps),
            state=state,
        ),
        PlanReport(
            file_count=len(steps),
            link_count=0,
            directory_count=0,
            field_counts=(),
            listed_changes=listed,
            listed_total=total,
            checks=(
                CheckNote(
                    name="删除分类值",
                    scope=CheckScope.FULL,
                    detail="全量读取规范副本，删除指定分类值；空数组表示未标注，格式信息副本由规范副本同步；不访问原始数据",
                ),
            ),
            notices=(),
        ),
        parameters.model_dump(mode="json"),
    )


def _dataset(
    deps: NavWriteDependencies,
    parameters: ClassificationRemoveParameters,
    state: PreviewState,
    entries: list[EntryLocation],
    checkpoint: Callable[[], None],
) -> tuple[list[WriteFileStep], dict[str, bytes]]:
    """仅变更选中的分类键，其余值及键顺序从原始 JSON 对象保留。"""
    canonical = [entry for entry in entries if entry.view is View.TASK]
    if len(canonical) != 1:
        raise nav_input_error("NAV_CLASSIFICATION_REMOVE", "数据集必须有唯一规范入口")
    current, raw = reads.snapshot(deps.rescan.nav_root, canonical[0], state, checkpoint)
    if any(
        doc.payload is None or doc.payload.get("dataset_id") != current.dataset_id
        for doc in current.documents
    ):
        raise nav_input_error("NAV_CLASSIFICATION_REMOVE", "规范入口基础 JSON 身份不一致")
    information = dict(plans.payload(current, 1))
    values = current.scene if parameters.kind == "scene" else current.tasks
    if parameters.value not in values:
        raise nav_conflict_error("NAV_CLASSIFICATION_REMOVE", "分类值在预览期间变化，请重新预览")
    if parameters.kind == "scene":
        information["scene"] = [
            value for value in scene_values(information.get("scene")) if value != parameters.value
        ]
    else:
        # 任务数组只删除相等项；不顺手去重、清空格或丢弃其他未知值。
        tasks = information["tasks"]
        if not isinstance(tasks, list):
            raise nav_input_error("NAV_CLASSIFICATION_REMOVE", "任务必须是数组")
        information["tasks"] = [value for value in tasks if value != parameters.value]
    after = dump_navigation_json(information)
    steps: list[WriteFileStep] = []
    originals: dict[str, bytes] = {}
    for location in entries:
        previous = (
            raw
            if location == canonical[0]
            else reads.snapshot(deps.rescan.nav_root, location, state, checkpoint)[1]
        )
        before = previous["数据集信息.json"]
        if before == after:
            continue
        path = str(location.path / "数据集信息.json")
        originals[path] = before
        steps.append(
            WriteFileStep(
                path=path,
                before=plans.image(before),
                after=plans.image(after),
                after_content=after.decode("utf-8"),
            )
        )
    return steps, originals
