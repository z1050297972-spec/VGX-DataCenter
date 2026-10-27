"""0005 调度持久化声明（领域层，09）；资源列由 JobRow 继承，两张表注册共用 MetaData。

只声明结构，不执行迁移、核卡或调度；数据库版本由入口在连接服务前检查。
"""

from datetime import date, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from rdp.infra.db.models import Base
from rdp.infra.db.utc import UTCDateTime


class JobSchedulingColumns(Base):
    """jobs 的资源列及已批准的提交人可空扩展，原有索引/CHECK 与这些约束合并。

    Attributes:
        submitter_id: 账号正编号；为空时 submitter_name 必须为“系统”；有编号同名账号合法，不设账号外键。
        gpu_index: 非负物理编号，未领卡为 NULL；终态保留历史。
        wait_reason: NULL/gpu/navigation_lock，独立于 state；终态 NULL。
        holds_navigation_lock: 严格布尔展示副本，默认 False；终态 False。
    """

    __abstract__ = True
    __table_args__ = (
        CheckConstraint(
            "(submitter_id IS NULL AND submitter_name = '系统') OR "
            "(submitter_id IS NOT NULL AND submitter_id > 0)",
            name="job_submitter_identity",
        ),
        CheckConstraint("gpu_index IS NULL OR gpu_index >= 0", name="gpu_index"),
        CheckConstraint(
            "wait_reason IS NULL OR wait_reason IN ('gpu','navigation_lock')", name="wait_reason"
        ),
        CheckConstraint("holds_navigation_lock IN (0,1)", name="navigation_boolean"),
        CheckConstraint(
            "holds_navigation_lock = 0 OR (state IN ('running','cancelling') AND wait_reason IS NULL)",
            name="navigation_holder_state",
        ),
        CheckConstraint(
            "state NOT IN ('completed','cancelled','interrupted') OR "
            "(wait_reason IS NULL AND holds_navigation_lock = 0)",
            name="terminal_resources",
        ),
        CheckConstraint(
            "wait_reason != 'navigation_lock' OR state IN ('running','cancelling')",
            name="navigation_wait_state",
        ),
        CheckConstraint(
            "wait_reason != 'gpu' OR (state IN ('queued','running') AND gpu_index IS NULL)",
            name="gpu_wait_state",
        ),
    )

    submitter_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    gpu_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    wait_reason: Mapped[str | None] = mapped_column(String(24), nullable=True)
    holds_navigation_lock: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )


class ScheduleSubmissionRow(Base):
    """每日去重行，和新作业及提交操作日志同事务插入；历史永久保留。

    Attributes:
        schedule_name: 稳定规则名，1-64 码点，复合主键第一项。
        local_date: 本机时区的日历日期，复合主键第二项，不带 UTC 意义。
        job_id: 唯一的永久正作业编号，不外键关联账号。
        submitted_at: UTC aware 提交时刻，由 UTCDateTime 编解码，不能是 monotonic。
    """

    __tablename__ = "schedule_submissions"
    __table_args__ = (
        CheckConstraint("length(schedule_name) BETWEEN 1 AND 64", name="schedule_name"),
        CheckConstraint("job_id > 0", name="job_id"),
        UniqueConstraint("job_id", name="uq_schedule_submissions_job_id"),
        Index("ix_schedule_submissions_name_job", "schedule_name", "job_id"),
    )

    schedule_name: Mapped[str] = mapped_column(String(64), primary_key=True)
    local_date: Mapped[date] = mapped_column(Date, primary_key=True)
    job_id: Mapped[int] = mapped_column(Integer, nullable=False)
    submitted_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)


class WorkerGpuCheckRow(Base):
    """当前实例启动核对的数据库展示副本，不参与真正的 GPU 互斥。

    Attributes:
        gpu_index: 配置物理编号，非负主键；每次启动整体替换行集。
        instance_id: 本次 worker uuid4 hex，与心跳关联，防止旧实例结果冒充新核对。
        available: 核对通过 True，失败 False；失败卡本实例不再分配。
        diagnostics: 失败时的有界统一诊断 JSON 数组，通过为空。
        checked_at: aware UTC 核对时刻，由 UTCDateTime 统一编解码。
    """

    __tablename__ = "worker_gpu_checks"
    __table_args__ = (
        CheckConstraint("gpu_index >= 0", name="gpu_index"),
        CheckConstraint("length(instance_id) = 32", name="instance_id"),
        CheckConstraint("available IN (0,1)", name="available"),
    )

    gpu_index: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    instance_id: Mapped[str] = mapped_column(String(32), nullable=False)
    available: Mapped[bool] = mapped_column(Boolean, nullable=False)
    diagnostics: Mapped[list[dict[str, object]]] = mapped_column(JSON, nullable=False)
    checked_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
