"""账号领域表声明（06），共享 infra.db.models.Base 的 MetaData 和命名约定。

由 api/ops 入口导入并注册两表；基础层不得反向 import accounts。
历史操作者快照不建账号外键，否则删号会破坏记录；会话外键则 ON DELETE CASCADE。
"""

from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from rdp.infra.db.models import Base
from rdp.infra.db.utc import UTCDateTime


class AccountRow(Base):
    """账号及 G2 连续失败状态；删除是真删除，内部编号不可复用。

    Attributes:
        account_id: INTEGER 主键，1 至 2^63-1、无单位、不可空；SQLite AUTOINCREMENT 自动分配，
            显式禁止复用已提交后删除的编号，保护 ActorRef 历史身份。
        login_name: 唯一小写 ASCII 登录名，3-32 字符、不可空、无默认、无单位，不允许更名。
        display_name: 显示名，1-64 个码点，无首尾空白/控制字符、不可空、无默认。
        role: administrator/member，无单位、不可空、无默认。
        status: enabled/disabled，无单位、不可空、新建默认 enabled。
        password_hash: Argon2id 编码，1-512 字符、不可空、无默认、不作为接口响应或日志。
        must_change_password: 布尔、无单位、不可空、默认 True；运维首号显式 False。
        created_at: 创建时刻，UTCDateTime、微秒、不可空、无默认。
        updated_at: 最后修改时刻，UTCDateTime、微秒、不可空、无默认、不早于 created_at。
        created_by_id: 创建人快照编号，1 至 2^63-1；运维为 NULL，无单位、无默认、不建外键。
        created_by_name: 当时显示名或运维，1-64 字符、不可空、无默认。
        updated_by_id: 修改人快照编号，同 created_by_id；运维为 NULL、无默认、不建外键。
        updated_by_name: 当时显示名或运维，1-64 字符、不可空、无默认。
        failed_attempts: 连续错密码次数，0-5 次、不可空、默认 0；等待中不增长。
        blocked_until: 等待截止 UTCDateTime、微秒、默认 NULL；未等待为 NULL。
    """

    __tablename__ = "accounts"
    __table_args__ = (
        CheckConstraint("account_id > 0", name="positive_id"),
        CheckConstraint(
            "length(login_name) BETWEEN 3 AND 32 AND substr(login_name,1,1) GLOB '[a-z]' AND login_name NOT GLOB '*[^a-z0-9_.-]*'",
            name="login_name",
        ),
        CheckConstraint("length(display_name) BETWEEN 1 AND 64", name="display_name_length"),
        CheckConstraint("role IN ('administrator','member')", name="role"),
        CheckConstraint("status IN ('enabled','disabled')", name="status"),
        CheckConstraint("length(password_hash) BETWEEN 1 AND 512", name="password_hash_length"),
        CheckConstraint("failed_attempts BETWEEN 0 AND 5", name="failed_attempts"),
        CheckConstraint(
            "(failed_attempts = 5 AND blocked_until IS NOT NULL) OR (failed_attempts < 5 AND blocked_until IS NULL)",
            name="failure_wait",
        ),
        CheckConstraint("updated_at >= created_at", name="time_order"),
        CheckConstraint("created_by_id IS NULL OR created_by_id > 0", name="created_by_id"),
        CheckConstraint("updated_by_id IS NULL OR updated_by_id > 0", name="updated_by_id"),
        CheckConstraint("length(created_by_name) BETWEEN 1 AND 64", name="created_by_name"),
        CheckConstraint("length(updated_by_name) BETWEEN 1 AND 64", name="updated_by_name"),
        {"sqlite_autoincrement": True},
    )

    account_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    login_name: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(64), nullable=False)
    role: Mapped[str] = mapped_column(String(13), nullable=False)
    status: Mapped[str] = mapped_column(
        String(8), nullable=False, default="enabled", server_default="enabled"
    )
    password_hash: Mapped[str] = mapped_column(String(512), nullable=False)
    must_change_password: Mapped[bool] = mapped_column(
        Boolean(create_constraint=True, name="must_change_password"),
        nullable=False,
        default=True,
        server_default="1",
    )
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    created_by_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_by_name: Mapped[str] = mapped_column(String(64), nullable=False)
    updated_by_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    updated_by_name: Mapped[str] = mapped_column(String(64), nullable=False)
    failed_attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    blocked_until: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)


class SessionRow(Base):
    """服务端会话，仅存随机令牌摘要，不存 cookie 原文。

    Attributes:
        token_digest: 主键，64 位小写 SHA-256 hex，无单位、不可空、无默认。
        account_id: accounts 外键，1 至 2^63-1，无单位、不可空、无默认；删除账号级联删除。
        created_at: 会话创建时刻，UTCDateTime、微秒、不可空、无默认。
        last_seen_at: 最后持久化活动时刻，UTCDateTime、微秒、不可空、无默认，不早于 created_at；索引供清理。
    """

    __tablename__ = "account_sessions"
    __table_args__ = (
        CheckConstraint(
            "length(token_digest) = 64 AND token_digest NOT GLOB '*[^0-9a-f]*'", name="token_digest"
        ),
        CheckConstraint("last_seen_at >= created_at", name="time_order"),
    )

    token_digest: Mapped[str] = mapped_column(String(64), primary_key=True)
    account_id: Mapped[int] = mapped_column(
        ForeignKey("accounts.account_id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, index=True)
