"""M0/08 公共契约测试；数据库与文件只使用临时目录，不依赖真实数据或默认状态目录。"""

from datetime import timedelta
from pathlib import Path
from typing import cast

import pytest
from accounts_support import model_database
from jobs_execution_support import execution_case
from jobs_progress_support import progress, saved_record
from jobs_storage_support import NOW, PROGRESS, job_row

from rdp.infra.db.connection import session_scope
from rdp.infra.db.records import find_error
from rdp.infra.diagnostics import DefectError
from rdp.jobs.execution import ExecutionContext, execute_job
from rdp.jobs.outcome import JobOutcome
from rdp.jobs.records import StateChange, find_job, transition_job
from rdp.jobs.types import JobState


@pytest.mark.parametrize(
    ("source", "target"),
    [
        ("queued", "running"),
        ("queued", "cancelled"),
        ("running", "completed"),
        ("running", "cancelling"),
        ("cancelling", "cancelled"),
        ("running", "interrupted"),
    ],
)
def test_legal_edges(source: str, target: str, tmp_path: Path) -> None:
    """验收1：六条合法边逐条经过 transition_job，开始/结束时间、结果和摘要只由此函数写入。"""
    old, new = JobState(source), JobState(target)
    ended = NOW + timedelta(seconds=5)
    path = "logs/示例：数数/2026-10-26_120005_000.log" if new is JobState.RUNNING else None
    with model_database(tmp_path) as engine:
        with session_scope(engine) as session:
            session.add(job_row(old))
        with session_scope(engine) as session:
            before = find_job(session, 71)
            after = transition_job(session, 71, StateChange(old, new, ended, log_path=path))
            assert after.job_id == before.job_id and after.state is new
            assert after.progress == before.progress
            assert after.elapsed_s == before.elapsed_s
            assert after.started_at == (ended if new is JobState.RUNNING else before.started_at)
            if new in {JobState.COMPLETED, JobState.CANCELLED, JobState.INTERRUPTED}:
                assert after.ended_at == ended
                assert after.summary is not None and after.summary.state is new
                assert after.summary.outcome == (
                    JobOutcome.PARTIALLY_SUCCEEDED if new is JobState.COMPLETED else None
                )
                assert after.summary.progress == after.progress
                assert after.summary.artifacts == after.artifacts
            else:
                assert after.ended_at is after.summary is None
            assert after.log_path == (path if new is JobState.RUNNING else before.log_path)
        with session_scope(engine, read_only=True) as session:
            assert find_job(session, 71) == after


@pytest.mark.parametrize(
    ("source", "target"),
    [
        (source, target)
        for source in ("queued", "running", "cancelling", "completed", "cancelled", "interrupted")
        for target in ("queued", "running", "cancelling", "completed", "cancelled", "interrupted")
        if (source, target)
        not in {
            ("queued", "running"),
            ("queued", "cancelled"),
            ("running", "completed"),
            ("running", "cancelling"),
            ("cancelling", "cancelled"),
            ("running", "interrupted"),
        }
    ],
)
def test_illegal_edges(source: str, target: str, tmp_path: Path) -> None:
    """验收1：六态所有非法边（含自转换、取消转完成、恢复转排队）抛 DefectError，数据库不变。"""
    old, new = JobState(source), JobState(target)
    path = "logs/示例：数数/2026-10-26_120001_000.log" if new is JobState.RUNNING else None
    with model_database(tmp_path) as engine:
        with session_scope(engine) as session:
            session.add(job_row(old))
        with session_scope(engine, read_only=True) as session:
            before = find_job(session, 71)
        with pytest.raises(DefectError), session_scope(engine) as session:
            transition_job(
                session, 71, StateChange(old, new, NOW + timedelta(seconds=1), log_path=path)
            )
        with session_scope(engine, read_only=True) as session:
            assert find_job(session, 71) == before


@pytest.mark.parametrize(
    "case",
    [
        ("completed", 0, 0, 0, False, "succeeded"),
        ("completed", 3, 0, 0, False, "succeeded"),
        ("completed", 3, 0, 1, False, "succeeded_with_warnings"),
        ("completed", 3, 1, 2, False, "partially_succeeded"),
        ("completed", 3, 3, 0, False, "failed"),
        ("completed", 0, 0, 0, True, "failed"),
        ("cancelled", 3, 3, 2, False, None),
        ("interrupted", 3, 3, 2, False, None),
    ],
)
def test_completed_outcome_only(
    case: tuple[str, int, int, int, bool, str | None], tmp_path: Path
) -> None:
    """验收1/6：completed的结果按独立已知计数核对，cancelled/interrupted保留最后计数且outcome=None。"""
    target, total, failed, warnings, aborted, expected = case
    old = JobState.CANCELLING if target == "cancelled" else JobState.RUNNING
    row = job_row(old)
    row.total_items, row.failed_items, row.warning_count = total, failed, warnings
    row.progress = PROGRESS | {
        "done": total,
        "total": total,
        "total_items": total,
        "failed_items": failed,
        "warning_count": warnings,
    }
    with model_database(tmp_path) as engine:
        with session_scope(engine) as session:
            session.add(row)
        with session_scope(engine) as session:
            after = transition_job(
                session, 71, StateChange(old, JobState(target), NOW, aborted=aborted)
            )
        assert after.summary is not None
        assert after.summary.outcome == expected
        assert (
            after.summary.total_items,
            after.summary.failed_items,
            after.summary.warning_count,
            after.summary.aborted,
        ) == (total, failed, warnings, aborted)
        assert after.progress is not None and after.progress.total_items == total


