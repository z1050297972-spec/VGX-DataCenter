"""账号领域的秘密输入校验，只使用内存值，不查询数据库或分配 Argon2 工作区。"""

import hmac

from pydantic import SecretStr

from rdp.accounts._issues import problem
from rdp.accounts.errors import AccountInputError
from rdp.accounts.policy import PASSWORD_MAX_CHARS, PASSWORD_MIN_CHARS
from rdp.accounts.types import PasswordChange


def password_text(value: object) -> str:
    """只返回已校验的内存口令，拒绝输入时不回显原文。"""
    if not isinstance(value, SecretStr):
        raise problem(AccountInputError, "口令类型不符合要求", field="password")
    raw = value.get_secret_value()
    if not PASSWORD_MIN_CHARS <= len(raw) <= PASSWORD_MAX_CHARS or any(
        0xD800 <= ord(c) <= 0xDFFF for c in raw
    ):
        raise problem(AccountInputError, "口令须为 10 至 128 个有效 Unicode 码点", field="password")
    return raw


def password_change(value: object) -> None:
    """在只读预检和哈希开始之前校验两份口令及新旧不同，不回显任一原文。"""
    if not isinstance(value, PasswordChange):
        raise problem(AccountInputError, "改密字段不合法")
    current = password_text(value.current_password)
    fresh = password_text(value.new_password)
    if hmac.compare_digest(current.encode("utf-8"), fresh.encode("utf-8")):
        raise problem(AccountInputError, "新口令不能与当前口令相同")
