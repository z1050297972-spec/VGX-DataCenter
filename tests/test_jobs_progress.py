"""M0/08 公共契约测试；数据库与文件只使用临时目录，不依赖真实数据或默认状态目录。"""

import json
import math
import sys
import time
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from threading import Event, Thread
from typing import cast

import pytest
from jobs_api_support import job_api_case
from jobs_execution_support import execution_case
from jobs_loop_support import wait_for
from jobs_progress_support import MutableClock, diagnostic, progress, reporter_context, saved_record
from jobs_storage_support import NOW
from pydantic import ValidationError
from sqlalchemy import text

from rdp.infra.db.connection import session_scope
from rdp.infra.diagnostics import ConflictError, DefectError
from rdp.jobs.errors import JobCancelledError, WorkerStoppingError
from rdp.jobs.execution import ExecutionContext, execute_job
from rdp.jobs.processes import ToolCommand
from rdp.jobs.records import StateChange, save_progress, transition_job
from rdp.jobs.types import ExecutionSnapshot, JobClock, JobProgress, JobState


def test_throttle_latest(tmp_path: Path) -> None:
    """验收5：注入单调时钟一秒内多次report最多一次SQL，snapshot始终为最新完整值。"""
    clock = MutableClock()
    with reporter_context(tmp_path, JobClock(clock.now, clock.monotonic)) as (
        reporter,
        engine,
        _,
        _,
    ):
        reporter.report(progress(1))
        assert saved_record(engine).progress == progress(1)
        assert reporter.next_flush_deadline() is None
        for count in (2, 3):
            clock.seconds += 0.2
            reporter.report(progress(count))
            assert reporter.snapshot().progress == progress(count)
            assert saved_record(engine).progress == progress(1)
        assert reporter.next_flush_deadline() == 101.0
        clock.seconds = 100.999
        reporter.flush_due()
        assert saved_record(engine).progress == progress(1)
        clock.seconds = 101.0
        reporter.flush_due()
        assert saved_record(engine).progress == progress(3)
        assert reporter.next_flush_deadline() is None


def test_throttle_clock_rollback(tmp_path: Path) -> None:
    """验收5/5.4：UTC墙钟回拨不改变每秒节流；非法单调时钟/NaN/倒退归DefectError。"""
    clock = MutableClock()
    with reporter_context(tmp_path, JobClock(clock.now, clock.monotonic)) as (
        reporter,
        engine,
        _,
        _,
    ):
        reporter.report(progress(1))
        clock.wall -= timedelta(days=1)
        clock.seconds += 0.5
        reporter.report(progress(2))
        assert saved_record(engine).progress == progress(1)
        clock.seconds += 0.5
        reporter.flush_due()
        assert saved_record(engine).progress == progress(2)
        assert saved_record(engine).progress_at == NOW - timedelta(days=1)
        for invalid in (100.0, math.nan, math.inf, cast(float, True)):
            clock.seconds = invalid
            with pytest.raises(DefectError):
                reporter.snapshot()


def test_short_lock_skip(tmp_path: Path) -> None:
    """验收5：BEGIN短锁忙100毫秒跳过且保留内存，下一秒才重试；不更改普通busy_timeout。"""
    clock = MutableClock()
    with reporter_context(tmp_path, JobClock(clock.now, clock.monotonic)) as (
        reporter,
        engine,
        _,
        _,
    ):
        with session_scope(engine):
            start = time.monotonic()
            reporter.report(progress(1))
            assert time.monotonic() - start < 0.6
            assert reporter.snapshot().progress == progress(1)
        reporter.flush_due()
        assert saved_record(engine).progress is None
        clock.seconds += 1
        reporter.flush_due()
        assert saved_record(engine).progress == progress(1)
        with session_scope(engine, read_only=True) as session:
            assert session.scalar(text("PRAGMA busy_timeout")) == 5000


