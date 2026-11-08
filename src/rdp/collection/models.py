"""采集登记领域表声明；复用 SQLAlchemy Base 与 UTC 类型，建表只走 0019 迁移。

历史身份不设账号外键，账号删除不影响登记对象；MAC 唯一性在持有写锁的领域事务内验证。
"""

from datetime import datetime

from sqlalchemy import JSON, CheckConstraint, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from rdp.infra.db.models import Base
from rdp.infra.db.utc import UTCDateTime


class RegistryRow(Base):
    """三张登记表共用的历史字段，不单独建表。

    Attributes:
        id: 正整数永久编号，各表独立 AUTOINCREMENT，不复用。
        name: 去首尾空白的唯一名称，机器人至多64字符，词表至多32字符。
        status: active 或 retired，停用后仍可编辑。
        created_by_id: 创建账号编号；系统为 None，不建外键。
        created_by_name: 创建时显示名，删除账号后保持。
        created_at: 创建的 UTC 微秒时刻。
        updated_by_id: 最后修改账号编号；系统为 None。
        updated_by_name: 最后修改时显示名。
        updated_at: 最后修改的 UTC 微秒时刻。
    """

    __abstract__ = True
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True)
    status: Mapped[str] = mapped_column(String(7))
    created_by_id: Mapped[int | None] = mapped_column(Integer)
    created_by_name: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime())
    updated_by_id: Mapped[int | None] = mapped_column(Integer)
    updated_by_name: Mapped[str] = mapped_column(String(64))
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime())


class RobotRow(RegistryRow):
    """机器人登记，不保存密码或连接凭据。

    Attributes:
        id: robots.robot_id 列，平台分配的永久编号。
        robot_model: 和数据集同一套型号字符串，1至64字符。
        serial_number: 可空序列号，非空时唯一且1至64字符。
        macs: 至多8张网卡的规范 JSON 数组。
        address: 可空 IPv4、IPv6 或主机名，至多253字符。
        ssh_port: SSH 端口，1至65535。
        ssh_user: 可空 SSH 用户名，1至32字符，不含空白。
    """

    __tablename__ = "robots"
    __table_args__ = (
        CheckConstraint("length(name) BETWEEN 1 AND 64", name="name"),
        CheckConstraint("length(robot_model) BETWEEN 1 AND 64", name="model"),
        CheckConstraint(
            "serial_number IS NULL OR length(serial_number) BETWEEN 1 AND 64", name="serial"
        ),
        CheckConstraint("ssh_port BETWEEN 1 AND 65535", name="port"),
        CheckConstraint("status IN ('active','retired')", name="status"),
        {"sqlite_autoincrement": True},
    )
    id: Mapped[int] = mapped_column("robot_id", Integer, primary_key=True)
    robot_model: Mapped[str] = mapped_column(String(64))
    serial_number: Mapped[str | None] = mapped_column(String(64), unique=True)
    macs: Mapped[list[dict[str, str | None]]] = mapped_column(JSON)
    address: Mapped[str | None] = mapped_column(String(253))
    ssh_port: Mapped[int] = mapped_column(Integer, default=22, server_default="22")
    ssh_user: Mapped[str | None] = mapped_column(String(32))


class MethodRow(RegistryRow):
    """采集方式表；来源随名称一起可编辑，编号始终不变。

    Attributes:
        data_origin: 真机采集、UMI 采集、ego 采集或仿真生成。
    """

    __tablename__ = "collection_methods"
    __table_args__ = (
        CheckConstraint("length(name) BETWEEN 1 AND 32", name="name"),
        CheckConstraint("status IN ('active','retired')", name="status"),
        CheckConstraint(
            "data_origin IN ('真机采集','UMI 采集','ego 采集','仿真生成')", name="origin"
        ),
        {"sqlite_autoincrement": True},
    )
    data_origin: Mapped[str] = mapped_column(String(16))


class PurposeRow(RegistryRow):
    """用途表；只管理名称、状态及继承的历史身份字段。"""

    __tablename__ = "collection_purposes"
    __table_args__ = (
        CheckConstraint("length(name) BETWEEN 1 AND 32", name="name"),
        CheckConstraint("status IN ('active','retired')", name="status"),
        {"sqlite_autoincrement": True},
    )
