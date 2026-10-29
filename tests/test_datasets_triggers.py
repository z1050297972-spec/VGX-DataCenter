"""生产worker自动扫描的集成验证；运行真实队列及执行器，仅系统时钟、配置和导航指向测试资源。"""

import time
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from threading import Event, Lock, Thread

import pytest
from datasets_execution_support import dataset_case
from datasets_trigger_support import worker_inputs
from jobs_loop_support import wait_for
from jobs_storage_support import NOW
from nav_manifest import FakeNavigation
from sqlalchemy import select

from rdp.infra.db.connection import session_scope
from rdp.infra.diagnostics import ConflictError
from rdp.jobs.models import JobRow
from rdp.jobs.registry import production_registry
from rdp.jobs.service import JobService
from rdp.jobs.types import JobClock
from rdp.ops.lifecycle import start_worker
from rdp.ops.runtime import prepare_service


def test_production_worker_automatic_scans(tmp_path: Path, fake_nav: FakeNavigation) -> None:
    """生产装配启动后自动完成一次全量扫描，推进600秒后再完成一次，提交人均为系统。"""
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
                wait_for(lambda: have_completed(1), timeout_s=5.0)
                with guard:
                    offset[0] = 600.0
                wait_for(lambda: have_completed(2), timeout_s=5.0)
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
    assert not failures, failures
    assert len(completed) == 2
    assert all(
        name == "系统" and account_id is None and outcome == "succeeded" and total == 10
        for _, name, account_id, outcome, total in completed
    )


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
