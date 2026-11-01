"""HF 凭据的管理员入口；只操作状态目录，不访问任何存储根。"""

import os
import re
import tempfile
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, SecretStr, field_validator
from sqlalchemy.orm import Session

from rdp.accounts._sessions import authorize
from rdp.accounts.models import AccountRow
from rdp.api._account_context import identity
from rdp.api.account_auth import AccountRequestContext, get_admin_context
from rdp.api.jobs import get_job_context
from rdp.audit.records import append_operation
from rdp.audit.types import (
    AuditContext,
    AuditValues,
    ObjectRef,
    OperationDetails,
    OperationEvent,
    OperationResult,
    OperationType,
)
from rdp.infra.actors import ActorRef
from rdp.infra.db.connection import session_scope
from rdp.jobs.downloads.plan import CREDENTIAL_FILENAME

router = APIRouter(prefix="/api/downloads", tags=["downloads"])
Admin = Annotated[AccountRequestContext, Depends(get_admin_context)]


class TokenInput(BaseModel):
    """密钥仅存在于请求内存，不进入作业参数或模型 repr。"""

    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    token: SecretStr

    @field_validator("token")
    @classmethod
    def _valid_token(cls, value: SecretStr) -> SecretStr:
        """与下载计划的 HTTP 头规则一致，拒绝空值、空白和非 ASCII。"""
        if re.fullmatch(r"[!-~]+", value.get_secret_value()) is None:
            raise ValueError("令牌必须为非空 ASCII 可见字符")
        return value


class TokenState(BaseModel):
    """只返回凭据是否存在，不返回内容。"""

    configured: bool


@router.get("/token", response_model=TokenState, operation_id="get_download_token")
def get_download_token(request: Request, context: Admin) -> TokenState:
    """读取状态目录中的凭据存在性。

    Args:
        request: 当前请求。
        context: 管理员上下文。

    Returns:
        是否设置凭据，不包含凭据内容。

    Raises:
        ExternalError: 状态服务不可用。

    Side Effects:
        只查询状态目录。

    Time Semantics:
        返回读取时刻的快照。
    """
    paths = get_job_context(request, context).paths
    return TokenState(configured=(paths.root / CREDENTIAL_FILENAME).is_file())


@router.put("/token", response_model=TokenState, operation_id="set_download_token")
def set_download_token(request: Request, context: Admin, body: TokenInput) -> TokenState:
    """将管理员提供的凭据写入私有状态目录。

    Args:
        request: 当前请求。
        context: 管理员身份和请求时刻。
        body: 不回显的密钥。

    Returns:
        设置完成状态，不包含密钥。

    Raises:
        AuthorizationError: 事务中会话或权限失效。
        OSError: 状态目录不可写。

    Side Effects:
        在状态目录写入权限为 0600 的凭据文件，同时追加不含凭据的操作日志。

    Time Semantics:
        先重验管理员身份，再同步写入；不访问存储根。
    """
    paths = get_job_context(request, context).paths
    with session_scope(request.app.state.database_engine) as session:
        actor = authorize(session, identity(context), context.now, admin=True)
        _audit_change(session, context, actor, OperationType.SET_DOWNLOAD_TOKEN)
        # 临时文件与目标同目录，原子替换使 worker 不会读到截断的凭据。
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=paths.root, delete=False
        ) as stream:
            temporary = Path(stream.name)
            try:
                stream.write(body.token.get_secret_value())
                stream.flush()
                os.fchmod(stream.fileno(), 0o600)
                Path(temporary).replace(paths.root / CREDENTIAL_FILENAME)
            finally:
                temporary.unlink(missing_ok=True)
    return TokenState(configured=True)


@router.delete("/token", response_model=TokenState, operation_id="clear_download_token")
def clear_download_token(request: Request, context: Admin) -> TokenState:
    """清除管理员设置的凭据。

    Args:
        request: 当前请求。
        context: 管理员身份和请求时刻。

    Returns:
        未设置状态。

    Raises:
        AuthorizationError: 事务中会话或权限失效。
        OSError: 凭据无法删除。

    Side Effects:
        删除状态目录中的凭据并追加不含凭据的操作日志，不访问存储根。

    Time Semantics:
        先重验管理员身份，再同步清除。
    """
    paths = get_job_context(request, context).paths
    with session_scope(request.app.state.database_engine) as session:
        actor = authorize(session, identity(context), context.now, admin=True)
        _audit_change(session, context, actor, OperationType.CLEAR_DOWNLOAD_TOKEN)
        (paths.root / CREDENTIAL_FILENAME).unlink(missing_ok=True)
    return TokenState(configured=False)


def _audit_change(
    session: Session, context: AccountRequestContext, account: AccountRow, operation: OperationType
) -> None:
    """沿用账号对象格式但只重复操作人，不写 token、状态、IP 或请求编号。"""
    actor = ActorRef(account.account_id, account.display_name)
    append_operation(
        session,
        OperationEvent(
            occurred_at=context.now,
            actor=actor,
            operation=operation,
            # 日志现有对象模型要求目标；以操作人账号复用其身份，不额外记录凭据属性。
            target=ObjectRef("account", str(account.account_id), account.display_name),
            result=OperationResult.SUCCESS,
            failure_category=None,
            context=AuditContext(source_ip=None, request_id=None),
            details=OperationDetails(before=AuditValues(), after=AuditValues()),
        ),
    )
