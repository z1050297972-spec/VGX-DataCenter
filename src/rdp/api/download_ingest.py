"""下载入库 HTTP 入口（M2-05）；只提交 worker 作业、读取状态目录预览，不访问存储根。"""

from fastapi import APIRouter

from rdp.api._account_context import identity
from rdp.api._job_views import response as _response
from rdp.api.job_schemas import JobResponse
from rdp.api.jobs import JobContext
from rdp.jobs.downloads.ingest_models import (
    INGEST_APPLY_TYPE,
    INGEST_PREVIEW_TYPE,
    IngestConfirmation,
    IngestOptions,
    IngestParameters,
    IngestPreviewView,
)
from rdp.jobs.navwrite.create_models import FormatEntrySelection
from rdp.jobs.navwrite.create_service import CreationAccess, read_creation_options
from rdp.jobs.navwrite.create_views import CreationJobId
from rdp.jobs.navwrite.errors import nav_input_error
from rdp.jobs.navwrite.previews import read_preview
from rdp.jobs.outcome import JobOutcome
from rdp.jobs.service import JobRequest
from rdp.jobs.types import JobState

router = APIRouter(prefix="/api/jobs", tags=["download-ingest"])


def _request(context: JobContext) -> JobRequest:
    """复用请求的唯一时刻、身份和操作日志上下文。"""
    return JobRequest(identity(context.account), context.account.now, context.account.audit)


def _formats(context: JobContext, version: str | None) -> tuple[FormatEntrySelection, ...]:
    """候选来自 M1 登记和索引，额外包含本次刚读到的 LeRobot 版本。"""
    access = CreationAccess(context.service.engine, context.paths, context.service)
    options = read_creation_options(access, _request(context))
    result: list[FormatEntrySelection] = []
    for item in options.formats:
        versions = set(item.versions)
        if item.format == "lerobot" and version is not None:
            versions.add(version)
        if item.has_versions:
            result.extend(
                FormatEntrySelection(format=item.format, version=value)
                for value in sorted(versions)
            )
        else:
            result.append(FormatEntrySelection(format=item.format))
    return tuple(result)


def _read(context: JobContext, identifier: int) -> IngestPreviewView:
    """认证查询后只读取成功的入库预览，不向 Web 暴露可执行计划正文。"""
    record = context.service.get(_request(context), identifier)
    if (
        record.type_name != INGEST_PREVIEW_TYPE
        or record.state is not JobState.COMPLETED
        or record.summary is None
        or record.summary.outcome is not JobOutcome.SUCCEEDED
    ):
        raise nav_input_error("DOWNLOAD_INGEST", "请先完成入库预览")
    preview = read_preview(context.paths, identifier)
    details = preview.report.creation
    if details is None:
        raise nav_input_error("DOWNLOAD_INGEST", "预览缺少创建计划")
    return IngestPreviewView.model_validate(
        {
            "preview_job_id": str(identifier),
            "parameters": preview.parameters["input"],
            "fields": preview.parameters["fields"],
            "checks": tuple(check.detail for check in preview.report.checks),
            "notices": tuple(notice.message for notice in preview.report.notices),
            "format_entry_options": _formats(context, details.resolved_version),
        }
    )


@router.post(
    "/{job_id}/download-ingest-preview",
    response_model=JobResponse,
    status_code=201,
    operation_id="submit_download_ingest_preview",
)
def submit_ingest_preview(
    context: JobContext, job_id: CreationJobId, body: IngestOptions
) -> JobResponse:
    """为成功的数据集下载提交入库预览。

    Args:
        context: 当前成员身份、唯一 UTC 请求时刻与作业服务。
        job_id: 下载编号的规范十进制文本，正数且不超过 SQLite 整数范围。
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
    parameters = IngestParameters(download_job_id=int(job_id), **body.model_dump())
    return _response(
        context.service.submit(
            _request(context), INGEST_PREVIEW_TYPE, parameters.model_dump(mode="json")
        ),
        role=identity(context.account).account.role,
    )


@router.get(
    "/{job_id}/download-ingest-preview",
    response_model=IngestPreviewView,
    operation_id="get_download_ingest_preview",
)
def get_ingest_preview(context: JobContext, job_id: CreationJobId) -> IngestPreviewView:
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
    "/download-ingest",
    response_model=JobResponse,
    status_code=201,
    operation_id="confirm_download_ingest",
)
def confirm_ingest(context: JobContext, body: IngestConfirmation) -> JobResponse:
    """确认同一份成功预览并提交下载入库写作业。

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
