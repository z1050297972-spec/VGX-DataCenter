"""删除分类值的 HTTP 入口（M1.5-16）；只读规范副本并提交作业，不执行导航写入。"""

from fastapi import APIRouter

from rdp.api._account_context import identity
from rdp.api._job_views import response
from rdp.api.datasets import DatasetContext
from rdp.api.job_schemas import JobResponse
from rdp.api.jobs import JobContext
from rdp.jobs.navwrite.classification_parameters import (
    CLASSIFICATION_REMOVE_PREVIEW_TYPE,
    ClassificationRemoveParameters,
)
from rdp.jobs.navwrite.classification_read import classification_dataset_ids
from rdp.jobs.service import JobRequest

router = APIRouter(prefix="/api/navigation", tags=["navigation"])


@router.post(
    "/classification/remove/preview",
    response_model=JobResponse,
    status_code=201,
    operation_id="preview_classification_remove",
)
def preview_classification_remove(
    context: JobContext, datasets: DatasetContext, body: ClassificationRemoveParameters
) -> JobResponse:
    """提交指定场景或任务值的全局删除预览。

    Args:
        context: 已通过认证、改密及同源检查的作业上下文。
        datasets: 当前应用的导航层只读配置。
        body: scene 或 tasks 及要删除的候选原值，不接收路径。

    Returns:
        HTTP 201，queued 作业记录；job_id 是十进制文本。

    Raises:
        JobInputError: 未标注占位符、无人使用或参数不合法，422。
        InputError: 规范入口数据不可读，400。
        AuthenticationError: 未登录或会话失效，401。
        AuthorizationError: 请求非同源，403。
        PasswordChangeRequiredError: 账号必须改密，403。
        ConflictError: 提交事务竞争，409。
        ExternalError: 导航层读取或数据库提交失败，502。
        DefectError: 服务装配或响应映射错误，500。

    Side Effects:
        只读导航规范副本；成功时新增预览作业及提交日志，不写导航层。

    Time Semantics:
        使用请求唯一 UTC 时刻；worker 会重新核对范围，响应不等待预览完成。
    """
    classification_dataset_ids(datasets.service.queries.nav_root, body, checkpoint=lambda: None)
    request = JobRequest(identity(context.account), context.account.now, context.account.audit)
    return response(
        context.service.submit(
            request, CLASSIFICATION_REMOVE_PREVIEW_TYPE, body.model_dump(mode="json")
        )
    )
