"""0013 等待期登录合并（基础层，M0-13）；只给既有日志加列，保留历史记录。"""

from alembic import op

from rdp.infra.db.migrations.versions.v0001_error_reports import downgrade as _reject_downgrade

revision: str = "0013_login_wait_attempts"
down_revision: str = "0012_scene_task_index"
branch_labels: tuple[str, ...] | None = None
depends_on: str | None = None


def upgrade() -> None:
    """为等待期合并增加次数和截止列，既有日志从一次起算。

    Args:
        无；使用Alembic注入的迁移事务。

    Returns:
        无；旧行attempt_count为1，waiting_until为NULL。

    Raises:
        SQLAlchemyError: 加列失败，由migrate整体回滚。

    Side Effects:
        同事务给login_logs加两列，不重建表、不修改既有来源或时间。

    Time Semantics:
        仅停服务迁移；截止列按UTC微秒存储，不读取当前时钟。
    """
    op.execute(
        "ALTER TABLE login_logs ADD COLUMN attempt_count INTEGER NOT NULL DEFAULT 1 "
        "CONSTRAINT ck_login_logs_attempt_count CHECK (attempt_count > 0)"
    )
    op.execute("ALTER TABLE login_logs ADD COLUMN waiting_until TEXT")


def downgrade() -> None:
    """拒绝丢弃已聚合尝试次数的自动降级。

    Args:
        无；由Alembic调用。

    Returns:
        无；保留当前数据库结构。

    Raises:
        InputError: 需人工恢复备份并匹配代码版本。

    Side Effects:
        无。

    Time Semantics:
        同步拒绝，不取时钟。
    """
    _reject_downgrade()