def test_entered_failure_not_skipped(tmp_path: Path) -> None:
    """规范7.1：进度已入事务的约束/提交失败不被当入场忙吞掉，错误传播到作业边界。"""
    clock = MutableClock()
    with reporter_context(tmp_path, JobClock(clock.now, clock.monotonic)) as (
        reporter,
        engine,
        _,
        _,
    ):
        with engine.begin() as connection:
            connection.exec_driver_sql(
                "CREATE TRIGGER reject_progress BEFORE UPDATE ON jobs BEGIN SELECT RAISE(ABORT, 'test'); END"
            )
        with pytest.raises(ConflictError):
            reporter.report(progress(1))
        assert reporter.snapshot().progress == progress(1)
        assert saved_record(engine).progress is None
        assert reporter.next_flush_deadline() == 101.0


def test_final_forced_snapshot(tmp_path: Path) -> None:
    """验收5：结束即使不足一秒也在终态普通事务保存最新值，数据库计数与日志摘要一致。"""
    clock = MutableClock()

    def execute(context: ExecutionContext) -> None:
        context.reporter.report(progress(1))
        context.reporter.report(progress(3))
        assert saved_record(dependencies.engine).progress == progress(1)

    with execution_case(tmp_path, {"steps": 3, "interval_ms": 0}, execute) as (
        work,
        dependencies,
        signals,
    ):
        dependencies = replace(dependencies, clock=JobClock(clock.now, clock.monotonic))
        record = execute_job(work, dependencies, signals)
        assert record is not None and record.progress == progress(3) and record.summary is not None
        assert record.summary.total_items == 3 and record.log_path is not None
        content = (dependencies.paths.root / record.log_path).read_text()
        summary = json.loads(content.split("summary=", 1)[1])
        assert summary["total_items"] == 3 and summary["progress"]["done"] == 3


def test_unknown_total(tmp_path: Path) -> None:
    """验收5：total=None经数据库与API仍为空，只有真实done，不编造百分比。"""
    with job_api_case(tmp_path) as fixture:
        fixture.login()
        value = fixture.client.post("/api/jobs/example", json={"steps": 3, "interval_ms": 0}).json()
        identifier = int(value["job_id"])
        reported = progress(2, total=None)
        with session_scope(fixture.engine) as session:
            transition_job(
                session,
                identifier,
                StateChange(
                    JobState.QUEUED, JobState.RUNNING, NOW, log_path="logs/示例：数数/test.log"
                ),
            )
            save_progress(
                session, identifier, ExecutionSnapshot(reported, (), (), None, 2), now=NOW
            )
        response = fixture.client.get(f"/api/jobs/{identifier}")
        assert response.status_code == 200 and response.json()["progress"]["total"] is None
        assert response.json()["progress"]["done"] == 2


def test_invalid_progress() -> None:
    """上报契约：stage_index越界、空白名称、负数/bool、done超过total、failed超过total_items均拒绝。"""
    valid: dict[str, object] = {
        "stage_index": 2,
        "stage_count": 3,
        "stage_name": "处理",
        "done": 7,
        "total": 11,
        "unit": "条",
        "warning_count": 5,
        "failed_items": 2,
        "total_items": 9,
    }
    progress = JobProgress.model_validate(valid)
    assert (progress.stage_index, progress.done, progress.failed_items, progress.warning_count) == (
        2,
        7,
        2,
        5,
    )
    assert JobProgress.model_validate(valid | {"total": None}).total is None
    invalid: list[dict[str, object]] = [
        {"stage_index": 4},
        {"stage_index": 0},
        {"stage_count": 0},
        {"stage_name": " "},
        {"stage_name": ""},
        {"unit": "\t"},
        {"total": 6},
        {"failed_items": 10},
        {"extra": "sensitive-marker"},
    ]
    for key in (
        "stage_index",
        "stage_count",
        "done",
        "total",
        "warning_count",
        "failed_items",
        "total_items",
    ):
        invalid.extend({key: value} for value in (-1, True, 1.5, "1"))
    for change in invalid:
        with pytest.raises(ValidationError) as caught:
            JobProgress.model_validate(valid | change)
        assert "sensitive-marker" not in str(caught.value)
    with pytest.raises(ValidationError):
        progress.done = 8


