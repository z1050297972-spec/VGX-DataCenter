"""资源调度与恢复的行为测试；数据库和文件均位于临时目录。"""

import time
from contextlib import AbstractContextManager
from dataclasses import replace
from pathlib import Path
from queue import Queue
from threading import Event, Lock, Thread
from typing import TextIO

import pytest
from jobs_gpu_support import gpu_case
from jobs_loop_support import running_loop, wait_for
from jobs_scheduling_execution_support import scheduling_case
from jobs_storage_support import NOW
from sqlalchemy import event, func, select
from sqlalchemy.orm import Session

from rdp.audit.models import OperationLogRow
from rdp.infra.db.connection import session_scope
from rdp.infra.diagnostics import DefectError
from rdp.infra.logging import LoggingSettings
from rdp.jobs import policy
from rdp.jobs.execution import ExecutionContext, ExecutionWork
from rdp.jobs.models import JobRow
from rdp.jobs.navigation import NavigationWriter
from rdp.jobs.resources import ResourcePool
from rdp.jobs.scheduling import Scheduler
from rdp.jobs.scheduling_types import SchedulingSettings, TypeCapacity
from rdp.jobs.types import JobState, WorkerHeartbeat
from rdp.jobs.worker import run_loop


def test_limit_one(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """验收1：上限1时三个同类作业按job_id逐个开始，重叠执行数从不超过1。"""
    from rdp.jobs.types import JobState

    monkeypatch.setattr(policy, "WORKER_POLL_INTERVAL_S", 0.005)
    entered: Queue[int] = Queue(maxsize=3)
    release = {number: Event() for number in (71, 72, 73)}

    def execute(context: ExecutionContext) -> None:
        entered.put_nowait(context.job_id)
        deadline = time.monotonic() + 2
        while not release[context.job_id].is_set() and time.monotonic() < deadline:
            context.reporter.wait(0.005)
        assert release[context.job_id].is_set()

    with scheduling_case(tmp_path, execute=execute) as case:
        for number in release:
            case.add(number, "a")
        with running_loop(case.dependencies):
            try:
                for number in release:
                    assert entered.get(timeout=1) == number
                    assert all(
                        case.get(later).state is JobState.QUEUED
                        for later in release
                        if later > number
                    )
                    assert entered.empty()
                    release[number].set()
                wait_for(
                    lambda: (
                        all(case.get(number).state is JobState.COMPLETED for number in release)
                        and case.resources.pool.claims() == ()
                    )
                )
                assert case.resources.pool.claims() == ()
            finally:
                for ready in release.values():
                    ready.set()


def test_limit_two(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """验收1：覆盖上限2后同类恰好两个并行，第三个等任一名额归还。"""
    from rdp.jobs.types import JobState

    monkeypatch.setattr(policy, "WORKER_POLL_INTERVAL_S", 0.005)
    entered: Queue[int] = Queue(maxsize=3)
    release, guard = Event(), Lock()
    counts = {"active": 0, "maximum": 0}

    def execute(context: ExecutionContext) -> None:
        with guard:
            counts["active"] += 1
            counts["maximum"] = max(counts["maximum"], counts["active"])
        try:
            entered.put_nowait(context.job_id)
            deadline = time.monotonic() + 2
            while not release.is_set() and time.monotonic() < deadline:
                context.reporter.wait(0.005)
            assert release.is_set(), "测试执行等待超时"
        finally:
            with guard:
                counts["active"] -= 1

    with scheduling_case(tmp_path, concurrency=2, execute=execute) as case:
        for number in (71, 72, 73):
            case.add(number, "a")
        with running_loop(case.dependencies):
            try:
                assert sorted((entered.get(timeout=1), entered.get(timeout=1))) == [71, 72]
                assert case.get(73).state is JobState.QUEUED and entered.empty()
                release.set()
                assert entered.get(timeout=1) == 73
                wait_for(
                    lambda: (
                        all(case.get(number).state is JobState.COMPLETED for number in (71, 72, 73))
                        # 终态先提交，执行器finally随后归还资源；两者之间允许调度测试线程。
                        and case.resources.pool.claims() == ()
                    )
                )
                assert counts["maximum"] == 2 and counts["active"] == 0
                assert case.resources.pool.claims() == ()
            finally:
                release.set()


def test_other_type(tmp_path: Path) -> None:
    """验收1/K3：A类型已满时跳过其排队项，编号更大的B类型可以开始。"""
    from rdp.jobs.types import JobState

    with scheduling_case(tmp_path) as case:
        case.add(71, "a")
        case.add(72, "a")
        case.add(73, "b")
        first = case.scheduler.claim_next()
        second = case.scheduler.claim_next()
        assert first is not None and first.record.job_id == 71
        assert second is not None and second.record.job_id == 73
        assert case.get(72).state is JobState.QUEUED
        assert case.scheduler.claim_next() is None
        assert first.claim is not None and second.claim is not None
        case.resources.pool.release(first.claim)
        third = case.scheduler.claim_next()
        assert third is not None and third.record.job_id == 72
        assert third.claim is not None
        case.resources.pool.release(third.claim)
        case.resources.pool.release(second.claim)


def test_same_type_fifo(tmp_path: Path) -> None:
    """K3：同类队首等GPU时后项不能越过，submitted_at回拨不改变job_id顺序。"""
    from datetime import timedelta

    from jobs_storage_support import NOW

    from rdp.jobs.types import JobState, WaitReason

    with scheduling_case(tmp_path, gpus=(0,), needs_gpu=True) as case:
        occupied = case.resources.pool.reserve(70, "b").claim
        assert occupied is not None
        case.add(71, "a")
        case.add(72, "a")
        with session_scope(case.dependencies.engine) as session:
            later = session.get(JobRow, 72)
            assert later is not None
            later.submitted_at = NOW - timedelta(days=1)
        assert case.scheduler.claim_next() is None
        assert case.get(71).wait_reason is WaitReason.GPU
        assert case.get(72).state is JobState.QUEUED and case.get(72).wait_reason is None
        case.resources.pool.release(occupied)
        for number in (71, 72):
            work = case.scheduler.claim_next()
            assert work is not None and work.record.job_id == number and work.claim is not None
            case.resources.pool.release(work.claim)


def test_queue_cancel_race(tmp_path: Path) -> None:
    """契约：Web先取消候选时领取不执行，预留类型/GPU凭据finally归还，不写入运行态。"""
    from jobs_storage_support import NOW

    from rdp.jobs.records import StateChange, transition_job
    from rdp.jobs.types import JobState

    with scheduling_case(tmp_path, gpus=(0,), needs_gpu=True) as case:
        case.add(71, "a")
        cancelled = False

        def cancel_after_select(*args: object) -> None:
            nonlocal cancelled
            statement = args[2]
            if not cancelled and isinstance(statement, str) and "min(jobs.job_id)" in statement:
                cancelled = True
                with session_scope(case.dependencies.engine) as session:
                    transition_job(
                        session, 71, StateChange(JobState.QUEUED, JobState.CANCELLED, NOW)
                    )

        event.listen(case.dependencies.engine, "after_cursor_execute", cancel_after_select)
        try:
            assert case.scheduler.claim_next() is None
        finally:
            event.remove(case.dependencies.engine, "after_cursor_execute", cancel_after_select)
        assert cancelled
        record = case.get(71)
        assert record.state is JobState.CANCELLED
        assert record.gpu_index is None and record.started_at is None and record.log_path is None
        assert case.resources.pool.claims() == ()


def test_claim_busy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """契约：领取BEGIN忙在100毫秒预算内退回，不占普通5秒锁，不泄漏预留资源。"""
    from rdp.jobs.types import JobState

    monkeypatch.setattr(policy, "PROGRESS_LOCK_TIMEOUT_MS", 20)
    with scheduling_case(tmp_path, gpus=(0,), needs_gpu=True) as case:
        case.add(71, "a")
        with case.dependencies.engine.begin():
            started = time.monotonic()
            assert case.scheduler.claim_next() is None
            assert time.monotonic() - started < 0.5
            assert case.resources.pool.claims() == ()
            assert case.get(71).state is JobState.QUEUED
        work = case.scheduler.claim_next()
        assert work is not None and work.claim is not None
        case.resources.pool.release(work.claim)


def test_claim_atomic(tmp_path: Path) -> None:
    """契约：领取状态、首次时间、日志路径、卡号同事务；故障回滚全部并归还内存凭据。"""
    from rdp.infra.diagnostics import ExternalError
    from rdp.jobs.types import JobState

    def fail(*args: object) -> None:
        statement = args[2]
        if (
            isinstance(statement, str)
            and statement.startswith("UPDATE jobs")
            and "state=" in statement
        ):
            raise OSError("模拟领取状态写入后故障")

    with scheduling_case(tmp_path, gpus=(0,), needs_gpu=True) as case:
        case.add(71, "a")
        before = case.get(71)
        event.listen(case.dependencies.engine, "after_cursor_execute", fail)
        try:
            with pytest.raises(ExternalError):
                case.scheduler.claim_next()
        finally:
            event.remove(case.dependencies.engine, "after_cursor_execute", fail)
        assert case.get(71) == before
        assert case.resources.pool.claims() == ()
        work = case.scheduler.claim_next()
        assert work is not None and work.claim is not None
        assert work.record.state is JobState.RUNNING and work.record.gpu_index == 0
        assert work.record.started_at is not None and work.record.log_path is not None
        assert case.get(71) == work.record
        case.resources.pool.release(work.claim)


def test_thread_start_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """契约：领取提交后线程start失败，退回排队并清领取字段，归还卡/容量，主循环失败收尾。"""
    from jobs_storage_support import NOW

    from rdp.jobs import _loop
    from rdp.jobs.types import JobState, WorkerHeartbeat
    from rdp.jobs.worker import run_loop

    class UnstartableThread(Thread):
        """模拟操作系统拒绝启动线程。"""

        def start(self) -> None:
            """在创建任何线程之前拒绝启动。"""
            raise OSError("模拟线程启动失败")

    # 仅替换操作系统线程启动边界，不替换调度选择、事务或资源释放。
    monkeypatch.setattr(_loop, "Thread", UnstartableThread)
    with scheduling_case(tmp_path) as case:
        case.add(71, "a")
        result = run_loop(
            case.dependencies,
            Event(),
            WorkerHeartbeat("00000000000040008000000000000001", 123, NOW, NOW),
        )
        assert result.code == 1 and result.unreaped_threads == ()
        assert case.resources.pool.claims() == ()
        record = case.get(71)
        assert (
            record.state is JobState.QUEUED
            and record.started_at is None
            and record.log_path is None
        )


def test_per_job_signals(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """契约：并发作业的取消标志、monitor、日志上下文及60秒警告互不串扰。"""
    from jobs_storage_support import NOW

    from rdp.infra.logging import job_id_context, log_context
    from rdp.jobs.records import StateChange, transition_job
    from rdp.jobs.types import JobState

    monkeypatch.setattr(policy, "WORKER_POLL_INTERVAL_S", 0.005)
    monkeypatch.setattr(policy, "CANCEL_STALL_WARNING_S", 0.02)
    entered: Queue[int] = Queue(maxsize=2)
    gates = {number: Event() for number in (71, 72)}
    identities: dict[int, int | None] = {}

    def execute(context: ExecutionContext) -> None:
        identities[context.job_id] = job_id_context.get()
        entered.put_nowait(context.job_id)
        assert gates[context.job_id].wait(timeout=2), "测试闸门超时"
        context.reporter.check_cancelled()

    def warnings(number: int) -> int:
        return sum(
            "未响应取消" in item.getMessage() and f"job_id={number}" in item.getMessage()
            for item in caplog.records
        )

    previous = job_id_context.get()
    with scheduling_case(tmp_path, execute=execute) as case, log_context(job_id=999):
        case.add(71, "a")
        case.add(72, "b")
        with running_loop(case.dependencies):
            try:
                assert sorted((entered.get(timeout=1), entered.get(timeout=1))) == [71, 72]
                for number in (71, 72):
                    with session_scope(case.dependencies.engine) as session:
                        transition_job(
                            session, number, StateChange(JobState.RUNNING, JobState.CANCELLING, NOW)
                        )
                    wait_for(lambda number=number: warnings(number) == 1)
                    if number == 71:
                        assert case.get(72).state is JobState.RUNNING and warnings(72) == 0
                    gates[number].set()
                    wait_for(lambda number=number: case.get(number).state is JobState.CANCELLED)
                assert warnings(71) == warnings(72) == 1
                assert identities == {71: 71, 72: 72} and job_id_context.get() == 999
            finally:
                for gate in gates.values():
                    gate.set()
    assert job_id_context.get() == previous


def test_recovery_first(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """契约：启动先统一清资源副本，全部遗留无资源完成准备，恢复候选只优先于同类型queued。"""
    from rdp.jobs.types import JobState
    from rdp.ops.worker import run_worker

    monkeypatch.setattr(policy, "WORKER_POLL_INTERVAL_S", 0.005)
    stop = Event()
    observed: list[tuple[int, str, bool]] = []

    def execute(context: ExecutionContext) -> None:
        other = case.get(72)
        observed.append(
            (
                context.job_id,
                context.mode.value,
                other.gpu_index is None
                and not other.holds_navigation_lock
                and other.recovery_count == 1,
            )
        )
        if len(observed) == 3:
            stop.set()

    with scheduling_case(tmp_path, execute=execute) as case:
        case.add(71, "a", JobState.RUNNING)
        case.add(72, "a", JobState.RUNNING)
        case.add(73, "b")
        with session_scope(case.dependencies.engine) as session:
            row = session.get(JobRow, 72)
            assert row is not None
            row.gpu_index = 9
            row.holds_navigation_lock = True
        results: list[int] = []
        failures: list[BaseException] = []

        def run() -> None:
            try:
                results.append(
                    run_worker(
                        case.dependencies,
                        stop,
                        LoggingSettings("worker", case.dependencies.paths.logs, stderr=False),
                        scheduling=case.resources.configuration,
                    ).code
                )
            except BaseException as error:
                failures.append(error)

        thread = Thread(target=run, daemon=True)
        try:
            thread.start()
            thread.join(timeout=2)
            assert not thread.is_alive() and not failures and results == [0]
        finally:
            stop.set()
            thread.join(timeout=2)
            assert not thread.is_alive()

        assert sorted((number, mode) for number, mode, _ in observed) == [
            (71, "restart"),
            (72, "restart"),
            (73, "fresh"),
        ]
        assert all(clean for _, _, clean in observed)
        assert case.resources.pool.claims() == ()


def test_recovery_different_types(tmp_path: Path) -> None:
    """契约：全部准备后恢复A等卡不阻挡有容量的新B，准备和领取分离，不存在全局恢复资源屏障。"""
    from rdp.jobs.execution import recover_job
    from rdp.jobs.scheduling import Scheduler
    from rdp.jobs.types import ExecutionMode, JobState, WaitReason

    with scheduling_case(tmp_path, concurrency=2, gpus=(0,), needs_gpu=frozenset({"a"})) as case:
        occupied = case.resources.pool.reserve(70, "a").claim
        assert occupied is not None
        case.add(71, "a", JobState.RUNNING)
        original_start = case.get(71).started_at
        case.add(72, "b")
        case.add(73, "a")
        recovered = recover_job(71, case.dependencies)
        assert recovered is not None and recovered.claim is None
        scheduler = Scheduler(case.dependencies, case.resources, recovered=(recovered,))
        other = scheduler.claim_next()
        assert other is not None and other.record.job_id == 72 and other.claim is not None
        assert case.get(71).wait_reason is WaitReason.GPU
        assert case.get(73).state is JobState.QUEUED
        case.resources.pool.release(occupied)
        resumed = scheduler.claim_next()
        assert resumed is not None and resumed.record.job_id == 71 and resumed.claim is not None
        assert resumed.mode is ExecutionMode.RESTART
        assert resumed.record.recovery_count == 1 and resumed.record.started_at == original_start
        assert resumed.record.gpu_index == 0 and resumed.record.wait_reason is None
        case.resources.pool.release(resumed.claim)
        case.resources.pool.release(other.claim)


def test_recovery_capacity(tmp_path: Path) -> None:
    """契约：全部恢复资格先不受容量限制准备一次，数量超过降低的上限时执行按容量领取，不使用旧卡。"""
    from rdp.jobs.execution import ExecutionWork, recover_job
    from rdp.jobs.scheduling import Scheduler
    from rdp.jobs.types import JobState

    with scheduling_case(tmp_path, concurrency=2) as case:
        recovered: list[ExecutionWork] = []
        for number in (71, 72, 73):
            case.add(number, "a", JobState.RUNNING)
            ready = recover_job(number, case.dependencies)
            assert ready is not None
            recovered.append(ready)
        assert [case.get(number).recovery_count for number in (71, 72, 73)] == [1, 1, 1]
        assert case.resources.pool.claims() == ()
        scheduler = Scheduler(case.dependencies, case.resources, recovered=tuple(recovered))
        first, second = scheduler.claim_next(), scheduler.claim_next()
        assert first is not None and first.record.job_id == 71 and first.claim is not None
        assert second is not None and second.record.job_id == 72 and second.claim is not None
        assert scheduler.claim_next() is None
        assert [claim.job_id for claim in case.resources.pool.claims()] == [71, 72]
        case.resources.pool.release(first.claim)
        third = scheduler.claim_next()
        assert third is not None and third.record.job_id == 73 and third.claim is not None
        assert third.record.recovery_count == 1 and third.record.gpu_index is None
        case.resources.pool.release(second.claim)
        case.resources.pool.release(third.claim)


def test_recovery_cancel(tmp_path: Path) -> None:
    """契约：恢复等资源期间被取消，最终已取消并清等待，不能遗失running记录或执行其类型函数。"""
    from jobs_storage_support import NOW

    from rdp.jobs.execution import recover_job
    from rdp.jobs.records import StateChange, transition_job
    from rdp.jobs.scheduling import Scheduler
    from rdp.jobs.types import JobState, WaitReason

    with scheduling_case(tmp_path, concurrency=2, gpus=(0,), needs_gpu=True) as case:
        occupied = case.resources.pool.reserve(70, "b").claim
        assert occupied is not None
        case.add(71, "a", JobState.RUNNING)
        recovered = recover_job(71, case.dependencies)
        assert recovered is not None
        scheduler = Scheduler(case.dependencies, case.resources, recovered=(recovered,))
        assert scheduler.claim_next() is None
        assert case.get(71).wait_reason is WaitReason.GPU
        with session_scope(case.dependencies.engine) as session:
            transition_job(session, 71, StateChange(JobState.RUNNING, JobState.CANCELLING, NOW))
        assert scheduler.claim_next() is None
        final = case.get(71)
        assert final.state is JobState.CANCELLED and final.wait_reason is None
        assert final.recovery_count == 1 and final.summary is not None
        assert case.resources.pool.claims() == (occupied,)
        case.resources.pool.release(occupied)
        assert scheduler.claim_next() is None


def test_unknown_type(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """契约：未登记类型通过有界诊断名额领取并失败，不永久堵队列或创建无界线程。"""
    from rdp.jobs.types import JobState

    monkeypatch.setattr(policy, "WORKER_POLL_INTERVAL_S", 0.005)
    with scheduling_case(tmp_path) as case:
        case.add(71, "removed_one")
        case.add(72, "removed_two")
        case.add(73, "a")
        with running_loop(case.dependencies) as (_, _, results):
            wait_for(
                lambda: all(case.get(number).state is JobState.COMPLETED for number in (71, 72, 73))
            )
        assert results[0].code == 0 and case.resources.pool.claims() == ()
        for number in (71, 72):
            record = case.get(number)
            assert record.summary is not None and record.summary.outcome == "failed"
            assert any(
                item.key == "type" and item.value == record.type_name
                for group in record.diagnostics
                for sample in group.samples
                for item in sample.objects
            )
        last = case.get(73)
        assert last.summary is not None and last.summary.outcome == "succeeded"


def test_terminal_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """契约：任一并发作业终态提交失败使整个worker停止领取/心跳，其余线程共用停止预算。"""
    from rdp.jobs.types import JobState

    monkeypatch.setattr(policy, "WORKER_POLL_INTERVAL_S", 0.005)
    entered: Queue[int] = Queue(maxsize=3)
    release = Event()

    def execute(context: ExecutionContext) -> None:
        entered.put_nowait(context.job_id)
        if context.job_id == 71:
            assert release.wait(timeout=2)
        else:
            context.reporter.wait(2)

    def fail(*args: object) -> None:
        statement, parameters = args[2], args[3]
        if (
            isinstance(statement, str)
            and statement.startswith("UPDATE jobs")
            and "summary=" in statement
            and isinstance(parameters, tuple)
            and 71 in parameters
        ):
            raise OSError("模拟单作业终态提交失败")

    with scheduling_case(tmp_path, execute=execute) as case:
        case.add(71, "a")
        case.add(72, "b")
        case.add(73, "a")
        event.listen(case.dependencies.engine, "before_cursor_execute", fail)
        try:
            with running_loop(case.dependencies) as (_stop, thread, results):
                try:
                    assert sorted((entered.get(timeout=1), entered.get(timeout=1))) == [71, 72]
                    release.set()
                    thread.join(timeout=2)
                    assert (
                        not thread.is_alive()
                        and results[0].code == 1
                        and not results[0].unreaped_threads
                    )
                finally:
                    release.set()
        finally:
            event.remove(case.dependencies.engine, "before_cursor_execute", fail)
        assert case.get(71).state is case.get(72).state is JobState.RUNNING
        assert case.get(73).state is JobState.QUEUED and entered.empty()
        assert case.resources.pool.claims() == ()
        errors = [item for item in caplog.records if item.levelname == "ERROR"]
        assert len(errors) == 1 and "终态持久化失败" in errors[0].getMessage()


def test_shared_stop_budget(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """契约：多个执行线程共用30秒截止，不按线程叠加；完整返回遗留daemon线程供入口保锁。"""
    from rdp.jobs.worker import WorkerLoopResult

    monkeypatch.setattr(policy, "WORKER_STOP_TIMEOUT_S", 0.1)
    monkeypatch.setattr(policy, "WORKER_POLL_INTERVAL_S", 0.005)
    entered: Queue[int] = Queue(maxsize=3)
    release = Event()
    results: list[WorkerLoopResult] = []

    def execute(context: ExecutionContext) -> None:
        entered.put_nowait(context.job_id)
        assert release.wait(2)

    with scheduling_case(tmp_path, concurrency=3, execute=execute) as case:
        for number in (71, 72, 73):
            case.add(number, "a")
        try:
            with running_loop(case.dependencies) as (stop, thread, results):
                assert {entered.get(timeout=1) for _ in range(3)} == {71, 72, 73}
                started = time.monotonic()
                stop.set()
                thread.join(timeout=0.5)
                elapsed = time.monotonic() - started
                assert not thread.is_alive() and 0.09 <= elapsed < 0.25
                assert results[0].code == 1 and len(results[0].unreaped_threads) == 3
                assert all(
                    owned.daemon and owned.is_alive() for owned in results[0].unreaped_threads
                )
        finally:
            release.set()
            for result in results:
                for owned in result.unreaped_threads:
                    owned.join(timeout=1)
                    assert not owned.is_alive()


def test_resource_release() -> None:
    """契约：完成后名额可以被下一作业使用；伪造、跨池或重复释放为DefectError且不改其他卡主。"""
    settings = SchedulingSettings(
        (1, 3), (TypeCapacity("a", "甲", 1, True), TypeCapacity("b", "乙", 2, True))
    )
    pool = ResourcePool(settings, available_gpus=(1, 3))
    assert pool.claims() == ()
    first = pool.reserve(79, "a").claim
    second = pool.reserve(81, "b").claim
    assert first is not None and second is not None
    assert (first.gpu_index, second.gpu_index) == (1, 3)
    assert pool.claims() == (first, second)
    other = ResourcePool(settings, available_gpus=(1, 3))
    foreign = other.reserve(79, "a").claim
    assert foreign is not None
    for invalid in (replace(first), replace(first, job_id=100), foreign):
        with pytest.raises(DefectError):
            pool.release(invalid)
        assert pool.claims() == (first, second)
    pool.release(first)
    replacement = pool.reserve(82, "a").claim
    assert replacement is not None and replacement.gpu_index == 1
    with pytest.raises(DefectError):
        pool.release(first)
    assert pool.claims() == (second, replacement)
    pool.release(second)
    pool.release(replacement)
    other.release(foreign)
    assert pool.claims() == other.claims() == ()


def test_display_short_lock(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """契约：等待/持锁副本BEGIN忙只跳过本次，后续检查点即使无新进度仍补写最新清空值。"""
    from jobs_progress_support import MutableClock, reporter_context, saved_record

    from rdp.jobs import progress as progress_module
    from rdp.jobs.scheduling_types import ResourceDisplay
    from rdp.jobs.types import JobClock, WaitReason

    monkeypatch.setattr(progress_module, "PROGRESS_LOCK_TIMEOUT_MS", 20)
    clock = MutableClock()
    with reporter_context(tmp_path, JobClock(clock.now, clock.monotonic)) as (
        reporter,
        engine,
        _signals,
        _path,
    ):
        with engine.begin():
            started = time.monotonic()
            reporter.set_resource_display(ResourceDisplay(WaitReason.NAVIGATION_LOCK, False))
            assert time.monotonic() - started < 0.5
        assert saved_record(engine).wait_reason is None
        clock.seconds += 1
        reporter.check_cancelled()
        assert saved_record(engine).wait_reason is WaitReason.NAVIGATION_LOCK
        clock.seconds += 1
        reporter.set_resource_display(ResourceDisplay(None, True))
        assert saved_record(engine).holds_navigation_lock
        clock.seconds += 1
        with engine.begin():
            reporter.set_resource_display(ResourceDisplay(None, False))
        assert saved_record(engine).holds_navigation_lock
        clock.seconds += 1
        reporter.check_cancelled()
        final = saved_record(engine)
        assert (
            final.wait_reason is None and not final.holds_navigation_lock and final.progress is None
        )


def test_display_commit_failure(tmp_path: Path) -> None:
    """契约：展示事务已入场后的错误不能吞为锁忙，故障传播到执行/主循环边界。"""
    from jobs_progress_support import MutableClock, reporter_context, saved_record

    from rdp.infra.diagnostics import ExternalError
    from rdp.jobs.scheduling_types import ResourceDisplay
    from rdp.jobs.types import JobClock

    def fail(*args: object) -> None:
        statement = args[2]
        if (
            isinstance(statement, str)
            and statement.startswith("UPDATE jobs")
            and "holds_navigation_lock" in statement
        ):
            raise OSError("模拟入场后资源写入故障")

    clock = MutableClock()
    with reporter_context(tmp_path, JobClock(clock.now, clock.monotonic)) as (
        reporter,
        engine,
        _signals,
        _path,
    ):
        before = saved_record(engine)
        event.listen(engine, "after_cursor_execute", fail)
        try:
            with pytest.raises(ExternalError):
                reporter.set_resource_display(ResourceDisplay(None, True))
        finally:
            event.remove(engine, "after_cursor_execute", fail)
        assert saved_record(engine) == before
        clock.seconds += 1
        reporter.flush_due()
        assert saved_record(engine).holds_navigation_lock


def test_terminal_clear(tmp_path: Path) -> None:
    """契约：完成、取消、中断的最终事务必清等待和持锁，旧周期副本不能重新覆盖终态，卡号保留。"""
    from jobs_storage_support import NOW, job_database, job_row

    from rdp.infra.diagnostics import ConflictError
    from rdp.jobs.records import StateChange, find_job, transition_job
    from rdp.jobs.resources import save_resource_display
    from rdp.jobs.scheduling_types import ResourceDisplay
    from rdp.jobs.types import JobState, WaitReason

    pairs = (
        (JobState.RUNNING, JobState.COMPLETED),
        (JobState.CANCELLING, JobState.CANCELLED),
        (JobState.RUNNING, JobState.INTERRUPTED),
        (JobState.QUEUED, JobState.CANCELLED),
    )
    with job_database(tmp_path) as (engine, _paths):
        with session_scope(engine) as session:
            for number, (state, _) in enumerate(pairs, start=71):
                row = job_row(state, job_id=number)
                row.gpu_index = None if state is JobState.QUEUED else number
                row.wait_reason = "gpu" if state is JobState.QUEUED else None
                row.holds_navigation_lock = state in {JobState.RUNNING, JobState.CANCELLING}
                session.add(row)
        for number, (state, target) in enumerate(pairs, start=71):
            with session_scope(engine) as session:
                result = transition_job(session, number, StateChange(state, target, NOW))
                assert result.state is target
                assert result.wait_reason is None and not result.holds_navigation_lock
                assert result.gpu_index == (None if state is JobState.QUEUED else number)
            with session_scope(engine) as session, pytest.raises(ConflictError):
                save_resource_display(session, number, ResourceDisplay(WaitReason.GPU, False))
            with session_scope(engine, read_only=True) as session:
                assert find_job(session, number) == result


def test_recovery_clear(tmp_path: Path) -> None:
    """契约：启动一个事务清所有非终态等待/持锁及running/cancelling卡号，不受容量限制，原有终态历史卡不变。"""
    from jobs_storage_support import job_database, job_row

    from rdp.jobs.records import find_job
    from rdp.jobs.resources import reset_resources_on_startup
    from rdp.jobs.types import JobState, WaitReason

    with job_database(tmp_path) as (engine, _paths):
        with session_scope(engine) as session:
            for number, state in enumerate(JobState, start=71):
                row = job_row(state, job_id=number)
                row.gpu_index = None if state is JobState.QUEUED else number
                row.wait_reason = "gpu" if state is JobState.QUEUED else None
                row.holds_navigation_lock = state is JobState.RUNNING
                session.add(row)
        with session_scope(engine, read_only=True) as session:
            before = {number: find_job(session, number) for number in range(71, 77)}
            assert before[71].wait_reason is WaitReason.GPU
            assert before[72].gpu_index == 72 and before[72].holds_navigation_lock
        with session_scope(engine) as session:
            assert reset_resources_on_startup(session) == 3
        with session_scope(engine, read_only=True) as session:
            for number, previous in before.items():
                expected = (
                    replace(previous, gpu_index=None, wait_reason=None, holds_navigation_lock=False)
                    if number <= 73
                    else previous
                )
                assert find_job(session, number) == expected
            with pytest.raises(DefectError):
                reset_resources_on_startup(session)


def test_holder_handoff(tmp_path: Path) -> None:
    """契约：A释放时展示写入锁忙，B取得写锁后同事务清A旧标记，调度页不会出现双持锁者。"""
    from jobs_storage_support import job_database, job_row

    from rdp.infra.diagnostics import ConflictError
    from rdp.jobs.records import find_job
    from rdp.jobs.resources import save_resource_display
    from rdp.jobs.scheduling_types import ResourceDisplay
    from rdp.jobs.types import JobState, WaitReason

    with job_database(tmp_path) as (engine, _paths):
        with session_scope(engine) as session:
            session.add_all(
                [
                    job_row(),
                    job_row(job_id=72),
                    job_row(JobState.COMPLETED, job_id=73),
                    job_row(JobState.QUEUED, job_id=74),
                ]
            )
        with session_scope(engine) as session:
            save_resource_display(session, 71, ResourceDisplay(None, True))
        with session_scope(engine) as session:
            save_resource_display(session, 72, ResourceDisplay(None, True))
            save_resource_display(session, 71, ResourceDisplay(None, False))
        with session_scope(engine, read_only=True) as session:
            assert not find_job(session, 71).holds_navigation_lock
            assert find_job(session, 72).holds_navigation_lock
        with session_scope(engine) as session:
            save_resource_display(session, 74, ResourceDisplay(WaitReason.GPU, False))
            save_resource_display(session, 72, ResourceDisplay(WaitReason.NAVIGATION_LOCK, False))
        with session_scope(engine, read_only=True) as session:
            assert find_job(session, 74).wait_reason is WaitReason.GPU
            assert find_job(session, 72).wait_reason is WaitReason.NAVIGATION_LOCK
        with session_scope(engine) as session:
            with pytest.raises(DefectError):
                save_resource_display(session, 74, ResourceDisplay(None, True))
            with pytest.raises(DefectError):
                save_resource_display(
                    session, 72, ResourceDisplay(WaitReason.NAVIGATION_LOCK, True)
                )
            with pytest.raises(ConflictError):
                save_resource_display(session, 73, ResourceDisplay(None, False))


def test_two_recoveries_do_not_block_other_type(tmp_path: Path) -> None:
    """阻塞1：A类两个restart遗留均先准备、各加一次恢复次数；A上限1时第二个等容量，新B仍立即领取。"""
    from rdp.jobs.execution import recover_job
    from rdp.jobs.scheduling import Scheduler
    from rdp.jobs.types import ExecutionMode, JobState

    with scheduling_case(tmp_path) as case:
        for number in (71, 72):
            case.add(number, "a", JobState.RUNNING)
        case.add(73, "b")
        case.add(74, "a")
        first = recover_job(71, case.dependencies)
        second = recover_job(72, case.dependencies)
        assert first is not None and second is not None
        assert [case.get(number).recovery_count for number in (71, 72)] == [1, 1]
        assert case.resources.pool.claims() == ()
        scheduler = Scheduler(case.dependencies, case.resources, recovered=(first, second))
        running = scheduler.claim_next()
        other = scheduler.claim_next()
        assert running is not None and running.record.job_id == 71 and running.claim is not None
        assert other is not None and other.record.job_id == 73 and other.claim is not None
        assert scheduler.claim_next() is None
        assert case.get(74).state is JobState.QUEUED
        case.resources.pool.release(running.claim)
        next_recovery = scheduler.claim_next()
        assert (
            next_recovery is not None
            and next_recovery.record.job_id == 72
            and next_recovery.claim is not None
        )
        assert (
            next_recovery.mode is ExecutionMode.RESTART and next_recovery.record.recovery_count == 1
        )
        case.resources.pool.release(next_recovery.claim)
        new = scheduler.claim_next()
        assert (
            new is not None
            and new.record.job_id == 74
            and new.mode is ExecutionMode.FRESH
            and new.claim is not None
        )
        case.resources.pool.release(new.claim)
        case.resources.pool.release(other.claim)


def test_queued_gpu_wait_clears_on_capacity(tmp_path: Path) -> None:
    """阻塞2：queued队首曾等GPU，本轮类型上限满时主循环清旧GPU等待，不以旧标记持续等卡。"""
    from rdp.jobs.types import JobState, WaitReason

    with scheduling_case(tmp_path, gpus=(0,), needs_gpu=True) as case:
        card = case.resources.pool.reserve(69, "b").claim
        assert card is not None
        case.add(71, "a")
        assert case.scheduler.claim_next() is None and case.get(71).wait_reason is WaitReason.GPU
        case.resources.pool.release(card)
        same_type = case.resources.pool.reserve(70, "a").claim
        assert same_type is not None
        assert case.scheduler.claim_next() is None
        assert case.get(71).state is JobState.QUEUED and case.get(71).wait_reason is None
        case.resources.pool.release(same_type)
        work = case.scheduler.claim_next()
        assert work is not None and work.claim is not None and work.record.wait_reason is None
        case.resources.pool.release(work.claim)


def test_queued_gpu_wait_clears_on_claim_and_cancel(tmp_path: Path) -> None:
    """阻塞2：领取事务清GPU等待，排队取消终态事务也清；旧周期副本不得覆盖已取消记录，启动清全部非终态。"""
    from jobs_storage_support import NOW

    from rdp.infra.diagnostics import ConflictError
    from rdp.jobs.records import StateChange, transition_job
    from rdp.jobs.resources import save_resource_display
    from rdp.jobs.scheduling_types import ResourceDisplay
    from rdp.jobs.types import JobState, WaitReason

    with scheduling_case(tmp_path, concurrency=2, gpus=(0,), needs_gpu=True) as case:
        occupied = case.resources.pool.reserve(70, "b").claim
        assert occupied is not None
        case.add(71, "a")
        case.add(72, "b")
        assert case.scheduler.claim_next() is None
        assert case.get(71).wait_reason is case.get(72).wait_reason is WaitReason.GPU
        case.resources.pool.release(occupied)
        work = case.scheduler.claim_next()
        assert work is not None and work.claim is not None and work.record.wait_reason is None
        with session_scope(case.dependencies.engine) as session:
            cancelled = transition_job(
                session, 72, StateChange(JobState.QUEUED, JobState.CANCELLED, NOW)
            )
            assert cancelled.wait_reason is None
        with pytest.raises(ConflictError), session_scope(case.dependencies.engine) as session:
            save_resource_display(session, 72, ResourceDisplay(WaitReason.GPU, False))
        assert case.get(72).state is JobState.CANCELLED and case.get(72).wait_reason is None
        case.resources.pool.release(work.claim)


def test_queue_wait_has_one_writer(tmp_path: Path) -> None:
    """阻塞2：主循环独占queued的GPU等待写入，每轮重判；reporter只写本运行作业的导航锁副本。"""
    from jobs_progress_support import MutableClock, reporter_context, saved_record

    from rdp.jobs.scheduling_types import ResourceDisplay
    from rdp.jobs.types import JobClock, WaitReason

    clock = MutableClock()
    with reporter_context(tmp_path, JobClock(clock.now, clock.monotonic)) as (
        reporter,
        engine,
        _signals,
        _path,
    ):
        before = saved_record(engine)
        with pytest.raises(DefectError):
            reporter.set_resource_display(ResourceDisplay(WaitReason.GPU, False))
        assert saved_record(engine) == before
        reporter.set_resource_display(ResourceDisplay(WaitReason.NAVIGATION_LOCK, False))
        assert saved_record(engine).wait_reason is WaitReason.NAVIGATION_LOCK


def test_cross_type_gpu_fifo(tmp_path: Path) -> None:
    """契约：A类队首job_id较小且在等卡，B类队首在后，卡释放后先给A，不按类型登记顺序分配。"""
    from rdp.jobs.types import JobState, WaitReason

    with scheduling_case(tmp_path, gpus=(0,), needs_gpu=True) as case:
        occupied = case.resources.pool.reserve(70, "b").claim
        assert occupied is not None
        case.add(71, "a")
        case.add(72, "b")
        assert case.scheduler.claim_next() is None
        assert case.get(71).wait_reason is WaitReason.GPU
        case.resources.pool.release(occupied)
        first = case.scheduler.claim_next()
        assert first is not None and first.record.job_id == 71
        assert first.record.gpu_index == 0 and first.record.wait_reason is None
        assert case.get(72).state is JobState.QUEUED
        assert first.claim is not None
        case.resources.pool.release(first.claim)
        second = case.scheduler.claim_next()
        assert second is not None and second.record.job_id == 72 and second.claim is not None
        case.resources.pool.release(second.claim)


def test_run_loop_checks_schedules_and_finishes_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """契约：run_loop级集成以可控时钟跨每日时刻，主循环每轮调用定时检查，两个清除作业被领取并完成，摘要计数正确。"""
    from datetime import timedelta

    from jobs_loop_support import running_loop, wait_for
    from jobs_maintenance_support import seed_errors
    from jobs_schedules_support import scheduled_case
    from jobs_storage_support import NOW
    from sqlalchemy import select

    from rdp.infra.db.connection import session_scope
    from rdp.jobs import policy
    from rdp.jobs.models import JobRow
    from rdp.jobs.types import JobState

    monkeypatch.setattr(policy, "WORKER_POLL_INTERVAL_S", 0.01)
    with scheduled_case(tmp_path, NOW) as case:

        def completed() -> list[int]:
            with session_scope(case.dependencies.engine, read_only=True) as session:
                return list(
                    session.scalars(
                        select(JobRow.job_id).where(
                            JobRow.type_name == "purge_errors",
                            JobRow.state == JobState.COMPLETED.value,
                        )
                    )
                )

        seed_errors(case.dependencies.engine, (NOW - timedelta(days=40),))
        with running_loop(case.dependencies) as (_stop, _thread, results):
            wait_for(lambda: len(completed()) == 1)
            seed_errors(case.dependencies.engine, (NOW - timedelta(days=40),))
            case.clock.wall = (NOW + timedelta(days=1)).replace(hour=3)
            case.clock.seconds += 1
            wait_for(lambda: len(completed()) == 2)
            with session_scope(case.dependencies.engine, read_only=True) as session:
                rows = session.scalars(select(JobRow).order_by(JobRow.job_id)).all()
                assert len(rows) == 2 and all(
                    row.outcome == "succeeded" and row.total_items == 1 for row in rows
                )
        assert results[0].code == 0


def test_queued_heads_single_query(tmp_path: Path) -> None:
    """契约：一条SQL只取每类最小queued编号并按job_id排序，后项不加载；空队列返回空，不维护跨轮游标。"""
    from datetime import timedelta

    from jobs_storage_support import NOW, job_database, job_row
    from sqlalchemy import delete, event

    from rdp.jobs.records import queued_type_heads
    from rdp.jobs.types import JobState

    statements: list[str] = []

    def capture(*args: object) -> None:
        statement = args[2]
        if isinstance(statement, str) and statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    with job_database(tmp_path) as (engine, _paths):
        with session_scope(engine) as session:
            for number, kind, state in (
                (71, "a", JobState.RUNNING),
                (72, "a", JobState.QUEUED),
                (73, "b", JobState.QUEUED),
                (74, "a", JobState.QUEUED),
                (75, "c", JobState.CANCELLED),
                (76, "b", JobState.QUEUED),
                (77, "c", JobState.QUEUED),
            ):
                row = job_row(state, job_id=number)
                row.type_name = kind
                row.submitted_at = NOW - timedelta(seconds=number)
                session.add(row)
        event.listen(engine, "before_cursor_execute", capture)
        try:
            with session_scope(engine, read_only=True) as session:
                heads = queued_type_heads(session)
            assert [(item.job_id, item.type_name) for item in heads] == [
                (72, "a"),
                (73, "b"),
                (77, "c"),
            ]
            assert len(statements) == 1
        finally:
            event.remove(engine, "before_cursor_execute", capture)
        with session_scope(engine) as session:
            with pytest.raises(DefectError):
                queued_type_heads(session)
            session.execute(delete(JobRow).where(JobRow.state == "queued"))
        with session_scope(engine, read_only=True) as session:
            assert queued_type_heads(session) == ()


def test_startup_reset_atomic_failure(tmp_path: Path) -> None:
    """阻塞1：清除全部非终态资源副本的单事务失败时整体回滚并阻止启动，不跳过忙锁继续准备或调度。"""
    from jobs_storage_support import job_database, job_row

    from rdp.infra.diagnostics import ExternalError
    from rdp.jobs.records import find_job
    from rdp.jobs.resources import reset_resources_on_startup

    def fail(*args: object) -> None:
        statement = args[2]
        if isinstance(statement, str) and statement.startswith("UPDATE jobs"):
            raise OSError("模拟清空后的I/O故障")

    with job_database(tmp_path) as (engine, _paths):
        with session_scope(engine) as session:
            row = job_row()
            row.gpu_index = 3
            row.holds_navigation_lock = True
            session.add(row)
        with session_scope(engine, read_only=True) as session:
            before = find_job(session, 71)
        event.listen(engine, "after_cursor_execute", fail)
        try:
            with pytest.raises(ExternalError), session_scope(engine) as session:
                reset_resources_on_startup(session)
        finally:
            event.remove(engine, "after_cursor_execute", fail)
        with session_scope(engine, read_only=True) as session:
            assert find_job(session, 71) == before


def test_resource_pool_lock_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    """契约：资源池使用RESOURCE_POOL_LOCK_TIMEOUT_S，超预算DefectError且无部分占用；不借用输出线程join预算。"""
    from threading import Lock

    from rdp.jobs import policy, resources

    # 在标准库锁工厂边界注入真实锁，制造确定的竞争，不窥探资源池私有字段。
    lock = Lock()
    monkeypatch.setattr(resources, "Lock", lambda: lock)
    monkeypatch.setattr(policy, "RESOURCE_POOL_LOCK_TIMEOUT_S", 0.01)
    monkeypatch.setattr(policy, "OUTPUT_JOIN_TIMEOUT_S", 2.0)
    pool = ResourcePool(
        SchedulingSettings((), (TypeCapacity("a", "甲", 1, False),)), available_gpus=()
    )
    lock.acquire()
    started = time.monotonic()
    try:
        with pytest.raises(DefectError):
            pool.reserve(1, "a")
        assert time.monotonic() - started < 0.5
        assert lock.locked()
    finally:
        lock.release()
    assert pool.claims() == ()


def test_pool_inputs_and_admission() -> None:
    """资源池契约：严格验证输入，区分类型满与等卡，空有效池不无限等待，未知类型共用一个诊断名额。"""
    from typing import cast

    from rdp.jobs.scheduling_types import Admission
    from rdp.jobs.types import WaitReason

    types = (
        TypeCapacity("a", "甲", 1, True),
        TypeCapacity("b", "乙", 3, True),
        TypeCapacity("c", "丙", 1, False),
    )
    settings = SchedulingSettings((1, 3), types)
    for invalid, available in (
        (replace(settings, gpus=(1, 1)), (1,)),
        (replace(settings, types=(types[0], types[0])), (1,)),
        (replace(settings, types=(replace(types[0], concurrency=0),)), (1,)),
        (replace(settings, types=(replace(types[0], requires_gpu=cast(bool, 1)),)), (1,)),
        (settings, (4,)),
        (settings, (3, 1)),
        (settings, (1, 1)),
        (replace(settings, gpus=(True,)), (True,)),
    ):
        with pytest.raises(DefectError):
            ResourcePool(invalid, available_gpus=available)
    pool = ResourcePool(settings, available_gpus=(1, 3))
    for number, name in ((True, "a"), (0, "a"), (-1, "a"), (2**63, "a"), (1, "bad-key")):
        with pytest.raises(DefectError):
            pool.reserve(number, name)
        assert pool.claims() == ()
    first = pool.reserve(1, "a").claim
    assert first is not None and first.gpu_index == 1
    assert pool.reserve(2, "a") == Admission(None, None)
    second = pool.reserve(3, "b").claim
    assert second is not None and second.gpu_index == 3
    assert pool.reserve(4, "b") == Admission(None, WaitReason.GPU)
    assert pool.reserve(5, "c").claim is not None
    with pytest.raises(DefectError):
        pool.reserve(1, "a")
    assert pool.reserve(6, "removed_one").claim is not None
    assert pool.reserve(7, "removed_two") == Admission(None, None)
    excluded = ResourcePool(settings, available_gpus=())
    no_card = excluded.reserve(8, "a").claim
    assert no_card is not None and no_card.gpu_index is None
    for claim in pool.claims():
        pool.release(claim)
    excluded.release(no_card)


def test_scheduler_rejects_unprepared_candidates(tmp_path: Path) -> None:
    """调度构造契约：未准备、重复、携带凭据或非法依赖的恢复候选在启动执行前拒绝。"""
    from typing import cast

    from rdp.jobs.execution import ExecutorDependencies, recover_job
    from rdp.jobs.scheduling import Scheduler
    from rdp.jobs.scheduling_types import ResourceClaim
    from rdp.jobs.types import ExecutionMode, JobState

    with scheduling_case(tmp_path) as case:
        case.add(71, "a", JobState.RUNNING)
        ready = recover_job(71, case.dependencies)
        assert ready is not None
        for pending in (
            (ready, ready),
            (replace(ready, mode=ExecutionMode.FRESH),),
            (replace(ready, record=replace(ready.record, recovery_count=0)),),
            (replace(ready, claim=ResourceClaim(71, "a", None)),),
        ):
            with pytest.raises(DefectError):
                Scheduler(case.dependencies, case.resources, recovered=pending)
        with pytest.raises(DefectError):
            Scheduler(cast(ExecutorDependencies, None), case.resources, recovered=())
        assert case.resources.pool.claims() == ()


def test_head_query_uses_isolated_short_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """调度只读查询同样使用短锁预算，且不会污染下一个普通连接的默认预算。"""
    from typing import cast

    from sqlalchemy import Connection

    monkeypatch.setattr(policy, "PROGRESS_LOCK_TIMEOUT_MS", 20)
    observed: list[int] = []

    def capture(*args: object) -> None:
        statement = args[2]
        if isinstance(statement, str) and "min(jobs.job_id)" in statement:
            observed.append(
                cast(Connection, args[0]).exec_driver_sql("PRAGMA busy_timeout").scalar_one()
            )

    with scheduling_case(tmp_path) as case:
        event.listen(case.dependencies.engine, "before_cursor_execute", capture)
        try:
            assert case.scheduler.claim_next() is None
        finally:
            event.remove(case.dependencies.engine, "before_cursor_execute", capture)
        assert observed == [20]
        with case.dependencies.engine.connect() as connection:
            assert connection.exec_driver_sql("PRAGMA busy_timeout").scalar_one() == 5000


def test_released_gpu_does_not_bypass_earlier_head_in_same_scan(tmp_path: Path) -> None:
    """同轮较早需卡队首已等待后，途中归还的卡不能给较晚类型；CPU类型仍可领取，下轮先给较早队首。"""
    from rdp.infra.config import JobsConfig
    from rdp.jobs.example import CountParameters, execute_count
    from rdp.jobs.registry import JobDefinition
    from rdp.jobs.scheduling import Scheduler, resolve_scheduling
    from rdp.jobs.scheduling_types import Admission, ResourceClaim
    from rdp.jobs.types import JobState, RecoveryMode, WaitReason

    class ReleaseAfterWait(ResourcePool):
        """保留真实名额分配，只在作业5被判为等卡之后精确归还占用卡。"""

        occupied: ResourceClaim | None = None

        def reserve(self, job_id: int, type_name: str) -> Admission:
            """归还发生在返回等卡结果之前，后续队首看到的卡已空闲，不依赖线程时序。"""
            admission = super().reserve(job_id, type_name)
            if job_id == 5 and admission.wait_reason is WaitReason.GPU:
                assert self.occupied is not None
                self.release(self.occupied)
                self.occupied = None
            return admission

    with scheduling_case(tmp_path, gpus=(0,), concurrency=2, needs_gpu=True) as case:
        registry = case.dependencies.registry
        registry.register(
            JobDefinition("cpu", "CPU作业", CountParameters, RecoveryMode.RESTART, execute_count)
        )
        settings = resolve_scheduling(JobsConfig(gpus=(0,)), registry)
        pool = ReleaseAfterWait(settings, available_gpus=(0,))
        pool.occupied = pool.reserve(1, "a").claim
        assert pool.occupied is not None
        resources = replace(
            case.resources,
            pool=pool,
            configuration=replace(
                case.resources.configuration,
                catalog=replace(case.resources.configuration.catalog, settings=settings),
            ),
        )
        scheduler = Scheduler(
            replace(case.dependencies, resources=resources), resources, recovered=()
        )
        case.add(5, "a")
        case.add(7, "b")
        case.add(9, "cpu")
        try:
            cpu = scheduler.claim_next()
            assert cpu is not None and cpu.record.job_id == 9 and cpu.record.gpu_index is None
            assert case.get(5).state is case.get(7).state is JobState.QUEUED
            assert case.get(5).wait_reason is WaitReason.GPU
            first = scheduler.claim_next()
            assert first is not None and first.record.job_id == 5 and first.record.gpu_index == 0
            assert first.claim is not None
            assert scheduler.claim_next() is None
            pool.release(first.claim)
            second = scheduler.claim_next()
            assert second is not None and second.record.job_id == 7 and second.record.gpu_index == 0
        finally:
            for claim in pool.claims():
                pool.release(claim)


@pytest.mark.parametrize("phase", ["open", "summary"])
def test_cancelled_recovery_log_failure_does_not_stop_claiming(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, phase: str
) -> None:
    """恢复候选取消终态提交后，打开或追加日志摘要失败只记一次带job_id的ERROR，继续领取其他作业。"""
    from typing import IO, TextIO, cast

    from jobs_storage_support import NOW

    from rdp.jobs.execution import recover_job
    from rdp.jobs.records import StateChange, transition_job
    from rdp.jobs.scheduling import Scheduler
    from rdp.jobs.types import JobState

    with scheduling_case(tmp_path) as case:
        case.add(71, "a", JobState.RUNNING)
        prepared = recover_job(71, case.dependencies)
        assert prepared is not None and prepared.record.log_path is not None
        target = case.dependencies.paths.root / prepared.record.log_path
        scheduler = Scheduler(case.dependencies, case.resources, recovered=(prepared,))
        case.add(72, "b")
        with session_scope(case.dependencies.engine) as session:
            transition_job(session, 71, StateChange(JobState.RUNNING, JobState.CANCELLING, NOW))
        opened: list[TextIO] = []
        original = Path.open

        def fail_open(path: Path, mode: str = "r", *, encoding: str | None = None) -> IO[str]:
            if path == target and mode == "a":
                if phase == "open":
                    raise OSError("模拟打开日志失败")
                stream = original(path, mode, encoding=encoding)
                opened.append(stream)
                return cast(TextIO, _SummaryFailure(stream))
            return original(path, mode, encoding=encoding)

        try:
            with monkeypatch.context() as patch:
                patch.setattr(Path, "open", fail_open)
                next_job = scheduler.claim_next()
                assert next_job is not None and next_job.record.job_id == 72
                assert scheduler.claim_next() is None
            cancelled = case.get(71)
            assert cancelled.state is JobState.CANCELLED and cancelled.summary is not None
            assert cancelled.wait_reason is None and not cancelled.holds_navigation_lock
            errors = [item for item in caplog.records if item.levelname == "ERROR"]
            assert len(errors) == 1 and "job_id=71" in errors[0].getMessage()
            assert all(stream.closed for stream in opened)
        finally:
            for stream in opened:
                stream.close()
            for claim in case.resources.pool.claims():
                case.resources.pool.release(claim)


class _SummaryFailure:
    """只在文件流写摘要时模拟磁盘故障，实际句柄仍需关闭。"""

    def __init__(self, stream: TextIO) -> None:
        """保存真实临时日志流。"""
        self.stream = stream

    def write(self, text: str) -> int:
        """正常内容可追加，只拒绝终态摘要。"""
        if "作业结尾 summary=" in text:
            raise OSError("模拟摘要写入失败")
        return self.stream.write(text)

    def flush(self) -> None:
        """刷新真实流，避免隐藏其他写入。"""
        self.stream.flush()

    def close(self) -> None:
        """关闭实际句柄供测试核对资源回收。"""
        self.stream.close()


def test_stop_after_committed_claim_returns_fresh_job_to_queue(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """领取提交后、线程启动前停止：interrupt作业退回排队、清领取字段，不写日志/审计，下一实例只执行一次。"""
    command = tmp_path / "fake-nvidia-smi"
    command.write_text("#!/bin/sh\nprintf '0\\n'\n", encoding="utf-8")
    command.chmod(0o700)
    executed: list[int] = []
    stop = Event()
    claimed: list[ExecutionWork] = []
    original = Scheduler.claim_next

    def stop_after_claim(scheduler: Scheduler) -> ExecutionWork | None:
        work = original(scheduler)
        if work is not None:
            claimed.append(work)
            stop.set()
        return work

    monkeypatch.setattr(policy, "WORKER_POLL_INTERVAL_S", 0.005)
    with gpu_case(
        tmp_path / "state",
        command,
        gpus=(0,),
        execute=lambda context: executed.append(context.job_id),
    ) as case:
        case.add(71)
        with monkeypatch.context() as patch:
            patch.setattr(Scheduler, "claim_next", stop_after_claim)
            result = run_loop(
                case.dependencies,
                stop,
                WorkerHeartbeat("00000000000040008000000000000001", 123, NOW, NOW),
            )
        assert result.code == 0 and not result.unreaped_threads and executed == []
        assert len(claimed) == 1 and claimed[0].record.gpu_index == 0
        queued = case.get(71)
        assert queued.state is JobState.QUEUED
        assert (
            queued.gpu_index is queued.wait_reason is queued.started_at is queued.log_path is None
        )
        assert not queued.holds_navigation_lock and queued.recovery_count == 0
        assert case.resources.pool.claims() == ()
        assert claimed[0].record.log_path is not None
        assert not (case.dependencies.paths.root / claimed[0].record.log_path).exists()
        with session_scope(case.dependencies.engine, read_only=True) as session:
            assert session.scalar(select(func.count()).select_from(OperationLogRow)) == 0
        resources = replace(
            case.resources,
            pool=ResourcePool(case.resources.configuration.catalog.settings, available_gpus=(0,)),
            navigation=NavigationWriter(),
        )
        with running_loop(replace(case.dependencies, resources=resources)):
            wait_for(lambda: case.get(71).state is JobState.COMPLETED)
        assert executed == [71] and case.get(71).recovery_count == 0
        assert resources.pool.claims() == ()


@pytest.mark.parametrize("stage", ["update", "begin"])
def test_unstarted_return_failure_fails_worker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, stage: str
) -> None:
    """未启动领取的短事务退回失败必须导致实例失败，不能把残留running当作正常停止；未使用名额仍归还。"""
    holder: AbstractContextManager[Session] | None = None
    monkeypatch.setattr(policy, "PROGRESS_LOCK_TIMEOUT_MS", 10)
    stop = Event()
    original = Scheduler.claim_next
    executed: list[int] = []

    def stop_after_claim(scheduler: Scheduler) -> ExecutionWork | None:
        nonlocal holder
        work = original(scheduler)
        if work is not None:
            stop.set()
            if stage == "begin":
                holder = session_scope(case.dependencies.engine)
                holder.__enter__()
        return work

    def fail_return(*args: object) -> None:
        if (
            stage == "update"
            and stop.is_set()
            and isinstance(args[2], str)
            and args[2].startswith("UPDATE jobs")
        ):
            raise OSError("模拟退回事务失败")

    with scheduling_case(tmp_path, execute=lambda context: executed.append(context.job_id)) as case:
        case.add(71, "a")
        event.listen(case.dependencies.engine, "before_cursor_execute", fail_return)
        try:
            monkeypatch.setattr(Scheduler, "claim_next", stop_after_claim)
            result = run_loop(
                case.dependencies,
                stop,
                WorkerHeartbeat("00000000000040008000000000000001", 123, NOW, NOW),
            )
        finally:
            try:
                if holder is not None:
                    holder.__exit__(None, None, None)
            finally:
                event.remove(case.dependencies.engine, "before_cursor_execute", fail_return)
        assert result.code == 1 and not result.unreaped_threads and executed == []
        assert case.get(71).state is JobState.RUNNING
        assert case.resources.pool.claims() == ()
        assert "未启动领取退回失败 job_id=71" in caplog.text


def test_unstarted_return_preserves_cancel_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """领取后停止前收到取消时完成取消而非重新排队；新领取字段清空且恢复次数不变。"""
    from jobs_storage_support import NOW

    from rdp.jobs.execution import ExecutionWork
    from rdp.jobs.records import StateChange, transition_job
    from rdp.jobs.scheduling import Scheduler
    from rdp.jobs.types import JobState, WorkerHeartbeat
    from rdp.jobs.worker import run_loop

    stop = Event()
    original = Scheduler.claim_next

    with scheduling_case(tmp_path) as case:
        case.add(71, "a")

        def cancel_after_claim(scheduler: Scheduler) -> ExecutionWork | None:
            work = original(scheduler)
            if work is not None:
                with session_scope(case.dependencies.engine) as session:
                    transition_job(
                        session, 71, StateChange(JobState.RUNNING, JobState.CANCELLING, NOW)
                    )
                stop.set()
            return work

        monkeypatch.setattr(Scheduler, "claim_next", cancel_after_claim)
        result = run_loop(
            case.dependencies,
            stop,
            WorkerHeartbeat("00000000000040008000000000000001", 123, NOW, NOW),
        )
        assert result.code == 0 and case.resources.pool.claims() == ()
        record = case.get(71)
        assert record.state is JobState.CANCELLED and record.summary is not None
        assert (
            record.started_at is record.log_path is record.gpu_index is record.wait_reason is None
        )
        assert record.recovery_count == 0 and not record.holds_navigation_lock


@pytest.mark.parametrize("mode", ["resume", "restart"])
@pytest.mark.parametrize("cancel_requested", [False, True], ids=["no-cancel", "cancel"])
def test_unstarted_recovery_preserves_previous_execution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str, cancel_requested: bool
) -> None:
    """续跑/重跑已有历史，未启动本次线程只能清新领资源，不能当作新作业退回排队或抹去恢复资格。"""
    from jobs_storage_support import NOW

    from rdp.jobs.execution import ExecutionWork
    from rdp.jobs.records import StateChange, transition_job
    from rdp.jobs.registry import JobRegistry
    from rdp.jobs.scheduling import Scheduler
    from rdp.jobs.types import JobState, RecoveryMode, WorkerHeartbeat
    from rdp.jobs.worker import run_loop

    stop = Event()
    claimed: list[ExecutionWork] = []
    original = Scheduler.claim_next

    def stop_after_claim(scheduler: Scheduler) -> ExecutionWork | None:
        work = original(scheduler)
        if work is not None:
            claimed.append(work)
            if cancel_requested:
                with session_scope(case.dependencies.engine) as session:
                    transition_job(
                        session,
                        work.record.job_id,
                        StateChange(JobState.RUNNING, JobState.CANCELLING, NOW),
                    )
            stop.set()
        return work

    with scheduling_case(tmp_path, gpus=(0,), needs_gpu=True) as case:
        case.add(71, "a", JobState.RUNNING)
        registry = JobRegistry()
        for definition in case.dependencies.registry.definitions():
            registry.register(replace(definition, recovery_mode=RecoveryMode(mode)))
        dependencies = replace(case.dependencies, registry=registry)
        monkeypatch.setattr(Scheduler, "claim_next", stop_after_claim)
        result = run_loop(
            dependencies, stop, WorkerHeartbeat("00000000000040008000000000000001", 123, NOW, NOW)
        )
        assert result.code == 0 and len(claimed) == 1
        previous = claimed[0].record
        assert claimed[0].mode.value == mode and previous.gpu_index == 0
        record = case.get(71)
        assert (
            record.state is (JobState.CANCELLING if cancel_requested else JobState.RUNNING)
            and record.recovery_count == previous.recovery_count == 1
        )
        assert (record.started_at, record.log_path, record.progress, record.elapsed_s) == (
            previous.started_at,
            previous.log_path,
            previous.progress,
            previous.elapsed_s,
        )
        assert record.gpu_index is record.wait_reason is None and not record.holds_navigation_lock
        assert case.resources.pool.claims() == ()


def test_start_error_after_thread_launch_does_not_requeue(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """start在实际启动后抛错不能冒充未启动领取；保留running与存活线程，供正常停止预算及保锁处理。"""
    from jobs_storage_support import NOW

    from rdp.jobs import _loop
    from rdp.jobs.types import JobState, WorkerHeartbeat
    from rdp.jobs.worker import WorkerLoopResult, run_loop

    entered, release = Event(), Event()
    results: list[WorkerLoopResult] = []

    def execute(_context: ExecutionContext) -> None:
        entered.set()
        assert release.wait(2)

    class StartedThenFailed(Thread):
        """模拟线程已启动，但start调用随后被错误打断。"""

        def start(self) -> None:
            """让真实执行函数进入后再报告启动调用失败，不伪造线程标志。"""
            super().start()
            assert entered.wait(1)
            raise OSError("模拟启动后的调用失败")

    monkeypatch.setattr(_loop, "Thread", StartedThenFailed)
    monkeypatch.setattr(policy, "WORKER_STOP_TIMEOUT_S", 0.05)
    with scheduling_case(tmp_path, execute=execute) as case:
        case.add(71, "a")
        try:
            results.append(
                run_loop(
                    case.dependencies,
                    Event(),
                    WorkerHeartbeat("00000000000040008000000000000001", 123, NOW, NOW),
                )
            )
            result = results[0]
            assert result.code == 1 and len(result.unreaped_threads) == 1
            assert result.unreaped_threads[0].is_alive()
            record = case.get(71)
            assert record.state is JobState.RUNNING and record.started_at is not None
            assert case.resources.pool.claims()
        finally:
            release.set()
            for result in results:
                for thread in result.unreaped_threads:
                    thread.join(timeout=1)
                    assert not thread.is_alive()
        assert case.resources.pool.claims() == ()
