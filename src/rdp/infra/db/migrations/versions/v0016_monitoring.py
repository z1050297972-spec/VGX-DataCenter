"""0016 持久保存 worker 最近一次镜像检查结果。"""

from alembic import op

from rdp.infra.db.migrations.versions.v0001_error_reports import downgrade as _reject_downgrade

revision: str = "0016_monitoring"
down_revision: str = "0015_download_staging"
branch_labels: tuple[str, ...] | None = None
depends_on: str | None = None


def upgrade() -> None:
    """创建镜像状态表。

    Args:
        无。

    Returns:
        无。

    Raises:
        SQLAlchemyError: 建表失败。

    Side Effects:
        新建镜像状态表。

    Time Semantics:
        在迁移事务中同步执行。
    """
    op.execute(
        "CREATE TABLE monitoring_resources (id INTEGER NOT NULL PRIMARY KEY, snapshot TEXT NOT NULL)"
    )
    op.execute("""
        CREATE TABLE monitoring_mirror (
            id INTEGER NOT NULL PRIMARY KEY,
            status TEXT,
            checked_at TEXT,
            requested_seq INTEGER NOT NULL DEFAULT 0,
            completed_seq INTEGER NOT NULL DEFAULT 0
        )
    """)


def downgrade() -> None:
    """拒绝自动降级以保护平台状态。

    Args:
        无。

    Returns:
        无。

    Raises:
        InputError: 始终拒绝降级。

    Side Effects:
        无。

    Time Semantics:
        同步拒绝。
    """
    _reject_downgrade()
