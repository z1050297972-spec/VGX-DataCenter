"""0022 保存成功清洗预览；只建平台报告表，不访问数据或导航层。"""

import sqlalchemy as sa
from alembic import op

from rdp.infra.db.migrations.versions.v0001_error_reports import downgrade as _reject_downgrade

revision: str = "0022_cleaning_previews"
down_revision: str = "0021_dataset_lineage"
branch_labels: tuple[str, ...] | None = None
depends_on: str | None = None


def upgrade() -> None:
    """新增随永久作业保留的清洗报告表。

    Args:
        无。

    Returns:
        无；已有作业不补造报告。

    Raises:
        SQLAlchemyError: 创建报告表失败。

    Side Effects:
        在迁移事务内建立 cleaning_previews；dataset_id 不连接可重建索引。

    Time Semantics:
        必须在 0021 后执行；生成时刻列使用平台 UTC 文本格式。
    """
    op.create_table(
        "cleaning_previews",
        sa.Column("job_id", sa.Integer(), sa.ForeignKey("jobs.job_id"), primary_key=True),
        sa.Column("dataset_id", sa.Text(), nullable=False),
        sa.Column("tool_name", sa.Text(), nullable=False),
        sa.Column("robot_model", sa.Text(), nullable=False),
        sa.Column("binary_sha256", sa.Text(), nullable=False),
        sa.Column("config_sha256", sa.Text(), nullable=False),
        sa.Column("rules_sha256", sa.Text(), nullable=False),
        sa.Column("report", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
    )


def downgrade() -> None:
    """拒绝降级删除永久清洗报告。

    Args:
        无。

    Returns:
        无。

    Raises:
        InputError: 始终拒绝降级。

    Side Effects:
        无；保留报告表。

    Time Semantics:
        同步拒绝，不读取时钟。
    """
    _reject_downgrade()
