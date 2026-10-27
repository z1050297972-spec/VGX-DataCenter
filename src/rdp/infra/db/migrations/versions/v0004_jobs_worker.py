"""0004 作业/心跳及审计 job 对象迁移；冻结 SQL 定义，不导入领域模型或运行时常量。

SQLite 不能直接修改 CHECK，operation_logs 在同一迁移事务中复制重建，必须保存 sqlite_sequence，
不能只按现存 MAX(log_id) 推算；保留期可能已经删掉最大编号的记录（08 负责人批准）。
"""

from alembic import op
from sqlalchemy import text

from rdp.infra.db.migrations.versions.v0001_error_reports import downgrade as _reject_downgrade
from rdp.infra.db.validation import invalid_field

revision: str = "0004_jobs_worker"
down_revision: str = "0003_audit_login_logs"
branch_labels: tuple[str, ...] | None = None
depends_on: str | None = None


def upgrade() -> None:
    """原子扩展审计对象 CHECK 并创建永久作业记录和单行心跳表。

    Args:
        无；Alembic 提供外层已备份、持有 BEGIN IMMEDIATE 的连接。

    Returns:
        无；新增 jobs/worker_heartbeat，列和约束与 0004的表声明一致。
        jobs 主键 INTEGER PRIMARY KEY AUTOINCREMENT，无账号外键；UTC 时间 TEXT，
        JSON 参数/进度/诊断/摘要、独立计数和日志相对路径永久保存；
        (state,job_id)索引用于领取和状态筛选，全部列表按job_id复用主键索引，避免墙钟回拨打乱顺序。
        recovery_count为NOT NULL整数，默认0、CHECK范围0至3；新提交/重新提交从0开始，自动重跑不清零。
        log_path唯一，running/cancelling/completed/interrupted要求非空，与领取状态同事务写入。
        心跳 singleton_id=1，实例标识、pid、启动/最后心跳 UTC 时刻必填。

    Raises:
        SQLAlchemyError: 任一步 DDL、复制、序列恢复或索引创建失败，交 migrate 按既有四类映射。
        InputError: 原审计表/序列损坏或不能保证历史编号不复用，拒绝猜测并回滚。

    Side Effects:
        重建 operation_logs：所有旧列、记录、名字、编号、其他 CHECK 和两个原索引保持原样，
        只将 object_kind CHECK 从 account/audit_settings 扩为 account/audit_settings/job。
        删除旧表前读取其 sqlite_sequence.seq；复制后把新表序列恢复为
        max(重建前序列,重建后序列,现存最大编号)，空表和删除了历史最大编号也不降低高水位。
        不改 0003 脚本，不回填作业历史；表替换、序列、索引、新表和版本更新全在一个事务，
        任一步失败整体回滚至 0003，外层备份保留，不留下中间表或半套索引。

    Time Semantics:
        升级前停 Web/worker，由 migrate 持有迁移锁并备份；沿用单次 5 秒数据库锁预算，
        复制耗时取决于历史行数，按数据库执行，不在 Python 全量加载，无自动重试。
    """
    previous_sequence = _operation_sequence()
    # 新表使用冻结DDL；先保留旧表再复制，只有同一事务提交才对外出现新结构。
    op.execute(text("ALTER TABLE operation_logs RENAME TO operation_logs_before_0004"))
    op.execute(text(_OPERATIONS_DDL))
    op.execute(
        text(
            "INSERT INTO operation_logs (log_id, occurred_at, actor_id, actor_name, operation, object_kind, object_id, object_name, result, failure_category, request_id, source_ip, details) SELECT log_id, occurred_at, actor_id, actor_name, operation, object_kind, object_id, object_name, result, failure_category, request_id, source_ip, details FROM operation_logs_before_0004"
        )
    )
    op.execute(text("DROP TABLE operation_logs_before_0004"))
    # 保留期可能已删掉最大编号；仅从复制后的MAX(log_id)恢复会复用已经发出的编号。
    op.execute(
        text(
            "UPDATE sqlite_sequence SET seq=MAX(seq,:previous) WHERE name='operation_logs'"
        ).bindparams(previous=previous_sequence)
    )
    op.execute(text(_JOBS_DDL))
    op.execute(text(_HEARTBEAT_DDL))
    for statement in _INDEX_DDL:
        op.execute(text(statement))


