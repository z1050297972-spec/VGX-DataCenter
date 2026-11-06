"""0018 将筛选切换到规范信息顶层；只迁移索引，导航文件由回填作业负责。"""

from alembic import op

from rdp.infra.db.migrations.versions.v0001_error_reports import downgrade as _reject_downgrade

revision: str = "0018_information_filters"
down_revision: str = "0017_multi_scene"
branch_labels: tuple[str, ...] | None = None
depends_on: str | None = None


def upgrade() -> None:
    """增加信息帧率索引并清除旧来源文件提供的筛选值。

    Args:
        无。

    Returns:
        无；FPS 未标注，来源未知；重新扫描后按规范信息填充。

    Raises:
        SQLAlchemyError: 数据库迁移失败。

    Side Effects:
        新增 datasets.fps 列并重置来源索引，不读写导航层或存储根。

    Time Semantics:
        在迁移事务内同步执行；升级后需重新扫描。
    """
    op.execute(
        "ALTER TABLE datasets ADD COLUMN fps INTEGER CONSTRAINT ck_datasets_fps CHECK (fps IS NULL OR fps > 0)"
    )
    # 旧来源取自另一份文件，不能沿用它冒充新契约已经读取过信息顶层。
    op.execute("UPDATE datasets SET data_origin = 'unknown'")


def downgrade() -> None:
    """拒绝恢复已废弃的数据来源筛选语义。

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
