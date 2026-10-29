"""清除作业的事务、保留期和执行摘要测试；只使用临时数据库。"""

from datetime import timedelta
from pathlib import Path

import pytest
from jobs_maintenance_support import maintenance_work, seed_audit
from jobs_schedules_support import scheduled_case
from jobs_storage_support import NOW
from sqlalchemy import event, func, select
from sqlalchemy.orm import Session

from rdp.audit.models import LoginLogRow, OperationLogRow
from rdp.infra.db.connection import session_scope
from rdp.jobs.execution import execute_job
from rdp.jobs.records import StateChange, transition_job
from rdp.jobs.types import JobState


def test_two_rules() -> None:
    """验收7：生产每天03:00登记两个清除作业和M1统计；后者为全量参数，三个类型均可重跑。"""
    from datetime import time

    from rdp.jobs.registry import production_registry
    from rdp.jobs.schedules import production_schedules
    from rdp.jobs.types import RecoveryMode

    registry = production_registry()
    rules = production_schedules(registry).definitions()
    assert {(rule.name, rule.type_name, rule.local_time) for rule in rules} == {
        ("清除过期报错", "purge_errors", time(3)),
        ("清除过期日志", "purge_audit_logs", time(3)),
        ("统计数据集大小", "dataset_sizing", time(3)),
    }
    assert len(rules) == 3 and all(
        rule.parameters == ({"dataset_id": None} if rule.type_name == "dataset_sizing" else {})
        for rule in rules
    )
    for rule in rules:
        definition = registry.lookup(rule.type_name)
        assert definition is not None and definition.recovery_mode is RecoveryMode.RESTART


def test_errors_boundary(tmp_path: Path) -> None:
    """验收7：报错保留期取配置，严格早于UTC截止才删；恰好边界、较新、未来记录都留。"""
    from datetime import timedelta

    from jobs_maintenance_support import seed_errors
    from jobs_storage_support import NOW, job_database
    from sqlalchemy import select

    from rdp.infra.db.connection import session_scope
    from rdp.infra.db.models import ErrorReportRow
    from rdp.jobs.maintenance import MaintenanceService

    cutoff = NOW - timedelta(days=7)
    with job_database(tmp_path) as (engine, _paths):
        seed_errors(
            engine,
            (
                cutoff - timedelta(microseconds=1),
                cutoff,
                cutoff + timedelta(microseconds=1),
                NOW + timedelta(days=1),
            ),
        )
        service = MaintenanceService(engine, 7)
        assert service.purge_errors(NOW) == 1
        with session_scope(engine, read_only=True) as session:
            assert set(session.scalars(select(ErrorReportRow.error_id))) == {"2", "3", "4"}
        assert service.purge_errors(NOW) == 0


def test_audit_boundary(tmp_path: Path) -> None:
    """验收7：操作/登录日志用当前共同保留期，分别断言严格早于才删、边界及未来均留。"""
    from datetime import timedelta

    from jobs_maintenance_support import seed_audit
    from jobs_storage_support import NOW, job_database
    from sqlalchemy import select

    from rdp.audit.models import LoginLogRow, OperationLogRow
    from rdp.infra.db.connection import session_scope
    from rdp.jobs.maintenance import MaintenanceService

    cutoff = NOW - timedelta(days=30)
    moments = (
        cutoff - timedelta(microseconds=1),
        cutoff,
        cutoff + timedelta(microseconds=1),
        NOW + timedelta(days=1),
    )
    with job_database(tmp_path) as (engine, _paths):
        seed_audit(engine, moments, moments)
        result = MaintenanceService(engine, 7).purge_logs(NOW)
        assert (
            result.operation_count,
            result.login_count,
            result.retention_days,
            result.cutoff,
        ) == (1, 1, 30, cutoff)
        with session_scope(engine, read_only=True) as session:
            for table in (OperationLogRow, LoginLogRow):
                assert set(session.scalars(select(table.occurred_at))) == set(moments[1:])


