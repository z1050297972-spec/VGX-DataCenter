"""信息回填的 HTTP 入口（M1.5-15）；仅管理员提交，不读写导航或数据盘。

预览报告、确认写入使用既有接口，本模块不另建执行流水线。
"""

from fastapi import APIRouter, Depends

from rdp.api._account_context import identity
from rdp.api._job_views import response
from rdp.api.account_auth import get_admin_context
from rdp.api.job_schemas import JobResponse
from rdp.api.jobs import JobContext
from rdp.jobs.navwrite.backfill_parameters import BACKFILL_PREVIEW_TYPE, BackfillParameters
from rdp.jobs.service import JobRequest

router = APIRouter(
    prefix="/api/navigation", tags=["navigation"], dependencies=[Depends(get_admin_context)]
)


@router.post(
    "/backfill/preview",
    response_model=JobResponse,
    status_code=201,
    operation_id="preview_information_backfill",
)
def preview_information_backfill(context: JobContext, body: BackfillParameters) -> JobResponse:
    """管理员提交覆盖全部数据集的只读回填预览作业。

    Args:
        context: 服务端认证身份、请求唯一 UTC 时刻和作业服务。
        body: 空对象；不接受路径、数据集范围或执行计划。

    Returns:
        HTTP 201，queued 作业记录，job_id 是十进制文本。

    Raises:
        AuthenticationError: 未登录或会话失效，401。
        AuthorizationError: 非管理员或 Origin 非本站，403。
        PasswordChangeRequiredError: 账号必须改密，403。
        JobInputError: 参数或类型非法，422。
        ConflictError: 提交数据库事务竞争，409。
        ExternalError: 数据库或作业依赖不可用，502。
        DefectError: 依赖装配或响应映射错误，500。

    Side Effects:
        原子新增作业和操作日志；不读取导航，不执行迁移。

    Time Semantics:
        沿用请求唯一时刻，提交后立即返回；worker 完成预览后再由用户确认写入。
    """
    request = JobRequest(identity(context.account), context.account.now, context.account.audit)
    return response(
        context.service.submit(request, BACKFILL_PREVIEW_TYPE, body.model_dump(mode="json"))
    )
