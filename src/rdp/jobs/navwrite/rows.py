"""全局标记"导航层恢复失败"的数据库表声明（M1-07，ADR 0005 修订），共用基础层 Base。

只声明表；不 create_all，表结构由迁移 0010 创建，运行期模型与冻结 DDL 逐项一致。
"""

from datetime import datetime

from sqlalchemy import JSON, CheckConstraint, Integer
from sqlalchemy.orm import Mapped, mapped_column

from rdp.infra.db.models import Base
from rdp.infra.db.utc import UTCDateTime


class NavRecoveryFailureRow(Base):
    """单行表：有这一行就表示写导航层的作业被挡住。

    Attributes:
        singleton_id: 主键，只能为 1，由 CHECK 保证最多一行。
        set_at: 第一次设置的 UTC 时刻，微秒。
        job_ids: 留有对不上项的写入作业编号数组，升序、非空。
        items: MismatchItem 样例数组，至多 MARKER_ITEM_SAMPLE_LIMIT 条。
        total_items: 对不上的项总数，≥ 1。
    """

    __tablename__ = "nav_recovery_failure"
    __table_args__ = (
        CheckConstraint("singleton_id = 1", name="singleton"),
        CheckConstraint("total_items >= 1", name="total"),
    )

    singleton_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    set_at: Mapped[datetime] = mapped_column(UTCDateTime())
    job_ids: Mapped[list[int]] = mapped_column(JSON)
    items: Mapped[list[dict[str, object]]] = mapped_column(JSON)
    total_items: Mapped[int] = mapped_column(Integer)