def test_audit_atomic(tmp_path: Path) -> None:
    """验收7：第二张日志表删除失败时第一张也回滚，作业失败而非成功零计数。"""
    from datetime import timedelta

    from jobs_maintenance_support import maintenance_work, seed_audit
    from jobs_schedules_support import scheduled_case
    from jobs_storage_support import NOW
    from sqlalchemy import event, func, select

    from rdp.audit.models import LoginLogRow, OperationLogRow
    from rdp.infra.db.connection import session_scope
    from rdp.jobs.execution import execute_job

    old = NOW - timedelta(days=40)
    with scheduled_case(tmp_path, NOW) as case:
        engine = case.dependencies.engine
        seed_audit(engine, (old,), (old,))
        work, signals = maintenance_work(case, "purge_audit_logs")

        def fail(*args: object) -> None:
            if isinstance(args[2], str) and args[2].startswith("DELETE FROM login_logs"):
                raise OSError("模拟第二表删除失败")

        event.listen(engine, "before_cursor_execute", fail)
        try:
            result = execute_job(work, case.dependencies, signals)
        finally:
            event.remove(engine, "before_cursor_execute", fail)
        assert (
            result is not None and result.summary is not None and result.summary.outcome == "failed"
        )
        assert result.diagnostics[0].samples[0].category == "external"
        with session_scope(engine, read_only=True) as session:
            for table in (OperationLogRow, LoginLogRow):
                assert (
                    session.scalar(
                        select(func.count()).select_from(table).where(table.occurred_at == old)
                    )
                    == 1
                )


def test_zero_counts(tmp_path: Path) -> None:
    """契约：无匹配记录仍完成，摘要零条；正常结果只由calculate_outcome计算，不写假失败。"""
    from jobs_maintenance_support import maintenance_work
    from jobs_schedules_support import scheduled_case
    from jobs_storage_support import NOW

    from rdp.jobs.execution import execute_job

    with scheduled_case(tmp_path, NOW) as case:
        for kind in ("purge_errors", "purge_audit_logs"):
            work, signals = maintenance_work(case, kind)
            result = execute_job(work, case.dependencies, signals)
            assert (
                result is not None
                and result.summary is not None
                and result.summary.outcome == "succeeded"
            )
            summary = result.summary
            assert summary.total_items == summary.failed_items == summary.warning_count == 0
            assert (
                summary.progress is not None
                and summary.progress.done == 0
                and summary.progress.unit == "条"
            )


def test_summary_counts(tmp_path: Path) -> None:
    """契约：报错删除数写入摘要，日志清除的两类独立计数在摘要可辨别，总条目为两数之和，日志结尾一致。"""
    import json
    from datetime import timedelta

    from jobs_maintenance_support import maintenance_work, seed_audit, seed_errors
    from jobs_schedules_support import scheduled_case
    from jobs_storage_support import NOW

    from rdp.jobs.execution import execute_job

    old = NOW - timedelta(days=40)
    with scheduled_case(tmp_path, NOW) as case:
        seed_errors(case.dependencies.engine, (old, old, old, NOW))
        seed_audit(case.dependencies.engine, (old, old), (old, old, old))
        for kind, expected in (("purge_errors", 3), ("purge_audit_logs", 5)):
            work, signals = maintenance_work(case, kind)
            result = execute_job(work, case.dependencies, signals)
            assert (
                result is not None
                and result.summary is not None
                and result.summary.outcome == "succeeded"
            )
            assert result.summary.total_items == expected and result.summary.progress is not None
            if kind == "purge_audit_logs":
                assert (
                    "操作日志删除2条" in result.summary.progress.stage_name
                    and "登录日志删除3条" in result.summary.progress.stage_name
                )
            assert result.log_path is not None
            text = (case.dependencies.paths.root / result.log_path).read_text(encoding="utf-8")
            saved = json.loads(text.split("作业结尾 summary=", 1)[1].splitlines()[0])
            assert (saved["total_items"], saved["failed_items"], saved["warning_count"]) == (
                expected,
                0,
                0,
            )
            assert saved["progress"]["stage_name"] == result.summary.progress.stage_name
            assert saved["outcome"] == "succeeded"


