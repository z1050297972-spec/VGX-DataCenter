"""M0/08 公共契约测试；数据库与文件只使用临时目录，不依赖真实数据或默认状态目录。"""

import os
import signal
import sys
import time
from contextlib import suppress
from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from threading import Event, Thread
from typing import cast

import pytest
from db_support import sqlite_connection
from jobs_execution_support import execution_case
from jobs_loop_support import running_loop, wait_for
from jobs_process_resources import BlockedTool
from jobs_progress_support import MutableClock, saved_record
from jobs_scheduling_support import (
    claim_fixture,
    fresh_dependencies,
    resources_fixture,
    scheduling_fixture,
)
from jobs_storage_support import NOW, PROGRESS, job_row
from sqlalchemy import select

from rdp.infra.config import PlatformConfig
from rdp.infra.db.connection import create_database_engine, session_scope
from rdp.infra.db.migration import migrate
from rdp.infra.db.records import find_error
from rdp.infra.diagnostics import DefectError, ExternalError
from rdp.infra.logging import LoggingSettings, job_id_context, log_context, request_id_context
from rdp.infra.state import initialize_state, state_paths
from rdp.jobs import policy, processes
from rdp.jobs.errors import JobCancelledError
from rdp.jobs.execution import ExecutionContext, ExecutorDependencies, execute_job, recover_job
from rdp.jobs.logs import JobLog
from rdp.jobs.models import JobRow, WorkerHeartbeatRow
from rdp.jobs.processes import ToolCommand
from rdp.jobs.records import StateChange, save_progress, transition_job
from rdp.jobs.registry import JobRegistry, production_registry
from rdp.jobs.types import (
    ExecutionSnapshot,
    JobClock,
    JobProgress,
    JobState,
    RecoveryMode,
    WorkerHeartbeat,
)
from rdp.jobs.worker import WorkerLoopResult, heartbeat_online, run_loop, worker_lock
from rdp.ops.worker import run_worker


