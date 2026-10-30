"""0012 数据集场景、任务与机器人型号索引列（基础层，M1.5-03）；只加列，不重建表。"""

from alembic import op

from rdp.infra.db.migrations.versions.v0001_error_reports import downgrade as _reject_downgrade

revision: str = "0012_scene_task_index"
down_revision: str = "0011_data_origin"
branch_labels: tuple[str, ...] | None = None
depends_on: str | None = None


def upgrade() -> None:
    """给 datasets 增加 scene、tasks、robot_model 三列，保留全部既有索引行。

    Args:
        无；Alembic 注入已有备份与写事务的连接。

    Returns:
        无；旧行 scene、robot_model 为 NULL，tasks 为空数组，下一次扫描按导航层内容重写。

    Raises:
        SQLAlchemyError: 加列失败；由 migrate 回滚整个事务。

    Side Effects:
        同事务对 datasets 执行三次 ALTER TABLE ADD COLUMN。不重建表、不碰子表和外键，
        不读取导航层；失败保留迁移前备份。

    Time Semantics:
        仅停服务维护窗口运行；锁预算沿用 migrate，不读时钟或重试。
    """
    # 只加可空列或带默认值的列，SQLite 直接支持，不需要像 0011 那样保存并恢复子表。
    op.execute("ALTER TABLE datasets ADD COLUMN scene TEXT")
    op.execute("ALTER TABLE datasets ADD COLUMN tasks JSON NOT NULL DEFAULT '[]'")
    op.execute("ALTER TABLE datasets ADD COLUMN robot_model TEXT")


def downgrade() -> None:
    """拒绝会丢失人工分类索引的自动降级。

    Args:
        无；由 Alembic 调用。

    Returns:
        无；始终拒绝。

    Raises:
        InputError: 不支持自动降级，需恢复完整备份及匹配代码。

    Side Effects:
        无；保留当前结构。

    Time Semantics:
        同步拒绝，不取时钟。
    """
    _reject_downgrade()
