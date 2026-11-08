"""人工血缘 HTTP 入口；只读核对后提交预览，确认沿用通用 nav_write_apply。"""

from fastapi import APIRouter

from rdp.api._account_context import identity
from rdp.api._job_views import response
from rdp.api.datasets import DatasetContext
from rdp.api.job_schemas import JobResponse
from rdp.api.jobs import JobContext
from rdp.jobs.navwrite import _lineage_read
from rdp.jobs.navwrite.lineage_parameters import LINEAGE_PREVIEW_TYPE, LineageParameters
from rdp.jobs.service import JobRequest

router = APIRouter(prefix="/api/navigation", tags=["navigation"])


@router.post(
    "/lineage/preview",
    response_model=JobResponse,
    status_code=201,
    operation_id="preview_lineage",
)
def preview_lineage(
    context: JobContext, datasets: DatasetContext, body: LineageParameters
) -> JobResponse:
    """提交转换来源登记或人工记录删除的只读预览。

    Args:
        context: 已认证账号、唯一请求时刻及作业服务。
        datasets: 当前应用的数据集索引与只读导航配置。
        body: 目标编号及 add/remove 参数；输入 1 至 8 个、说明至多 500 字符。

    Returns:
        HTTP 201，queued 的 nav_lineage_preview 作业，不表示导航已改动。

    Raises:
        JobInputError: 参数非法、输入不存在或删除目标非人工补录，422。
        DatasetNotFoundError: 产物数据集未入索引，404。
        InputError: 规范入口或来源文件不可用，400。
        AuthenticationError: 未登录或会话失效，401。
        AuthorizationError: 写请求不同源，403。
        PasswordChangeRequiredError: 账号必须改密，403。
        ConflictError: 读取时文件变化或提交竞争，409。
        ExternalError: 文件读取或数据库提交失败，502。

    Side Effects:
        只读索引和导航文件；通过检查才新增预览作业及提交日志，不访问数据盘。

    Time Semantics:
        文件读取不持数据库事务；worker 重新核对并记录指纹，立即返回不轮询。
    """
    queries = datasets.service.queries
    _lineage_read.read(queries.engine, queries.nav_root, body, lambda: None)
    request = JobRequest(identity(context.account), context.account.now, context.account.audit)
    return response(
        context.service.submit(request, LINEAGE_PREVIEW_TYPE, body.model_dump(mode="json"))
    )
