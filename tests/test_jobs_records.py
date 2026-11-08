"""作业记录公共存取边界测试；调用方持有临时库事务，不接触真实数据或导航层。"""

from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from typing import cast

import pytest
from accounts_support import model_database
from db_support import sqlite_connection
from jobs_storage_support import NOW, PROGRESS, job_database, job_row
from sqlalchemy import select
from sqlalchemy.orm import Session

from rdp.infra.actors import ActorRef
from rdp.infra.db.connection import session_scope
from rdp.infra.diagnostics import (
    ConflictError,
    DefectError,
    Diagnostic,
    DiagnosticCategory,
    DiagnosticGroup,
    DiagnosticLevel,
    InputError,
)
from rdp.jobs.errors import JobInputError, JobNotFoundError
from rdp.jobs.models import WorkerHeartbeatRow
from rdp.jobs.records import (
    NewJob,
    claim_job,
    find_job,
    insert_job,
    next_queued_job,
    save_heartbeat,
    save_progress,
)
from rdp.jobs.registry import production_registry
from rdp.jobs.types import ExecutionSnapshot, JobProgress, JobState, RecoveryMode, WorkerHeartbeat


def test_find_job_detached_snapshot(tmp_path: Path) -> None:
    """读取公共记录返回脱离Session的完整快照，UTC、历史身份、独立计数和未知/空字段不丢失。"""
    with model_database(tmp_path) as engine:
        with session_scope(engine) as session:
            session.add(job_row())
        with session_scope(engine, read_only=True) as session:
            record = find_job(session, 71)
        assert (record.job_id, record.state, record.recovery_mode, record.recovery_count) == (
            71,
            JobState.RUNNING,
            RecoveryMode.INTERRUPT,
            0,
        )
        assert record.submitted_by == ActorRef(7, "历史提交人")
        assert record.submitted_at == record.started_at == record.progress_at == NOW
        assert record.ended_at is record.summary is record.resubmitted_from is None
        # M4-02：历史JSON未存parts时仍可读，默认投影为空元组。
        assert record.progress is not None and record.progress.model_dump() == PROGRESS | {
            "parts": ()
        }
        assert record.parameters == {"steps": 4, "interval_ms": 0}
        assert record.artifacts == ("产物/样例",)
        assert (record.elapsed_s, record.tool_exit_code, record.diagnostics) == (2.5, 0, ())
        record.parameters["steps"] = 100
        with session_scope(engine, read_only=True) as session:
            assert find_job(session, 71).parameters["steps"] == 4


def test_find_rejects_invalid_missing_and_unmanaged(tmp_path: Path) -> None:
    """记录边界：非法编号为安全输入诊断，查无编号含对象身份，非受管Session拒绝，不静默制造空记录。"""
    with model_database(tmp_path) as engine:
        for identifier in (0, -1, True, 2**63, cast(int, "sensitive-marker")):
            with session_scope(engine, read_only=True) as session:
                with pytest.raises(JobInputError) as caught:
                    find_job(session, identifier)
                assert "sensitive-marker" not in str(caught.value)
        with session_scope(engine, read_only=True) as session:
            with pytest.raises(JobNotFoundError) as caught_missing:
                find_job(session, 999)
            diagnostic = caught_missing.value.diagnostics[0]
            assert any(item.key == "job_id" and item.value == "999" for item in diagnostic.objects)
            assert diagnostic.actual and diagnostic.consequence
        with Session(engine) as unmanaged, pytest.raises(DefectError):
            find_job(unmanaged, 71)


