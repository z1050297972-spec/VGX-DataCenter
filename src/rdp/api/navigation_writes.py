"""导航预览报告、改指向和撤回的 HTTP 入口；只调用 Web 领域服务，不执行写入。"""

from fastapi import APIRouter
from pydantic import AwareDatetime, BaseModel, ConfigDict, JsonValue

from rdp.api._account_context import identity
from rdp.api._job_views import response as job_response
from rdp.api.datasets.creation import CreationContext
from rdp.api.datasets.creation_schemas import ConfirmCreationRequest
from rdp.api.job_schemas import JobResponse
from rdp.api.jobs import JobContext
from rdp.infra.db.validation import invalid_field
from rdp.infra.ids import error_source_kind
from rdp.jobs.errors import JobInputError
from rdp.jobs.navwrite import write_service as service
from rdp.jobs.navwrite.create_service import CreationAccess
from rdp.jobs.navwrite.create_views import CreationJobId, QueuedNavigationJob
from rdp.jobs.navwrite.errors import nav_input_error
from rdp.jobs.navwrite.models import ListedChange, NavOperation, PlanReport
from rdp.jobs.navwrite.policy import NAV_REVERT_PREVIEW_TYPE
from rdp.jobs.navwrite.previews import read_preview
from rdp.jobs.navwrite.repoint_models import REPOINT_PREVIEW_TYPE, RepointParameters
from rdp.jobs.navwrite.write_service import read_navigation_preview
from rdp.jobs.navwrite.write_views import ReversalDetails
from rdp.jobs.service import JobRequest
from rdp.jobs.types import JobState

router = APIRouter(prefix="/api", tags=["navigation-writes"])


@router.post(
    "/datasets/repoint-previews",
    response_model=JobResponse,
    status_code=201,
    operation_id="submit_dataset_repoint_preview",
)
def submit_repoint_preview(context: CreationContext, body: RepointParameters) -> JobResponse:
    """提交单个数据集的只读改指向预览。

    Args:
        context: 认证成员或管理员、请求时刻及最小服务依赖，Origin 由全局边界先验。
        body: dataset_id、old_prefix、new_prefix；额外字段和不合约前缀按 422 拒绝。

    Returns:
        201，nav_repoint_preview 的完整排队作业；不等待目标检查。

    Raises:
        DatasetNotFoundError: 数据集不存在，404。
        JobInputError: 参数或类型登记不合法，422。
        AuthenticationError: 会话失效，401。
        AuthorizationError: 写请求不同源，403。
        PasswordChangeRequiredError: 账号必须改密，403。
        InputError: 索引数据损坏，400。
        ConflictError: 提交事务竞争，409。
        ExternalError: 数据库提交失败，502。
        DefectError: 应用依赖或响应映射违约，500。

    Side Effects:
        只新增作业和提交日志，不读导航或数据盘；L19 在 worker 中核对。

    Time Semantics:
        使用认证上下文唯一 UTC 时刻；立即返回，客户端轮询 M0 作业接口。
    """
    return job_response(service.submit_repoint_preview(context.access, _request(context), body))


@router.post(
    "/jobs/{target_job_id}/revert-previews",
    response_model=JobResponse,
    status_code=201,
    operation_id="submit_navigation_revert_preview",
)
def submit_revert_preview(context: CreationContext, target_job_id: CreationJobId) -> JobResponse:
    """提交指定写导航层作业的撤回预览。

    Args:
        context: 当前确认者的认证及审计来源，无管理员角色限制。
        target_job_id: 目标作业的规范十进制文本，数值 1 至 MAX_SQLITE_INTEGER。

    Returns:
        201，nav_revert_preview 排队记录；worker 检查永久变更记录并列出后像差异。

    Raises:
        JobNotFoundError: 目标作业不存在，404。
        JobInputError: 编号非法，422。
        InputError: 目标不是写导航层作业，400。
        AuthenticationError: 提交会话失效，401。
        AuthorizationError: Origin 检查失败，403。
        PasswordChangeRequiredError: 提交者必须改密，403。
        ConflictError: 提交竞争，409。
        ExternalError: 数据库读取或提交失败，502。
        DefectError: 作业服务装配违约，500。

    Side Effects:
        新增只读撤回预览及提交日志；不读取目标前后像或执行撤回。

    Time Semantics:
        不受操作日志 30 天保留期约束，失败预览不自动提交写入。
    """
    return job_response(
        service.submit_revert_preview(context.access, _request(context), int(target_job_id))
    )


