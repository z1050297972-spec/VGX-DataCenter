"""创建 HTTP 服务的查询边界（M1-08）；只读数据库与状态文件，不持有导航或存储访问能力。"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

from pydantic import ValidationError
from sqlalchemy import select

from rdp.accounts.service import authorize_job_actor
from rdp.infra.db.connection import session_scope
from rdp.infra.db.validation import invalid_field
from rdp.infra.diagnostics import DefectError
from rdp.jobs import _storage
from rdp.jobs.datasets.catalog import MAX_SCAN_ENTRIES
from rdp.jobs.errors import JobInputError
from rdp.jobs.models import JobRow
from rdp.jobs.navwrite.create_models import (
    DATASET_PREVIEW_TYPE,
    LINK_PREVIEW_TYPE,
    DatasetPreviewParameters,
    LinkPreviewParameters,
)
from rdp.jobs.navwrite.create_views import QueuedNavigationJob
from rdp.jobs.navwrite.errors import Advice, nav_conflict_error, nav_input_error
from rdp.jobs.navwrite.models import (
    MakeDirStep,
    NavOperation,
    NavPreview,
    SetLinkStep,
    WriteFileStep,
)
from rdp.jobs.navwrite.policy import PREVIEW_RETENTION_DAYS
from rdp.jobs.navwrite.previews import read_preview
from rdp.jobs.outcome import JobOutcome
from rdp.jobs.service import JobRequest
from rdp.jobs.types import JobState

if TYPE_CHECKING:
    from rdp.jobs.navwrite.create_service import CreationAccess


def validate_access(access: CreationAccess) -> None:
    """拒绝跨引擎装配，不让一次请求在两个库之间拼接身份与作业。"""
    if access.jobs.engine is not access.engine or not access.engine.get_execution_options().get(
        "rdp_managed"
    ):
        raise DefectError()


def load(
    access: CreationAccess, request: JobRequest, identifier: int
) -> tuple[NavPreview, LinkPreviewParameters | DatasetPreviewParameters]:
    """成功作业记录与持久预览必须相互匹配，不接受仅有文件的半成品。"""
    validate_access(access)
    record = access.jobs.get(request, _storage.identifier(identifier))
    if (
        record.state is not JobState.COMPLETED
        or record.summary is None
        or record.summary.outcome not in (JobOutcome.SUCCEEDED, JobOutcome.SUCCEEDED_WITH_WARNINGS)
    ):
        raise nav_input_error("NAV_CREATE_PREVIEW", "预览作业尚未成功完成")
    preview = read_preview(access.paths, identifier)
    if preview.created_at.tzinfo is None:
        raise nav_input_error("NAV_CREATE_PREVIEW", "预览时刻没有时区")
    # 回拨按经过零时长处理；保留期仍使用创建时刻加固定天数，不刷新文件时刻。
    if max(timedelta(), request.now - preview.created_at) > timedelta(days=PREVIEW_RETENTION_DAYS):
        raise nav_input_error("NAV_CREATE_PREVIEW", "预览已过七天保留期，请重新预览")
    expected = {
        NavOperation.CREATE_LINK: LINK_PREVIEW_TYPE,
        NavOperation.CREATE_DATASET: DATASET_PREVIEW_TYPE,
    }
    if (
        record.type_name != expected.get(preview.plan.operation)
        or preview.preview_job_id != identifier
        or preview.parameters != record.parameters
        or len(preview.plan.dataset_ids) != 1
    ):
        raise nav_input_error("NAV_CREATE_PREVIEW", "预览作业类型、参数或计划关联不一致")
    try:
        parameters = (
            LinkPreviewParameters.model_validate(preview.parameters)
            if preview.plan.operation is NavOperation.CREATE_LINK
            else DatasetPreviewParameters.model_validate(preview.parameters)
        )
    except ValidationError as error:
        raise nav_input_error("NAV_CREATE_PREVIEW", "保存的创建参数不符合契约") from error
    _report(preview)
    return preview, parameters


def _report(preview: NavPreview) -> None:
    """报告必须是同一份计划的结构化投影，缺失或不一致属于程序缺陷。"""
    details = preview.report.creation
    if details is None:
        raise DefectError()
    files = tuple(step.path for step in preview.plan.steps if isinstance(step, WriteFileStep))
    links = tuple(step.path for step in preview.plan.steps if isinstance(step, SetLinkStep))
    directories = tuple(step.path for step in preview.plan.steps if isinstance(step, MakeDirStep))
    if (
        details.file_paths != files
        or tuple(link.path for link in details.links) != links
        or details.directory_paths != directories
        or (preview.report.file_count, preview.report.link_count, preview.report.directory_count)
        != (len(files), len(links), len(directories))
        or details.noop != (not preview.plan.steps)
    ):
        raise DefectError()


def queued(
    access: CreationAccess, request: JobRequest, dataset_ids: tuple[str, ...]
) -> tuple[QueuedNavigationJob, ...]:
    """读完短事务再读取排队作业的预览，文件 I/O 不占数据库事务。"""
    with session_scope(access.engine, read_only=True) as session:
        authorize_job_actor(session, request.identity, now=request.now)
        rows = (
            session.execute(
                select(JobRow)
                .where(JobRow.state == JobState.QUEUED.value)
                .order_by(JobRow.job_id)
                .limit(MAX_SCAN_ENTRIES + 1)
            )
            .scalars()
            .all()
        )
        candidates = tuple((row.job_id, row.type_name, row.parameters) for row in rows)
    if len(candidates) > MAX_SCAN_ENTRIES:
        raise nav_input_error("NAV_CREATE_QUEUE", "排队作业超过完整提醒预算")
    found: list[QueuedNavigationJob] = []
    for job_id, type_name, parameters in candidates:
        definition = access.jobs.registry.lookup(type_name)
        if definition is None or not definition.writes_navigation:
            continue
        reference = parameters.get("preview_job_id")
        if reference is None:
            target = parameters.get("dataset_id")
            ids = (target,) if isinstance(target, str) else ()
        else:
            ids = read_preview(access.paths, _storage.identifier(reference)).plan.dataset_ids
        overlap = tuple(sorted(set(ids).intersection(dataset_ids)))
        if overlap:
            found.append(QueuedNavigationJob(job_id=str(job_id), dataset_ids=overlap))
    return tuple(found)


def confirm_queue(
    access: CreationAccess,
    request: JobRequest,
    dataset_ids: tuple[str, ...],
    acknowledged_queue_job_ids: tuple[int, ...],
) -> None:
    """统一创建和改指向的排队确认规则，提醒不代替写锁内核对。"""
    acknowledged = validate_queue_ids(acknowledged_queue_job_ids)
    waiting = queued(access, request, dataset_ids)
    unseen = tuple(item for item in waiting if int(item.job_id) not in acknowledged)
    if unseen:
        problem = nav_conflict_error(
            "NAV_CREATE_QUEUE_CONFIRMATION",
            "已有尚未确认的排队写作业",
            expected="用户确认这些作业后再次提交",
            objects=tuple(
                (f"queued_job_id_{index}", item.job_id) for index, item in enumerate(unseen, 1)
            ),
            advice=Advice(
                "本次写入作业尚未提交，导航层未改变",
                "查看这些作业，确认后带 acknowledged_queue_job_ids 再次提交",
            ),
        )
        raise problem


def validate_queue_ids(values: tuple[int, ...]) -> tuple[int, ...]:
    """在读取预览之前也可校验编号，保留创建接口原有的参数错误优先级。"""
    acknowledged = tuple(_storage.identifier(value) for value in values)
    if len(acknowledged) != len(set(acknowledged)):
        problem = JobInputError(invalid_field("values", "不重复的正整数编号").diagnostics)
        raise problem
    return acknowledged
