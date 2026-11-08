"""来源文件的可重建血缘索引；逐输入保序，输入无外键以保留已移除或未知的历史编号。"""

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from rdp.infra.db.models import Base


class DatasetLineageRow(Base):
    """一条记录的一个输入；记录所属数据集消失时级联清除。

    Attributes:
        dataset_id: 记录所属的产物数据集编号。
        ordinal: 所有记录按文件顺序展开后的非负序号。
        record_id: 来源文件里的正整数记录编号。
        input_dataset_id: 输入数据集编号，允许索引里已找不到。
        note: 原始说明，未填为 None。
        removable: recorded_by.kind 为人工补录才为 True。
    """

    __tablename__ = "dataset_lineage"
    __table_args__ = (
        CheckConstraint("ordinal >= 0", name="ordinal"),
        CheckConstraint("record_id > 0", name="record_id"),
    )
    dataset_id: Mapped[str] = mapped_column(
        ForeignKey("datasets.dataset_id", ondelete="CASCADE"), primary_key=True
    )
    ordinal: Mapped[int] = mapped_column(Integer, primary_key=True)
    record_id: Mapped[int] = mapped_column(Integer)
    input_dataset_id: Mapped[str] = mapped_column(Text, index=True)
    note: Mapped[str | None] = mapped_column(Text)
    removable: Mapped[bool] = mapped_column(Boolean)
