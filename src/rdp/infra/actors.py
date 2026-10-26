"""基础层的历史身份值对象（06/07），不查账号、不依赖领域服务。

从 accounts.types 搬移同一个 ActorRef 并由原路径再导出，以允许 accounts → audit
而不产生 audit → accounts 的环；编号和当时显示名的既有契约不变。
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class ActorRef:
    """可在账号删除后继续显示的操作者身份快照。

    Attributes:
        account_id: 内部编号，1 至 2^63-1，无单位、无默认；仅运维操作为 None，不建外键。
        name: 当时的显示名，1-64 个 Unicode 码点、无首尾空白或控制字符、不可空、无默认；
            account_id 为 None 时固定为“运维”，用于首个管理员及运维重置。
    """

    account_id: int | None
    name: str
