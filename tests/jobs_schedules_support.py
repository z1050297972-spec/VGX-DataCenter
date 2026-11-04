"""定时作业的真实数据库与显式时钟夹具；不读取本机时区或实际配置目录。"""

from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

from jobs_progress_support import MutableClock
from jobs_scheduling_support import resources_fixture
from jobs_storage_support import job_database

from rdp.jobs.execution import ExecutorDependencies
from rdp.jobs.registry import production_registry
from rdp.jobs.schedules import ScheduleRegistry
from rdp.jobs.scheduling import Scheduler
from rdp.jobs.scheduling_types import ScheduledJob
from rdp.jobs.service import JobService
from rdp.jobs.types import JobClock


@dataclass
class ScheduleCase:
    """调度、提交和墙钟均为显式对象，重启只重建调度器的首次检查状态。"""

    dependencies: ExecutorDependencies
    definition: ScheduledJob
    clock: MutableClock
    scheduler: Scheduler
    service: JobService

    def restart(self) -> None:
        """复用已提交数据库历史，新实例不保留旧的启动补跑标记。"""
        assert self.dependencies.resources is not None
        self.scheduler = Scheduler(self.dependencies, self.dependencies.resources, recovered=())


@contextmanager
def scheduled_case(
    root: Path, now: datetime, *, zone: ZoneInfo | None = None, local_time: time = time(3)
) -> Generator[ScheduleCase]:
    """单条生产清除规则用于观察系统身份和每日去重，执行时刻由调用者推进。"""
    from dataclasses import replace

    registry = production_registry()
    definition = ScheduledJob(
        "清除", "purge_errors", {}, local_time, description="删除超过保留期的程序报错记录"
    )
    resources = resources_fixture(registry)
    catalog = replace(
        resources.configuration.catalog,
        schedules=ScheduleRegistry((definition,), registry),
        timezone=ZoneInfo("UTC") if zone is None else zone,
    )
    resources = replace(resources, configuration=replace(resources.configuration, catalog=catalog))
    clock = MutableClock(wall=now)
    with job_database(root) as (engine, paths):
        dependencies = ExecutorDependencies(
            engine,
            registry,
            paths,
            JobClock(clock.now, clock.monotonic),
            resources=resources,
            storage=None,
        )
        yield ScheduleCase(
            dependencies,
            definition,
            clock,
            Scheduler(dependencies, resources, recovered=()),
            JobService(engine, registry),
        )
