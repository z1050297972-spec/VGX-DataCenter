"""改指向与任意导航写作业撤回的 HTTP 入口（M1-09）；只调用 Web 领域服务。"""

from fastapi import APIRouter

from rdp.api._account_context import identity
from rdp.api._job_views import response as job_response
from rdp.api.datasets.creation import CreationContext
from rdp.api.datasets.creation_schemas import ConfirmCreationRequest
from rdp.api.job_schemas import JobResponse
from rdp.jobs.navwrite import write_service as service
from rdp.jobs.navwrite.create_views import CreationJobId
from rdp.jobs.navwrite.repoint_models import RepointParameters
from rdp.jobs.service import JobRequest

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
