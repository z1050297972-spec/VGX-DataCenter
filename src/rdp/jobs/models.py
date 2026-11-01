"""作业记录与单行心跳的 ORM 声明（08/09/11、0006）；领域层，不创建或迁移数据库。

共享基础层Base/UTCDateTime，导入时注册共用metadata；0006 迁移维护相同列与 CHECK。JSON 存进度/摘要/诊断快照，计数另列便于最终值一致性校验。
"""

from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from rdp.infra.db.models import Base
from rdp.infra.db.utc import UTCDateTime
from rdp.jobs.policy import JOB_RECOVERY_LIMIT
from rdp.jobs.scheduling_models import JobSchedulingColumns


class JobRow(JobSchedulingColumns):
    """永久作业记录，无账号外键；编号只由 SQLite AUTOINCREMENT 生成。

    Attributes:
        job_id: 正整数主键，不复用已发出的编号。
        type_name: 稳定英文类型，1-64 字符。
        display_name: 提交时显示名，1-40 码点，恢复使用同一路径。
        parameters: 无秘密 JSON 对象，最多 16 KiB。
        submitter_id: 正账号编号或系统的 None，不设外键；0005 可空声明由 JobSchedulingColumns 共用。
        submitter_name: 提交人名字快照，1-64 码点。
        submitted_at: UTC 微秒提交时刻。
        resubmitted_from: 原作业编号，普通提交 NULL；永久记录不级联删除。
        state: 六态英文码，初始化 queued；常规改变经 transition_job，未启动领取由 return_unstarted_job 受限退回。
        recovery_mode: 提交时方式快照，仅作记录及interrupt保守保护；续跑/重跑选择以当前登记为准。
        recovery_count: 已提交的自动恢复资格次数，0至JOB_RECOVERY_LIMIT=3，初始0；重跑不归零。
        started_at: 首次领取的 UTC 时刻，未领取 NULL；已启动后的恢复不变，未启动领取退回时清空。
        ended_at: 结束 UTC 时刻，进行中 NULL。
        outcome: 仅 completed 有四种结果之一，其余 NULL。
        total_items: 已处理条目数，非负。
        failed_items: 失败条目数，0 至 total_items。
        warning_count: 警告数，非负，与失败条目分开。
        aborted: 非取消异常整体中止标志，布尔。
        progress: 最后完整进度 JSON；未上报 NULL。
        progress_at: 最新进度 UTC 时刻；无进度 NULL。
        elapsed_s: 已保存执行片段总秒数，有限非负，恢复不算停机时长。
        artifacts: 产物位置数组，至多 100 项；取消不清理。
        log_path: 唯一相对状态目录路径，queued未领取可NULL；与首次running同事务登记，不能运行后补写。
        diagnostics: 至多 100 规则组加溢出组，每组完整总数和有限样例。
        summary: JobSummary 的冻结 JSON；非终态 NULL。
        tool_exit_code: 最后工具退出码，负数为信号，无工具 NULL。
        platform_version: 最近实际领取版本，1-128 个码点；历史未知或从未领取为 NULL。
    """

    __tablename__ = "jobs"
    __table_args__ = (
        *JobSchedulingColumns.__table_args__,
        CheckConstraint(
            "platform_version IS NULL OR length(platform_version) BETWEEN 1 AND 128",
            name="platform_version_length",
        ),
        CheckConstraint("job_id > 0 AND submitter_id > 0", name="positive_ids"),
        CheckConstraint("length(type_name) BETWEEN 1 AND 64", name="type_length"),
        CheckConstraint("length(display_name) BETWEEN 1 AND 40", name="display_length"),
        CheckConstraint("length(submitter_name) BETWEEN 1 AND 64", name="submitter_length"),
        CheckConstraint(
            "state IN ('queued','running','cancelling','completed','cancelled','interrupted')",
            name="state",
        ),
        CheckConstraint("recovery_mode IN ('resume','restart','interrupt')", name="recovery"),
        CheckConstraint(
            "total_items >= 0 AND failed_items BETWEEN 0 AND total_items AND warning_count >= 0",
            name="counts",
        ),
        CheckConstraint("elapsed_s >= 0", name="elapsed"),
        CheckConstraint(
            f"recovery_count BETWEEN 0 AND {JOB_RECOVERY_LIMIT}", name="recovery_count"
        ),
        CheckConstraint(
            "state NOT IN ('running','cancelling','completed','interrupted') OR log_path IS NOT NULL",
            name="claimed_log_path",
        ),
        UniqueConstraint("log_path", name="uq_jobs_log_path"),
        CheckConstraint(
            "(state = 'completed' AND outcome IS NOT NULL AND outcome IN ('succeeded','succeeded_with_warnings','partially_succeeded','failed')) OR (state != 'completed' AND outcome IS NULL)",
            name="outcome",
        ),
        CheckConstraint(
            "(state IN ('completed','cancelled','interrupted') AND ended_at IS NOT NULL AND summary IS NOT NULL) OR (state IN ('queued','running','cancelling') AND ended_at IS NULL AND summary IS NULL)",
            name="terminal",
        ),
        # job_id自增即提交顺序；state前缀支持领取/状态过滤，不用会回拨的墙钟排序。
        Index("ix_jobs_state_id", "state", "job_id"),
        # 全状态job_id游标直接复用INTEGER主键索引，不另建重复索引。
        {"sqlite_autoincrement": True},
    )

    job_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    type_name: Mapped[str] = mapped_column(String(64), nullable=False)
    display_name: Mapped[str] = mapped_column(String(40), nullable=False)
    parameters: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    submitter_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    submitter_name: Mapped[str] = mapped_column(String(64), nullable=False)
    submitted_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    resubmitted_from: Mapped[int | None] = mapped_column(Integer)
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    recovery_mode: Mapped[str] = mapped_column(String(16), nullable=False)
    recovery_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    ended_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    outcome: Mapped[str | None] = mapped_column(String(32))
    total_items: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_items: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    warning_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    aborted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # 未上报/非终态必须是SQL NULL，不能写JSON文本null，否则终态CHECK会误判。
    progress: Mapped[dict[str, object] | None] = mapped_column(JSON(none_as_null=True))
    progress_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    elapsed_s: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    artifacts: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    log_path: Mapped[str | None] = mapped_column(Text)
    diagnostics: Mapped[list[dict[str, object]]] = mapped_column(JSON, nullable=False)
    summary: Mapped[dict[str, object] | None] = mapped_column(JSON(none_as_null=True))
    tool_exit_code: Mapped[int | None] = mapped_column(Integer)
    platform_version: Mapped[str | None] = mapped_column(String(128), nullable=True)


