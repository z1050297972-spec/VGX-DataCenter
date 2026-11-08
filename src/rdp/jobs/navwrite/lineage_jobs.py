"""人工血缘预览作业；沿用指纹、差异报告和通用写入流水线，只计划来源文件。"""

from collections.abc import Callable
from functools import partial
from typing import cast

from rdp.accounts.types import Role
from rdp.infra.db.connection import session_scope
from rdp.infra.diagnostics import DefectError
from rdp.infra.timeutil import ensure_utc
from rdp.jobs.datasets.types import JsonValue
from rdp.jobs.execution import ExecutionContext
from rdp.jobs.navwrite import _create_plan as plans
from rdp.jobs.navwrite import _lineage_read
from rdp.jobs.navwrite._field_diff import differences
from rdp.jobs.navwrite.errors import nav_conflict_error
from rdp.jobs.navwrite.jobs import PreviewBuild, run_preview
from rdp.jobs.navwrite.jsonio import dump_navigation_json
from rdp.jobs.navwrite.lineage_parameters import LINEAGE_PREVIEW_TYPE, LineageParameters
from rdp.jobs.navwrite.models import (
    CheckNote,
    CheckScope,
    FileImage,
    NavOperation,
    NavWritePlan,
    PlanReport,
    WriteFileStep,
)
from rdp.jobs.navwrite.pipeline import NavWriteDependencies
from rdp.jobs.navwrite.preview_state import capture_preview_state, verify_preview_state
from rdp.jobs.navwrite.provenance import ActorStamp, LineageRecord, with_lineage_record
from rdp.jobs.records import find_job
from rdp.jobs.registry import JobDefinition
from rdp.jobs.types import RecoveryMode


def build_lineage_definition(dependencies: NavWriteDependencies | None) -> JobDefinition:
    """登记与字段编辑相同权限的人工血缘预览。

    Args:
        dependencies: worker 写入依赖；Web 传 None，仅登记参数和权限。

    Returns:
        nav_lineage_preview 定义，成员可提交、restart、并发 1、无需 GPU 或导航写锁。

    Raises:
        无。

    Side Effects:
        无；构造定义不读取文件或提交作业。

    Time Semantics:
        启动时登记，预览由 worker 执行，确认复用 nav_write_apply。
    """
    return JobDefinition(
        LINEAGE_PREVIEW_TYPE,
        "预览登记转换关系",
        LineageParameters,
        RecoveryMode.RESTART,
        partial(_execute, dependencies),
        submission_role=Role.MEMBER,
    )


def _execute(deps: NavWriteDependencies | None, context: ExecutionContext) -> None:
    """参数和依赖必须由登记表装配，预览只写状态目录。"""
    if deps is None or not isinstance(context.parameters, LineageParameters):
        raise DefectError()
    run_preview(context, deps, partial(_build, deps, context, context.parameters))


def _build(
    deps: NavWriteDependencies,
    context: ExecutionContext,
    parameters: LineageParameters,
    checkpoint: Callable[[], None],
) -> PreviewBuild:
    """只改原对象的 lineage；输入也记入指纹，防止确认前输入已被移除。"""
    nav = deps.rescan.nav_root
    state = capture_preview_state(
        nav, (parameters.dataset_id, *parameters.input_dataset_ids), None, checkpoint=checkpoint
    )
    source = _lineage_read.read(deps.rescan.engine, nav, parameters, checkpoint)
    entry_path = source.path.rsplit("/", 1)[0]
    expected = [
        file.sha256
        for dataset in state.datasets
        if dataset.dataset_id == parameters.dataset_id
        for entry in dataset.entries
        if entry.path == entry_path
        for file in entry.json_files
        if file.name == "来源.json"
    ]
    before = plans.image(source.raw) if source.raw is not None else FileImage(exists=False)
    if expected != [before.sha256]:
        raise nav_conflict_error("NAV_LINEAGE", "来源文件前像与预览指纹不一致")
    payload = dict(source.payload)
    records = cast(list[JsonValue], payload["lineage"])
    if parameters.action == "add":
        with session_scope(deps.rescan.engine, read_only=True) as session:
            actor = find_job(session, context.job_id).submitted_by
        record = LineageRecord(
            record_id=max((item.record_id for item in source.document.lineage), default=0) + 1,
            kind="转换",
            status="来历部分未知",
            note=parameters.note or None,
            inputs=tuple({"dataset_id": identifier} for identifier in parameters.input_dataset_ids),
            outputs=(),
            tool=None,
            config=None,
            robot_profile=None,
            parameters=None,
            job_id=None,
            started_at=None,
            finished_at=None,
            recorded_by=ActorStamp(
                kind="人工补录",
                account_id=actor.account_id,
                account_name=actor.name,
                at=ensure_utc(context.clock.now()).strftime("%Y-%m-%dT%H:%M:%SZ"),
            ),
        )
        with_lineage_record(source.document, record)
        payload["lineage"] = [*records, cast(JsonValue, record.model_dump(mode="json"))]
    else:
        payload["lineage"] = [
            value
            for value in records
            if isinstance(value, dict) and value["record_id"] != parameters.record_id
        ]
    after = dump_navigation_json(payload)
    step = WriteFileStep(
        path=source.path,
        before=before,
        after=plans.image(after),
        after_content=after.decode("utf-8"),
    )
    listed, total = differences([step], {source.path: source.raw or b"{}"}, checkpoint)
    verify_preview_state(nav, state, checkpoint=checkpoint)
    return PreviewBuild(
        NavWritePlan(
            operation=NavOperation.EDIT_DATASET_FIELDS,
            dataset_ids=(parameters.dataset_id,),
            steps=(step,),
            state=state,
        ),
        PlanReport(
            file_count=1,
            link_count=0,
            directory_count=0,
            field_counts=(),
            listed_changes=listed,
            listed_total=total,
            checks=(
                CheckNote(
                    name="人工转换关系",
                    scope=CheckScope.FULL,
                    detail="只改按任务入口来源.json；核对输入存在和人工记录删除权限。新增记录的 job_id、记录人和 UTC 时刻在确认写入时由服务器填入。",
                ),
            ),
            notices=(),
        ),
        parameters.model_dump(mode="json"),
    )