def test_progress_monotonic_counts(tmp_path: Path) -> None:
    """上报契约：同阶段done/累计计数不得倒退；切换新阶段done可清零，重跑由恢复先清零。"""
    clock = MutableClock()
    with reporter_context(tmp_path, JobClock(clock.now, clock.monotonic)) as (reporter, _, _, log):
        reporter.report(progress(4, failed_items=2, warning_count=3))
        for changes in ({"done": 3}, {"total_items": 3}, {"failed_items": 1}, {"warning_count": 2}):
            values = progress(4, failed_items=2, warning_count=3).model_dump() | changes
            with pytest.raises(DefectError):
                reporter.report(JobProgress.model_validate(values))
        reporter.report(
            progress(
                0, stage_index=2, stage_name="收尾", total_items=4, failed_items=2, warning_count=3
            )
        )
        assert reporter.snapshot().progress == progress(
            0, stage_index=2, stage_name="收尾", total_items=4, failed_items=2, warning_count=3
        )
        with pytest.raises(DefectError):
            reporter.report(progress(4, failed_items=2, warning_count=3))
        assert "阶段 1/2 · 处理" in log.read_text() and "阶段 2/2 · 收尾" in log.read_text()


def test_cancel_interruptible_wait(tmp_path: Path) -> None:
    """验收4：一分钟间隔在取消后约50毫秒内醒来，不等满间隔；零间隔仍检查取消。"""
    with reporter_context(tmp_path, JobClock(lambda: NOW, time.monotonic)) as (
        reporter,
        _,
        signals,
        _,
    ):
        started = Event()
        errors: list[BaseException] = []

        def waiting() -> None:
            started.set()
            try:
                reporter.wait(60)
            except BaseException as error:
                errors.append(error)

        thread = Thread(target=waiting, daemon=True)
        try:
            thread.start()
            assert started.wait(1)
            signals.cancelled.set()
            thread.join(timeout=0.5)
            assert not thread.is_alive() and len(errors) == 1
            assert isinstance(errors[0], JobCancelledError)
            with pytest.raises(JobCancelledError):
                reporter.wait(0)
        finally:
            signals.stopping.set()
            thread.join(timeout=1)


def test_stop_distinct_cancel(tmp_path: Path) -> None:
    """停止契约：stopping抛WorkerStoppingError而非JobCancelledError，两个都置位时取消优先。"""
    clock = MutableClock()
    with reporter_context(tmp_path, JobClock(clock.now, clock.monotonic)) as (
        reporter,
        _,
        signals,
        _,
    ):
        signals.stopping.set()
        with pytest.raises(WorkerStoppingError):
            reporter.check_cancelled()
        signals.cancelled.set()
        with pytest.raises(JobCancelledError):
            reporter.check_cancelled()
        with pytest.raises(JobCancelledError):
            reporter.wait(0)


def test_bounded_diagnostics(tmp_path: Path) -> None:
    """规范2.7/6.6：诊断总数完整、前N样例、规则组溢出明确合并，日志仍包含每条诊断。"""
    clock = MutableClock()
    with reporter_context(tmp_path, JobClock(clock.now, clock.monotonic)) as (
        reporter,
        engine,
        _,
        log,
    ):
        for index in range(15):
            reporter.diagnostic(diagnostic(index))
        for index in range(105):
            reporter.diagnostic(diagnostic(index, rule=f"另一个规则{index}"))
        snapshot = reporter.snapshot()
        assert len(snapshot.diagnostics) == 101
        first = snapshot.diagnostics[0]
        assert (first.total, first.warning_count, first.error_count) == (15, 15, 0)
        assert first.samples == tuple(diagnostic(i) for i in range(10))
        overflow = snapshot.diagnostics[-1]
        assert (overflow.source, overflow.rule, overflow.total) == (
            "平台",
            "诊断规则种类超过上限",
            6,
        )
        assert [item.rule for item in overflow.samples] == [
            f"另一个规则{i}" for i in range(99, 105)
        ]
        assert snapshot.progress is None
        assert log.read_text().count("继续其余条目") == 120
        reporter.flush_due()
        assert saved_record(engine).diagnostics == snapshot.diagnostics


