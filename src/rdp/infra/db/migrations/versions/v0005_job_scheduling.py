"""0005 作业资源与每日提交去重；冻结迁移不修改 0004，也不 import 可演进的领域模型。

DDL 在本版本冻结；模型变更必须另写迁移，不能在运行时从领域模型生成历史结构。
"""

from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from typing import Literal

from alembic import op
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from rdp.infra.db.connection import translate_database_error
from rdp.infra.db.validation import invalid_field
from rdp.infra.diagnostics import ConflictError, DiagnosticCategory

revision = "0005_job_scheduling"
down_revision = "0004_jobs_worker"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """原子扩展系统提交人、资源展示列及每日唯一提交表。

    Args:
        无；连接和事务由 Alembic 提供。

    Returns:
        无；成功版本为 0005_job_scheduling，既有作业和操作日志的值不变。

    Raises:
        ConflictError: 迁移写锁或约束竞争；不因有编号账号的历史名字为“系统”拒绝升级。
        InputError: 数据库损坏或源表记录不满足既有契约。
        ExternalError: 重建表、复制、索引或序列恢复 I/O 失败。
        DefectError: 版本前提、DDL 或列映射不一致。

    Side Effects:
        重建 jobs：submitter_id 可空，空编号必须 submitter_name='系统'；非空编号仍正整数，允许名字为“系统”的账号。
        新增 gpu_index NULL、wait_reason NULL、holds_navigation_lock NOT NULL DEFAULT 0，
        CHECK 约束与 scheduling_models 一致，原有全部列值、状态边、索引和日志路径唯一约束保留。
        重建 operation_logs，仅把空 actor_id 的固定名字约束放开为“运维”或“系统”，其他约束及索引不变。
        两张重建表先读取各自 sqlite_sequence，复制后恢复 max(旧序列,当前最大编号)，
        包括高编号行已删除及空表情形，保持 AUTOINCREMENT、不复用编号，不改旧迁移文本。
        新建 schedule_submissions，以 (schedule_name,local_date) 复合主键去重，job_id 唯一，
        索引 (schedule_name,job_id) 支持最近提交；日期是本地日历值，提交时刻用 UTC 文本。
        新建 worker_gpu_checks，保存每张配置卡的 instance_id、available、diagnostics 和 UTC checked_at；
        只作页面副本，实际可用集合由启动核对构造的内存池决定。
        整体由外层迁移事务提交；失败回滚，无新老结构混合或部分历史丢失。

    Time Semantics:
        不读取时钟、不提交定时作业；只在维护窗口且 worker 未运行时由受控迁移入口执行。
        锁/备份预算沿用第 5 张迁移入口，不自行无限重试。
    """
    with _translated():
        _rebuild("jobs", _JOBS_DDL, _JOB_COLUMNS)
        _rebuild("operation_logs", _OPERATIONS_DDL, _OPERATION_COLUMNS)
        op.execute(text(_SCHEDULES_DDL))
        op.execute(text(_GPU_CHECKS_DDL))
        for statement in _INDEX_DDL:
            op.execute(text(statement))


def downgrade() -> None:
    """仅在没有会丢失的调度数据时恢复 0004 的结构。

    Args:
        无；使用 Alembic 当前连接及外层事务。

    Returns:
        无；安全降级后活动版本为 0004_jobs_worker。

    Raises:
        ConflictError: 存在系统提交作业、系统操作日志、任一定时提交行、非空 GPU/等待原因
            或真持锁标记、任意 worker_gpu_checks 行；拒绝丢失历史和资源信息，全部结构保持 0005。
        InputError: 存量数据库损坏。
        ExternalError: 重建/复制/删除表或序列恢复失败，整个事务回滚。
        DefectError: 非 0005 结构或冻结 DDL 不一致。

    Side Effects:
        先完成全部拒绝条件检查，再重建 jobs/operation_logs 为冻结 0004 定义并删除空定时表及空核卡表；
        保留旧行、索引与两表 AUTOINCREMENT 高水位，不改 0004 文件，不静默删系统历史。

    Time Semantics:
        不按时间猜数据可丢弃；维护窗口同步迁移，锁等待沿用入口预算。
    """
    with _translated():
        _check_downgrade()
        _rebuild("jobs", _V4_JOBS_DDL, _JOB_COLUMNS)
        _rebuild("operation_logs", _V4_OPERATIONS_DDL, _OPERATION_COLUMNS)
        op.execute(text("DROP TABLE schedule_submissions"))
        op.execute(text("DROP TABLE worker_gpu_checks"))
        for statement in _INDEX_DDL:
            if "schedule_submissions" not in statement:
                op.execute(text(statement))


