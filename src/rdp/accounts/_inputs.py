"""账号领域的秘密输入校验，只使用内存值，不查询数据库或分配 Argon2 工作区。"""

import hmac

from pydantic import SecretStr

from rdp.accounts._issues import problem
from rdp.accounts.errors import AccountInputError
from rdp.accounts.policy import (
    PASSWORD_MAX_CHARS,
    PASSWORD_MIN_CHARS,
    PASSWORD_TOO_LONG_MESSAGE,
    PASSWORD_TOO_SHORT_MESSAGE,
)
from rdp.accounts.types import PasswordChange


def password_text(value: object) -> str:
    """只返回已校验的内存密码，拒绝输入时不回显原文。"""
    if not isinstance(value, SecretStr):
        raise problem(AccountInputError, "密码类型不符合要求", field="password")
    raw = value.get_secret_value()
    if len(raw) < PASSWORD_MIN_CHARS:
        raise _password_length_error(PASSWORD_TOO_SHORT_MESSAGE)
    if len(raw) > PASSWORD_MAX_CHARS:
        raise _password_length_error(PASSWORD_TOO_LONG_MESSAGE)
    if any(0xD800 <= ord(c) <= 0xDFFF for c in raw):
        raise problem(AccountInputError, "密码须包含有效的 Unicode 字符", field="password")
    return raw


def _password_length_error(message: str) -> AccountInputError:
    """复用账号诊断结构，仅将密码长度错误的下一步替换为同一句提示。"""
    error = problem(AccountInputError, message, field="password")
    return AccountInputError(
        tuple(item.model_copy(update={"next_step": message}) for item in error.diagnostics)
    )


def password_change(value: object) -> None:
    """在只读预检和哈希开始之前校验两份密码及新旧不同，不回显任一原文。"""
    if not isinstance(value, PasswordChange):
        raise problem(AccountInputError, "改密字段不合法")
    current = password_text(value.current_password)
    fresh = password_text(value.new_password)
    if hmac.compare_digest(current.encode("utf-8"), fresh.encode("utf-8")):
        raise problem(AccountInputError, "新密码不能与当前密码相同")