def test_serial_execution(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """J2：同时仅一个作业线程，仅按job_id领取，墙钟回拨不改顺序；长作业期间主循环仍查取消和写心跳。"""
    monkeypatch.setattr(policy, "WORKER_POLL_INTERVAL_S", 0.01)
    monkeypatch.setattr(policy, "HEARTBEAT_INTERVAL_S", 0.03)
    order: list[int] = []
    heartbeats: list[datetime] = []

    def execute(context: ExecutionContext) -> None:
        order.append(context.job_id)
        context.reporter.wait(0.08)
        with session_scope(dependencies.engine, read_only=True) as session:
            heartbeat = session.get(WorkerHeartbeatRow, 1)
            assert heartbeat is not None
            heartbeats.append(heartbeat.last_seen_at)
        if context.job_id == 72:
            stop.set()

    with execution_case(tmp_path, {"steps": 3, "interval_ms": 0}, execute) as (_, dependencies, _):
        # 初始遗留interrupt先收尾，新队列顺序不受墙钟回拨影响。
        with session_scope(dependencies.engine) as session:
            for job_id in (72, 73):
                row = job_row(JobState.QUEUED, job_id=job_id)
                row.submitted_at = NOW + timedelta(days=73 - job_id)
                session.add(row)
        stop = Event()
        dependencies = replace(
            dependencies, clock=JobClock(lambda: datetime.now(UTC), time.monotonic)
        )
        result = run_loop(
            fresh_dependencies(dependencies),
            stop,
            WorkerHeartbeat("00000000000040008000000000000001", 123, NOW, NOW),
        )
        assert result.code == 0 and result.unreaped_threads == ()
        assert order == [72] and heartbeats[0] > NOW
        with session_scope(dependencies.engine, read_only=True) as session:
            queued = session.get(JobRow, 73)
            assert queued is not None and queued.state == "queued"


def test_recovery_priority(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """验收3：遗留running的续跑/重跑先于新queued，不重写开始时间、不新增running→queued边。"""
    monkeypatch.setattr(policy, "WORKER_POLL_INTERVAL_S", 0.01)
    order: list[tuple[int, str]] = []

    def execute(context: ExecutionContext) -> None:
        order.append((context.job_id, context.mode.value))
        if context.job_id == 72:
            stop.set()

    with execution_case(
        tmp_path, {"steps": 3, "interval_ms": 0}, execute, mode=RecoveryMode.RESUME
    ) as (work, dependencies, _):
        with session_scope(dependencies.engine) as session:
            session.add(job_row(JobState.QUEUED, job_id=72))
        stop = Event()
        result = run_loop(
            fresh_dependencies(dependencies),
            stop,
            WorkerHeartbeat("00000000000040008000000000000001", 123, NOW, NOW),
        )
        assert result.code == 0 and order == [(71, "resume"), (72, "fresh")]
        assert saved_record(dependencies.engine).started_at == work.record.started_at


def test_resume_context(tmp_path: Path) -> None:
    """验收3：续跑上下文mode=resume和previous_progress等于旧快照，保留累计计数与原日志。"""
    observed: list[ExecutionContext] = []
    with execution_case(
        tmp_path, {"steps": 4, "interval_ms": 0}, observed.append, mode=RecoveryMode.RESUME
    ) as (work, dependencies, signals):
        previous = JobProgress.model_validate(PROGRESS)
        with session_scope(dependencies.engine) as session:
            save_progress(session, 71, ExecutionSnapshot(previous, (), ("产物",), -2, 4.5), now=NOW)
        recovered = recover_job(71, dependencies)
        assert recovered is not None and recovered.previous_progress == previous
        dependencies = fresh_dependencies(dependencies)
        recovered = replace(recovered, claim=claim_fixture(recovered.record, dependencies))
        record = execute_job(recovered, dependencies, signals)
        assert len(observed) == 1 and observed[0].mode.value == "resume"
        assert observed[0].previous_progress == previous
        assert record is not None and record.progress == previous
        assert record.elapsed_s >= 4.5 and record.artifacts == ("产物",)
        assert (
            record.log_path == work.record.log_path and record.started_at == work.record.started_at
        )


def test_restart_context(tmp_path: Path) -> None:
    """验收3：重跑mode=restart和previous_progress仍为旧快照，但本次累计计数/诊断清零，耗时片段保留。"""
    initial: list[ExecutionSnapshot] = []
    previous_values: list[JobProgress | None] = []

    def observe(context: ExecutionContext) -> None:
        assert context.mode.value == "restart"
        initial.append(context.reporter.snapshot())
        previous_values.append(context.previous_progress)

    with execution_case(
        tmp_path, {"steps": 4, "interval_ms": 0}, observe, mode=RecoveryMode.RESTART
    ) as (work, dependencies, signals):
        previous = JobProgress.model_validate(PROGRESS)
        with session_scope(dependencies.engine) as session:
            save_progress(session, 71, ExecutionSnapshot(previous, (), ("产物",), -2, 4.5), now=NOW)
        recovered = recover_job(71, dependencies)
        assert recovered is not None and recovered.previous_progress == previous
        dependencies = fresh_dependencies(dependencies)
        recovered = replace(recovered, claim=claim_fixture(recovered.record, dependencies))
        record = execute_job(recovered, dependencies, signals)
        assert previous_values == [previous] and initial[0].progress is None
        assert initial[0].diagnostics == () and initial[0].tool_exit_code is None
        assert initial[0].elapsed_s >= 4.5 and initial[0].artifacts == ("产物",)
        assert (
            record is not None
            and record.started_at == work.record.started_at
            and record.log_path == work.record.log_path
        )


def test_recover_cancelling(tmp_path: Path) -> None:
    """验收3/4：旧cancelling先写中断段再cancelled，无结果，保留进度计数，不再执行函数。"""
    with execution_case(tmp_path, {"steps": 4, "interval_ms": 0}) as (_, dependencies, _):
        previous = JobProgress.model_validate(PROGRESS)
        with session_scope(dependencies.engine) as session:
            save_progress(session, 71, ExecutionSnapshot(previous, (), (), None, 4.5), now=NOW)
            transition_job(session, 71, StateChange(JobState.RUNNING, JobState.CANCELLING, NOW))
        assert recover_job(71, dependencies) is None
        record = saved_record(dependencies.engine)
        assert record.state is JobState.CANCELLED and record.progress == previous
        assert record.summary is not None and record.summary.outcome is None
        assert record.log_path is not None
        content = (dependencies.paths.root / record.log_path).read_text()
        assert content.index("中断") < content.index("作业结尾") and '"mode": "cancel"' in content


def test_heartbeat_interval(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """验收8：启动立即心跳、其后每5单调秒一次，单行带实例uuid/pid/启动与最后UTC时刻。"""
    monkeypatch.setattr(policy, "WORKER_POLL_INTERVAL_S", 0.005)
    clock = MutableClock()
    with execution_case(tmp_path, {"steps": 3, "interval_ms": 0}) as (_, dependencies, _):
        dependencies = replace(dependencies, clock=JobClock(clock.now, clock.monotonic))

        def seen() -> datetime | None:
            with session_scope(dependencies.engine, read_only=True) as session:
                heartbeat = session.get(WorkerHeartbeatRow, 1)
                return None if heartbeat is None else heartbeat.last_seen_at

        with running_loop(dependencies):
            wait_for(lambda: seen() == NOW)
            clock.seconds = 104.999
            clock.wall = NOW + timedelta(seconds=4)
            Event().wait(0.03)
            assert seen() == NOW
            clock.seconds = 105
            clock.wall = NOW + timedelta(seconds=5)
            wait_for(lambda: seen() == NOW + timedelta(seconds=5))
            with session_scope(dependencies.engine, read_only=True) as session:
                rows = session.scalars(select(WorkerHeartbeatRow)).all()
                assert len(rows) == 1
                assert (rows[0].pid, rows[0].instance_id, rows[0].started_at) == (
                    123,
                    "00000000000040008000000000000001",
                    NOW,
                )


def test_heartbeat_busy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """验收8：心跳BEGIN短锁忙记WARNING说明后果，下个5秒周期再试，worker不退出。"""
    monkeypatch.setattr(policy, "WORKER_POLL_INTERVAL_S", 0.005)
    clock = MutableClock()
    with execution_case(tmp_path, {"steps": 3, "interval_ms": 0}) as (_, dependencies, _):
        with session_scope(dependencies.engine) as session:
            transition_job(session, 71, StateChange(JobState.RUNNING, JobState.INTERRUPTED, NOW))
        dependencies = replace(dependencies, clock=JobClock(clock.now, clock.monotonic))
        with running_loop(dependencies) as (_, thread, _):
            wait_for(lambda: _heartbeat_seen(dependencies) == NOW)
            with session_scope(dependencies.engine):
                clock.seconds = 105
                clock.wall = NOW + timedelta(seconds=5)
                wait_for(lambda: any("心跳写锁忙" in item.getMessage() for item in caplog.records))
                assert thread.is_alive() and _heartbeat_seen(dependencies) == NOW
            clock.seconds = 110
            wait_for(lambda: _heartbeat_seen(dependencies) == NOW + timedelta(seconds=5))


def test_heartbeat_threshold() -> None:
    """验收8：15秒恰好在线、超过离线、空心跳离线；未来心跳按经过0秒在线。"""
    seen = datetime(2026, 10, 26, 12, tzinfo=UTC)
    heartbeat = WorkerHeartbeat("00000000000040008000000000000001", 123, seen, seen)
    assert heartbeat_online(None, now=seen) is False
    assert heartbeat_online(heartbeat, now=seen + timedelta(seconds=15)) is True
    assert heartbeat_online(heartbeat, now=seen + timedelta(seconds=15, microseconds=1)) is False
    assert heartbeat_online(heartbeat, now=seen - timedelta(days=1)) is True
    local = (seen + timedelta(seconds=15)).astimezone(timezone(timedelta(hours=-6)))
    assert heartbeat_online(heartbeat, now=local) is True
    assert heartbeat.last_seen_at == seen


def test_heartbeat_invalid(tmp_path: Path) -> None:
    """心跳契约：非法aware时刻、pid、实例标识归DefectError，查询I/O失败不伪装离线。"""
    import sqlite3

    from accounts_support import AUDIT_CONTEXT, scenario
    from accounts_support import NOW as ACCOUNT_NOW
    from sqlalchemy import Connection, event

    from rdp.infra.diagnostics import ExternalError
    from rdp.jobs.service import JobRequest, JobService

    with scenario(tmp_path) as (accounts, administrator):
        service = JobService(accounts.engine, production_registry())
        request = JobRequest(administrator.identity, ACCOUNT_NOW, AUDIT_CONTEXT)

        def fail(
            _connection: Connection,
            _cursor: object,
            statement: str,
            _parameters: object,
            _context: object,
            _many: bool,
        ) -> None:
            if "FROM worker_heartbeat" in statement:
                error = sqlite3.OperationalError("测试心跳I/O")
                error.sqlite_errorcode = sqlite3.SQLITE_IOERR
                raise error

        event.listen(accounts.engine, "before_cursor_execute", fail)
        try:
            with pytest.raises(ExternalError):
                service.heartbeat(request)
        finally:
            event.remove(accounts.engine, "before_cursor_execute", fail)
    heartbeat = WorkerHeartbeat("00000000000040008000000000000001", 123, NOW, NOW)
    for broken in (
        replace(heartbeat, pid=0),
        replace(heartbeat, instance_id="bad"),
        replace(heartbeat, last_seen_at=NOW.replace(tzinfo=None)),
    ):
        with pytest.raises(DefectError):
            heartbeat_online(broken, now=NOW)


def test_stop_in_process(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """停止契约：注入Event在当前进程停止，所有合规线程30秒内回收，不等作业跑完、running留给下次恢复。"""
    monkeypatch.setattr(policy, "WORKER_POLL_INTERVAL_S", 0.01)
    entered = Event()

    def execute(context: ExecutionContext) -> None:
        entered.set()
        context.reporter.wait(60)

    with execution_case(
        tmp_path, {"steps": 3, "interval_ms": 0}, execute, mode=RecoveryMode.RESUME
    ) as (_, dependencies, _):
        stop = Event()
        results: list[WorkerLoopResult] = []
        thread = Thread(
            target=lambda: results.append(
                run_loop(
                    fresh_dependencies(dependencies),
                    stop,
                    WorkerHeartbeat("00000000000040008000000000000001", 123, NOW, NOW),
                )
            ),
            daemon=True,
        )
        try:
            thread.start()
            assert entered.wait(2)
            stop.set()
            thread.join(timeout=2)
            assert not thread.is_alive() and results[0].code == 0
            assert results[0].unreaped_threads == ()
            assert saved_record(dependencies.engine).state is JobState.RUNNING
        finally:
            stop.set()
            thread.join(timeout=3)


def test_lock_error_codes(tmp_path: Path) -> None:
    """验收2：锁忙返回具名非零码及含锁路径的说明；权限故障为另一失败码，不删除锁inode。"""
    paths = state_paths(PlatformConfig(state_dir=tmp_path), ("示例：数数",))
    initialize_state(paths)
    migrate(paths, now=NOW)
    engine = create_database_engine(paths.database)
    dependencies = ExecutorDependencies(
        engine,
        production_registry(),
        paths,
        JobClock(lambda: NOW, time.monotonic),
        resources=resources_fixture(production_registry()),
    )
    settings = LoggingSettings("worker", paths.logs)
    first = worker_lock(paths)
    try:
        result = run_worker(
            dependencies, Event(), settings, scheduling=scheduling_fixture(dependencies.registry)
        )
        assert result.code == 2 and not result.lock_retained
        assert (
            "另一个 worker 正在运行" in result.message and str(paths.worker_lock) in result.message
        )
        assert "另一个 worker 正在运行" in (paths.logs / "worker.log").read_text()
    finally:
        first.finish(())
    try:
        stop = Event()
        stop.set()
        result = run_worker(
            dependencies, stop, settings, scheduling=scheduling_fixture(dependencies.registry)
        )
        assert result.code == 0 and not result.lock_retained
        paths.worker_lock.unlink()
        paths.worker_lock.mkdir()
        result = run_worker(
            dependencies, Event(), settings, scheduling=scheduling_fixture(dependencies.registry)
        )
        assert result.code == 1
    finally:
        engine.dispose()


def test_context_logging(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """规范6.4：执行线程copy_context绑定job_id，输出与异常运行日志关联正确，退出恢复不串到下一作业。"""
    monkeypatch.setattr(policy, "WORKER_POLL_INTERVAL_S", 0.005)
    observed: list[tuple[str, int | None, str | None]] = []
    original = JobLog.write_line

    def record_line(log: JobLog, text: str, *, now: datetime) -> None:
        if "stdout " in text:
            observed.append(("output", job_id_context.get(), request_id_context.get()))
        original(log, text, now=now)

    monkeypatch.setattr(JobLog, "write_line", record_line)

    def execute(context: ExecutionContext) -> None:
        observed.append(("execute", job_id_context.get(), request_id_context.get()))
        context.run_process(
            ToolCommand("关联", (sys.executable, "-c", "print('ready')"), tmp_path, 2)
        )
        stop.set()

    with execution_case(
        tmp_path, {"steps": 3, "interval_ms": 0}, execute, mode=RecoveryMode.RESUME
    ) as (_, dependencies, _):
        stop = Event()
        with log_context(job_id=99, request_id="00000000000040008000000000000001"):
            result = run_loop(
                fresh_dependencies(dependencies),
                stop,
                WorkerHeartbeat("00000000000040008000000000000001", 123, NOW, NOW),
            )
            assert job_id_context.get() == 99
        assert result.code == 0
        assert observed == [
            ("execute", 71, "00000000000040008000000000000001"),
            ("output", 71, "00000000000040008000000000000001"),
        ]
        assert job_id_context.get() is None and request_id_context.get() is None


def test_final_failure_halts_claiming(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """恢复安全：终态写失败后停止领取及心跳，30秒内失败返回；遗留daemon线程则保留锁至进程退出，下实例恢复。"""
    monkeypatch.setattr(policy, "WORKER_POLL_INTERVAL_S", 0.005)

    def execute(_: ExecutionContext) -> None:
        return

    with execution_case(
        tmp_path, {"steps": 3, "interval_ms": 0}, execute, mode=RecoveryMode.RESUME
    ) as (work, dependencies, _):
        with session_scope(dependencies.engine) as session:
            session.add(job_row(JobState.QUEUED, job_id=72))
        with dependencies.engine.begin() as connection:
            connection.exec_driver_sql(
                "CREATE TRIGGER reject_terminal BEFORE UPDATE OF state ON jobs WHEN NEW.state='completed' BEGIN SELECT RAISE(ABORT, 'test'); END"
            )
        with running_loop(dependencies) as (_, thread, results):
            thread.join(timeout=2)
            assert (
                not thread.is_alive() and results[0].code == 1 and not results[0].unreaped_threads
            )
        assert saved_record(dependencies.engine).state is JobState.RUNNING
        with session_scope(dependencies.engine, read_only=True) as session:
            queued = session.get(JobRow, 72)
            assert queued is not None and queued.state == "queued"
        assert work.record.log_path is not None
        assert "summary=" not in (dependencies.paths.root / work.record.log_path).read_text()
        errors = [item for item in caplog.records if item.levelname == "ERROR"]
        assert len(errors) == 1 and "终态持久化失败" in errors[0].getMessage()


def test_external_group_and_failure_diagnostics(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """规范6.9/6.11：真实工具派生后代也随组终止；非零/信号/超时诊断含命令、stderr尾、对象、实际、后果和失败结果。"""
    import os
    import signal

    from jobs_process_resources import adopt_orphans, reap_known

    from rdp.jobs import processes

    monkeypatch.setattr(processes, "PROCESS_TERM_GRACE_S", 0.05)
    child_file = tmp_path / "child.pid"
    leader_file = tmp_path / "leader.pid"
    child_code = f"import os,signal,time; from pathlib import Path; signal.signal(signal.SIGTERM,signal.SIG_IGN); Path({str(child_file)!r}).write_text(str(os.getpid())); print('child-ready',flush=True); time.sleep(60)"
    parent_code = f"import os,signal,time,subprocess,sys; from pathlib import Path; signal.signal(signal.SIGTERM,signal.SIG_IGN); Path({str(leader_file)!r}).write_text(str(os.getpid())); subprocess.Popen([sys.executable,'-u','-c',{child_code!r}]); print('failure-tail',file=sys.stderr,flush=True); time.sleep(60)"

    def execute(context: ExecutionContext) -> None:
        context.run_process(
            ToolCommand("后代工具", (sys.executable, "-u", "-c", parent_code), tmp_path, 0.3)
        )

    with adopt_orphans():
        try:
            with execution_case(tmp_path, {"steps": 3, "interval_ms": 0}, execute) as (
                work,
                dependencies,
                signals,
            ):
                result = execute_job(work, dependencies, signals)
                assert (
                    result is not None
                    and result.summary is not None
                    and result.summary.outcome == "failed"
                )
                assert result.tool_exit_code == -signal.SIGKILL and child_file.exists()
                diagnostic = result.diagnostics[0].samples[0]
                objects = {item.key: item.value for item in diagnostic.objects}
                assert objects["job_id"] == "71" and objects["returncode"] == "-9"
                assert (
                    "failure-tail" in objects["stderr_tail"]
                    and sys.executable in objects["command"]
                )
                assert diagnostic.actual and diagnostic.consequence and diagnostic.next_step
                assert (
                    result.log_path is not None
                    and "child-ready" in (dependencies.paths.root / result.log_path).read_text()
                )
                reap_known(int(child_file.read_text()))
                assert not any(thread.is_alive() for thread in signals.monitor.threads)
        finally:
            try:
                if leader_file.exists():
                    with suppress(ProcessLookupError):
                        os.killpg(int(leader_file.read_text()), signal.SIGKILL)
            finally:
                if child_file.exists():
                    reap_known(int(child_file.read_text()), kill=True)


def test_external_readers_and_deadlines(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """进程资源：直接子进程退出但后代持管道不无限等EOF，正常路径有界wait/join；SIGKILL后仍收不回抛ExternalError，存活输出线程以daemon登记遗留。"""
    from jobs_process_resources import adopt_orphans, reap_known

    from rdp.jobs import processes

    monkeypatch.setattr(processes, "OUTPUT_JOIN_TIMEOUT_S", 0.05)
    monkeypatch.setattr(processes, "PROCESS_TERM_GRACE_S", 0.05)
    child_file = tmp_path / "held-pipe.pid"
    child_code = f"import os,signal,time; from pathlib import Path; signal.signal(signal.SIGTERM,signal.SIG_IGN); Path({str(child_file)!r}).write_text(str(os.getpid())); print('held-ready',flush=True); time.sleep(60)"
    parent_code = f"import subprocess,sys,time; subprocess.Popen([sys.executable,'-u','-c',{child_code!r}]); time.sleep(0.1)"

    def execute(context: ExecutionContext) -> None:
        context.run_process(
            ToolCommand("后代持管道", (sys.executable, "-u", "-c", parent_code), tmp_path, 2)
        )

    with adopt_orphans():
        try:
            with execution_case(tmp_path, {"steps": 3, "interval_ms": 0}, execute) as (
                work,
                dependencies,
                signals,
            ):
                started = time.monotonic()
                result = execute_job(work, dependencies, signals)
                assert time.monotonic() - started < 1
                assert result is not None and result.tool_exit_code == 0
                assert not any(thread.is_alive() for thread in signals.monitor.threads)
                assert child_file.exists()
                reap_known(int(child_file.read_text()))
        finally:
            if child_file.exists():
                reap_known(int(child_file.read_text()), kill=True)


@pytest.mark.parametrize(
    ("historical", "current", "expected"),
    [
        ("resume", "resume", "resume"),
        ("resume", "restart", "restart"),
        ("restart", "resume", "resume"),
        ("restart", "restart", "restart"),
        ("interrupt", "resume", "interrupt"),
        ("interrupt", "restart", "interrupt"),
        ("resume", "interrupt", "interrupt"),
        ("restart", "interrupt", "interrupt"),
        ("interrupt", "interrupt", "interrupt"),
        ("resume", None, "interrupt"),
        ("restart", None, "interrupt"),
        ("interrupt", None, "interrupt"),
    ],
)
def test_recovery_mode_snapshot(
    historical: str, current: str | None, expected: str, tmp_path: Path
) -> None:
    """恢复契约：执行方式取当前登记；历史/当前任一interrupt或类型已删均标中断，resume与restart互改使用当前值。"""
    with execution_case(
        tmp_path, {"steps": 3, "interval_ms": 0}, mode=RecoveryMode(historical)
    ) as (work, dependencies, _):
        registry = JobRegistry()
        definition = dependencies.registry.lookup("example_count")
        assert definition is not None
        if current is not None:
            registry.register(replace(definition, recovery_mode=RecoveryMode(current)))
        dependencies = replace(dependencies, registry=registry)
        recovered = recover_job(71, dependencies)
        record = saved_record(dependencies.engine)
        assert (record.started_at, record.log_path) == (
            work.record.started_at,
            work.record.log_path,
        )
        if expected == "interrupt":
            assert recovered is None and record.state is JobState.INTERRUPTED
            assert record.summary is not None and record.summary.outcome is None
        else:
            assert recovered is not None and recovered.mode.value == expected
            assert record.state is JobState.RUNNING and record.recovery_count == 1
        assert record.log_path is not None
        content = (dependencies.paths.root / record.log_path).read_text()
        assert content.index("作业开头") < content.index("中断")
        assert f'"mode": "{expected}"' in content


def test_recovery_heartbeat_not_blocked(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """J2/验收8：恢复作业也在线程执行，长续跑期间仍每秒查取消、每5秒写心跳。"""
    monkeypatch.setattr(policy, "WORKER_POLL_INTERVAL_S", 0.005)
    monkeypatch.setattr(policy, "HEARTBEAT_INTERVAL_S", 0.02)
    seen: list[datetime | None] = []

    def execute(context: ExecutionContext) -> None:
        assert context.mode.value == "resume"
        seen.append(_heartbeat_seen(dependencies))
        context.reporter.wait(0.08)
        seen.append(_heartbeat_seen(dependencies))
        stop.set()

    with execution_case(
        tmp_path, {"steps": 3, "interval_ms": 0}, execute, mode=RecoveryMode.RESUME
    ) as (_, dependencies, _):
        dependencies = replace(
            dependencies, clock=JobClock(lambda: datetime.now(UTC), time.monotonic)
        )
        stop = Event()
        result = run_loop(
            fresh_dependencies(dependencies),
            stop,
            WorkerHeartbeat("00000000000040008000000000000001", 123, NOW, NOW),
        )
        assert (
            result.code == 0 and seen[0] is not None and seen[1] is not None and seen[1] > seen[0]
        )


def test_shutdown_timeout_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """第2/14条：执行及输出线程均daemon，超30秒一次ERROR，返回FAILURE与活线程，不抛DefectError，入口保留原始fd。"""
    monkeypatch.setattr(policy, "WORKER_POLL_INTERVAL_S", 0.005)
    monkeypatch.setattr(policy, "WORKER_STOP_TIMEOUT_S", 0.08)
    entered, release = Event(), Event()

    def blocked(_: ExecutionContext) -> None:
        entered.set()
        release.wait(3)

    with (
        execution_case(
            tmp_path, {"steps": 3, "interval_ms": 0}, blocked, mode=RecoveryMode.RESUME
        ) as (_, dependencies, _),
        running_loop(dependencies) as (stop, thread, results),
    ):
        try:
            assert entered.wait(2)
            stop.set()
            thread.join(timeout=1)
            assert not thread.is_alive() and results[0].code == 1
            assert len(results[0].unreaped_threads) == 1
            assert all(item.daemon and item.is_alive() for item in results[0].unreaped_threads)
            assert (
                len([item for item in caplog.records if "停止超出预算" in item.getMessage()]) == 1
            )
        finally:
            release.set()
            for result in results:
                for owned in result.unreaped_threads:
                    owned.join(timeout=2)


def test_lock_retention_no_gc_close(tmp_path: Path) -> None:
    """第2条：入口失败返回后丢弃WorkerLock/WorkerExit引用并GC仍不放锁；正常全部线程退出才关闭fd。"""
    _retained_process(tmp_path, "shutdown_timeout")


def test_reader_timeout_retains_lock(tmp_path: Path) -> None:
    """第2/13条：执行线程已死但输出读线程仍活，也失败退出并保留锁，不伪报全部资源已回收。"""
    _retained_process(tmp_path, "reader_timeout")


@pytest.mark.parametrize(
    ("saved_count", "execute_again"), [(0, True), (1, True), (2, True), (3, False)]
)
def test_recovery_limit(saved_count: int, execute_again: bool, tmp_path: Path) -> None:
    """第9条：资格计数0→1→2→3均按当前方式恢复；第4次标中断，日志说明已达3次，重跑也不清此计数。"""
    with execution_case(tmp_path, {"steps": 4, "interval_ms": 0}, mode=RecoveryMode.RESTART) as (
        _,
        dependencies,
        _,
    ):
        with session_scope(dependencies.engine) as session:
            row = session.get(JobRow, 71)
            assert row is not None
            row.recovery_count = saved_count
        recovered = recover_job(71, dependencies)
        record = saved_record(dependencies.engine)
        assert (recovered is not None) == execute_again
        assert record.recovery_count == min(3, saved_count + 1)
        if not execute_again:
            assert record.state is JobState.INTERRUPTED and record.log_path is not None
            assert "恢复次数已达3次" in (dependencies.paths.root / record.log_path).read_text()


def test_recovery_attempt_before_execution(tmp_path: Path) -> None:
    """第9条：恢复计数在执行前提交；提交后立即崩溃也消耗一次，计数提交失败不启动执行。"""
    observed: list[ExecutionContext] = []
    with execution_case(
        tmp_path, {"steps": 4, "interval_ms": 0}, observed.append, mode=RecoveryMode.RESUME
    ) as (_, dependencies, _):
        recovered = recover_job(71, dependencies)
        assert recovered is not None and not observed
        assert saved_record(dependencies.engine).recovery_count == 1
        # 不执行便再次恢复，模拟资格提交后崩溃；第二次仍消耗资格。
        assert recover_job(71, dependencies) is not None
        assert saved_record(dependencies.engine).recovery_count == 2
        with dependencies.engine.begin() as connection:
            connection.exec_driver_sql(
                "CREATE TRIGGER reject_recovery BEFORE UPDATE OF recovery_count ON jobs BEGIN SELECT RAISE(ABORT, 'test'); END"
            )
        assert recover_job(71, dependencies) is None
        assert saved_record(dependencies.engine).state is JobState.INTERRUPTED and not observed


def test_recovery_record_corrupt(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """第9条：坏JSON位于单条恢复边界内；可安全终态则中断，否则ERROR跳过，后续恢复及新作业仍执行。"""
    with execution_case(tmp_path, {"steps": 4, "interval_ms": 0}, mode=RecoveryMode.RESUME) as (
        _,
        dependencies,
        _,
    ):
        database = dependencies.engine.url.database
        assert database is not None
        with sqlite_connection(database) as connection:
            connection.execute("UPDATE jobs SET parameters='{invalid' WHERE job_id=71")
        with caplog.at_level("ERROR"):
            assert recover_job(71, dependencies) is None
        assert any(
            "job_id=71" in entry.getMessage() and "跳过" in entry.getMessage()
            for entry in caplog.records
        )
        with sqlite_connection(database) as connection:
            assert connection.execute("SELECT state,recovery_count FROM jobs").fetchone() == (
                "running",
                0,
            )


def test_recovery_log_failure(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """第9条：日志不能写时禁止执行该条，尝试一次中断/取消终态；仍写失败只ERROR跳过，不令worker退出。"""
    with execution_case(tmp_path, {"steps": 4, "interval_ms": 0}, mode=RecoveryMode.RESUME) as (
        work,
        dependencies,
        _,
    ):
        assert work.record.log_path is not None
        # 普通目录占用日志路径，是可复现的文件故障，不依赖root权限差异。
        (dependencies.paths.root / work.record.log_path).mkdir()
        with caplog.at_level("ERROR"):
            assert recover_job(71, dependencies) is None
        record = saved_record(dependencies.engine)
        assert record.state is JobState.INTERRUPTED and record.recovery_count == 0
        assert record.diagnostics and record.diagnostics[0].samples[0].consequence
        assert any(
            "中断段" in entry.getMessage() and "job_id=71" in entry.getMessage()
            for entry in caplog.records
        )


def test_recovery_scan_advances(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """第9条：无法落终态而保留running的坏记录，本实例keyset游标越过它，不重复恢复、无队列饥饿。"""
    monkeypatch.setattr(policy, "WORKER_POLL_INTERVAL_S", 0.005)
    executed: list[int] = []

    def execute(context: ExecutionContext) -> None:
        executed.append(context.job_id)
        stop.set()

    with execution_case(
        tmp_path, {"steps": 3, "interval_ms": 0}, execute, mode=RecoveryMode.RESUME
    ) as (_, dependencies, _):
        with session_scope(dependencies.engine) as session:
            session.add(job_row(JobState.QUEUED, job_id=72))
        database = dependencies.engine.url.database
        assert database is not None
        with sqlite_connection(database) as connection:
            connection.execute("UPDATE jobs SET parameters='{broken' WHERE job_id=71")
        stop = Event()
        result = run_loop(
            fresh_dependencies(dependencies),
            stop,
            WorkerHeartbeat("00000000000040008000000000000001", 123, NOW, NOW),
        )
        assert result.code == 0 and executed == [72]
        assert len([entry for entry in caplog.records if "跳过该条" in entry.getMessage()]) == 1
        with sqlite_connection(database) as connection:
            assert connection.execute("SELECT state FROM jobs WHERE job_id=71").fetchone() == (
                "running",
            )


def test_cancel_stall_warning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """第10条：本实例首次观察cancelling后单调超过60秒，边界一次WARNING且日志统一诊断含编号/阶段/时长/后果；状态及业务计数不改。"""
    monkeypatch.setattr(policy, "WORKER_POLL_INTERVAL_S", 0.005)
    clock = MutableClock()
    acknowledged, release = Event(), Event()
    contexts: list[ExecutionContext] = []

    def uncooperative(context: ExecutionContext) -> None:
        contexts.append(context)
        try:
            context.reporter.wait(60)
        except JobCancelledError:
            acknowledged.set()
            release.wait(3)

    with execution_case(
        tmp_path, {"steps": 3, "interval_ms": 0}, uncooperative, mode=RecoveryMode.RESUME
    ) as (_, dependencies, _):
        dependencies = replace(dependencies, clock=JobClock(clock.now, clock.monotonic))
        with running_loop(dependencies):
            try:
                wait_for(lambda: bool(contexts))
                with session_scope(dependencies.engine) as session:
                    transition_job(
                        session, 71, StateChange(JobState.RUNNING, JobState.CANCELLING, NOW)
                    )
                assert acknowledged.wait(1)
                clock.seconds += 60
                Event().wait(0.02)
                assert not any("未响应取消" in item.getMessage() for item in caplog.records)
                clock.seconds += 0.001
                wait_for(lambda: any("未响应取消" in item.getMessage() for item in caplog.records))
                assert any(
                    "未响应取消" in item.getMessage() and "job_id=71" in item.getMessage()
                    for item in caplog.records
                )
                value = contexts[0].reporter.snapshot()
                assert value.progress is None and len(value.diagnostics) == 1
                diagnostic = value.diagnostics[0].samples[0]
                assert any(
                    item.key == "job_id" and item.value == "71" for item in diagnostic.objects
                )
                assert "60" in diagnostic.actual and diagnostic.consequence and diagnostic.next_step
                assert saved_record(dependencies.engine).state is JobState.CANCELLING
                clock.seconds += 100
                clock.wall -= timedelta(days=1)
                Event().wait(0.03)
                assert (
                    len([item for item in caplog.records if "未响应取消" in item.getMessage()]) == 1
                )
            finally:
                release.set()


def test_cancel_stall_not_repeated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """第10条：60秒前或线程已退出不提示；持续cancelling多轮只提示一次，UTC回拨不重复计时。"""
    monkeypatch.setattr(policy, "WORKER_POLL_INTERVAL_S", 0.005)
    clock = MutableClock()
    acknowledged, release = Event(), Event()
    contexts: list[ExecutionContext] = []

    def execute(context: ExecutionContext) -> None:
        contexts.append(context)
        try:
            context.reporter.wait(60)
        except JobCancelledError:
            acknowledged.set()
            assert release.wait(3)

    with execution_case(
        tmp_path, {"steps": 3, "interval_ms": 0}, execute, mode=RecoveryMode.RESUME
    ) as (_, dependencies, _):
        dependencies = replace(dependencies, clock=JobClock(clock.now, clock.monotonic))
        with running_loop(dependencies):
            try:
                wait_for(lambda: bool(contexts))
                with session_scope(dependencies.engine) as session:
                    transition_job(
                        session, 71, StateChange(JobState.RUNNING, JobState.CANCELLING, NOW)
                    )
                assert acknowledged.wait(1)
                clock.seconds = 159
                Event().wait(0.02)
                assert not any("未响应取消" in row.getMessage() for row in caplog.records)
                clock.seconds = 161
                wait_for(lambda: any("未响应取消" in row.getMessage() for row in caplog.records))
                clock.seconds = 300
                clock.wall -= timedelta(days=1)
                Event().wait(0.02)
                assert len([row for row in caplog.records if "未响应取消" in row.getMessage()]) == 1
                release.set()
                wait_for(lambda: saved_record(dependencies.engine).state is JobState.CANCELLED)
                clock.seconds = 600
                Event().wait(0.02)
                assert len([row for row in caplog.records if "未响应取消" in row.getMessage()]) == 1
            finally:
                release.set()


def test_systemd_orphan_boundary(tmp_path: Path) -> None:
    """第12条：生产入口契约要求KillMode=control-group和TimeoutStopSec>=30秒；测试SIGKILL后由夹具清理孤儿，不声称worker finally会运行。"""
    import inspect
    import os
    import subprocess

    from job_process_support import (
        PROCESS_EXIT_TIMEOUT_S,
        PROCESS_READY_TIMEOUT_S,
        prepare_process_case,
    )
    from jobs_process_resources import adopt_orphans

    case = prepare_process_case(tmp_path, "lock_inheritance")
    runner = Path(__file__).with_name("job_worker_process.py")
    with adopt_orphans():
        process: subprocess.Popen[bytes] | None = None
        try:
            process = subprocess.Popen(  # noqa: S603  # 理由：固定本地worker夹具，隔离进程组且finally回收。
                [sys.executable, str(runner), str(tmp_path), "lock_inheritance"],
                start_new_session=True,
            )
            case.wait_running(PROCESS_READY_TIMEOUT_S)
            case.wait_tool_ready(PROCESS_READY_TIMEOUT_S)
            pid = case.tool_pid()
            process.kill()
            process.wait(timeout=PROCESS_EXIT_TIMEOUT_S)
            assert os.waitpid(pid, os.WNOHANG) == (0, 0)
            contract = inspect.getdoc(run_worker) or ""
            assert (
                "KillMode=control-group" in contract
                and "TimeoutStopSec" in contract
                and "30秒" in contract
            )
            case.cleanup_orphans()
            with pytest.raises(ChildProcessError):
                os.waitpid(pid, os.WNOHANG)
        finally:
            try:
                if process is not None:
                    if process.poll() is None:
                        process.kill()
                    process.wait(timeout=PROCESS_EXIT_TIMEOUT_S)
            finally:
                case.cleanup_orphans()


@pytest.mark.parametrize("blocked_wait", [True, False])
def test_unreapable_external_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, blocked_wait: bool
) -> None:
    """第13条：模拟SIGKILL后wait超时或读线程join超时，ExternalError不伪造退出码，daemon读线程仍在monitor，主循环失败收尾。"""
    monkeypatch.setattr(policy, "WORKER_POLL_INTERVAL_S", 0.005)
    monkeypatch.setattr(policy, "WORKER_STOP_TIMEOUT_S", 0.03)
    monkeypatch.setattr(processes, "PROCESS_TERM_GRACE_S", 0.02)
    monkeypatch.setattr(processes, "PROCESS_REAP_TIMEOUT_S", 0.02)
    monkeypatch.setattr(processes, "OUTPUT_JOIN_TIMEOUT_S", 0.02)
    process = BlockedTool(blocked_wait)
    contexts: list[ExecutionContext] = []

    def execute(context: ExecutionContext) -> None:
        contexts.append(context)
        context.run_process(ToolCommand("不可回收工具", (sys.executable,), tmp_path, 0.01))

    try:
        monkeypatch.setattr(processes.subprocess, "Popen", process.launch)
        monkeypatch.setattr(processes.os, "killpg", process.send)
        with execution_case(
            tmp_path, {"steps": 3, "interval_ms": 0}, execute, mode=RecoveryMode.RESUME
        ) as (_, dependencies, _):
            results: list[WorkerLoopResult] = []
            try:
                with running_loop(dependencies) as (_, thread, results):
                    thread.join(timeout=2)
                    assert not thread.is_alive() and results[0].code == 1
                    assert len(results[0].unreaped_threads) == 2
                    assert all(
                        item.daemon and item.is_alive() for item in results[0].unreaped_threads
                    )
                record = saved_record(dependencies.engine)
                assert record.tool_exit_code == (None if blocked_wait else 0)
                assert record.summary is not None and record.summary.outcome == "failed"
                diagnostic = record.diagnostics[0].samples[0]
                assert diagnostic.category.value == "external" and "回收" in diagnostic.actual
                assert signal.SIGTERM in process.sent and signal.SIGKILL in process.sent
            finally:
                try:
                    process.release()
                    for result in results:
                        for thread in result.unreaped_threads:
                            thread.join(timeout=1)
                            assert not thread.is_alive()
                finally:
                    for context in contexts:
                        context.log.close()
    finally:
        process.close()


def test_heartbeat_online_rejects_invalid_snapshots() -> None:
    """在线纯边界：非法时刻、实例标识和pid均为DefectError，空心跳也不能绕过now校验。"""
    moment = datetime(2026, 10, 26, tzinfo=UTC)
    heartbeat = WorkerHeartbeat("00000000000040008000000000000001", 123, moment, moment)
    for now in (moment.replace(tzinfo=None), cast(datetime, None), cast(datetime, "bad")):
        with pytest.raises(DefectError):
            heartbeat_online(heartbeat, now=now)
        with pytest.raises(DefectError):
            heartbeat_online(None, now=now)
    for broken in (
        replace(heartbeat, pid=0),
        replace(heartbeat, pid=-1),
        replace(heartbeat, pid=True),
        replace(heartbeat, instance_id="0" * 32),
        replace(heartbeat, instance_id="invalid"),
        replace(heartbeat, started_at=moment.replace(tzinfo=None)),
        replace(heartbeat, last_seen_at=moment.replace(tzinfo=None)),
        cast(WorkerHeartbeat, object()),
    ):
        with pytest.raises(DefectError):
            heartbeat_online(broken, now=moment)


def test_lock_public_lifecycle(tmp_path: Path) -> None:
    """单实例边界：锁冲突含路径且不换inode，正常finish后可再获锁，重复处分拒绝。"""
    from jobs_storage_support import job_database

    from rdp.infra.diagnostics import ConflictError

    with job_database(tmp_path) as (_, paths):
        lock = worker_lock(paths)
        inode = paths.worker_lock.stat().st_ino
        try:
            with pytest.raises(ConflictError) as caught:
                worker_lock(paths)
            diagnostic = caught.value.diagnostics[0]
            assert "另一个 worker 正在运行" in diagnostic.actual
            assert any(item.value == str(paths.worker_lock) for item in diagnostic.objects)
            assert paths.worker_lock.stat().st_ino == inode
        finally:
            assert not lock.finish(())
        with pytest.raises(DefectError):
            lock.finish(())
        second = worker_lock(paths)
        assert not second.finish(()) and paths.worker_lock.stat().st_ino == inode


def _heartbeat_seen(dependencies: ExecutorDependencies) -> datetime | None:
    """通过真实临时库观察心跳，不依赖主循环内部计时字段。"""
    with session_scope(dependencies.engine, read_only=True) as session:
        row = session.get(WorkerHeartbeatRow, 1)
        return None if row is None else row.last_seen_at


def test_external_timeout_diagnostic_after_reap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """外部超时诊断必须在回收后包含真实负信号及最终stderr，不能提前冻结成None或空尾部。"""
    import sys

    from rdp.jobs import processes
    from rdp.jobs.processes import ToolCommand

    monkeypatch.setattr(processes, "PROCESS_TERM_GRACE_S", 0.05)
    code = "import sys,time; print('超时前错误',file=sys.stderr,flush=True); time.sleep(60)"

    def tool(context: ExecutionContext) -> None:
        context.run_process(
            ToolCommand("超时工具", (sys.executable, "-u", "-c", code), tmp_path, 0.1)
        )

    with execution_case(tmp_path, {"steps": 3, "interval_ms": 0}, tool) as (
        work,
        dependencies,
        signals,
    ):
        record = execute_job(work, dependencies, signals)
        assert record is not None and record.summary is not None
        assert record.summary.outcome == "failed" and record.summary.aborted
        diagnostic = record.diagnostics[0].samples[0]
        objects = {item.key: item.value for item in diagnostic.objects}
        assert objects["returncode"] == "-15" and "超时前错误" in objects["stderr_tail"]
        assert "timeout_s" in diagnostic.actual
        assert not any(thread.is_alive() for thread in signals.monitor.threads)


def test_runtime_clock_failure_still_returns_failure(tmp_path: Path) -> None:
    """初始时钟合法、运行中变成NaN时仍停止领取并有限收尾，不能让收尾再次读取坏时钟而逃逸异常。"""
    reads = 0

    def clock() -> float:
        nonlocal reads
        reads += 1
        return 100.0 if reads == 1 else float("nan")

    with execution_case(tmp_path, {"steps": 3, "interval_ms": 0}) as (_, dependencies, _):
        result = run_loop(
            fresh_dependencies(replace(dependencies, clock=JobClock(lambda: NOW, clock))),
            Event(),
            WorkerHeartbeat("00000000000040008000000000000001", 123, NOW, NOW),
        )
        assert result.code == 1 and not result.unreaped_threads
        assert saved_record(dependencies.engine).state is JobState.RUNNING


def test_execution_log_open_failure_preserves_history(tmp_path: Path) -> None:
    """执行开头失败仍尝试失败终态，续跑已有诊断的完整总数不能被新故障覆盖或由样例数重算。"""
    from jobs_progress_support import diagnostic

    from rdp.infra.diagnostics import DiagnosticGroup

    with execution_case(tmp_path, {"steps": 3, "interval_ms": 0}, mode=RecoveryMode.RESUME) as (
        work,
        dependencies,
        signals,
    ):
        history = DiagnosticGroup(
            "平台", "样例规则", 13, 0, 13, tuple(diagnostic(i) for i in range(10))
        )
        with session_scope(dependencies.engine) as session:
            save_progress(session, 71, ExecutionSnapshot(None, (history,), (), None, 0), now=NOW)
        work = replace(work, record=saved_record(dependencies.engine))
        assert work.record.log_path is not None
        (dependencies.paths.root / work.record.log_path).mkdir()
        result = execute_job(work, dependencies, signals)
        assert (
            result is not None and result.summary is not None and result.summary.outcome == "failed"
        )
        assert result.state is JobState.COMPLETED and result.summary.aborted
        assert result.diagnostics[0] == history and len(result.diagnostics) == 2


def test_external_failure_has_job_identity(tmp_path: Path) -> None:
    """作业最外层为工具失败补作业身份，仍保留命令、真实退出码、stderr尾和后果，不只保存裸工具错误。"""

    def execute(context: ExecutionContext) -> None:
        context.run_process(
            ToolCommand(
                "失败工具",
                (
                    sys.executable,
                    "-c",
                    "import sys; print('failure-tail',file=sys.stderr); raise SystemExit(7)",
                ),
                tmp_path,
                2,
            )
        )

    with execution_case(tmp_path, {"steps": 3, "interval_ms": 0}, execute) as (
        work,
        dependencies,
        signals,
    ):
        record = execute_job(work, dependencies, signals)
        assert (
            record is not None and record.summary is not None and record.summary.outcome == "failed"
        )
        diagnostic = record.diagnostics[0].samples[0]
        objects = {item.key: item.value for item in diagnostic.objects}
        assert objects["job_id"] == "71" and objects["returncode"] == "7"
        assert "failure-tail" in objects["stderr_tail"] and sys.executable in objects["command"]
        assert diagnostic.actual and diagnostic.consequence


def _retained_process(tmp_path: Path, mode: str) -> None:
    """在失败入口已经返回并GC后再启动第二实例，保证真实flock覆盖剩余进程寿命。"""
    import subprocess

    from job_process_support import (
        PROCESS_EXIT_TIMEOUT_S,
        PROCESS_READY_TIMEOUT_S,
        prepare_process_case,
    )

    case = prepare_process_case(tmp_path, mode)
    runner = Path(__file__).with_name("job_worker_process.py")
    first: subprocess.Popen[bytes] | None = None
    second: subprocess.Popen[bytes] | None = None
    try:
        first = subprocess.Popen(  # noqa: S603  # 理由：固定测试入口，无shell，退出前清理进程组。
            [sys.executable, str(runner), str(tmp_path), mode], start_new_session=True
        )
        if mode == "shutdown_timeout":
            case.wait_running(PROCESS_READY_TIMEOUT_S)
            case.stop()
        pid = first.pid
        wait_for(lambda: (tmp_path / f"returned-{pid}.json").exists(), timeout_s=3)
        returned = case.wait_worker_return(1)
        assert returned.code == 1 and returned.lock_retained and first.poll() is None
        assert (tmp_path / f"gc-{pid}").exists()
        if mode == "reader_timeout":
            assert case.wait_terminal(1).state is JobState.COMPLETED
        second = subprocess.Popen(  # noqa: S603  # 理由：独立进程验证保锁，不用内存变量替代文件锁。
            [sys.executable, str(runner), str(tmp_path), "lock"], start_new_session=True
        )
        assert second.wait(timeout=PROCESS_EXIT_TIMEOUT_S) == 2
        case.allow_process_exit()
        assert first.wait(timeout=PROCESS_EXIT_TIMEOUT_S) == 1
        paths = state_paths(PlatformConfig(state_dir=tmp_path), ("示例：数数", "测试作业"))
        lock = worker_lock(paths)
        assert not lock.finish(())
    finally:
        try:
            for process in (second, first):
                if process is not None:
                    if process.poll() is None:
                        process.kill()
                    process.wait(timeout=PROCESS_EXIT_TIMEOUT_S)
        finally:
            case.cleanup_orphans()


def test_whitespace_stderr_nonzero_stays_external(tmp_path: Path) -> None:
    """契约：真实工具只有空白stderr且非零退出，仍报告外部失败及退出码，不创建程序缺陷报错。"""
    failures: list[ExternalError] = []

    def execute(context: ExecutionContext) -> None:
        try:
            context.run_process(
                ToolCommand(
                    "空白工具",
                    (sys.executable, "-c", "import sys; sys.stderr.write('\\n  \\n'); sys.exit(1)"),
                    tmp_path,
                    2,
                )
            )
        except ExternalError as error:
            failures.append(error)
            raise

    with execution_case(tmp_path, {"steps": 3, "interval_ms": 0}, execute) as (
        work,
        dependencies,
        signals,
    ):
        result = execute_job(work, dependencies, signals)
        assert len(failures) == 1
        assert (
            result is not None and result.summary is not None and result.summary.outcome == "failed"
        )
        diagnostic = result.diagnostics[0].samples[0]
        objects = {item.key: item.value for item in diagnostic.objects}
        assert diagnostic.category.value == "external" and objects["returncode"] == "1"
        assert objects["stderr_tail"] == "（stderr仅含空白）"
        assert result.log_path is not None
        assert "stderr 空白工具│  \n" in (dependencies.paths.root / result.log_path).read_text()
        with session_scope(dependencies.engine, read_only=True) as session:
            assert find_error(session, "71") is None
        assert not any(thread.is_alive() for thread in signals.monitor.threads)


def test_whitespace_stderr_unreaped_stays_external(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """契约：已有空白stderr且SIGKILL后wait仍超时，保留外部失败和未知退出码，不被诊断校验改成缺陷。"""
    process = BlockedTool(True)
    failures: list[ExternalError] = []
    contexts: list[ExecutionContext] = []
    original_wait = process.wait
    monkeypatch.setattr(processes, "PROCESS_TERM_GRACE_S", 0.02)
    monkeypatch.setattr(processes, "PROCESS_REAP_TIMEOUT_S", 0.02)
    monkeypatch.setattr(processes.subprocess, "Popen", process.launch)
    monkeypatch.setattr(processes.os, "killpg", process.send)

    def execute(context: ExecutionContext) -> None:
        contexts.append(context)
        try:
            context.run_process(ToolCommand("空白工具", (sys.executable,), tmp_path, 0.01))
        except ExternalError as error:
            failures.append(error)
            raise

    try:
        with execution_case(tmp_path, {"steps": 3, "interval_ms": 0}, execute) as (
            work,
            dependencies,
            signals,
        ):
            assert work.record.log_path is not None
            target = dependencies.paths.root / work.record.log_path

            def wait(timeout: float) -> int:
                wait_for(
                    lambda: process.stderr.closed and "stderr 空白工具│  \n" in target.read_text()
                )
                return original_wait(timeout)

            monkeypatch.setattr(process, "wait", wait)
            _feed_whitespace_stderr(process)
            try:
                result = execute_job(work, dependencies, signals)
                assert len(failures) == 1
                assert result is not None and result.tool_exit_code is None
                diagnostic = result.diagnostics[0].samples[0]
                objects = {item.key: item.value for item in diagnostic.objects}
                assert (
                    diagnostic.category.value == "external"
                    and "SIGKILL后进程仍未回收" in diagnostic.actual
                )
                assert (
                    objects["returncode"] == "None"
                    and objects["stderr_tail"] == "（stderr仅含空白）"
                )
                with session_scope(dependencies.engine, read_only=True) as session:
                    assert find_error(session, "71") is None
            finally:
                _release_whitespace_tool(process, signals.monitor.threads, contexts)
    finally:
        process.close()


def _release_whitespace_tool(
    process: BlockedTool, threads: list[Thread], contexts: list[ExecutionContext]
) -> None:
    """先让真实管道到达EOF，再有界join并关闭日志，清理故障也不能跳过日志关闭。"""
    try:
        process.release()
        for thread in threads:
            thread.join(timeout=1)
            assert not thread.is_alive()
    finally:
        for context in contexts:
            context.log.close()


def _feed_whitespace_stderr(process: BlockedTool) -> None:
    """关闭stderr写端提供EOF握手，避免日志已刷新而内存尾部还在更新的调度竞争。"""
    with os.fdopen(process.writers.pop(), "wb", buffering=0) as stream:
        stream.write(b"\n  \n")