class WorkerHeartbeatRow(Base):
    """单行实例心跳，不以进程号是否存在判定在线。

    Attributes:
        singleton_id: 固定整数1，保证只保留一个当前实例。
        instance_id: uuid4 hex，32位小写字符，每次启动重新生成。
        pid: 当前实例正进程号，诊断使用。
        started_at: 本实例启动的UTC微秒时刻。
        last_seen_at: 最近心跳的UTC微秒时刻，允许墙钟回拨。
    """

    __tablename__ = "worker_heartbeat"
    __table_args__ = (
        CheckConstraint("singleton_id = 1", name="singleton"),
        CheckConstraint("pid > 0", name="pid"),
        CheckConstraint("length(instance_id) = 32", name="instance"),
    )

    singleton_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    instance_id: Mapped[str] = mapped_column(String(32), nullable=False)
    pid: Mapped[int] = mapped_column(Integer, nullable=False)
    started_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)


class DownloadAdjustmentRow(Base):
    """版本化下载调参快照，与迁移 0013 共用结构。

    Attributes:
        job_id: 对应作业的正整数主键。
        requested_version: 已提交的非负版本。
        applied_version: 已成功应用的非负版本，不超过请求版本。
        requested_concurrency: 待生效文件并发，1 至 16。
        requested_limit_bytes_per_s: 待生效速率，0 或 1024 至 10737418240 bytes/s。
        effective_concurrency: 已生效文件并发，1 至 16。
        effective_limit_bytes_per_s: 已生测速率，0 或 1024 至 10737418240 bytes/s。
        speed_bytes_per_s: 当前传输速度，非负 bytes/s。
        total_files: 文件总数，非负。
        completed_files: 完成文件数，非负。
        failed_files: 失败文件数，非负。
        skipped_files: 跳过文件数，非负。
    """

    __tablename__ = "download_adjustments"
    __table_args__ = (
        CheckConstraint("speed_bytes_per_s >= 0", name="speed"),
        CheckConstraint("total_files >= 0", name="total_files"),
        CheckConstraint("completed_files >= 0", name="completed_files"),
        CheckConstraint("failed_files >= 0", name="failed_files"),
        CheckConstraint("skipped_files >= 0", name="skipped_files"),
        CheckConstraint("requested_version >= 0", name="requested_version"),
        CheckConstraint(
            "applied_version >= 0 AND applied_version <= requested_version", name="applied_version"
        ),
        CheckConstraint("requested_concurrency BETWEEN 1 AND 16", name="requested_concurrency"),
        CheckConstraint(
            "requested_limit_bytes_per_s = 0 OR requested_limit_bytes_per_s BETWEEN 1024 AND 10737418240",
            name="requested_limit",
        ),
        CheckConstraint("effective_concurrency BETWEEN 1 AND 16", name="effective_concurrency"),
        CheckConstraint(
            "effective_limit_bytes_per_s = 0 OR effective_limit_bytes_per_s BETWEEN 1024 AND 10737418240",
            name="effective_limit",
        ),
    )
    job_id: Mapped[int] = mapped_column(
        ForeignKey("jobs.job_id", ondelete="CASCADE"), primary_key=True
    )
    requested_version: Mapped[int] = mapped_column(Integer, nullable=False)
    applied_version: Mapped[int] = mapped_column(Integer, nullable=False)
    requested_concurrency: Mapped[int] = mapped_column(Integer, nullable=False)
    requested_limit_bytes_per_s: Mapped[int] = mapped_column(Integer, nullable=False)
    effective_concurrency: Mapped[int] = mapped_column(Integer, nullable=False)
    effective_limit_bytes_per_s: Mapped[int] = mapped_column(Integer, nullable=False)

    speed_bytes_per_s: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    total_files: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    completed_files: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    failed_files: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    skipped_files: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
