"""清洗报告与转换提交 HTTP 入口（M4.5）；报告所有登录账号可看，转换仅管理员，不读取数据盘。"""

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import AwareDatetime, BaseModel, ConfigDict
from sqlalchemy.orm import Session

from rdp.api._account_context import identity
from rdp.api._job_views import response
from rdp.api.account_auth import AccountRequestContext, get_admin_context, get_authenticated_context
from rdp.api.account_schemas import AccountId
from rdp.api.database import get_read_session
from rdp.api.job_schemas import JobResponse
from rdp.api.jobs import JobContext
from rdp.api.storage import StorageInspector, list_storage_roots
from rdp.api.storage_schemas import StorageRootResponse
from rdp.infra.db.validation import invalid_field
from rdp.jobs.cleaning.models import CleaningReport
from rdp.jobs.cleaning.records import read_preview
from rdp.jobs.conversion._cleaning_selection import select
from rdp.jobs.conversion._output_storage import default_dataset_name
from rdp.jobs.conversion.parameters import (
    ConversionOptions,
    ConversionParameters,
    conversion_type_name,
)
from rdp.jobs.datasets.models import DatasetRow
from rdp.jobs.errors import JobInputError, JobNotFoundError
from rdp.jobs.records import find_job
from rdp.jobs.service import JobRequest

router = APIRouter(prefix="/api/cleaning-previews", tags=["cleaning-previews"])


class CleaningPreviewResponse(BaseModel):
    """预览身份和报告；作业编号沿用 API 十进制字符串，created_at 为 UTC。"""

    model_config = ConfigDict(frozen=True, extra="forbid")
    job_id: AccountId
    dataset_id: str
    tool_name: str
    robot_model: str
    binary_sha256: str
    config_sha256: str
    rules_sha256: str
    created_at: AwareDatetime
    report: CleaningReport


@router.get(
    "/{job_id}", response_model=CleaningPreviewResponse, operation_id="get_cleaning_preview"
)
def get_cleaning_preview(
    job_id: AccountId,
    account: Annotated[AccountRequestContext, Depends(get_authenticated_context)],
    session: Annotated[Session, Depends(get_read_session, scope="function")],
) -> CleaningPreviewResponse:
    """向任意登录账号返回指定作业的成功清洗报告。

    Args:
        job_id: 1 至 2^63-1 的规范十进制作业编号。
        account: 已认证且无需强制改密的请求身份。
        session: 响应发送前关闭的只读数据库事务。

    Returns:
        身份、三个完整 SHA-256、UTC 生成时刻及版本一报告。

    Raises:
        JobNotFoundError: 作业不存在、未成功完成或不是预览作业，返回 404。
        AuthenticationError: 未登录或会话无效，返回 401。
        DefectError: 存库报告版本或结构无法识别，返回 500。
        ExternalError: 数据库不可读取，返回 502。

    Side Effects:
        无（只读报告表，不重算清洗结果）。

    Time Semantics:
        当前事务快照，不等待运行中的预览完成。
    """
    preview = read_preview(session, int(job_id))
    return CleaningPreviewResponse.model_validate(
        preview.model_dump() | {"job_id": str(preview.job_id)}
    )


class ConversionDestinationResponse(StorageRootResponse):
    """挂载快照与预计位置；模板中的 {job_id} 是未来转换编号，不是预览编号。"""

    staging_template: str
    expected_output_path: str


class ConversionDestinationsResponse(BaseModel):
    """未预留、未检查占用的预计输出位置，顺序沿用登记根。"""

    model_config = ConfigDict(frozen=True, extra="forbid")
    items: tuple[ConversionDestinationResponse, ...]


