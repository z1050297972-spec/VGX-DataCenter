"""改指向与撤回的 Web 领域服务；只有数据库和状态目录能力，无法访问导航或数据盘。

沿用创建操作的最小依赖、排队提醒、M0 提交与永久作业记录；L19 仅在 worker builder 执行。
"""

from datetime import timedelta

from pydantic import ValidationError

from rdp.accounts.service import authorize_job_actor
from rdp.infra.db.connection import session_scope
from rdp.jobs.dataset_browser import _scope
from rdp.jobs.navwrite import _create_query as query
from rdp.jobs.navwrite.changes import read_change_record
from rdp.jobs.navwrite.create_service import CreationAccess
from rdp.jobs.navwrite.errors import nav_input_error
from rdp.jobs.navwrite.jobs import NAV_REVERT_PREVIEW_TYPE, NavRevertPreviewParameters
from rdp.jobs.navwrite.models import (
    ListedChange,
    NavOperation,
    NavPreview,
    SetLinkStep,
    WriteFileStep,
)
from rdp.jobs.navwrite.policy import NAV_APPLY_TYPE, PREVIEW_RETENTION_DAYS
from rdp.jobs.navwrite.previews import read_preview
from rdp.jobs.navwrite.repoint_models import REPOINT_PREVIEW_TYPE, RepointParameters
from rdp.jobs.navwrite.write_views import NavigationPreviewView, ReversalDetails
from rdp.jobs.outcome import JobOutcome
from rdp.jobs.service import JobRequest
from rdp.jobs.types import JobRecord, JobState


def submit_repoint_preview(
    access: CreationAccess, request: JobRequest, parameters: RepointParameters
) -> JobRecord:
    """提交单个数据集的只读改指向预览。

    Args:
        access: 共用引擎的作业服务与状态目录，不含导航或存储检查器。
        request: 服务器提供的认证身份、唯一 UTC 时刻及审计上下文。
        parameters: 数据集永久编号和通过 L17 形状校验的前缀。

    Returns:
        nav_repoint_preview 的 queued 记录，不等待目标核对。

    Raises:
        DatasetNotFoundError: 数据集未入索引。
        JobInputError: 参数超预算或类型未登记。
        AuthenticationError: 会话失效。
        PasswordChangeRequiredError: 账号必须先改密。
        InputError: 索引数据损坏。
        ConflictError: 提交或审计事务竞争。
        ExternalError: 数据库写入失败，整次提交回滚。
        DefectError: 跨引擎装配或审计上下文非法。

    Side Effects:
        原子新增只读作业与提交日志；不运行 builder，不访问前缀路径。

    Time Semantics:
        使用 request.now；提交后立即返回，无轮询或 POST 重试。
    """
    query.validate_access(access)
    with session_scope(access.engine, read_only=True) as session:
        authorize_job_actor(session, request.identity, now=request.now)
        _scope.require_dataset(session, parameters.dataset_id)
    return access.jobs.submit(request, REPOINT_PREVIEW_TYPE, parameters.model_dump(mode="json"))


def submit_revert_preview(
    access: CreationAccess, request: JobRequest, target_job_id: int
) -> JobRecord:
    """为任意已登记的写导航层作业提交撤回预览。

    Args:
        access: Web 最小依赖；永久变更记录由 worker 读取。
        request: 本次提交者认证身份与审计来源，必填。
        target_job_id: 目标作业正整数编号，不依赖操作日志是否还存在。

    Returns:
        nav_revert_preview 的 queued 记录；worker 核对 COMMITTED 变更记录及当前后像。

    Raises:
        JobNotFoundError: 目标作业不存在。
        InputError: 目标不是写导航层作业。
        JobInputError: 编号或提交参数不合法。
        AuthenticationError: 当前会话失效。
        PasswordChangeRequiredError: 账号需要先改密。
        ConflictError: 提交事务竞争。
        ExternalError: 数据库读取或提交失败。
        DefectError: 最小依赖的引擎不一致。

    Side Effects:
        只新增预览作业与提交日志，不读取导航，不立即执行反向计划。

    Time Semantics:
        使用本次请求时刻；永久变更记录不受操作日志保留期限制。
    """
    query.validate_access(access)
    record = access.jobs.get(request, target_job_id)
    definition = access.jobs.registry.lookup(record.type_name)
    if definition is None or not definition.writes_navigation:
        problem = nav_input_error("NAV_REVERT", "目标作业不是写导航层作业")
        raise problem
    return access.jobs.submit(request, NAV_REVERT_PREVIEW_TYPE, {"target_job_id": target_job_id})


def read_navigation_preview(
    access: CreationAccess, request: JobRequest, preview_job_id: int
) -> NavigationPreviewView:
    """读取改指向或撤回预览及提交前队列提醒。

    Args:
        access: Web 只读状态文件和数据库依赖。
        request: 当前成员/管理员的服务器身份及 UTC 时刻。
        preview_job_id: 成功预览的正整数编号。

    Returns:
        保存报告、参数、前后像摘要和当前 queued_jobs，不返回文件正文或可修改的执行计划。

    Raises:
        JobNotFoundError: 作业不存在。
        InputError: 类型/成功状态/参数关联不符，文件缺失、损坏或超过七天保留期。
        AuthenticationError: 会话失效。
        PasswordChangeRequiredError: 账号必须改密。
        ConflictError: 数据库读取竞争。
        ExternalError: 读取数据库或状态文件失败。
        DefectError: 引擎装配不一致。

    Side Effects:
        无（只读作业、预览文件和队列；不读导航、不重算预览）。

    Time Semantics:
        保留原 created_at；回拨按经过零时长，队列提醒为本次读取快照。
    """
    preview = _load(access, request, preview_job_id)
    changes: list[ListedChange] = []
    for step in preview.plan.steps:
        if isinstance(step, WriteFileStep):
            before, after = step.before.sha256 or "不存在", step.after.sha256 or "不存在"
        elif isinstance(step, SetLinkStep):
            before, after = step.before_target or "不存在", step.after_target
        else:
            before, after = "计划前像", step.op
        changes.append(ListedChange(file=step.path, json_path=step.op, before=before, after=after))
    return NavigationPreviewView(
        preview_job_id=str(preview_job_id),
        created_at=preview.created_at,
        operation="repoint_dataset"
        if preview.plan.operation is NavOperation.REPOINT_DATASET
        else "revert_change",
        dataset_ids=preview.plan.dataset_ids,
        reverts_job_id=str(preview.plan.reverts_job_id)
        if preview.plan.reverts_job_id is not None
        else None,
        parameters=preview.parameters,
        report=preview.report,
        changes=tuple(changes),
        queued_jobs=query.queued(access, request, preview.plan.dataset_ids),
        reversal=_reversal(access, preview),
    )


