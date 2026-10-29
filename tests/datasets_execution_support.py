"""扫描作业测试走真实登记、领取、执行、事务和导航锁；所有路径属于tmp_path。"""

import time
from collections.abc import Callable, Generator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from pathlib import Path
from threading import Event, Lock

from jobs_scheduling_support import claim_fixture, resources_fixture
from jobs_storage_support import NOW, job_row
from nav_manifest import FakeNavigation
from sqlalchemy import Engine

from rdp.infra.config import PlatformConfig
from rdp.infra.db.connection import create_database_engine, session_scope
from rdp.infra.db.migration import migrate
from rdp.infra.state import StatePaths, initialize_state, state_paths
from rdp.jobs.datasets.rescan import RescanDependencies, build_rescan_definition
from rdp.jobs.execution import ExecutionContext, ExecutionWork, ExecutorDependencies, execute_job
from rdp.jobs.progress import ExecutionMonitor, ExecutionSignals
from rdp.jobs.records import claim_job
from rdp.jobs.registry import JobRegistry
from rdp.jobs.types import ExecutionMode, JobClock, JobRecord, JobState


@dataclass
class DatasetCase:
    """临时状态布局和扫描依赖，运行入口返回持久化作业记录。"""

    engine: Engine
    paths: StatePaths
    scanning: RescanDependencies
    number: int = 71

    def run(
        self,
        dataset_id: str | None = None,
        execute: Callable[[ExecutionContext], None] | None = None,
    ) -> JobRecord:
        """按真实RESTART定义领取并执行一个作业，回调只能替换类型执行边界。"""
        definition = build_rescan_definition(self.scanning)
        if execute is not None:
            definition = replace(definition, execute=execute)
        registry = JobRegistry()
        registry.register(definition)
        with session_scope(self.engine) as session:
            row = job_row(JobState.QUEUED, job_id=self.number)
            row.type_name = definition.type_name
            row.display_name = definition.display_name
            row.parameters = {"dataset_id": dataset_id}
            row.recovery_mode = "restart"
            session.add(row)
        with session_scope(self.engine) as session:
            record = claim_job(session, self.number, now=NOW, paths=self.paths, gpu_index=None)
        self.number += 1
        deps = ExecutorDependencies(
            self.engine,
            registry,
            self.paths,
            JobClock(lambda: NOW, time.monotonic),
            resources=resources_fixture(registry),
            storage=None,
        )
        work = ExecutionWork(record, ExecutionMode.FRESH, None, claim=claim_fixture(record, deps))
        result = execute_job(
            work, deps, ExecutionSignals(Event(), Event(), ExecutionMonitor([], None, Lock()))
        )
        assert result is not None
        return result


@contextmanager
def dataset_case(root: Path, navigation: FakeNavigation) -> Generator[DatasetCase]:
    """真实迁移只写临时状态目录，不读默认配置或真实挂载表。"""
    paths = state_paths(PlatformConfig(state_dir=root), ("重新扫描数据集",))
    initialize_state(paths)
    migrate(paths, now=NOW)
    engine = create_database_engine(paths.database)
    try:
        yield DatasetCase(
            engine,
            paths,
            RescanDependencies(engine, navigation.nav_root, navigation.storage_roots, None),
        )
    finally:
        engine.dispose()
