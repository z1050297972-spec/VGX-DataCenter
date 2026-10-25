"""账号领域的秘密输入校验，只使用内存值，不查询数据库或分配 Argon2 工作区。"""

from pydantic import SecretStr

from rdp.accounts._issues import problem
from rdp.accounts.errors import AccountInputError
from rdp.accounts.policy import PASSWORD_MAX_CHARS, PASSWORD_MIN_CHARS


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
