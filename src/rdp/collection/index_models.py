"""采集信息的可重建索引表；由扫描发布，登记服务只读引用计数。

放在 collection 层供登记与上层 jobs 共用，避免登记服务反向依赖扫描器。
只外键绑定数据集索引，不外键绑定登记表，保留导航层里不存在的历史编号供提示。
"""

from sqlalchemy import CheckConstraint, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from rdp.infra.db.models import Base


class DatasetCollectionRow(Base):
    """唯一规范副本的有效采集投影；无采集信息时没有行。

    Attributes:
        dataset_id: 数据集永久编号，删除数据集索引时级联清除。
        status: planned、collecting 或 done。
        method_id: 采集方式正整数编号，未填为 None。
        purpose_id: 用途正整数编号，未填为 None。
    """

    __tablename__ = "dataset_collections"
    __table_args__ = (
        CheckConstraint("status IN ('planned','collecting','done')", name="status"),
        CheckConstraint("method_id IS NULL OR method_id > 0", name="method_id"),
        CheckConstraint("purpose_id IS NULL OR purpose_id > 0", name="purpose_id"),
    )
    dataset_id: Mapped[str] = mapped_column(
        ForeignKey("datasets.dataset_id", ondelete="CASCADE"), primary_key=True
    )
    status: Mapped[str] = mapped_column(String(10), index=True)
    method_id: Mapped[int | None] = mapped_column(Integer, index=True)
    purpose_id: Mapped[int | None] = mapped_column(Integer, index=True)


class DatasetCollectionRobotRow(Base):
    """数据集与机器人关联，复合主键保证同一数据集只计数一次。

    Attributes:
        dataset_id: 采集投影外键，删除投影时级联清除。
        robot_id: 正整数永久编号，允许登记表已缺失。
        ordinal: 去重后原顺序，0 至 15，同一数据集唯一。
    """

    __tablename__ = "dataset_collection_robots"
    __table_args__ = (
        CheckConstraint("robot_id > 0", name="robot_id"),
        CheckConstraint("ordinal BETWEEN 0 AND 15", name="ordinal"),
        UniqueConstraint("dataset_id", "ordinal"),
    )
    dataset_id: Mapped[str] = mapped_column(
        ForeignKey("dataset_collections.dataset_id", ondelete="CASCADE"), primary_key=True
    )
    robot_id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    ordinal: Mapped[int] = mapped_column(Integer)
