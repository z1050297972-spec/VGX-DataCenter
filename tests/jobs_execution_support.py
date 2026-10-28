"""执行公共边界夹具；真实临时库、类型登记和领取事务，不绕过状态转换。"""

import time
from collections.abc import Callable, Generator
from contextlib import contextmanager
from pathlib import Path
from threading import Event, Lock

from jobs_scheduling_support import claim_fixture, resources_fixture
from jobs_storage_support import NOW, job_database, job_row

from rdp.infra.db.connection import session_scope
from rdp.jobs.example import CountParameters, execute_count
from rdp.jobs.execution import ExecutionContext, ExecutionWork, ExecutorDependencies
from rdp.jobs.progress import ExecutionMonitor, ExecutionSignals
from rdp.jobs.records import claim_job
from rdp.jobs.registry import JobDefinition, JobRegistry
from rdp.jobs.types import ExecutionMode, JobClock, JobState, RecoveryMode


@contextmanager
def execution_case(
    root: Path,
    parameters: dict[str, object],
    execute: Callable[[ExecutionContext], None] = execute_count,
    *,
    mode: RecoveryMode = RecoveryMode.INTERRUPT,
) -> Generator[tuple[ExecutionWork, ExecutorDependencies, ExecutionSignals]]:
    """经真实领取获取含日志路径的执行输入；调用者可登记受控执行函数触发竞争与故障。"""
    with job_database(root) as (engine, paths):
        registry = JobRegistry()
        registry.register(
            JobDefinition("example_count", "示例：数数", CountParameters, mode, execute)
        )
        with session_scope(engine) as session:
            row = job_row(JobState.QUEUED)
            row.parameters = parameters
            row.recovery_mode = mode.value
            session.add(row)
        with session_scope(engine) as session:
            record = claim_job(session, 71, now=NOW, paths=paths, gpu_index=None)
        signals = ExecutionSignals(Event(), Event(), ExecutionMonitor([], None, Lock()))
        dependencies = ExecutorDependencies(
            engine,
            registry,
            paths,
            JobClock(lambda: NOW, time.monotonic),
            resources=resources_fixture(registry),
            storage=None,
        )
        try:
            yield (
                ExecutionWork(
                    record, ExecutionMode.FRESH, None, claim=claim_fixture(record, dependencies)
                ),
                dependencies,
                signals,
            )
        finally:
            if dependencies.resources is not None:
                for claim in dependencies.resources.pool.claims():
                    dependencies.resources.pool.release(claim)