@router.get(
    "/{job_id}/destinations",
    response_model=ConversionDestinationsResponse,
    operation_id="get_conversion_destinations",
)
def get_conversion_destinations(
    job_id: AccountId,
    inspector: StorageInspector,
    session: Annotated[Session, Depends(get_read_session, scope="function")],
) -> ConversionDestinationsResponse:
    """返回成功预览可选输出根的挂载快照及未预留的预计位置。

    Args:
        job_id: 成功清洗预览的正整数编号文本。
        inspector: 已登录请求的挂载元信息检查器，不持有存储目录访问能力。
        session: 当前只读数据库事务，读取预览与输入数据集名称。

    Returns:
        所有登记根及 UTC checked_at；暂存模板保留未来转换编号占位符。

    Raises:
        JobNotFoundError: 预览不存在或未成功，返回 404。
        JobInputError: 输入数据集索引缺失，返回 422。
        AuthenticationError: 未登录，返回 401。
        ExternalError: 数据库或挂载元信息读取失败，返回 502。
        DefectError: 挂载检查依赖或时钟非法，返回 500。

    Side Effects:
        无（只读数据库、挂载表和设备元信息）；不 stat/listdir 存储根，不读取容量或预留位置。

    Time Semantics:
        每次请求重新核对挂载；实际可达性和容量由 worker 执行前有界检查。
    """
    preview = read_preview(session, int(job_id))
    dataset = session.get(DatasetRow, preview.dataset_id)
    if dataset is None:
        raise JobInputError(invalid_field("dataset_id", "仍存在的数据集索引").diagnostics)
    name = default_dataset_name(dataset.name)
    return ConversionDestinationsResponse(
        items=tuple(
            ConversionDestinationResponse(
                **item.model_dump(),
                staging_template=str(Path(item.path) / "暂存/转换/{job_id}/out"),
                expected_output_path=str(Path(item.path) / "转换" / name),
            )
            for item in list_storage_roots(inspector).items
        )
    )


@router.post(
    "/{job_id}/convert",
    response_model=JobResponse,
    status_code=201,
    operation_id="convert_from_cleaning_preview",
    dependencies=[Depends(get_admin_context)],
)
def convert_from_cleaning_preview(
    job_id: AccountId,
    body: ConversionOptions,
    context: JobContext,
    session: Annotated[Session, Depends(get_read_session, scope="function")],
) -> JobResponse:
    """按管理员的最终选择从成功清洗预览提交转换。

    Args:
        job_id: 1 至 2^63-1 的预览作业编号，十进制字符串。
        body: 输出版本、空间百分比和 GiB 预留，以及报告内的最终剔除身份列表；Alpha 只允许 excluded_files，G2 可按源集剔除。
        context: 已认证管理员、作业服务及请求唯一 UTC 时刻。
        session: 只读数据库事务，仅用于读取预览和原作业输入。

    Returns:
        HTTP 201 的新排队转换作业，输出版本省略时取工具清单首项。

    Raises:
        JobInputError: 预览不存在、选择非法、Alpha 指定段剔除、无剩余文件或 episode，返回 422。
        AuthorizationError: 非管理员，返回 403。
        ExternalError: 数据库或审计写入失败，返回 502。
        ConflictError: 作业提交写锁竞争，返回 409。

    Side Effects:
        保存新作业及审计，不读取工具程序或存储根；剔除列表原样保存。

    Time Semantics:
        使用成功预览的永久快照；排队后由 worker 重新核对指纹和输入元数据。
    """
    try:
        preview = read_preview(session, int(job_id))
    except JobNotFoundError as error:
        raise JobInputError(error.diagnostics) from error
    select(preview, body)
    original = find_job(session, preview.job_id)
    parameters = ConversionParameters.model_validate(
        {
            "dataset_id": preview.dataset_id,
            "source_ids": original.parameters["source_ids"],
            "robot_model": preview.robot_model,
            "cleaning_preview_job_id": preview.job_id,
            # 保留省略状态，让工具参数模型采用清单默认空间百分比。
            **body.model_dump(exclude_unset=True),
        }
    )
    request = JobRequest(identity(context.account), context.account.now, context.account.audit)
    record = context.service.submit(
        request,
        conversion_type_name(preview.tool_name),
        parameters.model_dump(mode="json", exclude_unset=True),
    )
    return response(record, role=identity(context.account).account.role)
