"""0013 新建下载作业调参通道，不改变已有表或接口。"""

from alembic import op

from rdp.infra.db.migrations.versions.v0001_error_reports import downgrade as _reject_downgrade

revision: str = "0013_download_adjustments"
down_revision: str = "0012_scene_task_index"
branch_labels: tuple[str, ...] | None = None
depends_on: str | None = None


def upgrade() -> None:
    """建立每作业一行的版本化调参通道。

    Args:
        无；Alembic 提供迁移事务。

    Returns:
        无。

    Raises:
        SQLAlchemyError: 建表失败，由迁移器回滚。

    Side Effects:
        新建 download_adjustments 表及其外键，不改已有表。

    Time Semantics:
        只在维护窗口中同步执行，不读取时钟。
    """
    op.execute("""
        CREATE TABLE download_adjustments (
            job_id INTEGER NOT NULL PRIMARY KEY,
            requested_version INTEGER NOT NULL CHECK (requested_version >= 0),
            applied_version INTEGER NOT NULL CHECK (applied_version >= 0 AND applied_version <= requested_version),
            requested_concurrency INTEGER NOT NULL CHECK (requested_concurrency BETWEEN 1 AND 16),
            requested_limit_bytes_per_s INTEGER NOT NULL CHECK (requested_limit_bytes_per_s = 0 OR requested_limit_bytes_per_s BETWEEN 1024 AND 10737418240),
            effective_concurrency INTEGER NOT NULL CHECK (effective_concurrency BETWEEN 1 AND 16),
            effective_limit_bytes_per_s INTEGER NOT NULL CHECK (effective_limit_bytes_per_s = 0 OR effective_limit_bytes_per_s BETWEEN 1024 AND 10737418240),
            speed_bytes_per_s INTEGER NOT NULL DEFAULT 0 CHECK (speed_bytes_per_s >= 0),
            total_files INTEGER NOT NULL DEFAULT 0 CHECK (total_files >= 0),
            completed_files INTEGER NOT NULL DEFAULT 0 CHECK (completed_files >= 0),
            failed_files INTEGER NOT NULL DEFAULT 0 CHECK (failed_files >= 0),
            skipped_files INTEGER NOT NULL DEFAULT 0 CHECK (skipped_files >= 0),
            CONSTRAINT fk_download_adjustments_job_id_jobs FOREIGN KEY(job_id) REFERENCES jobs (job_id) ON DELETE CASCADE
        )
    """)


def downgrade() -> None:
    """拒绝自动降级，避免丢失调参记录。

    Args:
        无。

    Returns:
        无。

    Raises:
        InputError: 始终拒绝，须恢复备份和匹配版本。

    Side Effects:
        无。

    Time Semantics:
        同步拒绝，不等待。
    """
    _reject_downgrade()
