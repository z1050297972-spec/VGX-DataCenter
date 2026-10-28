"""0006 作业版本列声明（11 M2），只定义可复用 ORM 列与约束，不建立表或执行迁移。

JobRow 的列集合与活动迁移图必须同时切换；这里不注册第二份 jobs 表。
"""

from sqlalchemy import CheckConstraint, String
from sqlalchemy.orm import Mapped, mapped_column

from rdp.infra.db.models import Base


class JobVersionColumns(Base):
    """jobs 的可空执行版本列，与原有约束合并使用。

    Attributes:
        platform_version: 最近实际领取版本，1-128 个码点；历史未知或从未领取为 NULL。
            无默认伪造版本；生产写入由 record_execution_version 校验无控制字符。
    """

    __abstract__ = True
    __table_args__ = (
        CheckConstraint(
            "platform_version IS NULL OR length(platform_version) BETWEEN 1 AND 128",
            name="platform_version_length",
        ),
    )

    platform_version: Mapped[str | None] = mapped_column(String(128), nullable=True)
