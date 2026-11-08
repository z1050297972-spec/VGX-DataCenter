"""0019 创建机器人与采集词表、系统初始值及对应审计对象；不访问导航层或存储根。

冻结本版本 DDL，复用 0010 的冻结日志表定义，保留历史日志和发号高水位。
"""

from datetime import UTC, datetime

from alembic import op
from sqlalchemy import text

from rdp.infra.db.migrations.versions.v0001_error_reports import downgrade as _reject_downgrade
from rdp.infra.db.migrations.versions.v0010_nav_write_foundation import (
    INDEX_SQL,
    OPERATION_LOGS_SQL,
)
from rdp.infra.db.utc import format_utc_text

revision: str = "0019_collection_registry"
down_revision: str = "0018_information_filters"
branch_labels: tuple[str, ...] | None = None
depends_on: str | None = None

# 冻结 0019 的三张表定义，迁移运行时不导入领域模型。
_REGISTRY_SQL = (
    "\nCREATE TABLE robots (\n\trobot_id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT, \n\trobot_model VARCHAR(64) NOT NULL, \n\tserial_number VARCHAR(64), \n\tmacs JSON NOT NULL, \n\taddress VARCHAR(253), \n\tssh_port INTEGER DEFAULT '22' NOT NULL, \n\tssh_user VARCHAR(32), \n\tname VARCHAR(64) NOT NULL, \n\tstatus VARCHAR(7) NOT NULL, \n\tcreated_by_id INTEGER, \n\tcreated_by_name VARCHAR(64) NOT NULL, \n\tcreated_at TEXT NOT NULL, \n\tupdated_by_id INTEGER, \n\tupdated_by_name VARCHAR(64) NOT NULL, \n\tupdated_at TEXT NOT NULL, \n\tCONSTRAINT ck_robots_name CHECK (length(name) BETWEEN 1 AND 64), \n\tCONSTRAINT ck_robots_model CHECK (length(robot_model) BETWEEN 1 AND 64), \n\tCONSTRAINT ck_robots_serial CHECK (serial_number IS NULL OR length(serial_number) BETWEEN 1 AND 64), \n\tCONSTRAINT ck_robots_port CHECK (ssh_port BETWEEN 1 AND 65535), \n\tCONSTRAINT ck_robots_status CHECK (status IN ('active','retired')), \n\tCONSTRAINT uq_robots_serial_number UNIQUE (serial_number), \n\tCONSTRAINT uq_robots_name UNIQUE (name)\n)\n\n",
    "\nCREATE TABLE collection_methods (\n\tdata_origin VARCHAR(16) NOT NULL, \n\tid INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT, \n\tname VARCHAR(64) NOT NULL, \n\tstatus VARCHAR(7) NOT NULL, \n\tcreated_by_id INTEGER, \n\tcreated_by_name VARCHAR(64) NOT NULL, \n\tcreated_at TEXT NOT NULL, \n\tupdated_by_id INTEGER, \n\tupdated_by_name VARCHAR(64) NOT NULL, \n\tupdated_at TEXT NOT NULL, \n\tCONSTRAINT ck_collection_methods_name CHECK (length(name) BETWEEN 1 AND 32), \n\tCONSTRAINT ck_collection_methods_status CHECK (status IN ('active','retired')), \n\tCONSTRAINT ck_collection_methods_origin CHECK (data_origin IN ('真机采集','UMI 采集','ego 采集','仿真生成')), \n\tCONSTRAINT uq_collection_methods_name UNIQUE (name)\n)\n\n",
    "\nCREATE TABLE collection_purposes (\n\tid INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT, \n\tname VARCHAR(64) NOT NULL, \n\tstatus VARCHAR(7) NOT NULL, \n\tcreated_by_id INTEGER, \n\tcreated_by_name VARCHAR(64) NOT NULL, \n\tcreated_at TEXT NOT NULL, \n\tupdated_by_id INTEGER, \n\tupdated_by_name VARCHAR(64) NOT NULL, \n\tupdated_at TEXT NOT NULL, \n\tCONSTRAINT ck_collection_purposes_name CHECK (length(name) BETWEEN 1 AND 32), \n\tCONSTRAINT ck_collection_purposes_status CHECK (status IN ('active','retired')), \n\tCONSTRAINT uq_collection_purposes_name UNIQUE (name)\n)\n\n",
)


def upgrade() -> None:
    """创建三张登记表，依序写入五种采集方式及四种用途并扩展操作日志对象。

    Args:
        无；使用迁移入口已锁定、备份的数据库连接。

    Returns:
        无；新库中词表编号按工单初始取值顺序分配，机器人表为空。

    Raises:
        SQLAlchemyError: 创建、复制或初始化失败，由迁移入口映射数据库异常。

    Side Effects:
        同一事务新建三表、重建日志约束并写系统身份初始词表；失败整体回滚。
        保留原日志及 sqlite_sequence 高水位，不访问任何数据路径。

    Time Semantics:
        初始值采用迁移执行时的 UTC 微秒时刻；所有初始项共用一个时刻，不追溯到开发时间。
        Web/worker 停止后由迁移锁保护，同步执行，无额外重试。
    """
    for statement in _REGISTRY_SQL:
        op.execute(statement)
    now = format_utc_text(datetime.now(UTC))
    connection = op.get_bind()
    for name, origin in (
        ("主从臂遥操作", "真机采集"),
        ("VR 遥操作", "真机采集"),
        ("UMI 手持", "UMI 采集"),
        ("头戴相机", "ego 采集"),
        ("仿真脚本", "仿真生成"),
    ):
        connection.execute(
            text("""INSERT INTO collection_methods
            (name,data_origin,status,created_by_name,created_at,updated_by_name,updated_at)
            VALUES (:name,:origin,'active','系统',:now,'系统',:now)"""),
            {"name": name, "origin": origin, "now": now},
        )
    for name in ("训练", "评测", "演示", "试采"):
        connection.execute(
            text("""INSERT INTO collection_purposes
            (name,status,created_by_name,created_at,updated_by_name,updated_at)
            VALUES (:name,'active','系统',:now,'系统',:now)"""),
            {"name": name, "now": now},
        )
    previous = connection.scalar(
        text("SELECT COALESCE(MAX(seq),0) FROM sqlite_sequence WHERE name='operation_logs'")
    )
    op.execute("ALTER TABLE operation_logs RENAME TO operation_logs_before_0019")
    op.execute(
        OPERATION_LOGS_SQL.replace(
            "'navigation_write')",
            "'navigation_write','robot','collection_method','collection_purpose')",
        )
    )
    op.execute("INSERT INTO operation_logs SELECT * FROM operation_logs_before_0019")
    op.execute("DROP TABLE operation_logs_before_0019")
    op.execute(
        text(
            "UPDATE sqlite_sequence SET seq=MAX(seq,:previous) WHERE name='operation_logs'"
        ).bindparams(previous=previous)
    )
    for statement in INDEX_SQL:
        op.execute(statement)


def downgrade() -> None:
    """拒绝丢失机器人、词表及对应历史日志的降级。

    Args:
        无。

    Returns:
        无。

    Raises:
        InputError: 始终拒绝降级。

    Side Effects:
        无。

    Time Semantics:
        同步拒绝，不修改版本号。
    """
    _reject_downgrade()
