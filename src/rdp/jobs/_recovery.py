"""单条遗留作业恢复的内部事务；日志先于资格/状态提交，调用方逐编号隔离失败。"""

from typing import Literal

from rdp.infra.db.connection import session_scope
from rdp.infra.diagnostics import DefectError
from rdp.jobs import _storage
from rdp.jobs.execution import ExecutionWork, ExecutorDependencies
from rdp.jobs.logs import JobLog, JobLogMetadata, open_job_log
from rdp.jobs.models import JobRow
from rdp.jobs.policy import JOB_RECOVERY_LIMIT
from rdp.jobs.records import StateChange, find_job, transition_job
from rdp.jobs.types import ExecutionMode, JobRecord, JobState, RecoveryMode


def prepare(job_id: int, dependencies: ExecutorDependencies) -> ExecutionWork | None:
    """先完整追加中断段，再在普通事务中重读取消态或提交恢复资格。"""
    with session_scope(dependencies.engine, read_only=True) as session:
        record = find_job(session, job_id)
    mode, reason = _handling(record, dependencies)
    log, needs_header = open_job_log(dependencies.paths, record)
    try:
        if needs_header:
            log.write_header(record, JobLogMetadata(None, None, None))
            log.write_line("登记的日志文件不存在或为空，已重建开头", now=dependencies.clock.now())
        log.write_interruption(record.progress, mode, now=dependencies.clock.now(), reason=reason)
        result = _commit(record, mode, log, dependencies)
        if result.summary is not None:
            log.write_summary(result.summary, now=dependencies.clock.now())
            return None
        return ExecutionWork(result, ExecutionMode(mode), record.progress, claim=None)
    finally:
        log.close()


def _handling(
    record: JobRecord, dependencies: ExecutorDependencies
) -> tuple[RecoveryMode | Literal["cancel"], str]:
    """保存的声明只提供中断保护，续跑/重跑方式永远取当前代码登记。"""
    if record.state is JobState.CANCELLING:
        return "cancel", "上一实例正在取消，现结束取消"
    if record.state is not JobState.RUNNING:
        raise DefectError()
    definition = dependencies.registry.lookup(record.type_name)
    if definition is None:
        return RecoveryMode.INTERRUPT, "当前登记表已无此作业类型"
    if RecoveryMode.INTERRUPT in (record.recovery_mode, definition.recovery_mode):
        return RecoveryMode.INTERRUPT, "提交时或当前登记要求标记中断"
    if record.recovery_count >= JOB_RECOVERY_LIMIT:
        return RecoveryMode.INTERRUPT, f"恢复次数已达{JOB_RECOVERY_LIMIT}次"
    return definition.recovery_mode, "按当前登记恢复执行"


def _commit(
    record: JobRecord,
    mode: RecoveryMode | Literal["cancel"],
    log: JobLog,
    dependencies: ExecutorDependencies,
) -> JobRecord:
    """恢复资格、重跑清零与资源展示复位原子提交；状态仍只经过 transition_job。"""
    # 待实现：启动统一清空已先完成；这里只准备恢复资格，不取名额或等待容量。
    with session_scope(dependencies.engine) as session, _storage.operation(session, write=True):
        current = find_job(session, record.job_id)
        if current.state is JobState.CANCELLING:
            if mode != "cancel":
                log.write_interruption(
                    current.progress,
                    "cancel",
                    now=dependencies.clock.now(),
                    reason="恢复期间收到取消请求",
                )
            return transition_job(
                session,
                current.job_id,
                StateChange(current.state, JobState.CANCELLED, dependencies.clock.now()),
            )
        if mode is RecoveryMode.INTERRUPT:
            return transition_job(
                session,
                current.job_id,
                StateChange(current.state, JobState.INTERRUPTED, dependencies.clock.now()),
            )
        if current.state is not JobState.RUNNING or mode == "cancel":
            raise DefectError()
        row = session.get(JobRow, current.job_id)
        if row is None or row.recovery_count >= JOB_RECOVERY_LIMIT:
            raise DefectError()
        row.recovery_count += 1
        if mode is RecoveryMode.RESTART:
            row.progress = None
            row.progress_at = None
            row.total_items = row.failed_items = row.warning_count = 0
            row.diagnostics = []
            row.tool_exit_code = None
        session.flush()
        return find_job(session, record.job_id)
