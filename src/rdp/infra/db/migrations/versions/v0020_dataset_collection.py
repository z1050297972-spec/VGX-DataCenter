"""0020 增加采集信息及机器人关联索引；迁移不读取导航层，扫描后填充。"""

import sqlalchemy as sa
from alembic import op

from rdp.infra.db.migrations.versions.v0001_error_reports import downgrade as _reject_downgrade

revision: str = "0020_dataset_collection"
down_revision: str = "0019_collection_registry"
branch_labels: tuple[str, ...] | None = None
depends_on: str | None = None


def upgrade() -> None:
    """建立可重建的采集投影及有序机器人关联表。

    Args:
        无。

    Returns:
        无；已有数据集保持未标注，等待后续扫描投影。

    Raises:
        SQLAlchemyError: DDL 执行失败。

    Side Effects:
        在迁移事务内创建两张索引表和查询索引，不修改登记对象或导航文件。

    Time Semantics:
        必须在 0019 后执行；无时钟或外部文件读取。
    """
    op.create_table(
        "dataset_collections",
        sa.Column(
            "dataset_id",
            sa.Text(),
            sa.ForeignKey("datasets.dataset_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("status", sa.String(10), nullable=False),
        sa.Column("method_id", sa.Integer(), nullable=True),
        sa.Column("purpose_id", sa.Integer(), nullable=True),
        sa.CheckConstraint(
            "status IN ('planned','collecting','done')", name="ck_dataset_collections_status"
        ),
        sa.CheckConstraint(
            "method_id IS NULL OR method_id > 0", name="ck_dataset_collections_method_id"
        ),
        sa.CheckConstraint(
            "purpose_id IS NULL OR purpose_id > 0", name="ck_dataset_collections_purpose_id"
        ),
    )
    op.create_table(
        "dataset_collection_robots",
        sa.Column(
            "dataset_id",
            sa.Text(),
            sa.ForeignKey("dataset_collections.dataset_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("robot_id", sa.Integer(), primary_key=True),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.CheckConstraint("robot_id > 0", name="ck_dataset_collection_robots_robot_id"),
        sa.CheckConstraint("ordinal BETWEEN 0 AND 15", name="ck_dataset_collection_robots_ordinal"),
        sa.UniqueConstraint("dataset_id", "ordinal"),
    )
    for column in ("status", "method_id", "purpose_id"):
        op.create_index(f"ix_dataset_collections_{column}", "dataset_collections", [column])
    op.create_index(
        "ix_dataset_collection_robots_robot_id", "dataset_collection_robots", ["robot_id"]
    )


def downgrade() -> None:
    """拒绝删除已用于引用保护的索引契约。

    Args:
        无。

    Returns:
        无。

    Raises:
        InputError: 始终拒绝降级。

    Side Effects:
        无；保留索引表。

    Time Semantics:
        同步拒绝，不执行删除。
    """
    _reject_downgrade()
