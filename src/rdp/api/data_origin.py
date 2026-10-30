"""数据来源与预览报告的 HTTP 入口（M1-10）。

只提交作业、读取状态目录中的公开报告，不生成计划、不访问导航层或存储根。
确认写入和撤回提交继续使用 /api/jobs，执行均由第 07 张 worker 流水线完成。
"""

from fastapi import APIRouter
from pydantic import AwareDatetime, BaseModel, ConfigDict, JsonValue

from rdp.api._account_context import identity
from rdp.api._job_views import response
from rdp.api.job_schemas import JobResponse
from rdp.api.jobs import JobContext
from rdp.infra.db.validation import invalid_field
from rdp.infra.ids import error_source_kind
from rdp.jobs.errors import JobInputError
from rdp.jobs.navwrite.errors import nav_input_error
from rdp.jobs.navwrite.models import NavOperation, PlanReport
from rdp.jobs.navwrite.origin_parameters import DATA_ORIGIN_PREVIEW_TYPE, DataOriginParameters
from rdp.jobs.navwrite.previews import read_preview
from rdp.jobs.service import JobRequest
from rdp.jobs.types import JobState

router = APIRouter(prefix="/api/navigation", tags=["navigation"])


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
    """

    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)
    preview_job_id: str
    created_at: AwareDatetime
    parameters: dict[str, JsonValue]
    operation: NavOperation
    dataset_ids: tuple[str, ...]
    report: PlanReport


@router.post(
    "/data-origin/preview",
    response_model=JobResponse,
    status_code=201,
    operation_id="preview_data_origin",
)
def preview_data_origin(context: JobContext, body: DataOriginParameters) -> JobResponse:
    """提交改数据来源的只读预览作业，成员与管理员权限相同。

    Args:
        context: 全局同源、认证与改密检查通过的作业上下文。
        body: 数据集永久编号和六选一中文来源值；不接收路径或操作者。

    Returns:
        HTTP 201，新建 queued 的 nav_data_origin_preview，作业编号为文本。

    Raises:
        JobInputError: 参数非法或类型未登记，422；框架参数失败同样安全返回 422。
        AuthenticationError: 会话失效，401。
        AuthorizationError: Origin 非本站，403。
        PasswordChangeRequiredError: 必须改密，403。
        InputError: 数据库记录损坏，400。
        ConflictError: 提交事务竞争，409。
        ExternalError: 依赖未配置、数据库或操作日志写入失败，502。
        DefectError: 服务装配或时钟缺陷，500。

    Side Effects:
        仅新增作业与提交操作日志；Web 不访问导航层，来源格式与身份校验由 worker 执行。

    Time Semantics:
        复用请求唯一 UTC 时刻；提交不等待 worker，不重试写请求。
    """
    return response(
        context.service.submit(
            _request(context), DATA_ORIGIN_PREVIEW_TYPE, body.model_dump(mode="json")
        )
    )


@router.get(
    "/previews/{job_id}",
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
    job = context.service.get(_request(context), identifier)
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
    preview = read_preview(context.paths, identifier)
    return NavigationPreviewResponse(
        preview_job_id=str(preview.preview_job_id),
        created_at=preview.created_at,
        parameters=preview.parameters,
        operation=preview.plan.operation,
        dataset_ids=preview.plan.dataset_ids,
        report=preview.report,
    )


def _request(context: JobContext) -> JobRequest:
    """沿用全局认证身份、请求唯一时刻和服务器审计来源，不重新读取 cookie 或时钟。"""
    return JobRequest(identity(context.account), context.account.now, context.account.audit)
