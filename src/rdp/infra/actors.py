"""基础层的历史身份值对象和共用名字规则（06/07），不查账号、不依赖领域服务。

从 accounts.types 搬移同一个 ActorRef 并由原路径再导出，以允许 accounts → audit
而不产生 audit → accounts 的环；编号和当时显示名的既有契约不变。
"""

import unicodedata
from dataclasses import dataclass
from typing import TypeGuard


@dataclass(frozen=True)
class ActorRef:
    """可在账号删除后继续显示的操作者身份快照。

    Attributes:
        account_id: 内部编号，1 至 2^63-1，无单位、无默认；仅固定运维或系统身份为 None，不建外键。
        name: 当时的显示名，1-64 个 Unicode 码点、无首尾空白或控制字符、不可空、无默认；
            account_id 为 None 时仅“运维”或“系统”；作业提交只允许其中的“系统”。
    """

    account_id: int | None
    name: str


# 06/07 运维命令的固定历史身份，不创建账号行；不可变对象由写入及校验共用。
OPS_ACTOR = ActorRef(None, "运维")
# 09：定时提交没有账号行；不可冒用运维身份，查询时不标记为已删除。
SYSTEM_ACTOR = ActorRef(None, "系统")

# 06 显示名与 07 历史名字共用码点上限；放在基础层避免日志反向依赖账号领域。
DISPLAY_NAME_MAX_CHARS = 64


def is_display_name(value: object) -> TypeGuard[str]:
    """判断当前名字或历史快照是否符合统一的 Unicode 名字规则。

    Args:
        value: 未信任输入；仅接受 1-64 个 Unicode 码点的字符串，无首尾空白，
            排除 Cc、Cf、Cs 类别；不排除私用区字符，不做归一化。

    Returns:
        合法为 True，同时将输入类型收窄为 str；其他输入为 False。

    Raises:
        无。

    Side Effects:
        无；不改写输入、不访问账号或日志。

    Time Semantics:
        同步检查至多 64 个码点，无时钟或等待。
    """
    return (
        isinstance(value, str)
        and 1 <= len(value) <= DISPLAY_NAME_MAX_CHARS
        and value.strip() == value
        and not any(unicodedata.category(character) in {"Cc", "Cf", "Cs"} for character in value)
    )
