"""0017 将场景索引升级为 JSON 数组；只改数据库，不触碰导航层或存储根。

沿用 tasks 的 JSON 索引表示，标准库 json 保留旧文本（包括中文和引号）。
"""

import json

from alembic import op

from rdp.infra.db.migrations.versions.v0001_error_reports import downgrade as _reject_downgrade

revision: str = "0017_multi_scene"
down_revision: str = "0016_monitoring"
branch_labels: tuple[str, ...] | None = None
depends_on: str | None = None


def upgrade() -> None:
    """将已有单场景转换为数组并保留全部索引行。

    Args:
        无。

    Returns:
        无；旧值去首尾空格后成为单项数组，NULL 和空串成为空数组。

    Raises:
        SQLAlchemyError: 数据库结构或数据迁移失败。

    Side Effects:
        新建 scene_json 列、逐行迁移旧值后删除旧 scene 列；不读取导航层。

    Time Semantics:
        在迁移事务内同步执行；只保留当前行，不按数据集总量累积内存。
    """
    op.execute("ALTER TABLE datasets ADD COLUMN scene_json JSON NOT NULL DEFAULT '[]'")
    connection = op.get_bind()
    rows = connection.exec_driver_sql("SELECT dataset_id, scene FROM datasets")
    for identifier, value in rows:
        normalized = value.strip() if isinstance(value, str) else ""
        connection.exec_driver_sql(
            "UPDATE datasets SET scene_json = ? WHERE dataset_id = ?",
            (json.dumps([normalized] if normalized else [], ensure_ascii=False), identifier),
        )
    rows.close()
    # 新列全部填好才移除旧列，避免应用读到混合的字符串与数组形状。
    op.execute("ALTER TABLE datasets DROP COLUMN scene")


def downgrade() -> None:
    """拒绝有损降级，防止多场景被截断。

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
