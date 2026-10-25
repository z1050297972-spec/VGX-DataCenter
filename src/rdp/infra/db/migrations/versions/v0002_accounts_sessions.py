"""基础层第二版迁移契约（06），冻结 SQL，不反向引用账号领域模型。

从 0001 向前升级，结构与本版账号契约一致，不依赖后续可变的领域模型。
复用 migrate 的备份、BEGIN IMMEDIATE、事务回滚与前向迁移规则，不另建迁移器。
"""

import sqlalchemy as sa
from alembic import op

from rdp.infra.db.migrations.versions.v0001_error_reports import downgrade as _reject_downgrade

revision: str = "0002_accounts_sessions"
down_revision: str = "0001_error_reports"
branch_labels: tuple[str, ...] | None = None
depends_on: str | None = None


def upgrade() -> None:
    """创建账号、会话表及索引。

    Args:
        无；由 Alembic 提供持有写事务的在线连接。

    Returns:
        无；accounts、account_sessions 的列和命名约束与 06 模型逐项相同；
        时间底层 TEXT；accounts 使用 SQLite AUTOINCREMENT，会话外键 ON DELETE CASCADE；
        不创建默认账号，不改 error_reports 或已有报错数据。

    Raises:
        SQLAlchemyError: DDL、锁、约束或 I/O 失败；由外层 migrate 转成四类异常。

    Side Effects:
        只在当前事务创建两表和会话 account_id/last_seen_at 索引；失败整体回滚，
        版本停留 0001，不留半张表；外层保留完整升级前备份，不自动恢复。

    Time Semantics:
        必须在 migrate 完成备份并取得 BEGIN IMMEDIATE 后执行，无时钟读取、自动重试或降级。
    """
    op.create_table(
        "accounts",
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("login_name", sa.String(32), nullable=False),
        sa.Column("display_name", sa.String(64), nullable=False),
        sa.Column("role", sa.String(13), nullable=False),
        sa.Column("status", sa.String(8), nullable=False, server_default="enabled"),
        sa.Column("password_hash", sa.String(512), nullable=False),
        sa.Column(
            "must_change_password",
            sa.Boolean(create_constraint=True, name=op.f("ck_accounts_must_change_password")),
            nullable=False,
            server_default="1",
        ),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.Column("created_by_id", sa.Integer(), nullable=True),
        sa.Column("created_by_name", sa.String(64), nullable=False),
        sa.Column("updated_by_id", sa.Integer(), nullable=True),
        sa.Column("updated_by_name", sa.String(64), nullable=False),
        sa.Column("failed_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("blocked_until", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("account_id", name=op.f("pk_accounts")),
        *_account_checks(),
        sa.UniqueConstraint("login_name", name=op.f("uq_accounts_login_name")),
        sqlite_autoincrement=True,
    )
    op.create_table(
        "account_sessions",
        sa.Column("token_digest", sa.String(64), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("last_seen_at", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("token_digest", name=op.f("pk_account_sessions")),
        sa.CheckConstraint(
            "length(token_digest) = 64 AND token_digest NOT GLOB '*[^0-9a-f]*'",
            name=op.f("ck_account_sessions_token_digest"),
        ),
        sa.CheckConstraint(
            "last_seen_at >= created_at", name=op.f("ck_account_sessions_time_order")
        ),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["accounts.account_id"],
            name=op.f("fk_account_sessions_account_id_accounts"),
            ondelete="CASCADE",
        ),
    )
    op.create_index(op.f("ix_account_sessions_account_id"), "account_sessions", ["account_id"])
    op.create_index(op.f("ix_account_sessions_last_seen_at"), "account_sessions", ["last_seen_at"])


def downgrade() -> None:
    """拒绝第二版降级，避免破坏账号和会话。

    Args:
        无。

    Returns:
        无；不正常返回。

    Raises:
        InputError: 所有调用均拒绝，提示停止服务后人工恢复备份和匹配代码。

    Side Effects:
        无；执行 SQL 之前拒绝，不删除任何数据或自动恢复。

    Time Semantics:
        同步立即拒绝，无时钟、等待或重试。
    """
    _reject_downgrade()


def _account_checks() -> list[sa.CheckConstraint]:
    """冻结第二版 CHECK 的表达式和名称，不引用未来可能变化的规则。"""
    rules = (
        ("positive_id", "account_id > 0"),
        (
            "login_name",
            "length(login_name) BETWEEN 3 AND 32 AND substr(login_name,1,1) GLOB '[a-z]' AND login_name NOT GLOB '*[^a-z0-9_.-]*'",
        ),
        ("display_name_length", "length(display_name) BETWEEN 1 AND 64"),
        ("role", "role IN ('administrator','member')"),
        ("status", "status IN ('enabled','disabled')"),
        ("password_hash_length", "length(password_hash) BETWEEN 1 AND 512"),
        ("failed_attempts", "failed_attempts BETWEEN 0 AND 5"),
        (
            "failure_wait",
            "(failed_attempts = 5 AND blocked_until IS NOT NULL) OR (failed_attempts < 5 AND blocked_until IS NULL)",
        ),
        ("time_order", "updated_at >= created_at"),
        ("created_by_id", "created_by_id IS NULL OR created_by_id > 0"),
        ("updated_by_id", "updated_by_id IS NULL OR updated_by_id > 0"),
        ("created_by_name", "length(created_by_name) BETWEEN 1 AND 64"),
        ("updated_by_name", "length(updated_by_name) BETWEEN 1 AND 64"),
    )
    return [sa.CheckConstraint(sql, name=op.f("ck_accounts_" + name)) for name, sql in rules]
