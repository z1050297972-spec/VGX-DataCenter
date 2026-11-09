"""清洗报告只读 HTTP 入口（M4.5-02）；所有登录账号可看，不读取数据盘。"""

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import AwareDatetime, BaseModel, ConfigDict
from sqlalchemy.orm import Session

from rdp.api.account_auth import AccountRequestContext, get_authenticated_context
from rdp.api.account_schemas import AccountId
from rdp.api.database import get_read_session
from rdp.jobs.cleaning.models import CleaningReport
from rdp.jobs.cleaning.records import read_preview

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
