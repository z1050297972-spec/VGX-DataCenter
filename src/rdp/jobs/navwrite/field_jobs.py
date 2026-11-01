"""字段编辑预览的 worker 入口（M1.5-02、ADR 0009）；只生成计划，不写导航层。

复用既有快照、副本生成、JSON 编码及预览持久化能力，不新增依赖。
"""

from collections.abc import Callable
from functools import partial

from rdp.accounts.types import Role
from rdp.infra.diagnostics import DefectError, InputError
from rdp.jobs.datasets.catalog import REQUIRED_DOCUMENTS
from rdp.jobs.datasets.reading import discover_entries
from rdp.jobs.datasets.types import EntrySnapshot, View
from rdp.jobs.execution import ExecutionContext
from rdp.jobs.navwrite import _create_plan as plans
from rdp.jobs.navwrite import _create_read as reads
from rdp.jobs.navwrite._field_diff import differences
from rdp.jobs.navwrite._field_rules import apply_edit, source_references
from rdp.jobs.navwrite.errors import nav_conflict_error, nav_input_error
from rdp.jobs.navwrite.field_models import FIELD_PREVIEW_TYPE, FieldEditParameters
from rdp.jobs.navwrite.jobs import PreviewBuild, run_preview
from rdp.jobs.navwrite.jsonio import dump_navigation_json, regenerate_derived_fields
from rdp.jobs.navwrite.models import (
    CheckNote,
    CheckScope,
    NavOperation,
    NavWritePlan,
    PlanReport,
    WriteFileStep,
)
from rdp.jobs.navwrite.pipeline import NavWriteDependencies
from rdp.jobs.navwrite.preview_state import capture_preview_state, verify_preview_state
from rdp.jobs.navwrite.replica import generate_format_entry
from rdp.jobs.registry import JobDefinition
from rdp.jobs.types import RecoveryMode


def build_field_edit_definition(dependencies: NavWriteDependencies | None) -> JobDefinition:
    """登记字段编辑的只读预览作业。

    Args:
        dependencies: worker 完整依赖；Web 传 None，只校验参数。

    Returns:
        nav_fields_preview 定义，restart、并发 1、无 GPU、不拿导航写锁。

    Raises:
        无。

    Side Effects:
        无；不执行计划或访问文件。

    Time Semantics:
        启动期构造；预览完成后由 nav_write_apply 持锁执行同一计划。
    """
    return JobDefinition(
        FIELD_PREVIEW_TYPE,
        "预览编辑字段",
        FieldEditParameters,
        RecoveryMode.RESTART,
        partial(_execute, dependencies),
        submission_role=Role.MEMBER,
    )


def _execute(dependencies: NavWriteDependencies | None, context: ExecutionContext) -> None:
    """将已校验参数交给只读 builder，统一持久化预览。"""
    if dependencies is None or not isinstance(context.parameters, FieldEditParameters):
        raise DefectError()
    parameters = context.parameters
    run_preview(context, dependencies, partial(_build, dependencies, parameters))


def _build(
    deps: NavWriteDependencies, parameters: FieldEditParameters, checkpoint: Callable[[], None]
) -> PreviewBuild:
    """从同一 L12 状态构造规范和格式副本的写入步骤。"""
    nav = deps.rescan.nav_root
    state = capture_preview_state(nav, (parameters.dataset_id,), None, checkpoint=checkpoint)
    paths = {item.path for dataset in state.datasets for item in dataset.entries}
    snapshots = [
        reads.snapshot(nav, location, state, checkpoint)
        for location in discover_entries(nav).entries
        if str(location.path) in paths
    ]
    canonical = [
        (snapshot, raw) for snapshot, raw in snapshots if snapshot.location.view is View.TASK
    ]
    if len(canonical) != 1:
        raise nav_input_error("NAV_FIELDS", "数据集必须有唯一规范入口")
    current, raw = canonical[0]
    for snapshot, _ in snapshots:
        _check_identity(snapshot, parameters.dataset_id)
    payloads = {
        name: plans.payload(current, index) for index, name in enumerate(REQUIRED_DOCUMENTS)
    }
    known = source_references(payloads["原始路径.json"], payloads["子任务.json"])
    for edit in parameters.changes:
        checkpoint()
        if plans.image(raw[edit.document]).sha256 != edit.expected_sha256:
            raise nav_conflict_error(
                "NAV_FIELDS",
                "表单读取后文件发生变化，请重新加载",
                objects=(("dataset_id", parameters.dataset_id), ("file", edit.document)),
            )
        try:
            apply_edit(payloads[edit.document], edit, known)
        except InputError as error:
            raise nav_input_error(
                "NAV_FIELDS",
                error.diagnostics[0].actual,
                objects=(
                    ("dataset_id", parameters.dataset_id),
                    ("file", edit.document),
                    ("field", "/".join(map(str, edit.path))),
                ),
            ) from error
    files = tuple(
        dump_navigation_json(
            payloads[name]
            if name == "数据集信息.json"
            else regenerate_derived_fields(payloads[name], current.location)
        )
        for name in REQUIRED_DOCUMENTS
    )
    updated = plans.with_documents(current, files)
    steps: list[WriteFileStep] = []
    for name, after in zip(REQUIRED_DOCUMENTS, files, strict=True):
        _write(steps, str(current.location.path / name), raw[name], after)
    for snapshot, previous in snapshots:
        if snapshot.location.view is not View.FORMAT:
            continue
        checkpoint()
        generated = generate_format_entry(updated, snapshot)
        for file in generated.files:
            _write(
                steps, str(snapshot.location.path / file.name), previous[file.name], file.content
            )
    listed, total = differences(
        steps,
        {
            str(snapshot.location.path / name): content
            for snapshot, previous in snapshots
            for name, content in previous.items()
        },
        checkpoint,
    )
    verify_preview_state(nav, state, checkpoint=checkpoint)
    plan = NavWritePlan(
        operation=NavOperation.EDIT_DATASET_FIELDS,
        dataset_ids=(parameters.dataset_id,),
        steps=tuple(steps),
        state=state,
    )
    report = PlanReport(
        file_count=len(steps),
        link_count=0,
        directory_count=0,
        field_counts=(),
        listed_changes=listed,
        listed_total=total,
        checks=(
            CheckNote(
                name="导航层字段与副本",
                scope=CheckScope.FULL,
                detail="全量核对所有入口指纹；规范副本先写，全部按格式副本按 L8-L11 重新生成",
            ),
        ),
        notices=(),
    )
    return PreviewBuild(plan, report, parameters.model_dump(mode="json"))


def _write(steps: list[WriteFileStep], path: str, before: bytes, after: bytes) -> None:
    """只计划原字节不同的文件，前像用于底座回滚和撤回。"""
    if before != after:
        steps.append(
            WriteFileStep(
                path=path,
                before=plans.image(before),
                after=plans.image(after),
                after_content=after.decode("utf-8"),
            )
        )


def _check_identity(snapshot: EntrySnapshot, dataset_id: str) -> None:
    """三份JSON必须指向同一身份，不能用首个可读文件掩盖不一致。"""
    if any(
        doc.payload is None
        or doc.payload.get("dataset_id") != dataset_id
        or (
            "dataset_name" in doc.payload
            and doc.payload["dataset_name"] != snapshot.location.dataset_name
        )
        for doc in snapshot.documents
    ):
        raise nav_input_error(
            "NAV_FIELDS",
            "基础 JSON 身份与入口不一致",
            objects=(("dataset_id", dataset_id), ("entry_path", str(snapshot.location.path))),
        )
