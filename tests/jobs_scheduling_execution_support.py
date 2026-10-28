"""调度集成夹具；使用真实资源池、登记表和临时SQLite，不替换领域协作者。"""

import time
from collections.abc import Callable, Generator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo

from jobs_storage_support import NOW, job_row
from sqlalchemy import Engine

from rdp.infra.config import JobsConfig, PlatformConfig
from rdp.infra.db.connection import create_database_engine, session_scope
from rdp.infra.db.migration import migrate
from rdp.infra.state import StatePaths, initialize_state, state_paths
from rdp.jobs.example import CountParameters, execute_count
from rdp.jobs.execution import ExecutionContext, ExecutorDependencies
from rdp.jobs.navigation import NavigationWriter
from rdp.jobs.records import find_job
from rdp.jobs.registry import JobDefinition, JobRegistry
from rdp.jobs.resources import ResourcePool
from rdp.jobs.schedules import ScheduleRegistry
from rdp.jobs.scheduling import Scheduler, WorkerResources, WorkerScheduling, resolve_scheduling
from rdp.jobs.scheduling_types import SchedulingCatalog
from rdp.jobs.types import JobClock, JobRecord, JobState, RecoveryMode


@dataclass(frozen=True)
class SchedulingCase:
    """当前测试的真实基础设施及公开观察入口。"""

    dependencies: ExecutorDependencies
    resources: WorkerResources
    scheduler: Scheduler

    def add(self, number: int, type_name: str, state: JobState = JobState.QUEUED) -> None:
        """通过临时库样本建立指定编号和类型的历史或排队输入，测试预期独立于生产查询实现。"""
        with session_scope(self.dependencies.engine) as session:
            row = job_row(state, job_id=number)
            row.type_name = type_name
            row.parameters = {"steps": 1, "interval_ms": 0}
            definition = self.dependencies.registry.lookup(type_name)
            if definition is not None:
                row.recovery_mode = definition.recovery_mode.value
            session.add(row)

    def get(self, number: int) -> JobRecord:
        """经公共记录接口读取，不从资源池私有状态推断数据库展示。"""
        with session_scope(self.dependencies.engine, read_only=True) as session:
            return find_job(session, number)


@contextmanager
def scheduling_case(
    root: Path,
    *,
    concurrency: int = 1,
    gpus: tuple[int, ...] = (),
    execute: Callable[[ExecutionContext], None] = execute_count,
    needs_gpu: bool | frozenset[str] = False,
) -> Generator[SchedulingCase]:
    """配置两个独立类型及空每日登记；需要GPU时仅注入临时假命令路径。"""
    registry = JobRegistry()
    for key, name in (("a", "甲"), ("b", "乙")):
        registry.register(
            JobDefinition(
                key,
                name,
                CountParameters,
                RecoveryMode.RESTART,
                execute,
                concurrency=concurrency,
                requires_gpu=needs_gpu if isinstance(needs_gpu, bool) else key in needs_gpu,
            )
        )
    settings = resolve_scheduling(JobsConfig.model_validate({"gpus": gpus}), registry)
    catalog = SchedulingCatalog(settings, ScheduleRegistry((), registry), ZoneInfo("UTC"))
    with _migrated_database(root) as (engine, paths):
        command = None
        if gpus:
            command = root / "fake-nvidia-smi"
            command.write_text("#!/bin/sh\nprintf '0\\n1\\n'\n", encoding="utf-8")
            command.chmod(0o700)
        resources = WorkerResources(
            WorkerScheduling(catalog, command, 30),
            ResourcePool(settings, available_gpus=gpus),
            NavigationWriter(),
        )
        dependencies = ExecutorDependencies(
            engine,
            registry,
            paths,
            JobClock(lambda: NOW, time.monotonic),
            resources=resources,
            storage=None,
        )
        yield SchedulingCase(
            dependencies, resources, Scheduler(dependencies, resources, recovered=())
        )


@contextmanager
def _migrated_database(root: Path) -> Generator[tuple[Engine, StatePaths]]:
    """走真实迁移建立worker入口可接受的版本库，最终关闭引擎。"""
    paths = state_paths(PlatformConfig(state_dir=root), ("示例：数数",))
    initialize_state(paths)
    migrate(paths, now=NOW)
    engine = create_database_engine(paths.database)
    try:
        yield engine, paths
    finally:
        engine.dispose()