def test_artifact_bounds(tmp_path: Path) -> None:
    """产物契约：位置按报告顺序去重，长度和数量超限拒绝，取消不删产物。"""
    clock = MutableClock()
    with reporter_context(tmp_path, JobClock(clock.now, clock.monotonic)) as (
        reporter,
        _,
        signals,
        _,
    ):
        reporter.artifact("位置甲")
        reporter.artifact("位置乙")
        reporter.artifact("位置甲")
        assert reporter.snapshot().artifacts == ("位置甲", "位置乙")
        for location in ("", " ", "x" * 4097):
            with pytest.raises(DefectError):
                reporter.artifact(location)
        for index in range(98):
            reporter.artifact(str(index))
        with pytest.raises(DefectError):
            reporter.artifact("第101项")
        signals.cancelled.set()
        with pytest.raises(JobCancelledError):
            reporter.check_cancelled()
        assert len(reporter.snapshot().artifacts) == 100


def test_persist_elapsed_fragments(tmp_path: Path) -> None:
    """时间契约：每次周期保存elapsed_s，续跑只加新单调片段不含停机时间，重跑也保留耗时片段但计数清零，墙钟回拨无影响。"""
    clock = MutableClock()
    with reporter_context(tmp_path, JobClock(clock.now, clock.monotonic), resume=True) as (
        reporter,
        engine,
        _,
        _,
    ):
        assert reporter.snapshot().elapsed_s == 2.5
        clock.seconds += 3
        clock.wall += timedelta(days=7)
        reporter.report(progress(4, failed_items=1, warning_count=3))
        assert saved_record(engine).elapsed_s == 5.5
        clock.seconds += 2
        clock.wall -= timedelta(days=8)
        reporter.report(progress(5, failed_items=1, warning_count=3))
        assert saved_record(engine).elapsed_s == reporter.snapshot().elapsed_s == 7.5


def test_long_wait_flushes_latest(tmp_path: Path) -> None:
    """第1条：一秒内连报1/2/3后进入60秒wait，不再report；无竞争约1秒内库变成3，旧1不能一直保留到等待结束。"""
    with reporter_context(tmp_path, JobClock(lambda: NOW, time.monotonic)) as (
        reporter,
        engine,
        signals,
        _,
    ):
        for count in (1, 2, 3):
            reporter.report(progress(count))
        assert saved_record(engine).progress == progress(1)
        errors: list[BaseException] = []

        def waiting() -> None:
            try:
                reporter.wait(60)
            except WorkerStoppingError:
                pass
            except BaseException as error:
                errors.append(error)

        thread = Thread(target=waiting, daemon=True)
        try:
            thread.start()
            deadline = time.monotonic() + 1.5
            while time.monotonic() < deadline and saved_record(engine).progress != progress(3):
                signals.stopping.wait(0.02)
            assert saved_record(engine).progress == progress(3)
            assert thread.is_alive() and not errors
        finally:
            signals.stopping.set()
            thread.join(timeout=1)
        assert not thread.is_alive() and not errors


