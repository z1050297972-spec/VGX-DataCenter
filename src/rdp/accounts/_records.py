"""账号领域的输入规则和 ORM 快照适配；只操作显式会话，不拥有事务或日志。"""

import re
import unicodedata
from datetime import datetime
from typing import cast

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from rdp.accounts._issues import problem
from rdp.accounts.errors import AccountInputError, AccountNotFoundError
from rdp.accounts.models import AccountRow
from rdp.accounts.policy import DISPLAY_NAME_MAX_CHARS, LOGIN_NAME_PATTERN, LOGIN_WAIT
from rdp.accounts.types import AccountStatus, AccountView, ActorRef, Credentials, NewAccount, Role
from rdp.infra.diagnostics import ConflictError, InputError
from rdp.infra.ids import MAX_SQLITE_INTEGER
from rdp.infra.timeutil import ensure_utc


def utc(value: object, *, wait: bool = False) -> datetime:
    """校验显式时刻；只在需要新等待截止的调用中检查加时溢出。"""
    try:
        if not isinstance(value, datetime):
            raise ValueError()
        result = ensure_utc(value)
        if wait:
            _ = result + LOGIN_WAIT
        return result
    except (ValueError, TypeError, OverflowError):
        raise problem(AccountInputError, "时刻必须是可表示的带时区时间", field="now") from None


def login_name(value: object) -> str:
    """登录名严格匹配，不通过修剪或大小写变换悄悄改变身份。"""
    if not isinstance(value, str) or re.fullmatch(LOGIN_NAME_PATTERN, value) is None:
        raise problem(AccountInputError, "登录名须为 3 至 32 位小写 ASCII 标识", field="login_name")
    return value


def display_name(value: object) -> str:
    """只接受可显示的短名字，拒绝首尾空白及控制字符。"""
    if (
        not isinstance(value, str)
        or not 1 <= len(value) <= DISPLAY_NAME_MAX_CHARS
        or value.strip() != value
        or any(unicodedata.category(c) in {"Cc", "Cf", "Cs"} for c in value)
    ):
        raise problem(
            AccountInputError,
            "显示名须为无首尾空白或控制字符的 1 至 64 个码点",
            field="display_name",
        )
    return value


def identifier(value: object, *, zero: bool = False) -> int:
    """限制编号范围并拒绝 bool，游标显式允许零。"""
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or not (0 if zero else 1) <= value <= MAX_SQLITE_INTEGER
    ):
        raise problem(AccountInputError, "编号超出允许范围", field="account_id")
    return value


def new_account(value: object) -> NewAccount:
    """校验新建命令的非秘密字段，口令交给 PasswordCodec。"""
    if (
        not isinstance(value, NewAccount)
        or not isinstance(cast(object, value.credentials), Credentials)
        or not isinstance(cast(object, value.role), Role)
    ):
        raise problem(AccountInputError, "新账号字段或角色不合法")
    login_name(value.credentials.login_name)
    display_name(value.display_name)
    return value


def view(row: AccountRow) -> AccountView:
    """只复制安全字段，损坏存量值统一归输入数据问题，不返回 ORM 或哈希。"""
    try:
        return AccountView(
            identifier(row.account_id),
            login_name(row.login_name),
            display_name(row.display_name),
            Role(row.role),
            AccountStatus(row.status),
            row.must_change_password,
            ensure_utc(row.created_at),
            ensure_utc(row.updated_at),
            ActorRef(row.created_by_id, display_name(row.created_by_name)),
            ActorRef(row.updated_by_id, display_name(row.updated_by_name)),
        )
    except (ValueError, TypeError, OverflowError, AccountInputError):
        raise problem(InputError, "账号存量数据不符合声明") from None


def make_row(
    command: NewAccount, encoded: str, actor: ActorRef, now: datetime, force: bool
) -> AccountRow:
    """把已验证的命令和预计算哈希组合成新行，不执行 SQL。"""
    return AccountRow(
        login_name=command.credentials.login_name,
        display_name=command.display_name,
        role=command.role.value,
        status=AccountStatus.ENABLED.value,
        password_hash=encoded,
        must_change_password=force,
        created_at=now,
        updated_at=now,
        created_by_id=actor.account_id,
        created_by_name=actor.name,
        updated_by_id=actor.account_id,
        updated_by_name=actor.name,
        failed_attempts=0,
        blocked_until=None,
    )


def require_no_admin(session: Session) -> None:
    """首号必须在写锁内再核验；停用管理员也算已经存在。"""
    if session.scalar(
        select(func.count())
        .select_from(AccountRow)
        .where(AccountRow.role == Role.ADMINISTRATOR.value)
    ):
        raise problem(ConflictError, "已存在管理员，不能创建首个管理员")


def target(session: Session, key: int) -> AccountRow:
    """只按已校验的内部编号查询，目标不存在时给管理员可用的404诊断。"""
    row = session.get(AccountRow, key)
    if row is None:
        raise problem(AccountNotFoundError, "账号不存在", account_id=key)
    return row


def keep_admin(session: Session, row: AccountRow) -> None:
    """调用方持写锁且将移除当前启用管理员资格时，再计算不变量。"""
    if row.role != Role.ADMINISTRATOR.value or row.status != AccountStatus.ENABLED.value:
        return
    count = (
        session.scalar(
            select(func.count())
            .select_from(AccountRow)
            .where(
                AccountRow.role == Role.ADMINISTRATOR.value,
                AccountRow.status == AccountStatus.ENABLED.value,
            )
        )
        or 0
    )
    if count <= 1:
        raise problem(ConflictError, "至少保留一个启用的管理员", account_id=row.account_id)


def stamp(row: AccountRow, actor: ActorRef, now: datetime) -> None:
    """保留当时的人名快照，回拨不能倒退已有修改时刻。"""
    row.updated_by_id, row.updated_by_name = actor.account_id, actor.name
    row.updated_at = max(row.updated_at, now)