def test_retention_runtime(tmp_path: Path) -> None:
    """契约：提交以后修改日志保留设置，执行时用最新值；报错保留期来自worker配置而非作业参数。"""
    from dataclasses import replace
    from datetime import timedelta

    from accounts_support import AUDIT_CONTEXT
    from jobs_maintenance_support import maintenance_work, seed_audit, seed_errors
    from jobs_schedules_support import scheduled_case
    from jobs_storage_support import NOW

    from rdp.audit.records import change_retention
    from rdp.audit.types import RetentionChange
    from rdp.infra.actors import ActorRef
    from rdp.infra.db.connection import session_scope
    from rdp.jobs.execution import execute_job

    old = NOW - timedelta(days=10)
    with scheduled_case(tmp_path, NOW) as case:
        seed_audit(case.dependencies.engine, (old,), (old,))
        work, signals = maintenance_work(case, "purge_audit_logs")
        with session_scope(case.dependencies.engine) as session:
            change_retention(session, RetentionChange(7, ActorRef(7, "管理员"), AUDIT_CONTEXT, NOW))
        result = execute_job(work, case.dependencies, signals)
        assert result is not None and result.summary is not None and result.summary.total_items == 2
        seed_errors(case.dependencies.engine, (old,))
        with session_scope(case.dependencies.engine) as session:
            change_retention(
                session, RetentionChange(365, ActorRef(7, "管理员"), AUDIT_CONTEXT, NOW)
            )
        resources = case.dependencies.resources
        assert resources is not None
        dependencies = replace(
            case.dependencies,
            resources=replace(
                resources, configuration=replace(resources.configuration, error_retention_days=7)
            ),
        )
        work, signals = maintenance_work(case, "purge_errors")
        assert work.record.parameters == {}
        result = execute_job(work, dependencies, signals)
        assert result is not None and result.summary is not None and result.summary.total_items == 1


def test_restart_idempotent(tmp_path: Path) -> None:
    """契约：两个清除类型均restart，删除提交后崩溃可重跑，摘要只记本次实际删除数，不伪造旧数。"""
    from datetime import timedelta

    from jobs_maintenance_support import maintenance_work, seed_audit, seed_errors
    from jobs_schedules_support import scheduled_case
    from jobs_scheduling_support import fresh_dependencies
    from jobs_storage_support import NOW

    from rdp.jobs.execution import execute_job, recover_job
    from rdp.jobs.maintenance import MaintenanceService
    from rdp.jobs.scheduling import Scheduler
    from rdp.jobs.types import ExecutionMode

    old = NOW - timedelta(days=40)
    for kind in ("purge_errors", "purge_audit_logs"):
        with scheduled_case(tmp_path / kind, NOW) as case:
            seed_errors(case.dependencies.engine, (old,))
            seed_audit(case.dependencies.engine, (old,), (old,))
            work, signals = maintenance_work(case, kind)
            service = MaintenanceService(case.dependencies.engine, 30)
            # 删除已经提交，但作业尚未上报或落终态；新实例只从数据库恢复。
            if kind == "purge_errors":
                assert service.purge_errors(NOW) == 1
            else:
                assert service.purge_logs(NOW).operation_count == 1
            dependencies = fresh_dependencies(case.dependencies)
            prepared = recover_job(work.record.job_id, dependencies)
            assert prepared is not None and prepared.mode is ExecutionMode.RESTART
            assert dependencies.resources is not None
            scheduler = Scheduler(dependencies, dependencies.resources, recovered=(prepared,))
            resumed = scheduler.claim_next()
            assert resumed is not None
            result = execute_job(resumed, dependencies, signals)
            assert (
                result is not None
                and result.summary is not None
                and result.summary.outcome == "succeeded"
            )
            assert result.summary.total_items == 0 and result.recovery_count == 1