def test_cancel_wins_return(tmp_path: Path) -> None:
    """验收4：函数收到取消后正常返回，最终仍 cancelled，不能 completed。"""

    def cancel(context: ExecutionContext) -> None:
        context.reporter.report(progress(1))
        with session_scope(dependencies.engine) as session:
            transition_job(session, 71, StateChange(JobState.RUNNING, JobState.CANCELLING, NOW))
        signals.cancelled.set()

    with execution_case(tmp_path, {"steps": 3, "interval_ms": 0}, cancel) as (
        work,
        dependencies,
        signals,
    ):
        record = execute_job(work, dependencies, signals)
        assert record is not None and record.state is JobState.CANCELLED
        assert record.summary is not None and record.summary.outcome is None
        assert record.progress == progress(1) and not record.summary.aborted


def test_cancel_wins_exception(tmp_path: Path) -> None:
    """验收4：函数在取消后抛异常，最终 cancelled，无作业结果，原诊断保留。"""

    def cancel(context: ExecutionContext) -> None:
        context.reporter.report(progress(1))
        with session_scope(dependencies.engine) as session:
            transition_job(session, 71, StateChange(JobState.RUNNING, JobState.CANCELLING, NOW))
        signals.cancelled.set()
        raise RuntimeError("取消后异常")

    with execution_case(tmp_path, {"steps": 3, "interval_ms": 0}, cancel) as (
        work,
        dependencies,
        signals,
    ):
        record = execute_job(work, dependencies, signals)
        assert record is not None and record.state is JobState.CANCELLED
        assert record.summary is not None and record.summary.outcome is None
        assert record.progress == progress(1) and not record.summary.aborted
        assert record.diagnostics and "RuntimeError" in record.diagnostics[0].samples[0].actual