def test_checkpoint_flushes_latest(tmp_path: Path) -> None:
    """第1条：next_flush_deadline到期调用check_cancelled补写，report/wait/check共用节流；无脏值不写。"""
    clock = MutableClock()
    with reporter_context(tmp_path, JobClock(clock.now, clock.monotonic)) as (
        reporter,
        engine,
        _,
        _,
    ):
        reporter.report(progress(1))
        reporter.report(progress(3))
        assert reporter.next_flush_deadline() == 101
        clock.seconds = 101
        reporter.check_cancelled()
        assert saved_record(engine).progress == progress(3)
        clock.seconds = 102
        reporter.check_cancelled()
        assert saved_record(engine).elapsed_s == 1
        assert reporter.next_flush_deadline() is None


def test_process_poll_flushes_latest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """第1条：外部工具长时间无输出，进程轮询仍按补写截止保存最新值，不等工具退出。"""
    from rdp.jobs import progress as progress_module

    monkeypatch.setattr(progress_module, "PROGRESS_INTERVAL_S", 0.05)
    started = Event()

    def execute(context: ExecutionContext) -> None:
        for done in (1, 2, 3):
            context.reporter.report(progress(done))
        started.set()
        context.run_process(
            ToolCommand(
                "静默工具", (sys.executable, "-c", "import time; time.sleep(60)"), tmp_path, 60
            )
        )

    with execution_case(tmp_path, {"steps": 3, "interval_ms": 0}, execute) as (
        work,
        dependencies,
        signals,
    ):
        failures: list[BaseException] = []

        def run() -> None:
            try:
                execute_job(work, dependencies, signals)
            except BaseException as error:
                failures.append(error)

        thread = Thread(target=run, daemon=True)
        try:
            thread.start()
            assert started.wait(1)
            wait_for(lambda: saved_record(dependencies.engine).progress == progress(3))
            assert thread.is_alive() and not failures
        finally:
            signals.stopping.set()
            thread.join(timeout=3)
        assert not thread.is_alive() and not failures
        assert not any(item.is_alive() for item in signals.monitor.threads)


def test_flush_busy_delay(tmp_path: Path) -> None:
    """第1条：连续n次BEGIN忙保持最新值，每秒最多尝试一次；恢复可写后的首个截止落库，持续锁忙不承诺硬1秒。"""
    clock = MutableClock()
    with reporter_context(tmp_path, JobClock(clock.now, clock.monotonic)) as (
        reporter,
        engine,
        _,
        _,
    ):
        reporter.report(progress(1))
        with session_scope(engine):
            reporter.report(progress(3))
            for second in (101.0, 102.0):
                clock.seconds = second
                reporter.flush_due()
                assert reporter.next_flush_deadline() == second + 1
                reporter.check_cancelled()
                assert reporter.snapshot().progress == progress(3)
        clock.seconds = 102.999
        reporter.flush_due()
        assert saved_record(engine).progress == progress(1)
        clock.seconds = 103
        reporter.flush_due()
        assert saved_record(engine).progress == progress(3)


def test_flush_stop_priority(tmp_path: Path) -> None:
    """第1条：补写失败与取消同时出现优先取消；一次至多100毫秒短锁，不因数据库忙无限阻止取消。"""
    clock = MutableClock()
    with reporter_context(tmp_path, JobClock(clock.now, clock.monotonic)) as (
        reporter,
        engine,
        signals,
        _,
    ):
        reporter.report(progress(1))
        reporter.report(progress(3))
        with engine.begin() as connection:
            connection.exec_driver_sql(
                "CREATE TRIGGER reject_progress BEFORE UPDATE ON jobs BEGIN SELECT RAISE(ABORT, 'test'); END"
            )
        clock.seconds = 101
        signals.cancelled.set()
        with pytest.raises(JobCancelledError):
            reporter.check_cancelled()
        assert saved_record(engine).progress == progress(1)
        assert reporter.snapshot().progress == progress(3)


