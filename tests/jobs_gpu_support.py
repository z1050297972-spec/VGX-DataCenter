"""GPU作业的真实调度与执行夹具；只使用临时数据库和显式假命令。"""

import time
from collections.abc import Callable, Generator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from pathlib import Path
from threading import Event, Lock
from zoneinfo import ZoneInfo

from jobs_storage_support import NOW, job_row

from rdp.infra.config import JobsConfig, PlatformConfig
from rdp.infra.db.connection import create_database_engine, session_scope
from rdp.infra.db.migration import migrate
from rdp.infra.state import initialize_state, state_paths
from rdp.jobs.execution import ExecutionContext, ExecutorDependencies
from rdp.jobs.navigation import NavigationWriter
from rdp.jobs.progress import ExecutionMonitor, ExecutionSignals
from rdp.jobs.records import find_job
from rdp.jobs.registry import JobRegistry, production_registry
from rdp.jobs.resources import ResourcePool
from rdp.jobs.schedules import ScheduleRegistry
from rdp.jobs.scheduling import Scheduler, WorkerResources, WorkerScheduling, resolve_scheduling
from rdp.jobs.scheduling_types import SchedulingCatalog
from rdp.jobs.types import JobClock, JobRecord, JobState
from rdp.ops.worker import WorkerExit


@dataclass(frozen=True)
class GpuCase:
    """显式保存入口依赖和公共调度入口，测试不窥探名额池私有字段。"""

    dependencies: ExecutorDependencies
    resources: WorkerResources
    scheduler: Scheduler

    def add(self, number: int, *, gpu: bool = True, hold_s: int = 0) -> None:
        """提交已知合法的独立排队样本，实际领取仍由调度器完成。"""
        with session_scope(self.dependencies.engine) as session:
            row = job_row(JobState.QUEUED, job_id=number)
            row.type_name = "example_gpu" if gpu else "example_count"
            row.display_name = "示例：占用 GPU" if gpu else "示例：数数"
            row.parameters = {"hold_s": hold_s} if gpu else {"steps": 1, "interval_ms": 0}
            session.add(row)

    def get(self, number: int) -> JobRecord:
        """经公开查询读取永久结果与资源展示副本。"""
        with session_scope(self.dependencies.engine, read_only=True) as session:
            return find_job(session, number)


@contextmanager
def gpu_case(
    root: Path,
    command: Path,
    *,
    gpus: tuple[int, ...] = (0, 1),
    execute: Callable[[ExecutionContext], None] | None = None,
) -> Generator[GpuCase]:
    """默认使用生产登记回调；故障测试可替换类型函数，但不会替换框架核卡或进程入口。"""
    registry = JobRegistry()
    for definition in production_registry().definitions():
        if definition.type_name == "example_gpu":
            definition = replace(definition, concurrency=3, execute=execute or definition.execute)
        registry.register(definition)
    settings = resolve_scheduling(JobsConfig.model_validate({"gpus": gpus}), registry)
    catalog = SchedulingCatalog(settings, ScheduleRegistry((), registry), ZoneInfo("UTC"))
    paths = state_paths(
        PlatformConfig(state_dir=root), tuple(item.display_name for item in registry.definitions())
    )
    initialize_state(paths)
    migrate(paths, now=NOW)
    engine = create_database_engine(paths.database)
    resources = WorkerResources(
        WorkerScheduling(catalog, command if gpus else None, 30),
        ResourcePool(settings, available_gpus=gpus),
        NavigationWriter(),
    )
    dependencies = ExecutorDependencies(
        engine, registry, paths, JobClock(lambda: NOW, time.monotonic), resources=resources
    )
    try:
        yield GpuCase(dependencies, resources, Scheduler(dependencies, resources, recovered=()))
    finally:
        try:
            for claim in resources.pool.claims():
                resources.pool.release(claim)
        finally:
            engine.dispose()


def signals_fixture() -> ExecutionSignals:
    """每次执行独立的取消、停止和线程记录，不复用其他作业的信号。"""
    return ExecutionSignals(Event(), Event(), ExecutionMonitor([], None, Lock()))


@contextmanager
def running_gpu_worker(case: GpuCase) -> Generator[tuple[Event, list[WorkerExit]]]:
    """入口从resources=None开始装配；主循环线程在finally停止并有界回收。"""
    from threading import Thread

    from rdp.infra.logging import LoggingSettings
    from rdp.ops.worker import run_worker

    stop = Event()
    results: list[WorkerExit] = []
    errors: list[BaseException] = []

    def run() -> None:
        try:
            results.append(
                run_worker(
                    replace(case.dependencies, resources=None),
                    stop,
                    LoggingSettings("worker", case.dependencies.paths.logs),
                    scheduling=case.resources.configuration,
                )
            )
        except BaseException as error:
            errors.append(error)

    thread = Thread(target=run, daemon=True)
    try:
        thread.start()
        yield stop, results
    finally:
        stop.set()
        thread.join(timeout=3)
        assert not thread.is_alive() and errors == [], errors
    assert len(results) == 1 and results[0].code == 0 and not results[0].lock_retained
