"""转换入库 HTTP 入口（M4-04）；只提交 worker 作业、读取状态目录预览，不访问存储根。"""

from fastapi import APIRouter

from rdp.api._account_context import identity
from rdp.api._job_views import response as _response
from rdp.api.download_ingest import _formats  # pyright: ignore[reportPrivateUsage] # 理由：两类入库共享M1登记候选，不重复规则。
from rdp.api.job_schemas import JobResponse
from rdp.api.jobs import JobContext
from rdp.jobs.conversion.ingest_models import (
    APPLY_TYPE as INGEST_APPLY_TYPE,
)
from rdp.jobs.conversion.ingest_models import (
    CHECK_TYPE as INGEST_PREVIEW_TYPE,
)
from rdp.jobs.conversion.ingest_models import (
    DELETE_TYPE,
    ConversionIngestParameters,
    ConversionIngestPreviewView,
)
from rdp.jobs.conversion.staging import StagingPage, read_staging
from rdp.jobs.downloads.ingest_models import IngestConfirmation, IngestOptions
from rdp.jobs.navwrite.create_views import CreationJobId
from rdp.jobs.navwrite.errors import nav_input_error
from rdp.jobs.navwrite.previews import read_preview
from rdp.jobs.outcome import JobOutcome
from rdp.jobs.service import JobRequest
from rdp.jobs.types import JobState

router = APIRouter(prefix="/api/jobs", tags=["conversion-ingest"])


def _request(context: JobContext) -> JobRequest:
    """复用请求的唯一时刻、身份和操作日志上下文。"""
    return JobRequest(identity(context.account), context.account.now, context.account.audit)


def _read(context: JobContext, identifier: int) -> ConversionIngestPreviewView:
    """认证查询后只读取成功的入库预览，不向 Web 暴露可执行计划正文。"""
    record = context.service.get(_request(context), identifier)
    if (
        record.type_name != INGEST_PREVIEW_TYPE
        or record.state is not JobState.COMPLETED
        or record.summary is None
        or record.summary.outcome not in (JobOutcome.SUCCEEDED, JobOutcome.SUCCEEDED_WITH_WARNINGS)
    ):
        raise nav_input_error("CONVERSION_INGEST", "请先完成入库预览")
    preview = read_preview(context.paths, identifier)
    details = preview.report.creation
    if details is None:
        raise nav_input_error("CONVERSION_INGEST", "预览缺少创建计划")
    return ConversionIngestPreviewView.model_validate(
        {
            "preview_job_id": str(identifier),
            "parameters": preview.parameters["input"],
            "fields": preview.parameters["fields"],
            "check": preview.parameters["check"],
            "checks": tuple(check.detail for check in preview.report.checks),
            "notices": tuple(notice.message for notice in preview.report.notices),
            "format_entry_options": _formats(context, details.resolved_version),
        }
    )


@router.post(
    "/{job_id}/conversion-ingest-preview",
    response_model=JobResponse,
    status_code=201,
    operation_id="submit_conversion_ingest_preview",
)
def submit_ingest_preview(
    context: JobContext, job_id: CreationJobId, body: IngestOptions
) -> JobResponse:
    """为成功转换提交入库预览。

    Args:
        context: 当前成员身份、唯一 UTC 请求时刻与作业服务。
        job_id: 转换编号的规范十进制文本，正数且不超过 SQLite 整数范围。
        body: 可选数据集名、同根相对位置与按格式入口；无绝对路径。

    Returns:
        201，worker 预览作业，不等待检查完成。

    Raises:
        InputError: 编号、参数或作业类型非法。
        AuthenticationError: 会话失效。
        AuthorizationError: 写请求 Origin 非本站。
        ExternalError: 作业数据库不可用。

    Side Effects:
        只原子写入作业与操作日志，不读取数据或导航文件。

    Time Semantics:
        沿用 M0 提交预算，不重试写请求；存储检查由 worker 执行。
    """
    parameters = ConversionIngestParameters(conversion_job_id=int(job_id), **body.model_dump())
    return _response(
        context.service.submit(
            _request(context), INGEST_PREVIEW_TYPE, parameters.model_dump(mode="json")
        ),
        role=identity(context.account).account.role,
    )