def test_execution_exception(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """规范6.3/6.11：执行异常记录对象编号/实际/后果，completed 且 aborted=True、结果失败，仅边界一次 ERROR。"""

    def broken(context: ExecutionContext) -> None:
        context.reporter.report(progress(2))
        raise RuntimeError("测试错误可定位")

    with execution_case(tmp_path, {"steps": 3, "interval_ms": 0}, broken) as (
        work,
        dependencies,
        signals,
    ):
        with caplog.at_level("ERROR"):
            record = execute_job(work, dependencies, signals)
        assert record is not None and record == saved_record(dependencies.engine)
        assert record.summary is not None and (
            record.state.value,
            record.summary.outcome,
            record.summary.aborted,
        ) == ("completed", "failed", True)
        diagnostic = record.diagnostics[0].samples[0]
        assert any(item.key == "job_id" and item.value == "71" for item in diagnostic.objects)
        assert diagnostic.actual and diagnostic.consequence
        errors = [item for item in caplog.records if item.levelname == "ERROR"]
        assert len(errors) == 1
        with session_scope(dependencies.engine, read_only=True) as session:
            report = find_error(session, "71")
        assert report is not None and report.source_kind == "job"
        assert "RuntimeError" in report.report and "broken" in report.report
        assert report.report in errors[0].getMessage()


def test_final_commit_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """验收5：普通锁预算用尽仍无法提交终态，ERROR 且保持 running，日志无虚假最终摘要，worker停止领取及心跳并以WORKER_EXIT_FAILURE有界退出，不抛停止超时。"""
    from threading import Event

    from jobs_loop_support import running_loop

    from rdp.infra.db import connection
    from rdp.jobs import policy
    from rdp.jobs.types import RecoveryMode

    monkeypatch.setattr(connection, "BUSY_TIMEOUT_MS", 40)
    monkeypatch.setattr(policy, "PROGRESS_LOCK_TIMEOUT_MS", 20)
    monkeypatch.setattr(policy, "WORKER_POLL_INTERVAL_S", 0.005)
    entered, release = Event(), Event()

    def execute(_: ExecutionContext) -> None:
        entered.set()
        assert release.wait(2)

    with execution_case(
        tmp_path, {"steps": 3, "interval_ms": 0}, execute, mode=RecoveryMode.RESUME
    ) as (work, dependencies, _):
        with session_scope(dependencies.engine) as session:
            session.add(job_row(JobState.QUEUED, job_id=72))
        with running_loop(dependencies) as (_, thread, results):
            try:
                assert entered.wait(2)
                with session_scope(dependencies.engine):
                    release.set()
                    thread.join(timeout=2)
                    assert not thread.is_alive() and results[0].code == 1
            finally:
                release.set()
        with session_scope(dependencies.engine, read_only=True) as session:
            assert find_job(session, 71).state is JobState.RUNNING
            assert find_job(session, 72).state is JobState.QUEUED
        assert work.record.log_path is not None
        assert "summary=" not in (dependencies.paths.root / work.record.log_path).read_text()
        errors = [entry for entry in caplog.records if entry.levelname == "ERROR"]
        assert len(errors) == 1 and "终态持久化失败" in errors[0].getMessage()


def test_clock_rollback(tmp_path: Path) -> None:
    """规范5.4：墙钟回拨不拒绝状态转换，UTC时刻如实保存，elapsed取单调片段而非负墙钟差。"""
    earlier = NOW - timedelta(days=1)
    with model_database(tmp_path) as engine:
        with session_scope(engine) as session:
            session.add(job_row())
        with session_scope(engine) as session:
            after = transition_job(
                session, 71, StateChange(JobState.RUNNING, JobState.COMPLETED, earlier)
            )
        assert (after.started_at, after.ended_at, after.elapsed_s) == (NOW, earlier, 2.5)
        assert after.summary is not None and after.summary.elapsed_s == 2.5


def test_queued_cancel_summary(tmp_path: Path) -> None:
    """验收4/7：未领取即取消没有 started_at/log_path，计数零、无结果，终态摘要完整。"""
    with model_database(tmp_path) as engine:
        with session_scope(engine) as session:
            session.add(job_row(JobState.QUEUED))
        with session_scope(engine) as session:
            after = transition_job(
                session, 71, StateChange(JobState.QUEUED, JobState.CANCELLED, NOW)
            )
        assert after.started_at is after.log_path is after.progress is None
        assert after.ended_at == NOW
        assert after.summary is not None
        assert (
            after.summary.total_items,
            after.summary.failed_items,
            after.summary.warning_count,
            after.summary.elapsed_s,
        ) == (0, 0, 0, 0)
        assert after.summary.outcome is None and after.summary.aborted is False
        assert after.summary.artifacts == () and after.summary.tool_exit_code is None


def test_transition_rejects_invalid_change_and_detects_stale_state(tmp_path: Path) -> None:
    """转换边界：非法时钟/枚举/中止标记/非规范日志路径拒绝；合法意图遇过时状态才是带编号的ConflictError。"""
    from rdp.infra.diagnostics import ConflictError

    valid_path = "logs/示例：数数/2026-10-26_120000_000.log"
    invalid = [
        StateChange(JobState.QUEUED, JobState.RUNNING, NOW),
        StateChange(
            JobState.QUEUED, JobState.RUNNING, NOW.replace(tzinfo=None), log_path=valid_path
        ),
        StateChange(cast(JobState, "queued"), JobState.RUNNING, NOW, log_path=valid_path),
        StateChange(JobState.QUEUED, cast(JobState, "running"), NOW, log_path=valid_path),
        StateChange(JobState.QUEUED, JobState.CANCELLED, NOW, aborted=True),
        StateChange(JobState.QUEUED, JobState.CANCELLED, NOW, log_path=valid_path),
    ]
    invalid += [
        StateChange(JobState.QUEUED, JobState.RUNNING, NOW, log_path=value)
        for value in (
            str(tmp_path / "outside.log"),
            "logs/../outside.log",
            "logs//类型/file.log",
            "logs/类型/file.log/",
            "logs/类型/file.txt",
        )
    ]
    with model_database(tmp_path) as engine:
        with session_scope(engine) as session:
            session.add(job_row(JobState.QUEUED))
        for change in invalid:
            with pytest.raises(DefectError), session_scope(engine) as session:
                transition_job(session, 71, change)
        with session_scope(engine) as session:
            transition_job(session, 71, StateChange(JobState.QUEUED, JobState.CANCELLED, NOW))
        with pytest.raises(ConflictError) as caught, session_scope(engine) as session:
            transition_job(
                session,
                71,
                StateChange(JobState.QUEUED, JobState.RUNNING, NOW, log_path=valid_path),
            )
        assert any(
            item.key == "job_id" and item.value == "71"
            for item in caught.value.diagnostics[0].objects
        )
        with session_scope(engine, read_only=True) as session:
            assert find_job(session, 71).state is JobState.CANCELLED