@contextmanager
def _translated() -> Generator[None]:
    """迁移公开边界复用统一数据库错误分类，保留原始原因及外层事务回滚责任。"""
    try:
        yield
    except SQLAlchemyError as error:
        path = Path(op.get_bind().engine.url.database or "")
        raise translate_database_error(
            error, database=path, operation="迁移作业调度结构"
        ) from error


def _sequence(table: Literal["jobs", "operation_logs"]) -> int:
    """保留已删除历史编号的高水位；损坏或重复序列拒绝猜测。"""
    connection = op.get_bind()
    values = (
        connection.execute(
            text("SELECT seq FROM sqlite_sequence WHERE name=:name"), {"name": table}
        )
        .scalars()
        .all()
    )
    identifier = "job_id" if table == "jobs" else "log_id"
    # table和identifier仅来自本迁移的固定表/列清单，不接收外部输入。
    maximum = connection.execute(text(f"SELECT MAX({identifier}) FROM {table}")).scalar_one()  # noqa: S608
    if len(values) > 1 or (not values and maximum is not None):
        raise invalid_field(f"{table}.sequence", "唯一且完整的历史编号高水位")
    value = values[0] if values else 0
    if type(value) is not int or value < 0:
        raise invalid_field(f"{table}.sequence", "非负整数的历史编号高水位")
    return max(value, maximum or 0)


def _rebuild(table: Literal["jobs", "operation_logs"], ddl: str, columns: tuple[str, ...]) -> None:
    """同一事务复制重建并恢复序列；列名来自冻结清单，绝不将模型新增列自动加入旧数据复制。"""
    previous = _sequence(table)
    old = table + "_before_0005"
    op.execute(text(f"ALTER TABLE {table} RENAME TO {old}"))
    op.execute(text(ddl))
    names = ",".join(columns)
    # 表名和列名均由本文件冻结常量提供，参数绑定只用于值，不能绑定SQL标识符。
    op.execute(text(f"INSERT INTO {table} ({names}) SELECT {names} FROM {old}"))  # noqa: S608
    op.execute(text(f"DROP TABLE {old}"))
    # 空表复制也必须恢复序列；删除再插入兼容原表从未发号与删光记录两种情况。
    op.execute(text("DELETE FROM sqlite_sequence WHERE name=:name").bindparams(name=table))
    op.execute(
        text("INSERT INTO sqlite_sequence(name,seq) VALUES (:name,:seq)").bindparams(
            name=table, seq=previous
        )
    )