@router.get(
    "/{job_id}/conversion-ingest-preview",
    response_model=ConversionIngestPreviewView,
    operation_id="get_conversion_ingest_preview",
)
def get_ingest_preview(context: JobContext, job_id: CreationJobId) -> ConversionIngestPreviewView:
    """读取 worker 保存的入库预览摘要。

    Args:
        context: 已认证账号、作业服务与只读状态目录。
        job_id: 成功预览编号的规范十进制文本。

    Returns:
        名字、相对位置、勾选入口、14 项和检查说明。

    Raises:
        InputError: 作业不是成功预览、过期或文件不可用。
        AuthenticationError: 会话失效。
        ExternalError: 只读查询失败。

    Side Effects:
        只读数据库和状态预览，不访问存储根。

    Time Semantics:
        返回已保存快照；七天过期后要求重新预览。
    """
    return _read(context, int(job_id))


@router.post(
    "/conversion-ingest",
    response_model=JobResponse,
    status_code=201,
    operation_id="confirm_conversion_ingest",
)
def confirm_ingest(context: JobContext, body: IngestConfirmation) -> JobResponse:
    """确认同一份成功预览并提交转换入库写作业。

    Args:
        context: 确认人的身份、UTC 请求时刻及审计来源。
        body: 只有预览编号，不接受修改后的名字、路径或计划。

    Returns:
        201，受导航写门禁保护的排队入库作业。

    Raises:
        InputError: 预览未成功、不可读或编号非法。
        AuthenticationError: 会话失效。
        AuthorizationError: 写请求 Origin 非本站。
        ExternalError: 数据库提交失败。

    Side Effects:
        新增确认人的写作业与操作日志；导航和存储仅由 worker 修改。

    Time Semantics:
        提交立即返回；worker 写前复核并以冲突拒绝过期计划，不自动重试。
    """
    identifier = int(body.preview_job_id)
    _read(context, identifier)
    return _response(
        context.service.submit(
            _request(context),
            INGEST_APPLY_TYPE,
            {"preview_job_id": identifier},
            confirmed_write=True,
        ),
        role=identity(context.account).account.role,
    )


staging_router = APIRouter(prefix="/api/conversions", tags=["conversion-staging"])


@staging_router.get("/staging", operation_id="get_conversion_staging")
def get_staging(context: JobContext, before: CreationJobId | None = None) -> StagingPage:
    """读取转换暂存的作业状态投影。

    Args:
        context: 已认证账号与作业数据库、本机状态目录。
        before: 可选十进制编号游标，读取更早的一页。

    Returns:
        最新50项转换、检查结果和后续游标；大小是最近检查的快照。

    Raises:
        AuthenticationError: 会话失效。
        ExternalError: 数据库或提交记录不可读。

    Side Effects:
        无写入，不读取存储根。

    Time Semantics:
        当前数据库快照；不等待worker完成。
    """
    return read_staging(context.service.engine, context.paths, int(before) if before else None)


@staging_router.post(
    "/{job_id}/delete",
    response_model=JobResponse,
    status_code=201,
    operation_id="delete_conversion_staging",
)
def delete_staging(context: JobContext, job_id: CreationJobId) -> JobResponse:
    """为未入库的转换提交暂存删除，执行前由worker重新核对占用。

    Args:
        context: 管理员身份、请求UTC时刻和审计上下文。
        job_id: 规范正整数转换编号文本。

    Returns:
        201，排队中的删除作业。

    Raises:
        AuthenticationError: 会话失效。
        AuthorizationError: 非管理员或写请求Origin不符合要求。
        InputError: 参数非法。
        ExternalError: 数据库提交失败。

    Side Effects:
        原子增加作业和审计记录；本请求不删除任何文件。

    Time Semantics:
        立即返回；worker在暂存锁内重读已入库和活跃作业状态。
    """
    return _response(
        context.service.submit(_request(context), DELETE_TYPE, {"conversion_job_id": int(job_id)}),
        role=identity(context.account).account.role,
    )
