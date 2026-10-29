"""0006 作业执行版本迁移（11 M2），冻结列定义，不依赖会随业务变化的 ORM。

活动迁移图由 versions 目录唯一决定；DDL 固定为本次发布结构。
"""

from pathlib import Path

from alembic import op
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from rdp.infra.db.connection import translate_database_error
from rdp.infra.db.validation import invalid_field
from rdp.infra.diagnostics import ConflictError, DiagnosticCategory

revision = "0006_platform_version"
down_revision = "0005_job_scheduling"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """给作业表增加可空的平台执行版本列，保持历史事实不被伪造。

    Args:
        无；使用 Alembic 当前连接及迁移入口已经持有的事务。

    Returns:
        无；jobs 新增 platform_version VARCHAR(128)，允许 NULL，非空值长度 1-128。

    Raises:
        InputError: 原数据库损坏。
        ExternalError: 增列或 CHECK 创建失败，由外层事务回滚并保留升级前备份。
        DefectError: 非 0005 结构或冻结 DDL 错误。

    Side Effects:
        历史行全部保留 NULL，不拿升级时版本回填旧作业；只改 jobs 结构。
        保留原行、索引、约束和 sqlite_sequence 高水位，包括已删空但曾发号的表。

    Time Semantics:
        Web/worker 全停后执行；锁与备份预算复用 migrate，无额外时钟或重试。
    """
    _rebuild(_V6_JOBS_DDL)


def downgrade() -> None:
    """仅在没有执行版本事实会丢失时恢复 0005 作业结构。

    Args:
        无；复用 Alembic 当前连接和外层事务。

    Returns:
        无；移除 platform_version 并回到 0005，其他数据保持不变。

    Raises:
        ConflictError: 任意 platform_version 非 NULL；先拒绝，不丢执行历史。
        InputError: 存量数据库损坏。
        ExternalError: 表结构变更失败，全部回滚。
        DefectError: 非 0006 结构或 SQL 配置错误。

    Side Effects:
        先只读检查拒绝条件，再移除版本列及其 CHECK；保留其余约束、索引、记录和发号高水位。
        不修改旧 revision，不自动删除非空版本以凑降级条件。

    Time Semantics:
        停止两个服务后的维护窗口执行；不按记录年龄判断可否丢弃版本。
    """
    connection = op.get_bind()
    try:
        recorded = connection.execute(
            text("SELECT 1 FROM jobs WHERE platform_version IS NOT NULL LIMIT 1")
        ).first()
    except SQLAlchemyError as error:
        problem = translate_database_error(
            error, database=Path(connection.engine.url.database or ""), operation="检查版本降级"
        )
        raise problem from error
    if recorded is not None:
        diagnostic = invalid_field("platform_version", "没有执行版本事实才能降级").diagnostics[0]
        raise ConflictError(
            (diagnostic.model_copy(update={"category": DiagnosticCategory.CONFLICT}),)
        )
    _rebuild(_V5_JOBS_DDL)


def _rebuild(ddl: str) -> None:
    """冻结列重建jobs，沿用第9张序列保存办法；DDL不可从运行时模型生成。"""
    connection = op.get_bind()
    try:
        values = (
            connection.execute(text("SELECT seq FROM sqlite_sequence WHERE name='jobs'"))
            .scalars()
            .all()
        )
        maximum = connection.execute(text("SELECT MAX(job_id) FROM jobs")).scalar_one()
        if len(values) > 1 or (not values and maximum is not None):
            raise invalid_field("jobs.sequence", "唯一且完整的历史编号高水位")
        previous = values[0] if values else 0
        if type(previous) is not int or previous < 0:
            raise invalid_field("jobs.sequence", "非负整数的历史编号高水位")
        previous = max(previous, maximum or 0)
        connection.execute(text("ALTER TABLE jobs RENAME TO jobs_before_0006"))
        connection.execute(text(ddl))
        # 列名只来自冻结历史清单，SQL标识符不接受用户输入。
        names = ",".join(_COPY_COLUMNS)
        connection.execute(text(f"INSERT INTO jobs ({names}) SELECT {names} FROM jobs_before_0006"))  # noqa: S608
        connection.execute(text("DROP TABLE jobs_before_0006"))
        connection.execute(text("DELETE FROM sqlite_sequence WHERE name='jobs'"))
        connection.execute(
            text("INSERT INTO sqlite_sequence(name,seq) VALUES ('jobs',:seq)"), {"seq": previous}
        )
        connection.execute(text("CREATE INDEX ix_jobs_state_id ON jobs (state,job_id)"))
    except SQLAlchemyError as error:
        raise translate_database_error(
            error, database=Path(connection.engine.url.database or ""), operation="迁移作业版本"
        ) from error


