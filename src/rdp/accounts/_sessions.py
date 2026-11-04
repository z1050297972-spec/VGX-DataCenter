"""账号领域的会话与G2状态转换；只操作调用者给定会话，绝不调用 Argon2。"""

import hmac
import math
from datetime import datetime
from typing import cast

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from rdp.accounts import _records as records
from rdp.accounts._issues import problem
from rdp.accounts.errors import (
    AuthenticationError,
    AuthorizationError,
    CurrentPasswordError,
    LoginWaitError,
    PasswordChangeRequiredError,
)
from rdp.accounts.models import AccountRow, SessionRow
from rdp.accounts.policy import (
    ACCOUNT_SESSION_LIMIT,
    LOGIN_FAILURE_LIMIT,
    LOGIN_WAIT,
    SESSION_IDLE_TIMEOUT,
)
from rdp.accounts.security import new_session_token, session_digest
from rdp.accounts.types import AccountStatus, Role, SessionGrant, SessionIdentity
from rdp.infra.diagnostics import ConflictError, InputError


def authentication_error() -> AuthenticationError:
    """统一凭据错误的外部诊断，不包含登录名、密码或令牌。"""
    return problem(AuthenticationError, "账号或密码错误")


def wait_error(row: AccountRow, now: datetime) -> LoginWaitError | None:
    """已有等待只计算剩余秒数，回拨时最多返回60秒而不重写截止。"""
    if row.blocked_until is None or now >= row.blocked_until:
        return None
    seconds = min(60, max(1, math.ceil((row.blocked_until - now).total_seconds())))
    diagnostic = problem(
        InputError, f"还需等待 {seconds} 秒", expected="连续错误后的等待已经结束"
    ).diagnostics
    return LoginWaitError(diagnostic, retry_after_s=seconds)


def confirm(row: AccountRow | None, previous: AccountRow, now: datetime) -> AccountRow:
    """写锁内比较原始密码和G2状态，绝不把过时的验证结果用于提交。"""
    if row is None or row.status != AccountStatus.ENABLED.value:
        raise authentication_error()
    waiting = wait_error(row, now)
    if waiting is not None:
        raise waiting
    if not hmac.compare_digest(row.password_hash, previous.password_hash) or (
        row.failed_attempts,
        row.blocked_until,
    ) != (previous.failed_attempts, previous.blocked_until):
        raise problem(ConflictError, "账号状态已变化，请重试")
    return row


def wrong_password(row: AccountRow, now: datetime, *, current: bool = False) -> InputError:
    """返回应在计数提交后抛出的拒绝，不能在事务中抛出而回滚失败计数。"""
    count = 0 if row.blocked_until is not None and now >= row.blocked_until else row.failed_attempts
    row.failed_attempts = count + 1
    if row.failed_attempts >= LOGIN_FAILURE_LIMIT:
        row.failed_attempts = LOGIN_FAILURE_LIMIT
        row.blocked_until = now + LOGIN_WAIT
        waiting = wait_error(row, now)
        if waiting is not None:
            return waiting
    row.blocked_until = None
    if current:
        return problem(CurrentPasswordError, "当前密码不正确", field="current_password")
    return authentication_error()


def grant(session: Session, row: AccountRow, now: datetime) -> SessionGrant:
    """先淘汰已有旧会话再新建，回拨时也不能把刚签发的会话立即淘汰。"""
    oldest = (
        select(SessionRow.token_digest)
        .where(SessionRow.account_id == row.account_id)
        .order_by(SessionRow.created_at.desc(), SessionRow.token_digest.desc())
        .offset(ACCOUNT_SESSION_LIMIT - 1)
    )
    session.execute(
        delete(SessionRow).where(SessionRow.token_digest.in_(oldest)),
        execution_options={"synchronize_session": False},
    )
    token = new_session_token()
    digest = session_digest(token)
    session.add(
        SessionRow(token_digest=digest, account_id=row.account_id, created_at=now, last_seen_at=now)
    )
    return SessionGrant(SessionIdentity(records.view(row), digest, now, False), token)


def load(session: Session, digest: str) -> tuple[AccountRow, SessionRow]:
    """每次重新读取账号状态，不把旧身份快照当成权限缓存。"""
    saved = session.get(SessionRow, digest)
    if saved is None or not hmac.compare_digest(saved.token_digest, digest):
        raise authentication_error()
    account = session.get(AccountRow, saved.account_id)
    if account is None or account.status != AccountStatus.ENABLED.value:
        raise authentication_error()
    records.view(account)
    return account, saved


def identity(account: AccountRow, saved: SessionRow, refreshed: bool = False) -> SessionIdentity:
    """只返回安全账号快照，刷新标记须由已提交事务的调用者确认。"""
    return SessionIdentity(records.view(account), saved.token_digest, saved.last_seen_at, refreshed)


def authorize(
    session: Session,
    previous: SessionIdentity,
    now: datetime,
    *,
    admin: bool = False,
    allow_change: bool = False,
) -> AccountRow:
    """业务事务重新认证和授权，不信任调用者快照中的角色或强制改密标志。"""
    if not isinstance(cast(object, previous), SessionIdentity):
        raise authentication_error()
    account, saved = load(session, previous.token_digest)
    if (
        account.account_id != previous.account.account_id
        or now - saved.last_seen_at >= SESSION_IDLE_TIMEOUT
    ):
        raise authentication_error()
    if account.must_change_password and not allow_change:
        raise problem(PasswordChangeRequiredError, "必须先修改密码")
    if admin and account.role != Role.ADMINISTRATOR.value:
        raise problem(AuthorizationError, "需要管理员权限")
    return account


def revoke_all(session: Session, account_id: int) -> None:
    """与账号变更共用调用方写事务，不单独提交。"""
    session.execute(delete(SessionRow).where(SessionRow.account_id == account_id))