@pytest.mark.parametrize(
    "case",
    ["state", "counts", "summary", "outcome", "started", "recovery", "json", "parameters_shape"],
)
def test_find_rejects_corrupt_record(case: str, tmp_path: Path) -> None:
    """存量故障：状态/计数/摘要矛盾为DefectError，参数JSON损坏或非对象为InputError，不能回显载荷。"""
    with model_database(tmp_path) as engine:
        with session_scope(engine) as session:
            session.add(
                job_row(JobState.COMPLETED if case in {"summary", "outcome"} else JobState.RUNNING)
            )
        assert engine.url.database is not None
        with sqlite_connection(engine.url.database) as connection:
            connection.execute("PRAGMA ignore_check_constraints=ON")
            statements = {
                "state": "UPDATE jobs SET state='unknown'",
                "counts": "UPDATE jobs SET failed_items=0",
                "summary": "UPDATE jobs SET summary=json_set(summary,'$.state','cancelled')",
                "outcome": "UPDATE jobs SET outcome='succeeded'",
                "started": "UPDATE jobs SET started_at=NULL",
                "recovery": "UPDATE jobs SET recovery_count=4",
                "json": "UPDATE jobs SET parameters='{sensitive-marker'",
                "parameters_shape": "UPDATE jobs SET parameters='[]'",
            }
            connection.execute(statements[case])
        failure = InputError if case in {"json", "parameters_shape"} else DefectError
        with session_scope(engine, read_only=True) as session, pytest.raises(failure) as caught:
            find_job(session, 71)
        assert "sensitive-marker" not in str(caught.value)


def test_insert_is_owned_by_callers_transaction(tmp_path: Path) -> None:
    """插入公共边界：分配排队记录但不自行提交，调用者回滚即消失，提交后参数快照与身份永久保存。"""
    definition = production_registry().lookup("example_count")
    assert definition is not None
    parameters: dict[str, object] = {"steps": 4, "interval_ms": 0}
    command = NewJob(definition, parameters, ActorRef(7, "提交者"), NOW, None)
    first = None
    with model_database(tmp_path) as engine:
        with pytest.raises(RuntimeError, match="回滚"), session_scope(engine) as session:
            first = insert_job(session, command)
            assert first.state is JobState.QUEUED and first.job_id > 0
            with pytest.raises(JobNotFoundError), session_scope(engine, read_only=True) as reader:
                find_job(reader, first.job_id)
            raise RuntimeError("回滚")
        assert first is not None
        with pytest.raises(JobNotFoundError), session_scope(engine, read_only=True) as reader:
            find_job(reader, first.job_id)
        with session_scope(engine) as session:
            saved = insert_job(session, command)
        parameters["steps"] = 999
        with session_scope(engine, read_only=True) as reader:
            result = find_job(reader, saved.job_id)
        assert result.parameters == {"steps": 4, "interval_ms": 0}
        assert result.submitted_by == ActorRef(7, "提交者")
        assert result.submitted_at == NOW and result.recovery_count == 0
        assert (
            result.started_at
            is result.ended_at
            is result.log_path
            is result.progress
            is result.summary
            is None
        )
        assert result.elapsed_s == 0 and result.artifacts == () and result.diagnostics == ()


def test_next_job_uses_id_and_does_not_claim(tmp_path: Path) -> None:
    """领取候选只按自增编号，回拨不改提交顺序，空队列返回None；选择只读、不预占状态，也不跳过旧类型。"""
    with model_database(tmp_path) as engine:
        with session_scope(engine, read_only=True) as session:
            assert next_queued_job(session) is None
        first, second = job_row(JobState.QUEUED, job_id=71), job_row(JobState.QUEUED, job_id=72)
        first.submitted_at = NOW + timedelta(days=1)
        first.type_name = "removed_type"
        with session_scope(engine) as session:
            session.add_all([job_row(JobState.CANCELLED, job_id=70), second, first])
        with session_scope(engine, read_only=True) as session:
            selected = next_queued_job(session)
            assert selected is not None and (
                selected.job_id,
                selected.type_name,
                selected.state,
            ) == (71, "removed_type", JobState.QUEUED)
            assert find_job(session, 72).state is JobState.QUEUED
        with pytest.raises(DefectError), session_scope(engine) as session:
            next_queued_job(session)


