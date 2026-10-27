"""进度公共接口的真实数据库/日志夹具；只注入业务时钟，不替换生产存储函数。"""

from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from threading import Event, Lock

from jobs_storage_support import NOW, job_database, job_row
from sqlalchemy import Engine

from rdp.infra.db.connection import session_scope
from rdp.infra.diagnostics import Diagnostic, DiagnosticCategory, DiagnosticLevel, DiagnosticObject
from rdp.jobs.logs import open_job_log
from rdp.jobs.progress import ExecutionMonitor, ExecutionSignals, ProgressReporter
from rdp.jobs.records import find_job
from rdp.jobs.types import JobClock, JobProgress, JobRecord


@dataclass
class MutableClock:
    """单调读数和墙钟独立调整，测试可观察回拨不能改变频率。"""

    seconds: float = 100.0
    wall: datetime = NOW

    def now(self) -> datetime:
        """返回测试指定的墙钟，不依赖本机时区。"""
        return self.wall

    def monotonic(self) -> float:
        """返回测试指定的单调秒数，不隐式向前走。"""
        return self.seconds


def progress(done: int, **changes: object) -> JobProgress:
    """独立完成事件样本，计数来自测试输入，不调用生产计算函数。"""
    return JobProgress.model_validate(
        {
            "stage_index": 1,
            "stage_count": 2,
            "stage_name": "处理",
            "done": done,
            "total": 10,
            "unit": "条",
            "total_items": done,
            "failed_items": 0,
            "warning_count": 0,
        }
        | changes
    )


def diagnostic(index: int, *, rule: str = "样例规则") -> Diagnostic:
    """提供含作业身份的独立诊断，序号只进实际值，不破坏规则聚合键。"""
    return Diagnostic(
        level=DiagnosticLevel.WARNING,
        category=DiagnosticCategory.INPUT,
        stage="处理",
        source="平台",
        objects=(DiagnosticObject(key="job_id", value="71"),),
        rule=rule,
        actual=f"第{index}条有警告",
        expected="无警告",
        consequence="继续其余条目",
        next_step="检查条目",
    )


@contextmanager
def reporter_context(
    root: Path, clock: JobClock, *, resume: bool = False
) -> Generator[tuple[ProgressReporter, Engine, ExecutionSignals, Path]]:
    """创建真实上报边界，finally释放日志和临时引擎，不开启后台线程。"""
    with job_database(root) as (engine, paths):
        row = job_row()
        if not resume:
            row.progress = None
            row.progress_at = None
            row.total_items = row.failed_items = row.warning_count = 0
            row.elapsed_s = 0
            row.artifacts = []
            row.tool_exit_code = None
        with session_scope(engine) as session:
            session.add(row)
        record = saved_record(engine)
        log, _ = open_job_log(paths, record)
        signals = ExecutionSignals(Event(), Event(), ExecutionMonitor([], None, Lock()))
        try:
            reporter = ProgressReporter(engine, record, log, clock, signals)
            assert record.log_path is not None
            yield reporter, engine, signals, paths.root / record.log_path
        finally:
            log.close()


def saved_record(engine: Engine) -> JobRecord:
    """经公开查询接口观察已提交记录，不窥探上报对象内部状态。"""
    with session_scope(engine, read_only=True) as session:
        return find_job(session, 71)