@router.post(
    "/navigation/writes",
    response_model=JobResponse,
    status_code=201,
    operation_id="confirm_navigation_write",
)
def confirm_navigation_write(context: CreationContext, body: ConfirmCreationRequest) -> JobResponse:
    """确认改指向或撤回预览，统一提交 nav_write_apply。

    Args:
        context: 本次确认者身份、唯一请求时刻及审计上下文。
        body: preview_job_id 与已确认排队编号；不能夹带前缀或执行计划。

    Returns:
        201，nav_write_apply 排队记录；未确认新排队项返回 409 并列出编号。

    Raises:
        JobNotFoundError: 预览作业不存在，404。
        JobInputError: 参数、编号重复或类型未登记，422。
        InputError: 预览不合法或过期，400。
        AuthenticationError: 提交事务内会话失效，401。
        AuthorizationError: 写请求不同源，403。
        PasswordChangeRequiredError: 确认者必须改密，403。
        ConflictError: 未确认队列项或提交竞争，409。
        ExternalError: 读取预览或持久化失败，502。
        DefectError: 服务装配或响应映射非法，500。

    Side Effects:
        成功只提交作业及操作日志；worker 在写锁内核对，冲突时导航一行不写。

    Time Semantics:
        提交前刷新队列提醒；不自动重试 POST，不等待执行结束。
    """
    return job_response(
        service.submit_navigation_write(
            context.access,
            _request(context),
            int(body.preview_job_id),
            tuple(int(value) for value in body.acknowledged_queue_job_ids),
        )
    )


def _request(context: CreationContext) -> JobRequest:
    """由服务端认证上下文构造同一时刻的审计请求。"""
    return JobRequest(identity(context.account), context.account.now, context.account.audit)


class NavigationPreviewResponse(BaseModel):
    """确认写入前展示的预览，不把完整计划和文件正文发送给页面。

    Attributes:
        model_config: 冻结并拒绝未知字段。
        preview_job_id: 预览作业编号，十进制文本，避免浏览器丢失整数精度。
        created_at: 预览完成的 UTC 时刻。
        parameters: 已校验的预览参数。
        operation: 写导航层的稳定操作码。
        dataset_ids: 受影响数据集编号，升序。
        report: 与执行计划共同生成的报告，包含旧值、新值与检查范围。
        reverts_job_id: 撤回目标的文本编号，其他操作为 None。
        changes: 改指向与撤回的步骤前后像摘要；旧预览默认为空。
        queued_jobs: 改指向与撤回的当前同数据集排队提醒；其他预览默认为空。
        reversal: 原永久报告的反向替换片段，非撤回或缺原报告时为 None。
    """

    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)
    preview_job_id: str
    created_at: AwareDatetime
    parameters: dict[str, JsonValue]
    operation: NavOperation
    dataset_ids: tuple[str, ...]
    report: PlanReport
    reverts_job_id: CreationJobId | None = None
    changes: tuple[ListedChange, ...] = ()
    queued_jobs: tuple[QueuedNavigationJob, ...] = ()
    reversal: ReversalDetails | None = None


@router.get(
    "/navigation/previews/{job_id}",
    response_model=NavigationPreviewResponse,
    operation_id="get_navigation_preview",
)
def get_navigation_preview(context: JobContext, job_id: str) -> NavigationPreviewResponse:
    """读取已完成预览的报告，供查看后确认写入或撤回。

    Args:
        context: 已认证作业上下文；允许全部登录账号。
        job_id: 1 至 2^63-1 的规范十进制文本，不接受前导零。

    Returns:
        HTTP 200，预览参数、操作、受影响编号和检查报告；不返回文件正文。

    Raises:
        JobInputError: 编号形状非法，422。
        JobNotFoundError: 作业不存在，404。
        AuthenticationError: 会话失效，401。
        PasswordChangeRequiredError: 必须改密，403。
        InputError: 作业未成功结束、预览不存在、已过七天保留期或文件损坏，400。
        ConflictError: 读取数据库锁竞争，409。
        ExternalError: 依赖未配置、数据库或预览读取失败，502。
        DefectError: 响应映射缺陷，500。

    Side Effects:
        只读作业记录与状态目录；不读导航层，不写操作日志。

    Time Semantics:
        先完成授权查询再读文件，不持数据库事务做文件 I/O；无轮询或等待。
    """
    if error_source_kind(job_id) != "job":
        problem = JobInputError(invalid_field("job_id", "1至2^63-1的规范十进制文本").diagnostics)
        raise problem
    identifier = int(job_id)
    job = context.service.get(_preview_request(context), identifier)
    if (
        job.state is not JobState.COMPLETED
        or job.summary is None
        or job.summary.aborted
        or job.summary.failed_items
    ):
        problem = nav_input_error(
            "NAV_PREVIEW", "预览作业尚未成功结束", objects=(("job_id", job_id),)
        )
        raise problem
    if job.type_name in (REPOINT_PREVIEW_TYPE, NAV_REVERT_PREVIEW_TYPE):
        view = read_navigation_preview(
            CreationAccess(context.service.engine, context.paths, context.service),
            _preview_request(context),
            identifier,
        )
        return NavigationPreviewResponse.model_validate(view.model_dump())
    preview = read_preview(context.paths, identifier)
    return NavigationPreviewResponse(
        preview_job_id=str(preview.preview_job_id),
        created_at=preview.created_at,
        parameters=preview.parameters,
        operation=preview.plan.operation,
        dataset_ids=preview.plan.dataset_ids,
        report=preview.report,
    )


def _preview_request(context: JobContext) -> JobRequest:
    """沿用作业入口认证身份、请求时刻和审计来源。"""
    return JobRequest(identity(context.account), context.account.now, context.account.audit)
