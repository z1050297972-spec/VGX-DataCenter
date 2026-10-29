"""账号布局偏好表声明（领域层，M1-03），复用M0的Base/UTCDateTime及账号级联删除。

偏好不是数据集索引，重建索引时不得删除。仅迁移激活后的运行装配导入本模块，
离线OpenAPI通过Pydantic模型导出，不登记新表到活动版本的MetaData。
"""

from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from rdp.infra.db.models import Base
from rdp.infra.db.utc import UTCDateTime


class DatasetLayoutPreferenceRow(Base):
    """每个账号至多一项的布局偏好，与会话及数据集索引生命周期分离。

    Attributes:
        account_id: accounts.account_id正整数外键及主键；账号删除ON DELETE CASCADE。
        layout: A/B/C之一，长度1，不允许NULL或数据库默认值；默认A由无行读取语义提供。
        updated_at: UTCDateTime，非空、无数据库时钟默认；同值不更新，回拨取原时刻最大值。
    """

    __tablename__ = "dataset_layout_preferences"
    __table_args__ = (
        CheckConstraint("account_id > 0", name="account_id"),
        CheckConstraint("layout IN ('A','B','C')", name="layout"),
    )

    account_id: Mapped[int] = mapped_column(
        ForeignKey("accounts.account_id", ondelete="CASCADE"), primary_key=True
    )
    layout: Mapped[str] = mapped_column(String(1), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
