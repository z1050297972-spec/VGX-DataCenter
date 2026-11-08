"""0021 增加所有来源记录的输入投影；只建索引表，内容由后续扫描填充。"""

import sqlalchemy as sa
from alembic import op

from rdp.infra.db.migrations.versions.v0001_error_reports import downgrade as _reject_downgrade

revision: str = "0021_dataset_lineage"
down_revision: str = "0020_dataset_collection"
branch_labels: tuple[str, ...] | None = None
depends_on: str | None = None


def upgrade() -> None:
    """建立可重建的有序血缘输入索引。

    Args:
        无。

    Returns:
        无；已有数据等待扫描投影。

    Raises:
        SQLAlchemyError: 建表或建索引失败。

    Side Effects:
        迁移事务内创建 dataset_lineage 及输入查询索引，不读取导航层。

    Time Semantics:
        必须在 0020 后执行；不读取时钟或数据盘。
    """
    op.create_table(
        "dataset_lineage",
        sa.Column(
            "dataset_id",
            sa.Text(),
            sa.ForeignKey("datasets.dataset_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("ordinal", sa.Integer(), primary_key=True),
        sa.Column("record_id", sa.Integer(), nullable=False),
        sa.Column("input_dataset_id", sa.Text(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("removable", sa.Boolean(), nullable=False),
        sa.CheckConstraint("ordinal >= 0", name="ck_dataset_lineage_ordinal"),
        sa.CheckConstraint("record_id > 0", name="ck_dataset_lineage_record_id"),
    )
    op.create_index("ix_dataset_lineage_input_dataset_id", "dataset_lineage", ["input_dataset_id"])


def downgrade() -> None:
    """拒绝删除已启用的血缘索引契约。

    Args:
        无。

    Returns:
        无。

    Raises:
        InputError: 始终拒绝降级。

    Side Effects:
        无；保留已有索引表。

    Time Semantics:
        同步拒绝，不执行删除。
    """
    _reject_downgrade()
