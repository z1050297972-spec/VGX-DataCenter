"""M1.5-02 编辑表单与预览 HTTP 入口；只读导航或提交作业，不执行写入。"""

from typing import Annotated

from fastapi import APIRouter, Query

from rdp.api._account_context import identity
from rdp.api._job_views import response
from rdp.api.datasets import DatasetContext
from rdp.api.job_schemas import JobResponse
from rdp.api.jobs import JobContext
from rdp.infra.db.validation import invalid_field
from rdp.infra.ids import error_source_kind
from rdp.jobs.dataset_browser.schemas import DatasetId
from rdp.jobs.errors import JobInputError
from rdp.jobs.navwrite.field_models import (
    FIELD_PAGE_LIMIT,
    FIELD_PREVIEW_TYPE,
    EditableDocument,
    EditableFieldsPage,
    EditableFieldsQuery,
    FieldEditParameters,
)
from rdp.jobs.navwrite.field_read import read_editable_fields
from rdp.jobs.navwrite.field_service import submit_field_write
from rdp.jobs.service import JobRequest

router = APIRouter(tags=["datasets"])


@router.get(
    "/api/datasets/{dataset_id}/editable-fields",
    response_model=EditableFieldsPage,
    operation_id="get_editable_fields",
)
def get_editable_fields(
    context: DatasetContext,
    dataset_id: DatasetId,
    document: EditableDocument,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=FIELD_PAGE_LIMIT)] = FIELD_PAGE_LIMIT,
) -> EditableFieldsPage:
    """读取规范副本的编辑表单页。

    Args:
        context: 已认证数据集服务上下文。
        dataset_id: 永久编号，不接受文件路径。
        document: 三份基础 JSON 文件名。
        offset: 非负条目偏移。
        limit: 每页 1 至 FIELD_PAGE_LIMIT 个条目。

    Returns:
        HTTP 200，当前页字段及原字节哈希。

    Raises:
        InputError: 文件、规范入口或字段不可用，400；参数非法为 422。
        AuthenticationError: 会话失效，401。
        PasswordChangeRequiredError: 必须改密，403。
        ExternalError: 导航或数据库读取失败，502。
        ConflictError: 授权竞争，409。

    Side Effects:
        只读导航层和账号，不访问存储根或写操作日志。

    Time Semantics:
        单次读取不轮询；跨页通过原字节哈希识别变化。
    """
    queries = context.service.queries
    request = JobRequest(identity(context.account), context.account.now, context.account.audit)
    return read_editable_fields(
        queries.engine,
        queries.nav_root,
        request,
        dataset_id,
        EditableFieldsQuery(document=document, offset=offset, limit=limit),
    )


@router.post(
    "/api/navigation/fields/preview",
    response_model=JobResponse,
    status_code=201,
    operation_id="preview_field_edits",
)
def preview_field_edits(context: JobContext, body: FieldEditParameters) -> JobResponse:
    """提交编辑字段的只读预览作业。

    Args:
        context: 全局认证及同源检查通过的作业上下文。
        body: 数据集编号及改动项，含表单原字节哈希，不接收操作者。

    Returns:
        HTTP 201，queued 的 nav_fields_preview；确认沿用 nav_write_apply。

    Raises:
        JobInputError: 参数、条数或 16 KiB 参数预算不合格，422。
        AuthenticationError: 会话失效，401。
        AuthorizationError: 非同源请求，403。
        PasswordChangeRequiredError: 必须改密，403。
        ConflictError: 提交事务竞争，409。
        ExternalError: 提交服务或数据库失败，502。

    Side Effects:
        新增作业和提交日志；不读取文件、不写导航层。

    Time Semantics:
        使用请求唯一 UTC 时刻；不等待 worker 或重试。
    """
    request = JobRequest(identity(context.account), context.account.now, context.account.audit)
    return response(
        context.service.submit(request, FIELD_PREVIEW_TYPE, body.model_dump(mode="json"))
    )


@router.post(
    "/api/navigation/fields/previews/{job_id}/apply",
    response_model=JobResponse,
    status_code=201,
    operation_id="confirm_field_edits",
)
def confirm_field_edits(context: JobContext, datasets: DatasetContext, job_id: str) -> JobResponse:
    """核对字段预览后确认提交；过期状态返回 409，要求重新预览。

    Args:
        context: 当前认证账号与作业服务。
        datasets: 同一应用的数据集只读导航配置。
        job_id: 1 至 2^63-1 的规范十进制文本。

    Returns:
        HTTP 201，queued 的 nav_write_apply；不表示已经写入。

    Raises:
        JobInputError: 编号不合格，422。
        JobNotFoundError: 作业不存在，404。
        InputError: 预览未成功、关联不符或过期，400。
        ConflictError: 导航变化或提交竞争，409。
        AuthenticationError: 会话失效，401。
        AuthorizationError: 非同源，403。
        PasswordChangeRequiredError: 必须改密，403。
        ExternalError: 预览、导航或提交依赖失败，502。

    Side Effects:
        只读核对后新增写作业及提交日志；冲突不提交、不写导航。

    Time Semantics:
        使用请求 UTC 时刻，不等待 worker；写入时仍执行锁内复核。
    """
    if error_source_kind(job_id) != "job":
        problem = JobInputError(invalid_field("job_id", "规范正整数编号").diagnostics)
        raise problem
    request = JobRequest(identity(context.account), context.account.now, context.account.audit)
    return response(
        submit_field_write(
            context.service, context.paths, datasets.service.queries.nav_root, request, int(job_id)
        )
    )
