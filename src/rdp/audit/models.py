"""日志领域表声明（07）；共享 Base 和约束命名，表结构由 0003 迁移创建。

模块导入仅登记 MetaData，不连接数据库或自动建表。
不建账号外键，删除账号不级联日志；操作码用文本而非数据库枚举，方便第 8 张扩展。
JSON 复用 SQLAlchemy，字段白名单由 records 的追加及解码边界验证，不存完整业务载荷。
"""

from datetime import datetime

from sqlalchemy import JSON, CheckConstraint, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from rdp.audit.policy import DEFAULT_RETENTION_DAYS, MAX_RETENTION_DAYS, MIN_RETENTION_DAYS
from rdp.infra.db.models import Base
from rdp.infra.db.utc import UTCDateTime


class OperationLogRow(Base):
    """只追加的操作日志，不保存当前账号或对象的可变引用。

    Attributes:
        log_id: INTEGER 主键，1 至 2^63-1，AUTOINCREMENT，不复用。
        occurred_at: UTCDateTime，微秒，必填、无数据库时钟默认值。
        actor_id: 操作人编号，正整数；运维/系统 NULL，不建外键。
        actor_name: 当时显示名，1-64 码点，必填；空编号固定“运维”或“系统”。
        operation: OperationType 文本，1-64 字符，必填。
        object_kind: account/audit_settings/job/dataset_index/navigation_write，必填；job不是账号。
        object_id: 1-64 字符；新建执行失败尚无编号时 NULL，不建外键。
        object_name: 当时对象名字，1-64 码点，必填。
        result: success/failure，必填。
        failure_category: 成功 NULL，失败 input/conflict/external/defect，必填组合约束。
        request_id: 32 位服务器 uuid4 hex；运维/系统 NULL，不建外键。
        source_ip: 规范 IPv4/IPv6，1-45 字符；未取得或运维 NULL。
        details: OperationDetails 的 v1 JSON，必填；UTF-8 至多 MAX_DETAILS_BYTES，由追加边界验证。
    """

    __tablename__ = "operation_logs"
    __table_args__ = (
        CheckConstraint("log_id > 0", name="positive_id"),
        CheckConstraint("actor_id IS NULL OR actor_id > 0", name="actor_id"),
        CheckConstraint("length(actor_name) BETWEEN 1 AND 64", name="actor_name"),
        CheckConstraint("actor_id IS NOT NULL OR actor_name IN ('运维','系统')", name="ops_actor"),
        CheckConstraint("length(operation) BETWEEN 1 AND 64", name="operation_length"),
        CheckConstraint(
            "object_kind IN ('account','audit_settings','job','dataset_index','navigation_write')",
            name="object_kind",
        ),
        CheckConstraint(
            "object_id IS NULL OR length(object_id) BETWEEN 1 AND 64", name="object_id"
        ),
        CheckConstraint("length(object_name) BETWEEN 1 AND 64", name="object_name"),
        CheckConstraint(
            "(result = 'success' AND failure_category IS NULL) OR "
            "(result = 'failure' AND failure_category IS NOT NULL AND "
            "failure_category IN ('input','conflict','external','defect'))",
            name="result_category",
        ),
        CheckConstraint(
            "request_id IS NULL OR (length(request_id) = 32 AND request_id NOT GLOB '*[^0-9a-f]*')",
            name="request_id",
        ),
        CheckConstraint(
            "source_ip IS NULL OR length(source_ip) BETWEEN 1 AND 45", name="source_ip"
        ),
        Index("ix_operation_logs_time_id", "occurred_at", "log_id"),
        Index("ix_operation_logs_actor_time_id", "actor_id", "occurred_at", "log_id"),
        {"sqlite_autoincrement": True},
    )

    log_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    occurred_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    actor_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    actor_name: Mapped[str] = mapped_column(String(64), nullable=False)
    operation: Mapped[str] = mapped_column(String(64), nullable=False)
    object_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    object_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    object_name: Mapped[str] = mapped_column(String(64), nullable=False)
    result: Mapped[str] = mapped_column(String(7), nullable=False)
    failure_category: Mapped[str | None] = mapped_column(String(8), nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    source_ip: Mapped[str | None] = mapped_column(String(45), nullable=True)
    details: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)


