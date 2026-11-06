"""生产worker自动扫描的集成验证；运行真实队列及执行器，仅系统时钟、配置和导航指向测试资源。"""

import time
from collections.abc import Callable, Generator
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from threading import Event, Lock, Thread
from threading import enumerate as threads

import pytest
from datasets_execution_support import dataset_case
from datasets_trigger_support import worker_inputs
from jobs_loop_support import wait_for
from jobs_storage_support import NOW
from nav_manifest import FakeNavigation
from sqlalchemy import Engine, select

from rdp.infra.db.connection import session_scope
from rdp.infra.diagnostics import ConflictError
from rdp.jobs.models import JobRow
from rdp.jobs.registry import production_registry
from rdp.jobs.service import JobService
from rdp.jobs.types import JobClock
from rdp.monitoring.mirror import latest_mirror
from rdp.monitoring.resources import latest_resources
from rdp.ops.lifecycle import start_worker
from rdp.ops.runtime import prepare_service


@pytest.fixture(autouse=True)
def offline_mirror(monkeypatch: pytest.MonkeyPatch) -> None:
    """真实 worker 测试只使用假镜像响应，不访问网络。"""
    from rdp.jobs.downloads.plan import HttpResponse

    def request(*args: object, **kwargs: object) -> HttpResponse:
        return HttpResponse(200, {}, b"")

    monkeypatch.setattr("rdp.jobs.downloads.plan.UrllibTransport.request", request)


def _wait_mirror(engine: Engine, scan_ready: Callable[[], bool]) -> None:
    """等待 worker 保存假镜像响应的结果。"""
    wait_for(scan_ready, timeout_s=5.0)
    wait_for(lambda: latest_mirror(engine) is not None, timeout_s=5.0)
    result = latest_mirror(engine)
    assert result is not None and result.status == "effective"
    wait_for(lambda: latest_resources(engine) is not None, timeout_s=5.0)
    resources = latest_resources(engine)
    assert resources is not None and resources.system.total_bytes is not None
    assert resources.system.total_bytes > 0


def _assert_monitor_stopped(failures: list[BaseException]) -> None:
    """确认集成测试回收监控线程且后台观察无失败。"""
    assert all(thread.name != "network-monitor" for thread in threads())
    assert not failures, failures


def test_production_worker_automatic_scans(tmp_path: Path, fake_nav: FakeNavigation) -> None:
    """第14张：生产worker启动完成全量扫描，推进超过十分钟并继续处理作业时不再自动扫描。"""
    inputs = worker_inputs(tmp_path / "deployment", fake_nav)
    guard = Lock()
    offset = [0.0]
    failures: list[BaseException] = []
    completed: list[tuple[int, str, int | None, str | None, int]] = []

    def monotonic() -> float:
        with guard:
            return time.monotonic() + offset[0]

    inputs = replace(inputs, clock=JobClock(inputs.clock.now, monotonic))
    runtime = prepare_service("worker", no_stderr=True, inputs=inputs)

    def have_completed(count: int) -> bool:
        with session_scope(runtime.engine, read_only=True) as session:
            rows = session.execute(
                select(
                    JobRow.job_id,
                    JobRow.submitter_name,
                    JobRow.submitter_id,
                    JobRow.outcome,
                    JobRow.total_items,
                )
                .where(JobRow.type_name == "dataset_rescan", JobRow.state == "completed")
                .order_by(JobRow.job_id)
            ).all()
            if len(rows) >= count:
                completed[:] = [(row[0], row[1], row[2], row[3], row[4]) for row in rows]
                return True
        return False

    @contextmanager
    def controlled_stop(stop: Event) -> Generator[None]:
        def drive() -> None:
            try:
                # 同一个生产 worker 必须完成扫描和镜像检查；替身不访问网络。
                _wait_mirror(runtime.engine, lambda: have_completed(1))
                with guard:
                    offset[0] = 601.0
                _assert_no_more_scans(runtime.engine, inputs.clock, completed[0][0])
            except BaseException as error:
                failures.append(error)
            finally:
                stop.set()

        thread = Thread(target=drive, daemon=True)
        try:
            thread.start()
            yield
        finally:
            stop.set()
            thread.join(timeout=5)
            assert not thread.is_alive()

    assert start_worker(runtime, inputs=inputs, signals=controlled_stop) == 0
    _assert_monitor_stopped(failures)
    assert len(completed) == 1
    assert all(
        name == "系统" and account_id is None and outcome == "succeeded" and total == 10
        for _, name, account_id, outcome, total in completed
    )


def _assert_no_more_scans(engine: Engine, clock: JobClock, startup_id: int) -> None:
    """哨兵完成证明 worker 已继续轮询，避免仅靠 sleep 断言没有扫描。"""
    sentinel = JobService(engine, production_registry()).submit_system(
        "example_count", {"steps": 1, "interval_ms": 0}, now=clock.now()
    )

    def sentinel_completed() -> bool:
        with session_scope(engine, read_only=True) as session:
            return (
                session.scalar(select(JobRow.state).where(JobRow.job_id == sentinel.job_id))
                == "completed"
            )

    wait_for(sentinel_completed, timeout_s=5.0)
    with session_scope(engine, read_only=True) as session:
        scans = tuple(
            session.scalars(select(JobRow.job_id).where(JobRow.type_name == "dataset_rescan"))
        )
    assert scans == (startup_id,)


def test_system_submission_rolls_back_with_audit(tmp_path: Path, fake_nav: FakeNavigation) -> None:
    """系统提交已插作业后审计失败必须整体回滚，不能留下没有提交审计的排队作业。"""
    with dataset_case(tmp_path / "state", fake_nav) as case:
        service = JobService(case.engine, production_registry(case.scanning))
        with case.engine.begin() as connection:
            connection.exec_driver_sql(
                "CREATE TRIGGER reject_audit BEFORE INSERT ON operation_logs BEGIN SELECT RAISE(ABORT, 'audit failure'); END"
            )
        try:
            with pytest.raises(ConflictError):
                service.submit_system("dataset_rescan", {"dataset_id": None}, now=NOW)
        finally:
            with case.engine.begin() as connection:
                connection.exec_driver_sql("DROP TRIGGER reject_audit")
        with session_scope(case.engine, read_only=True) as session:
            assert tuple(session.scalars(select(JobRow.job_id))) == ()
        submitted = service.submit_system("dataset_rescan", {"dataset_id": None}, now=NOW)
        assert submitted.submitted_by.name == "系统" and submitted.submitted_by.account_id is None
