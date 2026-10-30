"""数据来源 HTTP 演练夹具：在临时应用里执行真实已提交作业，不开端口或额外线程。"""

import time
from threading import Event, Lock

from account_api_support import ApiCase
from jobs_scheduling_support import claim_fixture, resources_fixture
from nav_manifest import FakeNavigation

from rdp.infra.db.connection import session_scope
from rdp.jobs.datasets.rescan import RescanDependencies
from rdp.jobs.execution import ExecutionWork, ExecutorDependencies, execute_job
from rdp.jobs.navwrite.pipeline import NavWriteDependencies
from rdp.jobs.progress import ExecutionMonitor, ExecutionSignals
from rdp.jobs.records import claim_job
from rdp.jobs.registry import production_registry
from rdp.jobs.types import ExecutionMode, JobClock, JobRecord


def run_submitted(case: ApiCase, nav: FakeNavigation, job_id: int) -> JobRecord:
    """以真实登记、领取、写锁和执行器运行一个 HTTP 提交的作业。"""
    paths = case.app.state.job_paths
    rescan = RescanDependencies(case.engine, nav.nav_root, nav.storage_roots, None)
    writing = NavWriteDependencies(rescan, paths, case.app.state.job_service)
    registry = production_registry(rescan, writing)
    with session_scope(case.engine) as session:
        record = claim_job(session, job_id, now=case.clock.value, paths=paths, gpu_index=None)
    dependencies = ExecutorDependencies(
        case.engine,
        registry,
        paths,
        JobClock(case.clock, time.monotonic),
        resources=resources_fixture(registry),
        storage=None,
    )
    work = ExecutionWork(
        record, ExecutionMode.FRESH, None, claim=claim_fixture(record, dependencies)
    )
    result = execute_job(
        work, dependencies, ExecutionSignals(Event(), Event(), ExecutionMonitor([], None, Lock()))
    )
    assert result is not None
    return result