@pytest.mark.parametrize("phase", ["before", "after"])
def test_cancel_checkpoint(tmp_path: Path, phase: str) -> None:
    """契约：取消在清除事务前后响应，提交后的删除不恢复，不在两表原子清除中间中断。"""
    old = NOW - timedelta(days=40)
    with scheduled_case(tmp_path, NOW) as case:
        engine = case.dependencies.engine
        seed_audit(engine, (old,), (old,))
        work, signals = maintenance_work(case, "purge_audit_logs")
        deleted: list[bool] = []
        cancelled: list[bool] = []

        def cancel() -> None:
            cancelled.append(True)
            with session_scope(engine) as session:
                transition_job(
                    session,
                    work.record.job_id,
                    StateChange(JobState.RUNNING, JobState.CANCELLING, NOW),
                )
            signals.cancelled.set()

        def observe(*args: object) -> None:
            if isinstance(args[2], str) and args[2].startswith("DELETE FROM login_logs"):
                deleted.append(True)

        def after_commit(_session: Session) -> None:
            if deleted and not cancelled:
                cancel()

        if phase == "before":
            cancel()
        event.listen(engine, "after_cursor_execute", observe)
        event.listen(Session, "after_commit", after_commit)
        try:
            result = execute_job(work, case.dependencies, signals)
        finally:
            event.remove(Session, "after_commit", after_commit)
            event.remove(engine, "after_cursor_execute", observe)
        assert result is not None and result.state is JobState.CANCELLED
        with session_scope(engine, read_only=True) as session:
            for table in (OperationLogRow, LoginLogRow):
                count = session.scalar(
                    select(func.count()).select_from(table).where(table.occurred_at == old)
                )
                assert count == (1 if phase == "before" else 0)


def test_bad_clock(tmp_path: Path) -> None:
    """契约：注入坏时钟在清除前DefectError，不错归AuditInputError或删除数据。"""
    from datetime import UTC, datetime
    from typing import cast

    from jobs_maintenance_support import seed_audit, seed_errors
    from jobs_storage_support import NOW, job_database
    from sqlalchemy import event

    from rdp.infra.diagnostics import DefectError
    from rdp.jobs.maintenance import MaintenanceService

    deletes: list[str] = []

    def observe(*args: object) -> None:
        if isinstance(args[2], str) and args[2].startswith("DELETE"):
            deletes.append(args[2])

    with job_database(tmp_path) as (engine, _paths):
        seed_errors(engine, (NOW,))
        seed_audit(engine, (NOW,), (NOW,))
        service = MaintenanceService(engine, 30)
        event.listen(engine, "before_cursor_execute", observe)
        try:
            for method in (service.purge_errors, service.purge_logs):
                for moment in (NOW.replace(tzinfo=None), None, datetime(1, 1, 1, tzinfo=UTC)):
                    with pytest.raises(DefectError):
                        method(cast(datetime, moment))
            assert deletes == []
        finally:
            event.remove(engine, "before_cursor_execute", observe)
        for days in (0, True, 3651, "30"):
            with pytest.raises(DefectError):
                MaintenanceService(engine, cast(int, days))


def test_no_recursive_audit(tmp_path: Path) -> None:
    """契约：清除执行不递归写清除操作日志，系统提交动作仍有操作日志，两个恢复重跑不重复提交审计。"""
    from jobs_maintenance_support import maintenance_work
    from jobs_schedules_support import scheduled_case
    from jobs_scheduling_support import fresh_dependencies
    from jobs_storage_support import NOW
    from sqlalchemy import select

    from rdp.audit.models import OperationLogRow
    from rdp.infra.db.connection import session_scope
    from rdp.jobs.execution import execute_job, recover_job
    from rdp.jobs.scheduling import Scheduler

    with scheduled_case(tmp_path, NOW) as case:
        for kind in ("purge_errors", "purge_audit_logs"):
            work, signals = maintenance_work(case, kind)
            dependencies = fresh_dependencies(case.dependencies)
            prepared = recover_job(work.record.job_id, dependencies)
            assert prepared is not None and dependencies.resources is not None
            resumed = Scheduler(
                dependencies, dependencies.resources, recovered=(prepared,)
            ).claim_next()
            assert resumed is not None
            result = execute_job(resumed, dependencies, signals)
            assert (
                result is not None
                and result.summary is not None
                and result.summary.outcome == "succeeded"
            )
        with session_scope(case.dependencies.engine, read_only=True) as session:
            rows = session.scalars(select(OperationLogRow)).all()
            assert len(rows) == 2
            assert all(
                row.operation == "submit_job" and row.actor_id is None and row.actor_name == "系统"
                for row in rows
            )
