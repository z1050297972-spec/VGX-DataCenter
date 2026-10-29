"""0009重建索引审计对象扩展；冻结DDL仅新增对象种类，保留全部历史及发号高水位。"""

from alembic import op
from sqlalchemy import text

from rdp.infra.db.migrations.versions.v0001_error_reports import downgrade as _reject_downgrade

revision: str = "0009_rebuild_index_audit"
down_revision: str = "0008_dataset_layout"
branch_labels: tuple[str, ...] | None = None
depends_on: str | None = None


def upgrade() -> None:
    """扩展操作日志对象约束，允许记录全量数据集索引重建。

    Args:
        无；Alembic提供已有备份和写事务的连接。

    Returns:
        无；仅增加dataset_index对象种类，既有字段含义不变。

    Raises:
        SQLAlchemyError: DDL、复制或序列恢复失败，由migrate转换并整体回滚。

    Side Effects:
        同事务复制重建operation_logs及两个索引；保留历史行和sqlite_sequence，
        已删除高编号不复用，空表也保留发号高水位。不改旧迁移。

    Time Semantics:
        停服务后的维护窗口执行，锁预算沿用migrate；不读取时钟或存储根。
    """
    connection = op.get_bind()
    previous = connection.scalar(
        text("SELECT COALESCE(MAX(seq),0) FROM sqlite_sequence WHERE name='operation_logs'")
    )
    op.execute("ALTER TABLE operation_logs RENAME TO operation_logs_before_0009")
    op.execute(CREATE_SQL)
    op.execute(COPY_SQL)
    op.execute("DROP TABLE operation_logs_before_0009")
    op.execute(
        text(
            "UPDATE sqlite_sequence SET seq=MAX(seq,:previous) WHERE name='operation_logs'"
        ).bindparams(previous=previous)
    )
    for statement in INDEX_SQL:
        op.execute(statement)


def downgrade() -> None:
    """拒绝会丢失重建操作记录的降级。

    Args:
        无；由Alembic调用。

    Returns:
        无；始终拒绝。

    Raises:
        InputError: 不支持前向迁移的自动降级。

    Side Effects:
        无；保留当前结构和全部操作日志。

    Time Semantics:
        即时拒绝，不重试。
    """
    _reject_downgrade()


# 冻结0009表结构，不从运行时ORM生成；只放宽对象种类CHECK。
CREATE_SQL = "\nCREATE TABLE operation_logs (\n\tlog_id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT, \n\toccurred_at TEXT NOT NULL, \n\tactor_id INTEGER, \n\tactor_name VARCHAR(64) NOT NULL, \n\toperation VARCHAR(64) NOT NULL, \n\tobject_kind VARCHAR(16) NOT NULL, \n\tobject_id VARCHAR(64), \n\tobject_name VARCHAR(64) NOT NULL, \n\tresult VARCHAR(7) NOT NULL, \n\tfailure_category VARCHAR(8), \n\trequest_id VARCHAR(32), \n\tsource_ip VARCHAR(45), \n\tdetails JSON NOT NULL, \n\tCONSTRAINT ck_operation_logs_positive_id CHECK (log_id > 0), \n\tCONSTRAINT ck_operation_logs_actor_id CHECK (actor_id IS NULL OR actor_id > 0), \n\tCONSTRAINT ck_operation_logs_actor_name CHECK (length(actor_name) BETWEEN 1 AND 64), \n\tCONSTRAINT ck_operation_logs_ops_actor CHECK (actor_id IS NOT NULL OR actor_name IN ('运维','系统')), \n\tCONSTRAINT ck_operation_logs_operation_length CHECK (length(operation) BETWEEN 1 AND 64), \n\tCONSTRAINT ck_operation_logs_object_kind CHECK (object_kind IN ('account','audit_settings','job','dataset_index')), \n\tCONSTRAINT ck_operation_logs_object_id CHECK (object_id IS NULL OR length(object_id) BETWEEN 1 AND 64), \n\tCONSTRAINT ck_operation_logs_object_name CHECK (length(object_name) BETWEEN 1 AND 64), \n\tCONSTRAINT ck_operation_logs_result_category CHECK ((result = 'success' AND failure_category IS NULL) OR (result = 'failure' AND failure_category IS NOT NULL AND failure_category IN ('input','conflict','external','defect'))), \n\tCONSTRAINT ck_operation_logs_request_id CHECK (request_id IS NULL OR (length(request_id) = 32 AND request_id NOT GLOB '*[^0-9a-f]*')), \n\tCONSTRAINT ck_operation_logs_source_ip CHECK (source_ip IS NULL OR length(source_ip) BETWEEN 1 AND 45)\n)\n\n"
COPY_SQL = "INSERT INTO operation_logs (log_id,occurred_at,actor_id,actor_name,operation,object_kind,object_id,object_name,result,failure_category,request_id,source_ip,details) SELECT log_id,occurred_at,actor_id,actor_name,operation,object_kind,object_id,object_name,result,failure_category,request_id,source_ip,details FROM operation_logs_before_0009"
INDEX_SQL = (
    "CREATE INDEX ix_operation_logs_actor_time_id ON operation_logs (actor_id, occurred_at, log_id)",
    "CREATE INDEX ix_operation_logs_time_id ON operation_logs (occurred_at, log_id)",
)