def submit_navigation_write(
    access: CreationAccess,
    request: JobRequest,
    preview_job_id: int,
    acknowledged_queue_job_ids: tuple[int, ...],
) -> JobRecord:
    """确认保存的改指向/撤回预览后提交公共写入作业。

    Args:
        access: Web 作业与状态依赖，不接受客户端计划。
        request: 本次确认者身份及审计上下文，决定写入作业提交人。
        preview_job_id: 成功且未过期的预览编号，正整数。
        acknowledged_queue_job_ids: 用户已看到的同数据集排队编号，不重复；首次为空。

    Returns:
        nav_write_apply 的 queued 记录，参数只有 preview_job_id。

    Raises:
        JobNotFoundError: 预览作业不存在。
        JobInputError: 确认编号非法或重复。
        InputError: 预览类型、状态或持久化关联不合法。
        AuthenticationError: 提交事务内会话失效。
        PasswordChangeRequiredError: 确认者必须改密。
        ConflictError: 有未确认的新排队作业或提交事务竞争，不提交写入。
        ExternalError: 预览读取或数据库提交失败。
        DefectError: 引擎依赖不一致。

    Side Effects:
        只提交作业和操作日志；worker 仍须持锁复核 L12，同源队列确认不能绕过冲突。

    Time Semantics:
        确认前刷新提醒，返回后不等待执行；无 POST 自动重试。
    """
    preview = _load(access, request, preview_job_id)
    query.confirm_queue(access, request, preview.plan.dataset_ids, acknowledged_queue_job_ids)
    return access.jobs.submit(
        request, NAV_APPLY_TYPE, {"preview_job_id": preview_job_id}, confirmed_write=True
    )


def _load(access: CreationAccess, request: JobRequest, identifier: int) -> NavPreview:
    """成功记录与持久文件必须匹配，历史文件不直接成为执行许可。"""
    query.validate_access(access)
    record = access.jobs.get(request, identifier)
    expected = {
        REPOINT_PREVIEW_TYPE: NavOperation.REPOINT_DATASET,
        NAV_REVERT_PREVIEW_TYPE: NavOperation.REVERT_CHANGE,
    }
    if (
        record.type_name not in expected
        or record.state is not JobState.COMPLETED
        or record.summary is None
        or record.summary.outcome not in (JobOutcome.SUCCEEDED, JobOutcome.SUCCEEDED_WITH_WARNINGS)
    ):
        raise nav_input_error("NAV_WRITE_PREVIEW", "预览类型错误或尚未成功完成")
    preview = read_preview(access.paths, identifier)
    if preview.created_at.tzinfo is None or max(
        timedelta(), request.now - preview.created_at
    ) > timedelta(days=PREVIEW_RETENTION_DAYS):
        raise nav_input_error("NAV_WRITE_PREVIEW", "预览已过七天保留期或时刻非法，请重新预览")
    if (
        preview.preview_job_id != identifier
        or preview.plan.operation is not expected[record.type_name]
        or preview.parameters != record.parameters
    ):
        raise nav_input_error("NAV_WRITE_PREVIEW", "预览编号、类型或参数关联不一致")
    _association(preview)
    return preview


def _reversal(access: CreationAccess, preview: NavPreview) -> ReversalDetails | None:
    """反向片段来自永久报告；操作日志清理不影响它，也不加载文件前后像正文。"""
    if preview.plan.reverts_job_id is None:
        return None
    original = read_change_record(access.paths, preview.plan.reverts_job_id).report
    if original is None:
        return None
    return ReversalDetails(
        field_counts=original.field_counts,
        listed_changes=tuple(
            ListedChange(
                file=item.file, json_path=item.json_path, before=item.after, after=item.before
            )
            for item in (
                original.repoint_changes
                if original.repoint_changes is not None
                else original.listed_changes
            )
        ),
        listed_total=original.listed_total,
    )


def _association(preview: NavPreview) -> None:
    """值模型通过不代表关联正确，计划必须仍属于原参数指向的数据集/目标作业。"""
    try:
        if preview.plan.operation is NavOperation.REPOINT_DATASET:
            params = RepointParameters.model_validate(preview.parameters)
            valid = (
                preview.plan.dataset_ids == (params.dataset_id,)
                and preview.plan.reverts_job_id is None
            )
        else:
            target = NavRevertPreviewParameters.model_validate(preview.parameters)
            valid = preview.plan.reverts_job_id == target.target_job_id
    except ValidationError as error:
        raise nav_input_error("NAV_WRITE_PREVIEW", "保存的预览参数不符合值契约") from error
    if not valid:
        raise nav_input_error("NAV_WRITE_PREVIEW", "预览计划与输入的数据集或撤回目标不一致")