class LoginLogRow(Base):
    """登录日志，未知账号的身份字段为空，不能把输入原文塞入快照。

    Attributes:
        log_id: 正整数 AUTOINCREMENT 主键，必填、不复用。
        occurred_at: UTCDateTime 微秒，必填、无默认。
        account_id: 已确认账号的正整数编号；未知账号 NULL，不建外键。
        account_name: 已确认的显示名，1-64 码点；未知账号 NULL。
        login_name: 已确认账号的登录名，3-32 字符；未知账号 NULL。
        kind: login/logout/session_expired，必填。
        result: LoginResult 文本，必填；登出和过期删除固定 success。
        source_ip: ASGI client 的规范 IP，1-45 字符；缺失 NULL。
        request_id: 已知账号的当前请求编号，32 位 hex；未知账号 NULL（H2）。
        failure_category: failure 结果必填四类之一，其他结果 NULL；不存异常消息。
        attempt_count: 同一等待期的尝试次数，正整数，普通日志为1。
        waiting_until: 合并等待日志的UTC截止时刻；普通日志为NULL。
    """

    __tablename__ = "login_logs"
    __table_args__ = (
        CheckConstraint("log_id > 0", name="positive_id"),
        CheckConstraint("attempt_count > 0", name="attempt_count"),
        CheckConstraint("account_id IS NULL OR account_id > 0", name="account_id"),
        CheckConstraint("kind IN ('login','logout','session_expired')", name="kind"),
        CheckConstraint(
            "result IN ('success','wrong_password','disabled','waiting','account_missing','failure')",
            name="result",
        ),
        CheckConstraint("kind = 'login' OR result = 'success'", name="deletion_success"),
        CheckConstraint(
            "(result IN ('account_missing','failure') AND account_id IS NULL AND account_name IS NULL "
            "AND login_name IS NULL AND request_id IS NULL) OR "
            "(result != 'account_missing' AND account_id IS NOT NULL AND account_name IS NOT NULL "
            "AND login_name IS NOT NULL AND length(account_name) BETWEEN 1 AND 64 "
            "AND length(login_name) BETWEEN 3 AND 32)",
            name="identity_snapshot",
        ),
        CheckConstraint(
            "(result != 'failure' AND failure_category IS NULL) OR "
            "(result = 'failure' AND failure_category IS NOT NULL AND "
            "failure_category IN ('input','conflict','external','defect'))",
            name="failure_category",
        ),
        CheckConstraint(
            "request_id IS NULL OR (length(request_id) = 32 AND request_id NOT GLOB '*[^0-9a-f]*')",
            name="request_id",
        ),
        CheckConstraint(
            "source_ip IS NULL OR length(source_ip) BETWEEN 1 AND 45", name="source_ip"
        ),
        Index("ix_login_logs_time_id", "occurred_at", "log_id"),
        Index("ix_login_logs_account_time_id", "account_id", "occurred_at", "log_id"),
        {"sqlite_autoincrement": True},
    )

    log_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    occurred_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    account_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    account_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    login_name: Mapped[str | None] = mapped_column(String(32), nullable=True)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    result: Mapped[str] = mapped_column(String(16), nullable=False)
    source_ip: Mapped[str | None] = mapped_column(String(45), nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    failure_category: Mapped[str | None] = mapped_column(String(8), nullable=True)
    attempt_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="1", default=1
    )
    waiting_until: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)


class AuditSettingsRow(Base):
    """两种日志共用的单行设置；无行时读取默认值，不在读路径建行。

    Attributes:
        settings_id: 固定主键 1，表示唯一的共同保留期；不自增。
        retention_days: 非空整数，7-365 天；新行默认 30，无行也按 30 解释。
    """

    __tablename__ = "audit_settings"
    __table_args__ = (
        CheckConstraint("settings_id = 1", name="singleton"),
        CheckConstraint(
            f"retention_days BETWEEN {MIN_RETENTION_DAYS} AND {MAX_RETENTION_DAYS}",
            name="retention_days",
        ),
    )

    settings_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    retention_days: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=DEFAULT_RETENTION_DAYS,
        server_default=str(DEFAULT_RETENTION_DAYS),
    )