def test_resume_cumulative_baseline(tmp_path: Path) -> None:
    """第11条：续跑首报以previous_progress为累计基线，同阶段done/总条目/失败/警告均不得小于旧值，不接受局部增量。"""
    clock = MutableClock()
    with reporter_context(tmp_path, JobClock(clock.now, clock.monotonic), resume=True) as (
        reporter,
        _,
        _,
        _,
    ):
        for change in ({"done": 1}, {"total_items": 1}, {"failed_items": 0}, {"warning_count": 2}):
            with pytest.raises(DefectError):
                reporter.report(
                    JobProgress.model_validate(
                        progress(2, failed_items=1, warning_count=3).model_dump() | change
                    )
                )
        reporter.report(progress(3, failed_items=1, warning_count=4))
        assert reporter.snapshot().progress == progress(3, failed_items=1, warning_count=4)


def test_resume_stage_advance(tmp_path: Path) -> None:
    """第11条：续跑进入更高阶段done可归零，但累计计数不能归零；重跑才允许所有业务计数重置。"""
    clock = MutableClock()
    with reporter_context(
        tmp_path / "resume", JobClock(clock.now, clock.monotonic), resume=True
    ) as (reporter, _, _, _):
        with pytest.raises(DefectError):
            reporter.report(progress(0, stage_index=2))
        reporter.report(progress(0, stage_index=2, total_items=2, failed_items=1, warning_count=3))
        assert reporter.snapshot().progress == progress(
            0, stage_index=2, total_items=2, failed_items=1, warning_count=3
        )
    with reporter_context(tmp_path / "reset", JobClock(clock.now, clock.monotonic)) as (
        reporter,
        _,
        _,
        _,
    ):
        reporter.report(progress(0))
        assert reporter.snapshot().progress == progress(0)


def test_tool_exit_and_thread_ownership(tmp_path: Path) -> None:
    """上报边界保存真实负信号并拒绝bool；输出线程必须启动前登记daemon，容量有限、已结束线程可回收。"""
    clock = MutableClock()
    with reporter_context(tmp_path, JobClock(clock.now, clock.monotonic)) as (
        reporter,
        _,
        signals,
        _,
    ):
        assert reporter.snapshot().tool_exit_code is None
        for returncode in (0, 3, -9):
            reporter.tool_exit(returncode)
            assert reporter.snapshot().tool_exit_code == returncode
        with pytest.raises(DefectError):
            reporter.tool_exit(True)
        with pytest.raises(DefectError):
            reporter.track_output_thread(Thread())
        threads = [Thread(target=lambda: None, daemon=True) for _ in range(3)]
        try:
            for thread in threads:
                reporter.track_output_thread(thread)
            assert signals.monitor.threads == threads
            with pytest.raises(DefectError):
                reporter.track_output_thread(threads[0])
            with pytest.raises(DefectError):
                reporter.track_output_thread(Thread(daemon=True))
            threads[0].start()
            threads[0].join(timeout=1)
            replacement = Thread(daemon=True)
            reporter.track_output_thread(replacement)
            assert (
                threads[0] not in signals.monitor.threads and replacement in signals.monitor.threads
            )
        finally:
            for thread in threads:
                if thread.ident is not None:
                    thread.join(timeout=1)


def test_invalid_wait_and_diagnostic_identity(tmp_path: Path) -> None:
    """执行函数不能用非法时长或另一个作业的诊断污染当前作业；失败不改变快照。"""
    clock = MutableClock()
    with reporter_context(tmp_path, JobClock(clock.now, clock.monotonic)) as (reporter, _, _, _):
        for interval in (-1, 60.001, math.nan, math.inf, True):
            with pytest.raises(DefectError):
                reporter.wait(interval)
        value = diagnostic(1).model_dump() | {"objects": [{"key": "job_id", "value": "72"}]}
        from rdp.infra.diagnostics import Diagnostic

        with pytest.raises(DefectError):
            reporter.diagnostic(Diagnostic.model_validate(value))
        assert reporter.snapshot().diagnostics == ()
