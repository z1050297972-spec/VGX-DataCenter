"""账号领域登录事务编排；验证在事务外，G2/会话与登录日志原子提交，拒绝和故障各只记一次。"""

from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from datetime import datetime

from sqlalchemy import Engine, select

from rdp.accounts import _records as records
from rdp.accounts import _sessions as sessions
from rdp.accounts.models import AccountRow
from rdp.accounts.security import PasswordCheck, PasswordCodec
from rdp.accounts.types import AccountStatus, ActorRef, Credentials, SessionGrant
from rdp.audit.policy import (
    AUDIT_APPEND_FAILED,
    AUDIT_SHORT_LOCK_TIMEOUT_MS,
    LOGIN_AUDIT_APPEND_FAILED,
)
from rdp.audit.records import append_login
from rdp.audit.service import append_failed_login, append_missing_login
from rdp.audit.types import AuditContext, LoginEvent, LoginKind, LoginResult
from rdp.infra.db.connection import session_scope, session_scope_with_lock_timeout
from rdp.infra.diagnostics import (
    ConflictError,
    DefectError,
    DiagnosticCategory,
    ExternalError,
    InputError,
)


@dataclass
class LoginAttempt:
    """一次登录执行的安全记录状态，ORM字段排除repr，不能把本对象写日志。

    Attributes:
        now: 请求注入的UTC微秒时刻，不可空。
        audit: 入口提供的来源及请求编号，不可空。
        row: 只读阶段得到的原账号；尚未确认或不存在时None，排除repr。
        known_missing: 已明确查询不到账号为True，默认False。
        recorded: 业务结果已落日志，或拒绝补记已尝试；默认False，防止重复记录。
    """

    now: datetime
    audit: AuditContext
    row: AccountRow | None = field(default=None, repr=False)
    known_missing: bool = False
    recorded: bool = False


def event(
    state: LoginAttempt,
    row: AccountRow | None,
    result: LoginResult,
    *,
    category: DiagnosticCategory | None = None,
) -> LoginEvent:
    """只从已存身份构造事件，匿名记录不带输入登录名或请求编号。"""
    account = None if row is None else records.view(row)
    return LoginEvent(
        state.now,
        None if account is None else ActorRef(account.account_id, account.display_name),
        None if account is None else account.login_name,
        LoginKind.LOGIN,
        result,
        replace(state.audit, request_id=None) if account is None else state.audit,
        category,
    )


@contextmanager
def attempt(engine: Engine, now: datetime, audit: AuditContext) -> Generator[LoginAttempt]:
    """执行故障在原事务退出后补记；补记自身失败只标记原错误，不递归或替换类别。"""
    state = LoginAttempt(now, audit)
    try:
        yield state
    except Exception as error:
        if not state.recorded:
            try:
                if state.known_missing:
                    append_missing_login(engine, event(state, None, LoginResult.ACCOUNT_MISSING))
                else:
                    category = (
                        error.category
                        if isinstance(
                            error, (InputError, ConflictError, ExternalError, DefectError)
                        )
                        else DiagnosticCategory.DEFECT
                    )
                    append_failed_login(
                        engine, event(state, state.row, LoginResult.FAILURE, category=category)
                    )
            except Exception:
                error.add_note(AUDIT_APPEND_FAILED)
                error.add_note(LOGIN_AUDIT_APPEND_FAILED)
        raise


def reject(engine: Engine, state: LoginAttempt, failure: InputError, result: LoginResult) -> None:
    """保持原登录拒绝；短事务只重读原编号，删除或同名重建按匿名记录处理。"""
    state.recorded = True
    try:
        if state.row is None:
            append_missing_login(engine, event(state, None, LoginResult.ACCOUNT_MISSING))
        else:
            with session_scope_with_lock_timeout(
                engine, busy_timeout_ms=AUDIT_SHORT_LOCK_TIMEOUT_MS
            ) as session:
                row = session.get(AccountRow, state.row.account_id)
                append_login(
                    session,
                    event(state, row, LoginResult.ACCOUNT_MISSING if row is None else result),
                )
    except Exception:
        failure.add_note(AUDIT_APPEND_FAILED)
        failure.add_note(LOGIN_AUDIT_APPEND_FAILED)
    raise failure


def apply(
    engine: Engine, state: LoginAttempt, checked: PasswordCheck
) -> tuple[SessionGrant | None, InputError | None]:
    """在已有写事务重验快照，将实际判定、G2和会话同一次提交。"""
    previous = state.row
    if previous is None:
        raise DefectError()
    grant: SessionGrant | None = None
    failure: InputError | None = None
    with session_scope(engine) as session:
        row = session.get(AccountRow, previous.account_id)
        if row is None:
            result, failure = LoginResult.ACCOUNT_MISSING, sessions.authentication_error()
        elif row.status != AccountStatus.ENABLED.value:
            result, failure = LoginResult.DISABLED, sessions.authentication_error()
        elif (waiting := sessions.wait_error(row, state.now)) is not None:
            result, failure = LoginResult.WAITING, waiting
        else:
            row = sessions.confirm(row, previous, state.now)
            if not checked.matched:
                failure = sessions.wrong_password(row, state.now)
                result = LoginResult.WRONG_PASSWORD
            else:
                row.failed_attempts, row.blocked_until = 0, None
                if checked.replacement_hash is not None:
                    row.password_hash = checked.replacement_hash
                grant = sessions.grant(session, row, state.now)
                result = LoginResult.SUCCESS
        append_login(session, event(state, row, result))
    return grant, failure


def login(
    engine: Engine,
    passwords: PasswordCodec,
    credentials: Credentials,
    now: datetime,
    audit: AuditContext,
) -> SessionGrant:
    """将正常拒绝与执行故障区分，所有口令计算在数据库事务之外完成。"""
    with attempt(engine, now, audit) as state:
        with session_scope(engine, read_only=True) as session:
            state.row = session.scalar(
                select(AccountRow).where(AccountRow.login_name == credentials.login_name)
            )
        state.known_missing = state.row is None
        if state.row is None or state.row.status != AccountStatus.ENABLED.value:
            passwords.verify(None, credentials.password)
            reject(engine, state, sessions.authentication_error(), LoginResult.DISABLED)
        if state.row is None:
            raise DefectError()
        waiting = sessions.wait_error(state.row, now)
        if waiting is not None:
            reject(engine, state, waiting, LoginResult.WAITING)
        checked = passwords.verify(state.row.password_hash, credentials.password)
        result, failure = apply(engine, state, checked)
        state.recorded = True
        if failure is not None:
            raise failure
        if result is None:
            raise DefectError()
        return result