# 以下DDL与列清单固定为0005发布时的结构，不在迁移执行期间读取领域模型。
_JOBS_DDL = "\nCREATE TABLE jobs (\n\tjob_id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT, \n\ttype_name VARCHAR(64) NOT NULL, \n\tdisplay_name VARCHAR(40) NOT NULL, \n\tparameters JSON NOT NULL, \n\tsubmitter_id INTEGER, \n\tsubmitter_name VARCHAR(64) NOT NULL, \n\tsubmitted_at TEXT NOT NULL, \n\tresubmitted_from INTEGER, \n\tstate VARCHAR(16) NOT NULL, \n\trecovery_mode VARCHAR(16) NOT NULL, \n\trecovery_count INTEGER DEFAULT '0' NOT NULL, \n\tstarted_at TEXT, \n\tended_at TEXT, \n\toutcome VARCHAR(32), \n\ttotal_items INTEGER NOT NULL, \n\tfailed_items INTEGER NOT NULL, \n\twarning_count INTEGER NOT NULL, \n\taborted BOOLEAN NOT NULL, \n\tprogress JSON, \n\tprogress_at TEXT, \n\telapsed_s FLOAT NOT NULL, \n\tartifacts JSON NOT NULL, \n\tlog_path TEXT, \n\tdiagnostics JSON NOT NULL, \n\tsummary JSON, \n\ttool_exit_code INTEGER, \n\tgpu_index INTEGER, \n\twait_reason VARCHAR(24), \n\tholds_navigation_lock BOOLEAN DEFAULT '0' NOT NULL, \n\tCONSTRAINT ck_jobs_job_submitter_identity CHECK ((submitter_id IS NULL AND submitter_name = '系统') OR (submitter_id IS NOT NULL AND submitter_id > 0)), \n\tCONSTRAINT ck_jobs_gpu_index CHECK (gpu_index IS NULL OR gpu_index >= 0), \n\tCONSTRAINT ck_jobs_wait_reason CHECK (wait_reason IS NULL OR wait_reason IN ('gpu','navigation_lock')), \n\tCONSTRAINT ck_jobs_navigation_boolean CHECK (holds_navigation_lock IN (0,1)), \n\tCONSTRAINT ck_jobs_navigation_holder_state CHECK (holds_navigation_lock = 0 OR (state IN ('running','cancelling') AND wait_reason IS NULL)), \n\tCONSTRAINT ck_jobs_terminal_resources CHECK (state NOT IN ('completed','cancelled','interrupted') OR (wait_reason IS NULL AND holds_navigation_lock = 0)), \n\tCONSTRAINT ck_jobs_navigation_wait_state CHECK (wait_reason != 'navigation_lock' OR state IN ('running','cancelling')), \n\tCONSTRAINT ck_jobs_gpu_wait_state CHECK (wait_reason != 'gpu' OR (state IN ('queued','running') AND gpu_index IS NULL)), \n\tCONSTRAINT ck_jobs_positive_ids CHECK (job_id > 0 AND submitter_id > 0), \n\tCONSTRAINT ck_jobs_type_length CHECK (length(type_name) BETWEEN 1 AND 64), \n\tCONSTRAINT ck_jobs_display_length CHECK (length(display_name) BETWEEN 1 AND 40), \n\tCONSTRAINT ck_jobs_submitter_length CHECK (length(submitter_name) BETWEEN 1 AND 64), \n\tCONSTRAINT ck_jobs_state CHECK (state IN ('queued','running','cancelling','completed','cancelled','interrupted')), \n\tCONSTRAINT ck_jobs_recovery CHECK (recovery_mode IN ('resume','restart','interrupt')), \n\tCONSTRAINT ck_jobs_counts CHECK (total_items >= 0 AND failed_items BETWEEN 0 AND total_items AND warning_count >= 0), \n\tCONSTRAINT ck_jobs_elapsed CHECK (elapsed_s >= 0), \n\tCONSTRAINT ck_jobs_recovery_count CHECK (recovery_count BETWEEN 0 AND 3), \n\tCONSTRAINT ck_jobs_claimed_log_path CHECK (state NOT IN ('running','cancelling','completed','interrupted') OR log_path IS NOT NULL), \n\tCONSTRAINT uq_jobs_log_path UNIQUE (log_path), \n\tCONSTRAINT ck_jobs_outcome CHECK ((state = 'completed' AND outcome IS NOT NULL AND outcome IN ('succeeded','succeeded_with_warnings','partially_succeeded','failed')) OR (state != 'completed' AND outcome IS NULL)), \n\tCONSTRAINT ck_jobs_terminal CHECK ((state IN ('completed','cancelled','interrupted') AND ended_at IS NOT NULL AND summary IS NOT NULL) OR (state IN ('queued','running','cancelling') AND ended_at IS NULL AND summary IS NULL))\n)\n\n"
_OPERATIONS_DDL = "\nCREATE TABLE operation_logs (\n\tlog_id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT, \n\toccurred_at TEXT NOT NULL, \n\tactor_id INTEGER, \n\tactor_name VARCHAR(64) NOT NULL, \n\toperation VARCHAR(64) NOT NULL, \n\tobject_kind VARCHAR(16) NOT NULL, \n\tobject_id VARCHAR(64), \n\tobject_name VARCHAR(64) NOT NULL, \n\tresult VARCHAR(7) NOT NULL, \n\tfailure_category VARCHAR(8), \n\trequest_id VARCHAR(32), \n\tsource_ip VARCHAR(45), \n\tdetails JSON NOT NULL, \n\tCONSTRAINT ck_operation_logs_positive_id CHECK (log_id > 0), \n\tCONSTRAINT ck_operation_logs_actor_id CHECK (actor_id IS NULL OR actor_id > 0), \n\tCONSTRAINT ck_operation_logs_actor_name CHECK (length(actor_name) BETWEEN 1 AND 64), \n\tCONSTRAINT ck_operation_logs_ops_actor CHECK (actor_id IS NOT NULL OR actor_name IN ('运维','系统')), \n\tCONSTRAINT ck_operation_logs_operation_length CHECK (length(operation) BETWEEN 1 AND 64), \n\tCONSTRAINT ck_operation_logs_object_kind CHECK (object_kind IN ('account','audit_settings','job')), \n\tCONSTRAINT ck_operation_logs_object_id CHECK (object_id IS NULL OR length(object_id) BETWEEN 1 AND 64), \n\tCONSTRAINT ck_operation_logs_object_name CHECK (length(object_name) BETWEEN 1 AND 64), \n\tCONSTRAINT ck_operation_logs_result_category CHECK ((result = 'success' AND failure_category IS NULL) OR (result = 'failure' AND failure_category IS NOT NULL AND failure_category IN ('input','conflict','external','defect'))), \n\tCONSTRAINT ck_operation_logs_request_id CHECK (request_id IS NULL OR (length(request_id) = 32 AND request_id NOT GLOB '*[^0-9a-f]*')), \n\tCONSTRAINT ck_operation_logs_source_ip CHECK (source_ip IS NULL OR length(source_ip) BETWEEN 1 AND 45)\n)\n\n"
_SCHEDULES_DDL = "\nCREATE TABLE schedule_submissions (\n\tschedule_name VARCHAR(64) NOT NULL, \n\tlocal_date DATE NOT NULL, \n\tjob_id INTEGER NOT NULL, \n\tsubmitted_at TEXT NOT NULL, \n\tCONSTRAINT pk_schedule_submissions PRIMARY KEY (schedule_name, local_date), \n\tCONSTRAINT ck_schedule_submissions_schedule_name CHECK (length(schedule_name) BETWEEN 1 AND 64), \n\tCONSTRAINT ck_schedule_submissions_job_id CHECK (job_id > 0), \n\tCONSTRAINT uq_schedule_submissions_job_id UNIQUE (job_id)\n)\n\n"
_GPU_CHECKS_DDL = "\nCREATE TABLE worker_gpu_checks (\n\tgpu_index INTEGER NOT NULL, \n\tinstance_id VARCHAR(32) NOT NULL, \n\tavailable BOOLEAN NOT NULL, \n\tdiagnostics JSON NOT NULL, \n\tchecked_at TEXT NOT NULL, \n\tCONSTRAINT pk_worker_gpu_checks PRIMARY KEY (gpu_index), \n\tCONSTRAINT ck_worker_gpu_checks_gpu_index CHECK (gpu_index >= 0), \n\tCONSTRAINT ck_worker_gpu_checks_instance_id CHECK (length(instance_id) = 32), \n\tCONSTRAINT ck_worker_gpu_checks_available CHECK (available IN (0,1))\n)\n\n"
_V4_JOBS_DDL = "CREATE TABLE jobs (\n\tjob_id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT, \n\ttype_name VARCHAR(64) NOT NULL, \n\tdisplay_name VARCHAR(40) NOT NULL, \n\tparameters JSON NOT NULL, \n\tsubmitter_id INTEGER NOT NULL, \n\tsubmitter_name VARCHAR(64) NOT NULL, \n\tsubmitted_at TEXT NOT NULL, \n\tresubmitted_from INTEGER, \n\tstate VARCHAR(16) NOT NULL, \n\trecovery_mode VARCHAR(16) NOT NULL, \n\trecovery_count INTEGER DEFAULT '0' NOT NULL, \n\tstarted_at TEXT, \n\tended_at TEXT, \n\toutcome VARCHAR(32), \n\ttotal_items INTEGER NOT NULL, \n\tfailed_items INTEGER NOT NULL, \n\twarning_count INTEGER NOT NULL, \n\taborted BOOLEAN NOT NULL, \n\tprogress JSON, \n\tprogress_at TEXT, \n\telapsed_s FLOAT NOT NULL, \n\tartifacts JSON NOT NULL, \n\tlog_path TEXT, \n\tdiagnostics JSON NOT NULL, \n\tsummary JSON, \n\ttool_exit_code INTEGER, \n\tCONSTRAINT ck_jobs_positive_ids CHECK (job_id > 0 AND submitter_id > 0), \n\tCONSTRAINT ck_jobs_type_length CHECK (length(type_name) BETWEEN 1 AND 64), \n\tCONSTRAINT ck_jobs_display_length CHECK (length(display_name) BETWEEN 1 AND 40), \n\tCONSTRAINT ck_jobs_submitter_length CHECK (length(submitter_name) BETWEEN 1 AND 64), \n\tCONSTRAINT ck_jobs_state CHECK (state IN ('queued','running','cancelling','completed','cancelled','interrupted')), \n\tCONSTRAINT ck_jobs_recovery CHECK (recovery_mode IN ('resume','restart','interrupt')), \n\tCONSTRAINT ck_jobs_counts CHECK (total_items >= 0 AND failed_items BETWEEN 0 AND total_items AND warning_count >= 0), \n\tCONSTRAINT ck_jobs_elapsed CHECK (elapsed_s >= 0), \n\tCONSTRAINT ck_jobs_recovery_count CHECK (recovery_count BETWEEN 0 AND 3), \n\tCONSTRAINT ck_jobs_claimed_log_path CHECK (state NOT IN ('running','cancelling','completed','interrupted') OR log_path IS NOT NULL), \n\tCONSTRAINT uq_jobs_log_path UNIQUE (log_path), \n\tCONSTRAINT ck_jobs_outcome CHECK ((state = 'completed' AND outcome IS NOT NULL AND outcome IN ('succeeded','succeeded_with_warnings','partially_succeeded','failed')) OR (state != 'completed' AND outcome IS NULL)), \n\tCONSTRAINT ck_jobs_terminal CHECK ((state IN ('completed','cancelled','interrupted') AND ended_at IS NOT NULL AND summary IS NOT NULL) OR (state IN ('queued','running','cancelling') AND ended_at IS NULL AND summary IS NULL))\n)"
_V4_OPERATIONS_DDL = "CREATE TABLE operation_logs (\n\tlog_id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT, \n\toccurred_at TEXT NOT NULL, \n\tactor_id INTEGER, \n\tactor_name VARCHAR(64) NOT NULL, \n\toperation VARCHAR(64) NOT NULL, \n\tobject_kind VARCHAR(16) NOT NULL, \n\tobject_id VARCHAR(64), \n\tobject_name VARCHAR(64) NOT NULL, \n\tresult VARCHAR(7) NOT NULL, \n\tfailure_category VARCHAR(8), \n\trequest_id VARCHAR(32), \n\tsource_ip VARCHAR(45), \n\tdetails JSON NOT NULL, \n\tCONSTRAINT ck_operation_logs_positive_id CHECK (log_id > 0), \n\tCONSTRAINT ck_operation_logs_actor_id CHECK (actor_id IS NULL OR actor_id > 0), \n\tCONSTRAINT ck_operation_logs_actor_name CHECK (length(actor_name) BETWEEN 1 AND 64), \n\tCONSTRAINT ck_operation_logs_ops_actor CHECK (actor_id IS NOT NULL OR actor_name = '运维'), \n\tCONSTRAINT ck_operation_logs_operation_length CHECK (length(operation) BETWEEN 1 AND 64), \n\tCONSTRAINT ck_operation_logs_object_kind CHECK (object_kind IN ('account','audit_settings','job')), \n\tCONSTRAINT ck_operation_logs_object_id CHECK (object_id IS NULL OR length(object_id) BETWEEN 1 AND 64), \n\tCONSTRAINT ck_operation_logs_object_name CHECK (length(object_name) BETWEEN 1 AND 64), \n\tCONSTRAINT ck_operation_logs_result_category CHECK ((result = 'success' AND failure_category IS NULL) OR (result = 'failure' AND failure_category IS NOT NULL AND failure_category IN ('input','conflict','external','defect'))), \n\tCONSTRAINT ck_operation_logs_request_id CHECK (request_id IS NULL OR (length(request_id) = 32 AND request_id NOT GLOB '*[^0-9a-f]*')), \n\tCONSTRAINT ck_operation_logs_source_ip CHECK (source_ip IS NULL OR length(source_ip) BETWEEN 1 AND 45)\n)"
_JOB_COLUMNS = (
    "job_id",
    "type_name",
    "display_name",
    "parameters",
    "submitter_id",
    "submitter_name",
    "submitted_at",
    "resubmitted_from",
    "state",
    "recovery_mode",
    "recovery_count",
    "started_at",
    "ended_at",
    "outcome",
    "total_items",
    "failed_items",
    "warning_count",
    "aborted",
    "progress",
    "progress_at",
    "elapsed_s",
    "artifacts",
    "log_path",
    "diagnostics",
    "summary",
    "tool_exit_code",
)
_OPERATION_COLUMNS = (
    "log_id",
    "occurred_at",
    "actor_id",
    "actor_name",
    "operation",
    "object_kind",
    "object_id",
    "object_name",
    "result",
    "failure_category",
    "request_id",
    "source_ip",
    "details",
)
_INDEX_DDL = (
    "CREATE INDEX ix_jobs_state_id ON jobs (state, job_id)",
    "CREATE INDEX ix_operation_logs_actor_time_id ON operation_logs (actor_id, occurred_at, log_id)",
    "CREATE INDEX ix_operation_logs_time_id ON operation_logs (occurred_at, log_id)",
    "CREATE INDEX ix_schedule_submissions_name_job ON schedule_submissions (schedule_name, job_id)",
)


def _check_downgrade() -> None:
    """先完整判断是否有新版本专属数据，再开始任何DDL，拒绝损失系统身份或调度历史。"""
    queries = (
        "SELECT 1 FROM jobs WHERE submitter_id IS NULL OR gpu_index IS NOT NULL OR wait_reason IS NOT NULL OR holds_navigation_lock != 0 LIMIT 1",
        "SELECT 1 FROM operation_logs WHERE actor_id IS NULL AND actor_name='系统' LIMIT 1",
        "SELECT 1 FROM schedule_submissions LIMIT 1",
        "SELECT 1 FROM worker_gpu_checks LIMIT 1",
    )
    if any(op.get_bind().execute(text(query)).first() is not None for query in queries):
        diagnostic = invalid_field("0005", "没有系统身份、调度历史或资源状态才能降级").diagnostics[
            0
        ]
        raise ConflictError(
            (diagnostic.model_copy(update={"category": DiagnosticCategory.CONFLICT}),)
        )
