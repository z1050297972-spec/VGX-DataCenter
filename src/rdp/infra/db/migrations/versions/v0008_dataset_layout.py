"""账号数据集布局迁移（M1-03），沿用M0冻结DDL、单事务和升级前备份。

活动版本0008只新增布局偏好表；0007索引及M0永久记录保持原样。
"""

from alembic import op

from rdp.infra.db.migrations.versions.v0001_error_reports import downgrade as _reject_downgrade

revision: str = "0008_dataset_layout"
down_revision: str = "0007_dataset_index"
branch_labels: tuple[str, ...] | None = None
depends_on: str | None = None

# 与领域声明逐项对齐；冻结SQL避免将来ORM变化改写历史迁移。
CREATE_TABLE_SQL = """
CREATE TABLE dataset_layout_preferences (
    account_id INTEGER NOT NULL,
    layout VARCHAR(1) NOT NULL,
    updated_at TEXT NOT NULL,
    CONSTRAINT pk_dataset_layout_preferences PRIMARY KEY (account_id),
    CONSTRAINT ck_dataset_layout_preferences_account_id CHECK (account_id > 0),
    CONSTRAINT ck_dataset_layout_preferences_layout CHECK (layout IN ('A','B','C')),
    CONSTRAINT fk_dataset_layout_preferences_account_id_accounts
        FOREIGN KEY(account_id) REFERENCES accounts (account_id) ON DELETE CASCADE
)
"""


def upgrade() -> None:
    """在既有账号表旁创建独立布局偏好表。

    Args:
        无；复用Alembic注入的在线连接及migrate已经取得的事务。

    Returns:
        无；新表结构为CREATE_TABLE_SQL，不回填默认行，不修改索引或已有账号。

    Raises:
        SQLAlchemyError: DDL、锁或I/O失败，由迁移入口统一转换四类异常。

    Side Effects:
        仅创建dataset_layout_preferences；外层整体回滚失败并保留升级前备份，
        不调用create_all、不导入领域模型、不改变已有迁移文件。

    Time Semantics:
        Web/worker停止后维护窗口执行，沿用migrate锁预算；时间底层TEXT，由UTCDateTime解释。
    """
    op.execute(CREATE_TABLE_SQL)


def downgrade() -> None:
    """拒绝会丢失账号偏好的自动降级，沿用M0前向迁移策略。

    Args:
        无；由Alembic调用，不接受强制删除开关。

    Returns:
        无；总是拒绝，不删除偏好或更改版本。

    Raises:
        InputError: 本迁移只支持前向升级，恢复需使用升级前备份。

    Side Effects:
        无；保留全部账号偏好、数据集索引和现有版本。

    Time Semantics:
        即时拒绝，不等锁、不读取时间、不尝试按记录年龄丢弃数据。
    """
    _reject_downgrade()
