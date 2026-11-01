"""0015 保存 worker 的下载暂存只读扫描结果。"""

from alembic import op

from rdp.infra.db.migrations.versions.v0001_error_reports import downgrade as _reject_downgrade

revision: str = "0015_download_staging"
down_revision: str = "0013_download_adjustments"
branch_labels: tuple[str, ...] | None = None
depends_on: str | None = None


def upgrade() -> None:
    """新建每个扫描作业对应的一份快照。

    Args:
        无。

    Returns:
        无。

    Raises:
        SQLAlchemyError: 数据库建表失败。

    Side Effects:
        只新建快照表，不修改旧表或存储根。

    Time Semantics:
        在迁移事务中同步执行。
    """
    op.execute("""
        CREATE TABLE download_staging_snapshots (
            job_id INTEGER NOT NULL PRIMARY KEY,
            snapshot JSON NOT NULL,
            CONSTRAINT fk_download_staging_snapshots_job_id_jobs
                FOREIGN KEY(job_id) REFERENCES jobs (job_id) ON DELETE CASCADE
        )
    """)


def downgrade() -> None:
    """拒绝自动降级以保护已发布的快照。

    Args:
        无。

    Returns:
        无。

    Raises:
        InputError: 始终拒绝，须恢复备份及匹配版本。

    Side Effects:
        无。

    Time Semantics:
        同步拒绝。
    """
    _reject_downgrade()