def downgrade() -> None:
    """按平台只前进迁移策略拒绝降级，保护永久作业和 job 审计记录。

    Args:
        无；即使当前没有 job 审计记录也不自动降级。

    Returns:
        无；始终拒绝，不删除任何表或记录。

    Raises:
        InputError: 任意调用，提示停服务后人工恢复完整备份及匹配版本代码。

    Side Effects:
        无；有 job 记录时不尝试转成 account、不丢弃记录，执行任何 DDL 前拒绝。

    Time Semantics:
        同步拒绝，无锁重试、时钟或数据扫描。
    """
    _reject_downgrade()


# 0004冻结的SQLite建表及索引文本；不从可演进的领域模型动态生成。
_OPERATIONS_DDL = "CREATE TABLE operation_logs (\n\tlog_id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT, \n\toccurred_at TEXT NOT NULL, \n\tactor_id INTEGER, \n\tactor_name VARCHAR(64) NOT NULL, \n\toperation VARCHAR(64) NOT NULL, \n\tobject_kind VARCHAR(16) NOT NULL, \n\tobject_id VARCHAR(64), \n\tobject_name VARCHAR(64) NOT NULL, \n\tresult VARCHAR(7) NOT NULL, \n\tfailure_category VARCHAR(8), \n\trequest_id VARCHAR(32), \n\tsource_ip VARCHAR(45), \n\tdetails JSON NOT NULL, \n\tCONSTRAINT ck_operation_logs_positive_id CHECK (log_id > 0), \n\tCONSTRAINT ck_operation_logs_actor_id CHECK (actor_id IS NULL OR actor_id > 0), \n\tCONSTRAINT ck_operation_logs_actor_name CHECK (length(actor_name) BETWEEN 1 AND 64), \n\tCONSTRAINT ck_operation_logs_ops_actor CHECK (actor_id IS NOT NULL OR actor_name = '运维'), \n\tCONSTRAINT ck_operation_logs_operation_length CHECK (length(operation) BETWEEN 1 AND 64), \n\tCONSTRAINT ck_operation_logs_object_kind CHECK (object_kind IN ('account','audit_settings','job')), \n\tCONSTRAINT ck_operation_logs_object_id CHECK (object_id IS NULL OR length(object_id) BETWEEN 1 AND 64), \n\tCONSTRAINT ck_operation_logs_object_name CHECK (length(object_name) BETWEEN 1 AND 64), \n\tCONSTRAINT ck_operation_logs_result_category CHECK ((result = 'success' AND failure_category IS NULL) OR (result = 'failure' AND failure_category IS NOT NULL AND failure_category IN ('input','conflict','external','defect'))), \n\tCONSTRAINT ck_operation_logs_request_id CHECK (request_id IS NULL OR (length(request_id) = 32 AND request_id NOT GLOB '*[^0-9a-f]*')), \n\tCONSTRAINT ck_operation_logs_source_ip CHECK (source_ip IS NULL OR length(source_ip) BETWEEN 1 AND 45)\n)"
_JOBS_DDL = "CREATE TABLE jobs (\n\tjob_id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT, \n\ttype_name VARCHAR(64) NOT NULL, \n\tdisplay_name VARCHAR(40) NOT NULL, \n\tparameters JSON NOT NULL, \n\tsubmitter_id INTEGER NOT NULL, \n\tsubmitter_name VARCHAR(64) NOT NULL, \n\tsubmitted_at TEXT NOT NULL, \n\tresubmitted_from INTEGER, \n\tstate VARCHAR(16) NOT NULL, \n\trecovery_mode VARCHAR(16) NOT NULL, \n\trecovery_count INTEGER DEFAULT '0' NOT NULL, \n\tstarted_at TEXT, \n\tended_at TEXT, \n\toutcome VARCHAR(32), \n\ttotal_items INTEGER NOT NULL, \n\tfailed_items INTEGER NOT NULL, \n\twarning_count INTEGER NOT NULL, \n\taborted BOOLEAN NOT NULL, \n\tprogress JSON, \n\tprogress_at TEXT, \n\telapsed_s FLOAT NOT NULL, \n\tartifacts JSON NOT NULL, \n\tlog_path TEXT, \n\tdiagnostics JSON NOT NULL, \n\tsummary JSON, \n\ttool_exit_code INTEGER, \n\tCONSTRAINT ck_jobs_positive_ids CHECK (job_id > 0 AND submitter_id > 0), \n\tCONSTRAINT ck_jobs_type_length CHECK (length(type_name) BETWEEN 1 AND 64), \n\tCONSTRAINT ck_jobs_display_length CHECK (length(display_name) BETWEEN 1 AND 40), \n\tCONSTRAINT ck_jobs_submitter_length CHECK (length(submitter_name) BETWEEN 1 AND 64), \n\tCONSTRAINT ck_jobs_state CHECK (state IN ('queued','running','cancelling','completed','cancelled','interrupted')), \n\tCONSTRAINT ck_jobs_recovery CHECK (recovery_mode IN ('resume','restart','interrupt')), \n\tCONSTRAINT ck_jobs_counts CHECK (total_items >= 0 AND failed_items BETWEEN 0 AND total_items AND warning_count >= 0), \n\tCONSTRAINT ck_jobs_elapsed CHECK (elapsed_s >= 0), \n\tCONSTRAINT ck_jobs_recovery_count CHECK (recovery_count BETWEEN 0 AND 3), \n\tCONSTRAINT ck_jobs_claimed_log_path CHECK (state NOT IN ('running','cancelling','completed','interrupted') OR log_path IS NOT NULL), \n\tCONSTRAINT uq_jobs_log_path UNIQUE (log_path), \n\tCONSTRAINT ck_jobs_outcome CHECK ((state = 'completed' AND outcome IS NOT NULL AND outcome IN ('succeeded','succeeded_with_warnings','partially_succeeded','failed')) OR (state != 'completed' AND outcome IS NULL)), \n\tCONSTRAINT ck_jobs_terminal CHECK ((state IN ('completed','cancelled','interrupted') AND ended_at IS NOT NULL AND summary IS NOT NULL) OR (state IN ('queued','running','cancelling') AND ended_at IS NULL AND summary IS NULL))\n)"
_HEARTBEAT_DDL = "CREATE TABLE worker_heartbeat (\n\tsingleton_id INTEGER NOT NULL, \n\tinstance_id VARCHAR(32) NOT NULL, \n\tpid INTEGER NOT NULL, \n\tstarted_at TEXT NOT NULL, \n\tlast_seen_at TEXT NOT NULL, \n\tCONSTRAINT pk_worker_heartbeat PRIMARY KEY (singleton_id), \n\tCONSTRAINT ck_worker_heartbeat_singleton CHECK (singleton_id = 1), \n\tCONSTRAINT ck_worker_heartbeat_pid CHECK (pid > 0), \n\tCONSTRAINT ck_worker_heartbeat_instance CHECK (length(instance_id) = 32)\n)"
_INDEX_DDL = (
    "CREATE INDEX ix_operation_logs_actor_time_id ON operation_logs (actor_id, occurred_at, log_id)",
    "CREATE INDEX ix_operation_logs_time_id ON operation_logs (occurred_at, log_id)",
    "CREATE INDEX ix_jobs_state_id ON jobs (state, job_id)",
)


def _operation_sequence() -> int:
    """重建前校验高水位；非空表丢失序列时已经无法知道删掉过哪些编号，拒绝猜测。"""
    connection = op.get_bind()
    values = (
        connection.execute(text("SELECT seq FROM sqlite_sequence WHERE name='operation_logs'"))
        .scalars()
        .all()
    )
    maximum = connection.execute(text("SELECT MAX(log_id) FROM operation_logs")).scalar_one()
    if len(values) > 1 or (not values and maximum is not None):
        raise invalid_field("operation_logs.sequence", "唯一且完整的历史编号高水位")
    if not values:
        return 0
    value = values[0]
    if type(value) is not int or value < 0:
        raise invalid_field("operation_logs.sequence", "非负整数的历史编号高水位")
    return value
