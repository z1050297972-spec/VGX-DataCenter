"""账号 HTTP 声明（06），只做类型与字段约束，不返回 ORM、哈希或会话原文。

所有秘密用 SecretStr、repr=False；不设置任何凭据示例。错误边界只取声明字段名，
不得 stringify ValidationError 或回显 body。响应编号用十进制文本以保留 SQLite 64 位精度。
"""

from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, SecretStr

from rdp.accounts.policy import (
    ACCOUNT_PAGE_LIMIT,
    DISPLAY_NAME_MAX_CHARS,
    LOGIN_NAME_MAX_CHARS,
    LOGIN_NAME_MIN_CHARS,
    LOGIN_NAME_PATTERN,
    PASSWORD_MAX_CHARS,
    PASSWORD_MIN_CHARS,
)
from rdp.accounts.types import AccountStatus, AccountView, Role

AccountId = Annotated[str, Field(strict=True, pattern=r"^[1-9][0-9]{0,18}$", max_length=19)]
LoginName = Annotated[
    str,
    Field(
        strict=True,
        pattern=LOGIN_NAME_PATTERN,
        min_length=LOGIN_NAME_MIN_CHARS,
        max_length=LOGIN_NAME_MAX_CHARS,
    ),
]
DisplayName = Annotated[str, Field(strict=True, min_length=1, max_length=DISPLAY_NAME_MAX_CHARS)]
Password = Annotated[
    SecretStr,
    Field(min_length=PASSWORD_MIN_CHARS, max_length=PASSWORD_MAX_CHARS, repr=False, strict=True),
]


class AccountPayload(BaseModel):
    """统一拒绝额外字段并隐藏校验错误输入的 HTTP 模型基类。

    Attributes:
        model_config: frozen/extra=forbid/hide_input_in_errors 固定配置，不可空、无单位。
    """

    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)


class LoginRequest(AccountPayload):
    """登录请求，只能通过 POST body 传递。

    Attributes:
        login_name: 3-32 位严格小写 ASCII 名称，无单位、不可空、无默认。
        password: 10-128 个 Unicode 码点的 SecretStr，不归一化、不可空、无默认、无单位；不入日志。
    """

    login_name: LoginName
    password: Password


class CreateAccountRequest(LoginRequest):
    """管理员创建账号的请求，不能伪造创建人或状态。

    Attributes:
        login_name: 继承的严格登录名，不可空、无默认、3-32 字符。
        password: 继承的初始 SecretStr，不可空、无默认、10-128 个码点。
        display_name: 1-64 个码点，无首尾空白/控制字符、不可空、无默认。
        role: administrator/member，无单位、不可空、无默认。
    """

    display_name: DisplayName
    role: Role


class RoleRequest(AccountPayload):
    """角色修改请求。

    Attributes:
        role: administrator/member，无单位、不可空、无默认。
    """

    role: Role


class StatusRequest(AccountPayload):
    """启停修改请求。

    Attributes:
        status: enabled/disabled，无单位、不可空、无默认。
    """

    status: AccountStatus


class ResetPasswordRequest(AccountPayload):
    """管理员重置口令请求，不接受解除强制改密标记。

    Attributes:
        password: 新 SecretStr，10-128 个 Unicode 码点，不可空、无默认、无单位。
    """

    password: Password


class ChangePasswordRequest(AccountPayload):
    """本人改口令请求，无目标账号字段。

    Attributes:
        current_password: 当前 SecretStr，10-128 个码点，不可空、无默认、无单位。
        new_password: 新 SecretStr，10-128 个码点，不可空、无默认、不得等于当前口令。
    """

    current_password: Password
    new_password: Password


class ActorResponse(AccountPayload):
    """历史操作者的安全 JSON 表达。

    Attributes:
        account_id: 正整数十进制文本，1 至 2^63-1、无单位、无默认；运维为 null。
        name: 当时显示名，1-64 个码点、不可空、无默认；运维固定“运维”。
    """

    account_id: AccountId | None
    name: DisplayName


class AccountResponse(AccountPayload):
    """账号安全响应，对应领域快照，不含任何秘密或限流内部状态。

    Attributes:
        account_id: 1 至 2^63-1 的规范十进制文本、无单位、不可空、无默认。
        login_name: 严格登录名，3-32 字符、不可空、无默认。
        display_name: 显示名，1-64 个码点、不可空、无默认。
        role: administrator/member，无单位、不可空、无默认。
        status: enabled/disabled，无单位、不可空、无默认。
        must_change_password: 布尔、无单位、不可空、无默认。
        created_at: aware UTC 时刻，微秒精度、不可空、无默认。
        updated_at: aware UTC 修改时刻，微秒精度、不早于创建时刻、不可空、无默认。
        created_by: ActorResponse 快照，不可空、无单位、无默认。
        updated_by: ActorResponse 快照，不可空、无单位、无默认。
    """

    account_id: AccountId
    login_name: LoginName
    display_name: DisplayName
    role: Role
    status: AccountStatus
    must_change_password: bool
    created_at: datetime
    updated_at: datetime
    created_by: ActorResponse
    updated_by: ActorResponse


class AccountListResponse(AccountPayload):
    """管理员账号列表的一页。

    Attributes:
        items: 按内部编号升序的 0-100 条 AccountResponse，不可空、无默认。
        next_after_id: 下一页的规范十进制编号，无单位、无默认；没有后续页为 null。
    """

    items: tuple[AccountResponse, ...] = Field(max_length=ACCOUNT_PAGE_LIMIT)
    next_after_id: AccountId | None


def account_response(account: AccountView) -> AccountResponse:
    """将领域快照转换为不丢编号精度的响应模型。

    Args:
        account: 已经领域校验的 AccountView，不可空、无单位，不接受 ORM 或秘密对象。

    Returns:
        AccountResponse，所有编号转规范十进制文本，时刻为 aware UTC，完整保留人名快照。

    Raises:
        DefectError: 快照字段不符合声明、无效时间或编号越界；输出安全诊断，不返回部分响应。

    Side Effects:
        无；不连接数据库，不读取会话原文，不写日志或改变快照。

    Time Semantics:
        同步转换，保留微秒，不读取时钟。
    """
    raise NotImplementedError
