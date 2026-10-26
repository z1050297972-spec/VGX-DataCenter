"""基础层 0003 迁移契约（07），冻结 SQL，不依赖运行时领域模型。

列、约束和索引与 0003 定稿的表声明对应；
不能从领域导入模型或常量，防止旧迁移随业务代码变化（规范 1.1）。
"""

from alembic import op
from sqlalchemy import text

from rdp.infra.db.migrations.versions.v0001_error_reports import downgrade as _reject_downgrade

revision: str = "0003_audit_login_logs"
down_revision: str = "0002_accounts_sessions"
branch_labels: tuple[str, ...] | None = None
depends_on: str | None = None


def upgrade() -> None:
    """在已有迁移事务里创建两种日志表和共同保留期设置表。

    Args:
        无；由 Alembic 提供已备份且持有 BEGIN IMMEDIATE 的连接。

    Returns:
        无；operation_logs/login_logs/audit_settings 的列、CHECK 和索引与 07 模型一致；
        日志主键 AUTOINCREMENT，无账号外键；UTC 时间底层 TEXT，明细为 JSON。
        每种日志建 (occurred_at,log_id) 和 (账号编号,occurred_at,log_id) 索引；不建默认设置行。

    Raises:
        SQLAlchemyError: 任一 DDL、约束、锁或 I/O 失败；由外层 migrate 归入既有四类异常。

    Side Effects:
        仅新建三张表及索引，不更改既有账号/会话/报错数据，不回填历史日志；失败整个事务回滚，
        head 保持 0002，外层保留升级前备份。默认保留期 30，数据库约束 7-365，不安装调度任务。

    Time Semantics:
        备份和获锁已由 migrate 完成；沿用外层单次 5000 毫秒锁预算，无额外重试或时钟读取。
    """
    op.execute(
        text(
            "CREATE TABLE operation_logs (\n\tlog_id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT, \n\toccurred_at TEXT NOT NULL, \n\tactor_id INTEGER, \n\tactor_name VARCHAR(64) NOT NULL, \n\toperation VARCHAR(64) NOT NULL, \n\tobject_kind VARCHAR(16) NOT NULL, \n\tobject_id VARCHAR(64), \n\tobject_name VARCHAR(64) NOT NULL, \n\tresult VARCHAR(7) NOT NULL, \n\tfailure_category VARCHAR(8), \n\trequest_id VARCHAR(32), \n\tsource_ip VARCHAR(45), \n\tdetails JSON NOT NULL, \n\tCONSTRAINT ck_operation_logs_positive_id CHECK (log_id > 0), \n\tCONSTRAINT ck_operation_logs_actor_id CHECK (actor_id IS NULL OR actor_id > 0), \n\tCONSTRAINT ck_operation_logs_actor_name CHECK (length(actor_name) BETWEEN 1 AND 64), \n\tCONSTRAINT ck_operation_logs_ops_actor CHECK (actor_id IS NOT NULL OR actor_name = '运维'), \n\tCONSTRAINT ck_operation_logs_operation_length CHECK (length(operation) BETWEEN 1 AND 64), \n\tCONSTRAINT ck_operation_logs_object_kind CHECK (object_kind IN ('account','audit_settings')), \n\tCONSTRAINT ck_operation_logs_object_id CHECK (object_id IS NULL OR length(object_id) BETWEEN 1 AND 64), \n\tCONSTRAINT ck_operation_logs_object_name CHECK (length(object_name) BETWEEN 1 AND 64), \n\tCONSTRAINT ck_operation_logs_result_category CHECK ((result = 'success' AND failure_category IS NULL) OR (result = 'failure' AND failure_category IS NOT NULL AND failure_category IN ('input','conflict','external','defect'))), \n\tCONSTRAINT ck_operation_logs_request_id CHECK (request_id IS NULL OR (length(request_id) = 32 AND request_id NOT GLOB '*[^0-9a-f]*')), \n\tCONSTRAINT ck_operation_logs_source_ip CHECK (source_ip IS NULL OR length(source_ip) BETWEEN 1 AND 45)\n)"
        )
    )
    op.execute(
        text(
            "CREATE INDEX ix_operation_logs_actor_time_id ON operation_logs (actor_id, occurred_at, log_id)"
        )
    )
    op.execute(
        text("CREATE INDEX ix_operation_logs_time_id ON operation_logs (occurred_at, log_id)")
    )
    op.execute(
        text(
            "CREATE TABLE login_logs (\n\tlog_id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT, \n\toccurred_at TEXT NOT NULL, \n\taccount_id INTEGER, \n\taccount_name VARCHAR(64), \n\tlogin_name VARCHAR(32), \n\tkind VARCHAR(16) NOT NULL, \n\tresult VARCHAR(16) NOT NULL, \n\tsource_ip VARCHAR(45), \n\trequest_id VARCHAR(32), \n\tfailure_category VARCHAR(8), \n\tCONSTRAINT ck_login_logs_positive_id CHECK (log_id > 0), \n\tCONSTRAINT ck_login_logs_account_id CHECK (account_id IS NULL OR account_id > 0), \n\tCONSTRAINT ck_login_logs_kind CHECK (kind IN ('login','logout','session_expired')), \n\tCONSTRAINT ck_login_logs_result CHECK (result IN ('success','wrong_password','disabled','waiting','account_missing','failure')), \n\tCONSTRAINT ck_login_logs_deletion_success CHECK (kind = 'login' OR result = 'success'), \n\tCONSTRAINT ck_login_logs_identity_snapshot CHECK ((result IN ('account_missing','failure') AND account_id IS NULL AND account_name IS NULL AND login_name IS NULL AND request_id IS NULL) OR (result != 'account_missing' AND account_id IS NOT NULL AND account_name IS NOT NULL AND login_name IS NOT NULL AND length(account_name) BETWEEN 1 AND 64 AND length(login_name) BETWEEN 3 AND 32)), \n\tCONSTRAINT ck_login_logs_failure_category CHECK ((result != 'failure' AND failure_category IS NULL) OR (result = 'failure' AND failure_category IS NOT NULL AND failure_category IN ('input','conflict','external','defect'))), \n\tCONSTRAINT ck_login_logs_request_id CHECK (request_id IS NULL OR (length(request_id) = 32 AND request_id NOT GLOB '*[^0-9a-f]*')), \n\tCONSTRAINT ck_login_logs_source_ip CHECK (source_ip IS NULL OR length(source_ip) BETWEEN 1 AND 45)\n)"
        )
    )
    op.execute(
        text(
            "CREATE INDEX ix_login_logs_account_time_id ON login_logs (account_id, occurred_at, log_id)"
        )
    )
    op.execute(text("CREATE INDEX ix_login_logs_time_id ON login_logs (occurred_at, log_id)"))
    op.execute(
        text(
            "CREATE TABLE audit_settings (\n\tsettings_id INTEGER NOT NULL, \n\tretention_days INTEGER DEFAULT '30' NOT NULL, \n\tCONSTRAINT pk_audit_settings PRIMARY KEY (settings_id), \n\tCONSTRAINT ck_audit_settings_singleton CHECK (settings_id = 1), \n\tCONSTRAINT ck_audit_settings_retention_days CHECK (retention_days BETWEEN 7 AND 365)\n)"
        )
    )


def downgrade() -> None:
    """拒绝自动降级，避免静默丢失历史日志。

    Args:
        无。

    Returns:
        无；始终拒绝降级。

    Raises:
        InputError: 所有调用；提示停服务后人工恢复备份及匹配代码。

    Side Effects:
        无；执行任何删除 SQL 之前拒绝。

    Time Semantics:
        同步拒绝，无等待、时钟或重试。
    """
    _reject_downgrade()