# 冻结0005与0006发布时的DDL，保留列序及全部原约束；不读取可演进的领域模型。
_V5_JOBS_DDL = "\nCREATE TABLE jobs (\n\tjob_id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT, \n\ttype_name VARCHAR(64) NOT NULL, \n\tdisplay_name VARCHAR(40) NOT NULL, \n\tparameters JSON NOT NULL, \n\tsubmitter_id INTEGER, \n\tsubmitter_name VARCHAR(64) NOT NULL, \n\tsubmitted_at TEXT NOT NULL, \n\tresubmitted_from INTEGER, \n\tstate VARCHAR(16) NOT NULL, \n\trecovery_mode VARCHAR(16) NOT NULL, \n\trecovery_count INTEGER DEFAULT '0' NOT NULL, \n\tstarted_at TEXT, \n\tended_at TEXT, \n\toutcome VARCHAR(32), \n\ttotal_items INTEGER NOT NULL, \n\tfailed_items INTEGER NOT NULL, \n\twarning_count INTEGER NOT NULL, \n\taborted BOOLEAN NOT NULL, \n\tprogress JSON, \n\tprogress_at TEXT, \n\telapsed_s FLOAT NOT NULL, \n\tartifacts JSON NOT NULL, \n\tlog_path TEXT, \n\tdiagnostics JSON NOT NULL, \n\tsummary JSON, \n\ttool_exit_code INTEGER, \n\tgpu_index INTEGER, \n\twait_reason VARCHAR(24), \n\tholds_navigation_lock BOOLEAN DEFAULT '0' NOT NULL, \n\tCONSTRAINT ck_jobs_job_submitter_identity CHECK ((submitter_id IS NULL AND submitter_name = '系统') OR (submitter_id IS NOT NULL AND submitter_id > 0)), \n\tCONSTRAINT ck_jobs_gpu_index CHECK (gpu_index IS NULL OR gpu_index >= 0), \n\tCONSTRAINT ck_jobs_wait_reason CHECK (wait_reason IS NULL OR wait_reason IN ('gpu','navigation_lock')), \n\tCONSTRAINT ck_jobs_navigation_boolean CHECK (holds_navigation_lock IN (0,1)), \n\tCONSTRAINT ck_jobs_navigation_holder_state CHECK (holds_navigation_lock = 0 OR (state IN ('running','cancelling') AND wait_reason IS NULL)), \n\tCONSTRAINT ck_jobs_terminal_resources CHECK (state NOT IN ('completed','cancelled','interrupted') OR (wait_reason IS NULL AND holds_navigation_lock = 0)), \n\tCONSTRAINT ck_jobs_navigation_wait_state CHECK (wait_reason != 'navigation_lock' OR state IN ('running','cancelling')), \n\tCONSTRAINT ck_jobs_gpu_wait_state CHECK (wait_reason != 'gpu' OR (state IN ('queued','running') AND gpu_index IS NULL)), \n\tCONSTRAINT ck_jobs_positive_ids CHECK (job_id > 0 AND submitter_id > 0), \n\tCONSTRAINT ck_jobs_type_length CHECK (length(type_name) BETWEEN 1 AND 64), \n\tCONSTRAINT ck_jobs_display_length CHECK (length(display_name) BETWEEN 1 AND 40), \n\tCONSTRAINT ck_jobs_submitter_length CHECK (length(submitter_name) BETWEEN 1 AND 64), \n\tCONSTRAINT ck_jobs_state CHECK (state IN ('queued','running','cancelling','completed','cancelled','interrupted')), \n\tCONSTRAINT ck_jobs_recovery CHECK (recovery_mode IN ('resume','restart','interrupt')), \n\tCONSTRAINT ck_jobs_counts CHECK (total_items >= 0 AND failed_items BETWEEN 0 AND total_items AND warning_count >= 0), \n\tCONSTRAINT ck_jobs_elapsed CHECK (elapsed_s >= 0), \n\tCONSTRAINT ck_jobs_recovery_count CHECK (recovery_count BETWEEN 0 AND 3), \n\tCONSTRAINT ck_jobs_claimed_log_path CHECK (state NOT IN ('running','cancelling','completed','interrupted') OR log_path IS NOT NULL), \n\tCONSTRAINT uq_jobs_log_path UNIQUE (log_path), \n\tCONSTRAINT ck_jobs_outcome CHECK ((state = 'completed' AND outcome IS NOT NULL AND outcome IN ('succeeded','succeeded_with_warnings','partially_succeeded','failed')) OR (state != 'completed' AND outcome IS NULL)), \n\tCONSTRAINT ck_jobs_terminal CHECK ((state IN ('completed','cancelled','interrupted') AND ended_at IS NOT NULL AND summary IS NOT NULL) OR (state IN ('queued','running','cancelling') AND ended_at IS NULL AND summary IS NULL))\n)\n\n"
_V6_JOBS_DDL = "\nCREATE TABLE jobs (\n\tjob_id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT, \n\ttype_name VARCHAR(64) NOT NULL, \n\tdisplay_name VARCHAR(40) NOT NULL, \n\tparameters JSON NOT NULL, \n\tsubmitter_id INTEGER, \n\tsubmitter_name VARCHAR(64) NOT NULL, \n\tsubmitted_at TEXT NOT NULL, \n\tresubmitted_from INTEGER, \n\tstate VARCHAR(16) NOT NULL, \n\trecovery_mode VARCHAR(16) NOT NULL, \n\trecovery_count INTEGER DEFAULT '0' NOT NULL, \n\tstarted_at TEXT, \n\tended_at TEXT, \n\toutcome VARCHAR(32), \n\ttotal_items INTEGER NOT NULL, \n\tfailed_items INTEGER NOT NULL, \n\twarning_count INTEGER NOT NULL, \n\taborted BOOLEAN NOT NULL, \n\tprogress JSON, \n\tprogress_at TEXT, \n\telapsed_s FLOAT NOT NULL, \n\tartifacts JSON NOT NULL, \n\tlog_path TEXT, \n\tdiagnostics JSON NOT NULL, \n\tsummary JSON, \n\ttool_exit_code INTEGER, \n\tplatform_version VARCHAR(128), \n\tgpu_index INTEGER, \n\twait_reason VARCHAR(24), \n\tholds_navigation_lock BOOLEAN DEFAULT '0' NOT NULL, \n\tCONSTRAINT ck_jobs_job_submitter_identity CHECK ((submitter_id IS NULL AND submitter_name = '系统') OR (submitter_id IS NOT NULL AND submitter_id > 0)), \n\tCONSTRAINT ck_jobs_gpu_index CHECK (gpu_index IS NULL OR gpu_index >= 0), \n\tCONSTRAINT ck_jobs_wait_reason CHECK (wait_reason IS NULL OR wait_reason IN ('gpu','navigation_lock')), \n\tCONSTRAINT ck_jobs_navigation_boolean CHECK (holds_navigation_lock IN (0,1)), \n\tCONSTRAINT ck_jobs_navigation_holder_state CHECK (holds_navigation_lock = 0 OR (state IN ('running','cancelling') AND wait_reason IS NULL)), \n\tCONSTRAINT ck_jobs_terminal_resources CHECK (state NOT IN ('completed','cancelled','interrupted') OR (wait_reason IS NULL AND holds_navigation_lock = 0)), \n\tCONSTRAINT ck_jobs_navigation_wait_state CHECK (wait_reason != 'navigation_lock' OR state IN ('running','cancelling')), \n\tCONSTRAINT ck_jobs_gpu_wait_state CHECK (wait_reason != 'gpu' OR (state IN ('queued','running') AND gpu_index IS NULL)), \n\tCONSTRAINT ck_jobs_platform_version_length CHECK (platform_version IS NULL OR length(platform_version) BETWEEN 1 AND 128), \n\tCONSTRAINT ck_jobs_positive_ids CHECK (job_id > 0 AND submitter_id > 0), \n\tCONSTRAINT ck_jobs_type_length CHECK (length(type_name) BETWEEN 1 AND 64), \n\tCONSTRAINT ck_jobs_display_length CHECK (length(display_name) BETWEEN 1 AND 40), \n\tCONSTRAINT ck_jobs_submitter_length CHECK (length(submitter_name) BETWEEN 1 AND 64), \n\tCONSTRAINT ck_jobs_state CHECK (state IN ('queued','running','cancelling','completed','cancelled','interrupted')), \n\tCONSTRAINT ck_jobs_recovery CHECK (recovery_mode IN ('resume','restart','interrupt')), \n\tCONSTRAINT ck_jobs_counts CHECK (total_items >= 0 AND failed_items BETWEEN 0 AND total_items AND warning_count >= 0), \n\tCONSTRAINT ck_jobs_elapsed CHECK (elapsed_s >= 0), \n\tCONSTRAINT ck_jobs_recovery_count CHECK (recovery_count BETWEEN 0 AND 3), \n\tCONSTRAINT ck_jobs_claimed_log_path CHECK (state NOT IN ('running','cancelling','completed','interrupted') OR log_path IS NOT NULL), \n\tCONSTRAINT uq_jobs_log_path UNIQUE (log_path), \n\tCONSTRAINT ck_jobs_outcome CHECK ((state = 'completed' AND outcome IS NOT NULL AND outcome IN ('succeeded','succeeded_with_warnings','partially_succeeded','failed')) OR (state != 'completed' AND outcome IS NULL)), \n\tCONSTRAINT ck_jobs_terminal CHECK ((state IN ('completed','cancelled','interrupted') AND ended_at IS NOT NULL AND summary IS NOT NULL) OR (state IN ('queued','running','cancelling') AND ended_at IS NULL AND summary IS NULL))\n)\n\n"
_COPY_COLUMNS = (
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
    "gpu_index",
    "wait_reason",
    "holds_navigation_lock",
)