def test_claim_registers_unique_log_path_in_transaction(tmp_path: Path) -> None:
    """领取原子预留UTC日志路径，同毫秒按数据库已登记路径避让；领取不创建日志文件。"""
    with job_database(tmp_path) as (engine, paths):
        with session_scope(engine) as session:
            session.add_all(
                [job_row(JobState.QUEUED, job_id=71), job_row(JobState.QUEUED, job_id=72)]
            )
        with session_scope(engine) as session:
            first = claim_job(session, 71, now=NOW, paths=paths, gpu_index=None)
        with session_scope(engine) as session:
            second = claim_job(session, 72, now=NOW, paths=paths, gpu_index=None)
        assert (first.state, first.started_at, first.log_path) == (
            JobState.RUNNING,
            NOW,
            "logs/示例：数数/2026-10-26_120000_000.log",
        )
        assert second.log_path == "logs/示例：数数/2026-10-26_120000_000_72.log"
        assert tuple(paths.logs.rglob("*.log")) == ()
        with session_scope(engine, read_only=True) as session:
            assert find_job(session, 71) == first
            assert find_job(session, 72) == second


def test_insert_rejects_invalid_commands_before_writing(tmp_path: Path) -> None:
    """内部提交命令的身份/时间/参数/登记定义非法为DefectError，不能先写坏行或隐式补参数。"""
    definition = production_registry().lookup("example_count")
    assert definition is not None
    valid = NewJob(definition, {"steps": 4, "interval_ms": 0}, ActorRef(7, "提交者"), NOW, None)
    commands = (
        replace(valid, actor=ActorRef(None, "运维")),
        replace(valid, actor=ActorRef(0, "无效")),
        replace(valid, actor=ActorRef(7, " ")),
        replace(valid, now=NOW.replace(tzinfo=None)),
        replace(valid, resubmitted_from=0),
        replace(valid, parameters={"steps": 0, "interval_ms": 0}),
        replace(valid, parameters={"steps": 4, "interval_ms": 0, "password": "sensitive-marker"}),
        replace(valid, parameters={"steps": 4, "interval_ms": "x" * 20000}),
        replace(valid, definition=replace(definition, display_name="../bad")),
        cast(NewJob, None),
    )
    with model_database(tmp_path) as engine:
        for command in commands:
            with pytest.raises(DefectError) as caught, session_scope(engine) as session:
                insert_job(session, command)
            assert "sensitive-marker" not in str(caught.value)
        with session_scope(engine, read_only=True) as session:
            assert next_queued_job(session) is None


def test_save_progress_atomic_latest_snapshot(tmp_path: Path) -> None:
    """快照存取：未知total、独立计数、耗时、产物和退出码同事务更新，状态不变且调用者回滚有效。"""
    progress = JobProgress.model_validate(
        PROGRESS
        | {"done": 3, "total": None, "total_items": 3, "failed_items": 1, "warning_count": 4}
    )
    snapshot = ExecutionSnapshot(progress, (), ("产物/新样例",), -9, 5.0)
    updated = NOW + timedelta(seconds=1)
    with model_database(tmp_path) as engine:
        with session_scope(engine) as session:
            session.add(job_row())
        with pytest.raises(RuntimeError, match="回滚"), session_scope(engine) as session:
            save_progress(session, 71, snapshot, now=updated)
            assert find_job(session, 71).progress == progress
            raise RuntimeError("回滚")
        with session_scope(engine, read_only=True) as session:
            assert find_job(session, 71).progress_at == NOW
        with session_scope(engine) as session:
            assert save_progress(session, 71, snapshot, now=updated) is None
        with session_scope(engine, read_only=True) as session:
            result = find_job(session, 71)
        assert (result.state, result.started_at, result.ended_at) == (JobState.RUNNING, NOW, None)
        assert (
            result.progress is not None
            and result.progress == progress
            and result.progress_at == updated
        )
        assert result.progress.total is None
        assert (result.elapsed_s, result.artifacts, result.tool_exit_code) == (
            5.0,
            ("产物/新样例",),
            -9,
        )
        assert result.summary is None


