"""账号领域的不可变快照与命令（06 验收 9），不暴露 ORM 或生成秘密。

ActorRef 使用显示名，符合记录供人阅读的用途；内部编号区分删号后同名重建。
秘密字段用 SecretStr 且排除 repr；仍禁止把对象 dump 或原始异常写入日志。
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from pydantic import SecretStr

# 07 的日志领域复用既有值对象；保留原导入路径，避免 accounts 与 audit 成环。
from rdp.infra.actors import ActorRef as ActorRef


class Role(StrEnum):
    """仅有管理员和成员两种角色。

    Attributes:
        ADMINISTRATOR: 管理员，固定 administrator，无单位、不可空、无默认选择。
        MEMBER: 成员，固定 member，无单位、不可空、无默认选择。
    """

    ADMINISTRATOR = "administrator"
    MEMBER = "member"


class AccountStatus(StrEnum):
    """账号可恢复的启停状态，删除不作为状态保留。

    Attributes:
        ENABLED: 启用，固定 enabled，无单位、不可空、新建账号默认状态。
        DISABLED: 停用，固定 disabled，无单位、不可空、无默认选择。
    """

    ENABLED = "enabled"
    DISABLED = "disabled"


@dataclass(frozen=True)
class AccountView:
    """已脱离数据库会话的账号快照，不包含密码或令牌。

    Attributes:
        account_id: 内部编号，1 至 2^63-1，无单位、不可空、无默认。
        login_name: 唯一登录名，3-32 个小写 ASCII 字符，符合 LOGIN_NAME_PATTERN，不可空、无默认。
        display_name: 显示名，1-64 个 Unicode 码点，无首尾空白或控制字符，不可空、无默认。
        role: Role 两种值之一，无单位、不可空、无默认。
        status: AccountStatus 两种值之一，无单位、不可空、无默认。
        must_change_password: 下次登录必须改密码标记，布尔、无单位、不可空、无默认。
        created_at: 创建时刻，aware UTC、微秒、不可空、无默认。
        updated_at: 修改时刻，aware UTC、微秒、不早于 created_at、不可空、无默认。
        created_by: 创建人编号与当时显示名，不可空、无单位、无默认。
        updated_by: 最后修改人快照，不可空、无单位、无默认。
    """

    account_id: int
    login_name: str
    display_name: str
    role: Role
    status: AccountStatus
    must_change_password: bool
    created_at: datetime
    updated_at: datetime
    created_by: ActorRef
    updated_by: ActorRef


@dataclass(frozen=True)
class SessionIdentity:
    """一次鉴权的身份快照，写操作仍须在自己的事务内重新检查。

    Attributes:
        account: 当前启用账号快照，不可空、无单位、无默认。
        token_digest: SHA-256 小写 64 位 hex，不可空、无默认、无单位；不返回 HTTP，排除 repr。
        last_seen_at: 已持久化活动时刻，aware UTC、微秒、不可空、无默认。
        activity_refreshed: 本次 authenticate 是否实际提交了活动更新，布尔、无单位、不可空、无默认；
            未到刷新间隔、BUSY 跳过或并发请求已刷新时为 False。新签发的会话也为 False，签发单独设置 cookie。
    """

    account: AccountView
    token_digest: str = field(repr=False)
    last_seen_at: datetime
    activity_refreshed: bool


@dataclass(frozen=True)
class SessionGrant:
    """仅入口边界可取令牌以签发或续期 cookie 的结果。

    Attributes:
        identity: 登录/改密的新会话身份，或活动更新已提交且 activity_refreshed=True 的身份；不可空、无单位、无默认。
        token: secrets.token_urlsafe(32) 原文的 SecretStr，43 个 ASCII 字符，不可空、无默认；
            排除 repr，只在内存和 Set-Cookie 里使用，不作为响应模型字段。
    """

    identity: SessionIdentity
    token: SecretStr = field(repr=False)


@dataclass(frozen=True)
class Credentials:
    """待验证的登录凭据，不得作为异常或日志上下文。

    Attributes:
        login_name: 严格登录名，3-32 个小写 ASCII 字符，不可空、无默认。
        password: SecretStr 包装的原文，10-128 个 Unicode 码点，不归一化，不可空、无默认、无单位。
    """

    login_name: str
    password: SecretStr = field(repr=False)


@dataclass(frozen=True)
class NewAccount:
    """管理员建号或运维首号的输入，不携带未经授权的审计身份。

    Attributes:
        credentials: 登录名和初始密码，不可空、无单位、无默认、排除 repr。
        display_name: 1-64 个 Unicode 码点，不可空、无默认、无首尾空白或控制字符。
        role: Role 两种值之一，无单位、不可空、无默认。
    """

    credentials: Credentials = field(repr=False)
    display_name: str
    role: Role


@dataclass(frozen=True)
class PasswordChange:
    """本人改密码所需的两份秘密，不接受指定其他账号。

    Attributes:
        current_password: 当前密码 SecretStr，10-128 个码点，不可空、无默认、无单位、排除 repr。
        new_password: 新密码 SecretStr，同上；必须不同于当前密码，不归一化。
    """

    current_password: SecretStr = field(repr=False)
    new_password: SecretStr = field(repr=False)


@dataclass(frozen=True)
class AccountPage:
    """稳定编号游标的一页账号，允许空页。

    Attributes:
        items: 按内部编号升序的快照元组，0-100 项、不可空、无默认。
        next_after_id: 后续页游标，1 至 2^63-1、无单位、无默认；无下一页为 None。
    """

    items: tuple[AccountView, ...]
    next_after_id: int | None