def test_save_progress_rejects_invalid_snapshot_and_terminal(tmp_path: Path) -> None:
    """快照写入拒绝负/非有限时长、超容量产物/诊断和伪造进度，None不能覆盖已有进度，终态不再接受写入。"""
    from rdp.infra.diagnostics import ConflictError

    progress = JobProgress.model_validate(PROGRESS)
    valid = ExecutionSnapshot(progress, (), (), None, 3.0)
    diagnostic = Diagnostic(
        level=DiagnosticLevel.ERROR,
        category=DiagnosticCategory.EXTERNAL,
        stage="处理",
        source="平台",
        objects=(),
        rule="规则",
        actual="失败",
        expected="成功",
        consequence="条目失败",
        next_step="检查日志",
    )
    groups = tuple(
        DiagnosticGroup(
            source="平台",
            rule=f"规则{index}",
            total=1,
            error_count=1,
            warning_count=0,
            samples=(
                Diagnostic.model_validate(diagnostic.model_dump() | {"rule": f"规则{index}"}),
            ),
        )
        for index in range(102)
    )
    invalid = (
        replace(valid, elapsed_s=-1),
        replace(valid, elapsed_s=float("inf")),
        replace(valid, elapsed_s=float("nan")),
        replace(valid, artifacts=("",)),
        replace(valid, artifacts=("x" * 4097,)),
        replace(valid, artifacts=tuple(str(i) for i in range(101))),
        replace(valid, diagnostics=groups),
        replace(valid, progress=None),
        replace(
            valid,
            progress=JobProgress.model_construct(
                stage_index=1,
                stage_count=2,
                stage_name="处理",
                done=2,
                total=4,
                unit="条",
                warning_count=3,
                failed_items=99,
                total_items=2,
            ),
        ),
    )
    with model_database(tmp_path) as engine:
        with session_scope(engine) as session:
            session.add(job_row())
            session.add(job_row(JobState.COMPLETED, job_id=72))
        for snapshot in invalid:
            with pytest.raises(DefectError), session_scope(engine) as session:
                save_progress(session, 71, snapshot, now=NOW)
        with pytest.raises(ConflictError), session_scope(engine) as session:
            save_progress(session, 72, valid, now=NOW)
        with session_scope(engine, read_only=True) as session:
            assert find_job(session, 71).progress == progress


def test_save_progress_diagnostic_group_invariants(tmp_path: Path) -> None:
    """诊断聚合边界：总数与错误/警告口径及前N样例一致，不能保存超限样例、重复组或不匹配来源。"""
    diagnostic = Diagnostic(
        level=DiagnosticLevel.ERROR,
        category=DiagnosticCategory.EXTERNAL,
        stage="处理",
        source="平台",
        objects=(),
        rule="规则",
        actual="失败",
        expected="成功",
        consequence="条目失败",
        next_step="检查日志",
    )
    group = DiagnosticGroup("平台", "规则", 1, 1, 0, (diagnostic,))
    snapshot = ExecutionSnapshot(JobProgress.model_validate(PROGRESS), (group,), (), None, 3.0)
    invalid = (
        (replace(group, total=11, error_count=11, samples=(diagnostic,) * 11),),
        (replace(group, total=0, error_count=0),),
        (replace(group, error_count=0),),
        (replace(group, source="另一来源"),),
        (group, group),
    )
    with model_database(tmp_path) as engine:
        with session_scope(engine) as session:
            session.add(job_row())
        for groups in invalid:
            with pytest.raises(DefectError), session_scope(engine) as session:
                save_progress(session, 71, replace(snapshot, diagnostics=groups), now=NOW)
        with session_scope(engine) as session:
            save_progress(session, 71, snapshot, now=NOW)
        with session_scope(engine, read_only=True) as session:
            assert find_job(session, 71).diagnostics == (group,)


def test_save_progress_preserves_overflow_diagnostic_sources(tmp_path: Path) -> None:
    """第101个溢出组允许不同规则/来源样例，保留原诊断身份，不能为满足聚合键而改写来源。"""
    diagnostic = Diagnostic(
        level=DiagnosticLevel.ERROR,
        category=DiagnosticCategory.EXTERNAL,
        stage="处理",
        source="平台",
        objects=(),
        rule="规则",
        actual="失败",
        expected="成功",
        consequence="条目失败",
        next_step="检查日志",
    )
    groups = tuple(
        DiagnosticGroup(
            "平台",
            f"规则{i}",
            1,
            1,
            0,
            (Diagnostic.model_validate(diagnostic.model_dump() | {"rule": f"规则{i}"}),),
        )
        for i in range(100)
    )
    samples = (
        Diagnostic.model_validate(diagnostic.model_dump() | {"source": "工具甲", "rule": "新规则"}),
    )
    overflow = DiagnosticGroup("平台", "诊断规则种类超过上限", 1, 1, 0, samples)
    snapshot = ExecutionSnapshot(
        JobProgress.model_validate(PROGRESS), groups + (overflow,), (), None, 3.0
    )
    with model_database(tmp_path) as engine:
        with session_scope(engine) as session:
            session.add(job_row())
        with session_scope(engine) as session:
            save_progress(session, 71, snapshot, now=NOW)
        with session_scope(engine, read_only=True) as session:
            result = find_job(session, 71)
        assert len(result.diagnostics) == 101
        assert result.diagnostics[-1].samples == samples
        assert result.diagnostics[-1].total == 1


def test_heartbeat_singleton_transaction_and_validation(tmp_path: Path) -> None:
    """心跳存取边界：实例更新同一行且UTC回拨合法，调用者回滚保留旧值，非法身份/时刻或只读写入拒绝。"""
    first = WorkerHeartbeat("00000000000040008000000000000001", 123, NOW, NOW)
    second = WorkerHeartbeat(
        "00000000000040008000000000000002",
        456,
        NOW + timedelta(seconds=1),
        NOW - timedelta(seconds=1),
    )
    with model_database(tmp_path) as engine:
        with session_scope(engine) as session:
            assert save_heartbeat(session, first) is None
        with session_scope(engine) as session:
            save_heartbeat(session, second)
        with pytest.raises(RuntimeError, match="回滚"), session_scope(engine) as session:
            save_heartbeat(session, first)
            raise RuntimeError("回滚")
        with session_scope(engine, read_only=True) as session:
            rows = session.scalars(select(WorkerHeartbeatRow)).all()
            assert len(rows) == 1 and rows[0].singleton_id == 1
            assert (rows[0].instance_id, rows[0].pid, rows[0].started_at, rows[0].last_seen_at) == (
                second.instance_id,
                456,
                second.started_at,
                second.last_seen_at,
            )
        with pytest.raises(DefectError), session_scope(engine) as session:
            save_heartbeat(session, replace(first, pid=0))
        with pytest.raises(DefectError), session_scope(engine, read_only=True) as session:
            save_heartbeat(session, first)


def test_insert_exhausted_id_is_conflict(tmp_path: Path) -> None:
    """编号永久不复用：历史序列已达SQLite上限即使行已删除也归ConflictError，不误报磁盘已满。"""
    definition = production_registry().lookup("example_count")
    assert definition is not None
    command = NewJob(definition, {"steps": 4, "interval_ms": 0}, ActorRef(7, "提交者"), NOW, None)
    with model_database(tmp_path) as engine:
        with session_scope(engine) as session:
            insert_job(session, command)
        assert engine.url.database is not None
        with sqlite_connection(engine.url.database) as connection:
            connection.execute("DELETE FROM jobs")
            connection.execute(
                "UPDATE sqlite_sequence SET seq=9223372036854775807 WHERE name='jobs'"
            )
        with pytest.raises(ConflictError) as caught, session_scope(engine) as session:
            insert_job(session, command)
        diagnostic = caught.value.diagnostics[0]
        assert "编号" in diagnostic.actual
        assert diagnostic.consequence and diagnostic.next_step
        with session_scope(engine, read_only=True) as session:
            assert next_queued_job(session) is None
