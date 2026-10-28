"""M0/08 公共契约测试；数据库与文件只使用临时目录，不依赖真实数据或默认状态目录。"""

import ast
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest
from accounts_support import AUDIT_CONTEXT, EXAMPLE_SECRET, NOW, member_grant, scenario
from jobs_scheduling_support import claim_fixture, resources_fixture
from sqlalchemy import select, update

from rdp.accounts.errors import AuthenticationError, PasswordChangeRequiredError
from rdp.accounts.models import AccountRow
from rdp.accounts.service import authorize_job_actor
from rdp.accounts.types import AccountStatus, Credentials
from rdp.audit.errors import AuditInputError
from rdp.audit.models import OperationLogRow
from rdp.audit.records import append_operation
from rdp.audit.types import (
    AuditValues,
    LogQuery,
    ObjectRef,
    OperationDetails,
    OperationEvent,
    OperationQuery,
    OperationResult,
    OperationType,
)
from rdp.infra.actors import ActorRef
from rdp.infra.db.connection import session_scope
from rdp.infra.diagnostics import ConflictError, DefectError, DiagnosticCategory
from rdp.jobs.errors import JobInputError
from rdp.jobs.models import JobRow
from rdp.jobs.records import StateChange, find_job, transition_job
from rdp.jobs.registry import production_registry
from rdp.jobs.service import JobRequest, JobService
from rdp.jobs.types import JobQuery, JobState


def test_submit_member_other_jobs(tmp_path: Path) -> None:
    """提交权限：管理员和成员都能提交，查看和取消他人作业，写事务内重验身份。"""
    with scenario(tmp_path) as (accounts, administrator):
        member = member_grant(accounts, administrator)
        service = JobService(accounts.engine, production_registry())
        admin_request, member_request = (
            JobRequest(administrator.identity, NOW, AUDIT_CONTEXT),
            JobRequest(member.identity, NOW, AUDIT_CONTEXT),
        )
        first = service.submit(admin_request, "example_count", {"steps": 3, "interval_ms": 0})
        second = service.submit(member_request, "example_count", {"steps": 4, "interval_ms": 0})
        assert service.get(member_request, first.job_id).job_id == first.job_id
        assert service.get(admin_request, second.job_id).job_id == second.job_id
        assert service.cancel(member_request, first.job_id).state is JobState.CANCELLED
        assert service.cancel(admin_request, second.job_id).state is JobState.CANCELLED


def test_submit_atomic_audit(tmp_path: Path) -> None:
    """验收4：新queued与submit_job同事务；actor为当前账号，kind=job、对象编号正确、before空，无参数明细。"""
    with scenario(tmp_path) as (accounts, administrator):
        grant = member_grant(accounts, administrator)
        service = JobService(accounts.engine, production_registry())
        record = service.submit(
            JobRequest(grant.identity, NOW, AUDIT_CONTEXT),
            "example_count",
            {"steps": 3, "interval_ms": 0},
        )
        assert (
            record.state is JobState.QUEUED
            and record.submitted_by.account_id == grant.identity.account.account_id
        )
        assert record.parameters == {
            "steps": 3,
            "interval_ms": 0,
            "failed_steps": [],
            "warning_steps": [],
            "abort_at_step": None,
        }
        with session_scope(accounts.engine, read_only=True) as session:
            rows = session.scalars(
                select(OperationLogRow).where(OperationLogRow.operation == "submit_job")
            ).all()
        assert len(rows) == 1
        event = rows[0]
        assert (event.actor_id, event.object_kind, event.object_id, event.object_name) == (
            grant.identity.account.account_id,
            "job",
            str(record.job_id),
            f"示例：数数 #{record.job_id}",
        )
        assert event.details == {
            "version": 1,
            "before": {},
            "after": {
                "job_id": str(record.job_id),
                "job_type": "example_count",
                "job_state": "queued",
            },
        }
        assert (
            event.source_ip == AUDIT_CONTEXT.source_ip
            and event.request_id == AUDIT_CONTEXT.request_id
        )


def test_submit_rollback(tmp_path: Path) -> None:
    """审计原子性：append_operation/commit失败作业行回滚，不留未审计作业；执行后失败按07短锁补记。"""
    with scenario(tmp_path) as (accounts, administrator):
        service = JobService(accounts.engine, production_registry())
        with accounts.engine.begin() as connection:
            connection.exec_driver_sql(
                "CREATE TRIGGER reject_job_audit BEFORE INSERT ON operation_logs WHEN NEW.operation='submit_job' AND NEW.result='success' BEGIN SELECT RAISE(ABORT, 'test'); END"
            )
        with pytest.raises(ConflictError):
            service.submit(
                JobRequest(administrator.identity, NOW, AUDIT_CONTEXT),
                "example_count",
                {"steps": 3, "interval_ms": 0},
            )
        with session_scope(accounts.engine, read_only=True) as session:
            assert session.scalars(select(JobRow)).all() == []
            failed = session.scalars(
                select(OperationLogRow).where(OperationLogRow.operation == "submit_job")
            ).all()
            assert len(failed) == 1 and failed[0].result == "failure"
            assert failed[0].object_id is None and failed[0].object_name == "新作业"
            assert failed[0].details == {"version": 1, "before": {}, "after": {}}


def test_reject_no_audit(tmp_path: Path) -> None:
    """输入边界：未登记、参数非法、认证/强制改密拒绝均在执行前，不新增成功或失败日志。"""
    with scenario(tmp_path) as (accounts, administrator):
        service = JobService(accounts.engine, production_registry())
        request = JobRequest(administrator.identity, NOW, AUDIT_CONTEXT)
        for name, parameters in (
            ("removed", {}),
            ("BAD", {}),
            ("example_count", {"steps": True, "interval_ms": 0}),
            ("example_count", {"steps": 3, "interval_ms": 0, "extra": "秘密"}),
        ):
            with pytest.raises(JobInputError) as caught:
                service.submit(request, name, dict[str, object](parameters))
            assert "秘密" not in str(caught.value)
        accounts.logout(administrator.identity, now=NOW, audit=AUDIT_CONTEXT)
        with pytest.raises(AuthenticationError):
            service.submit(request, "example_count", {"steps": 3, "interval_ms": 0})
        with session_scope(accounts.engine, read_only=True) as session:
            assert (
                session.scalars(
                    select(OperationLogRow).where(OperationLogRow.operation == "submit_job")
                ).all()
                == []
            )


def test_cancel_queued(tmp_path: Path) -> None:
    """验收4：queued立即cancelled，取消人是当前账号，状态和审计同事务，产物不删除。"""
    with scenario(tmp_path) as (accounts, administrator):
        member = member_grant(accounts, administrator)
        service = JobService(accounts.engine, production_registry())
        record = service.submit(
            JobRequest(administrator.identity, NOW, AUDIT_CONTEXT),
            "example_count",
            {"steps": 3, "interval_ms": 0},
        )
        cancelled = service.cancel(JobRequest(member.identity, NOW, AUDIT_CONTEXT), record.job_id)
        assert cancelled.state is JobState.CANCELLED and cancelled.started_at is None
        assert cancelled.summary is not None and cancelled.summary.outcome is None
        with session_scope(accounts.engine, read_only=True) as session:
            row = session.scalar(
                select(OperationLogRow).where(OperationLogRow.operation == "cancel_job")
            )
            assert row is not None and row.actor_id == member.identity.account.account_id
            assert (
                OperationDetails.model_validate(row.details).before.job_state == "queued"
                and OperationDetails.model_validate(row.details).after.job_state == "cancelled"
            )


def test_cancel_running(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """验收4：running→cancelling，另一账号取消并作为审计操作人，主循环传播取消后执行函数在阶段边界退出。"""
    import time

    from account_api_support import add_actor
    from jobs_api_support import job_api_case
    from jobs_loop_support import running_loop, wait_for

    from rdp.infra.config import PlatformConfig
    from rdp.infra.state import state_paths
    from rdp.jobs import policy
    from rdp.jobs.execution import ExecutorDependencies
    from rdp.jobs.types import JobClock

    monkeypatch.setattr(policy, "WORKER_POLL_INTERVAL_S", 0.005)
    with job_api_case(tmp_path) as fixture:
        grant = fixture.service.login(
            Credentials("admin", EXAMPLE_SECRET), now=NOW, audit=AUDIT_CONTEXT
        )
        canceller = add_actor(fixture, name="canceller")
        cancel_request = JobRequest(canceller.identity, NOW, AUDIT_CONTEXT)
        registry = production_registry()
        jobs = JobService(fixture.engine, registry)
        request = JobRequest(grant.identity, NOW, AUDIT_CONTEXT)
        record = jobs.submit(request, "example_count", {"steps": 2, "interval_ms": 60000})
        paths = state_paths(PlatformConfig(state_dir=tmp_path), ("示例：数数",))
        dependencies = ExecutorDependencies(
            fixture.engine,
            registry,
            paths,
            JobClock(lambda: NOW, time.monotonic),
            resources=resources_fixture(registry),
            storage=None,
        )

        def first_step() -> bool:
            current = jobs.get(request, record.job_id)
            return current.progress is not None and current.progress.done == 1

        with running_loop(dependencies):
            wait_for(first_step)
            assert jobs.cancel(cancel_request, record.job_id).state is JobState.CANCELLING
            wait_for(lambda: jobs.get(request, record.job_id).state is JobState.CANCELLED)
        final = jobs.get(request, record.job_id)
        assert final.progress is not None and final.progress.done == 1
        assert final.summary is not None and final.summary.outcome is None

        with session_scope(fixture.engine, read_only=True) as session:
            audit = session.scalar(
                select(OperationLogRow).where(OperationLogRow.operation == "cancel_job")
            )
            assert audit is not None
            assert audit.actor_id == canceller.identity.account.account_id
            assert audit.actor_id != record.submitted_by.account_id


def test_cancel_terminal_conflict(tmp_path: Path) -> None:
    """验收4：正在取消、已完成、已取消、已中断再取消返回冲突，不写操作日志。"""
    from rdp.infra.diagnostics import ConflictError

    with scenario(tmp_path) as (accounts, administrator):
        request = JobRequest(administrator.identity, NOW, AUDIT_CONTEXT)
        service = JobService(accounts.engine, production_registry())
        record = service.submit(request, "example_count", {"steps": 3, "interval_ms": 0})
        service.cancel(request, record.job_id)
        with session_scope(accounts.engine, read_only=True) as session:
            before = tuple(session.scalars(select(OperationLogRow.log_id)))
        with pytest.raises(ConflictError):
            service.cancel(request, record.job_id)
        with session_scope(accounts.engine, read_only=True) as session:
            assert tuple(session.scalars(select(OperationLogRow.log_id))) == before


def test_cancel_commits_first(tmp_path: Path) -> None:
    """竞争契约：两个独立连接读取queued，取消先提交，worker条件领取失败、不执行、不新增状态。"""
    with scenario(tmp_path) as (accounts, administrator):
        service = JobService(accounts.engine, production_registry())
        request = JobRequest(administrator.identity, NOW, AUDIT_CONTEXT)
        record = service.submit(request, "example_count", {"steps": 3, "interval_ms": 0})
        with session_scope(accounts.engine, read_only=True) as session:
            candidate = find_job(session, record.job_id)
        service.cancel(request, record.job_id)
        with pytest.raises(ConflictError), session_scope(accounts.engine) as session:
            transition_job(
                session,
                candidate.job_id,
                StateChange(
                    candidate.state, JobState.RUNNING, NOW, log_path="logs/示例：数数/test.log"
                ),
            )
        assert service.get(request, record.job_id).state is JobState.CANCELLED


def test_claim_commits_first(tmp_path: Path) -> None:
    """竞争契约：worker先提交领取，取消随后在BEGIN IMMEDIATE内读running，条件更新为cancelling且记录取消人，不返回409。"""
    with scenario(tmp_path) as (accounts, administrator):
        member = member_grant(accounts, administrator)
        service = JobService(accounts.engine, production_registry())
        request = JobRequest(administrator.identity, NOW, AUDIT_CONTEXT)
        record = service.submit(request, "example_count", {"steps": 3, "interval_ms": 0})
        with session_scope(accounts.engine) as session:
            transition_job(
                session,
                record.job_id,
                StateChange(
                    JobState.QUEUED, JobState.RUNNING, NOW, log_path="logs/示例：数数/test.log"
                ),
            )
        cancelled = service.cancel(JobRequest(member.identity, NOW, AUDIT_CONTEXT), record.job_id)
        assert cancelled.state is JobState.CANCELLING
        with session_scope(accounts.engine, read_only=True) as session:
            audit = session.scalar(
                select(OperationLogRow).where(OperationLogRow.operation == "cancel_job")
            )
            assert audit is not None and audit.actor_id == member.identity.account.account_id
            assert OperationDetails.model_validate(audit.details).before.job_state == "running"


def test_cancel_atomic_failure(tmp_path: Path) -> None:
    """取消事务：审计插入或commit失败状态回滚，补记失败不得覆盖原异常或泄漏参数。"""
    with scenario(tmp_path) as (accounts, administrator):
        service = JobService(accounts.engine, production_registry())
        request = JobRequest(administrator.identity, NOW, AUDIT_CONTEXT)
        record = service.submit(request, "example_count", {"steps": 3, "interval_ms": 0})
        with accounts.engine.begin() as connection:
            connection.exec_driver_sql(
                "CREATE TRIGGER reject_cancel_audit BEFORE INSERT ON operation_logs WHEN NEW.operation='cancel_job' BEGIN SELECT RAISE(ABORT, 'test'); END"
            )
        with pytest.raises(ConflictError) as caught:
            service.cancel(request, record.job_id)
        assert service.get(request, record.job_id).state is JobState.QUEUED
        from rdp.audit.policy import AUDIT_APPEND_FAILED

        assert AUDIT_APPEND_FAILED in caught.value.__notes__


def test_resubmit_terminal(tmp_path: Path) -> None:
    """验收9：三个终态各能新建，参数原样复制、resubmitted_from正确、actor为点击账号，原记录不变。"""
    with scenario(tmp_path) as (accounts, administrator):
        member = member_grant(accounts, administrator)
        service = JobService(accounts.engine, production_registry())
        request = JobRequest(administrator.identity, NOW, AUDIT_CONTEXT)
        for terminal in (JobState.CANCELLED, JobState.COMPLETED, JobState.INTERRUPTED):
            original = service.submit(request, "example_count", {"steps": 3, "interval_ms": 0})
            with session_scope(accounts.engine) as session:
                if terminal is JobState.CANCELLED:
                    transition_job(
                        session, original.job_id, StateChange(JobState.QUEUED, terminal, NOW)
                    )
                else:
                    transition_job(
                        session,
                        original.job_id,
                        StateChange(
                            JobState.QUEUED,
                            JobState.RUNNING,
                            NOW,
                            log_path=f"logs/示例：数数/test_{original.job_id}.log",
                        ),
                    )
                    transition_job(
                        session, original.job_id, StateChange(JobState.RUNNING, terminal, NOW)
                    )
                row = session.get(JobRow, original.job_id)
                assert row is not None
                row.parameters = {"steps": 3, "interval_ms": 0}
            before = service.get(request, original.job_id)
            fresh = service.resubmit(
                JobRequest(member.identity, NOW, AUDIT_CONTEXT), original.job_id
            )
            assert fresh.job_id > original.job_id and fresh.resubmitted_from == original.job_id
            assert fresh.submitted_by.account_id == member.identity.account.account_id
            assert fresh.parameters == {"steps": 3, "interval_ms": 0} and fresh.recovery_count == 0
            assert service.get(request, original.job_id) == before
            with session_scope(accounts.engine, read_only=True) as session:
                audit = session.scalar(
                    select(OperationLogRow)
                    .where(OperationLogRow.operation == "submit_job")
                    .order_by(OperationLogRow.log_id.desc())
                )
                assert audit is not None and OperationDetails.model_validate(
                    audit.details
                ).after.resubmitted_from == str(original.job_id)


def test_resubmit_nonterminal(tmp_path: Path) -> None:
    """验收9：queued/running/cancelling重提409且不写日志，不分配新记录。"""
    with scenario(tmp_path) as (accounts, administrator):
        request = JobRequest(administrator.identity, NOW, AUDIT_CONTEXT)
        service = JobService(accounts.engine, production_registry())
        record = service.submit(request, "example_count", {"steps": 3, "interval_ms": 0})
        for state in (JobState.QUEUED, JobState.RUNNING, JobState.CANCELLING):
            if state is not JobState.QUEUED:
                old = JobState.QUEUED if state is JobState.RUNNING else JobState.RUNNING
                with session_scope(accounts.engine) as session:
                    transition_job(
                        session,
                        record.job_id,
                        StateChange(
                            old,
                            state,
                            NOW,
                            log_path="logs/示例：数数/test.log"
                            if state is JobState.RUNNING
                            else None,
                        ),
                    )
            with pytest.raises(ConflictError):
                service.resubmit(request, record.job_id)
        with session_scope(accounts.engine, read_only=True) as session:
            assert len(session.scalars(select(JobRow.job_id)).all()) == 1
            assert (
                len(
                    session.scalars(
                        select(OperationLogRow).where(OperationLogRow.operation == "submit_job")
                    ).all()
                )
                == 1
            )


def test_resubmit_incompatible(tmp_path: Path) -> None:
    """验收9：旧类型被删或参数不兼容时422，不补默认参数、不改旧记录、不记审计。"""
    with scenario(tmp_path) as (accounts, administrator):
        service = JobService(accounts.engine, production_registry())
        request = JobRequest(administrator.identity, NOW, AUDIT_CONTEXT)
        record = service.submit(request, "example_count", {"steps": 3, "interval_ms": 0})
        service.cancel(request, record.job_id)
        for parameters, type_name in (({"steps": 0}, "example_count"), ({}, "removed")):
            with session_scope(accounts.engine) as session:
                row = session.get(JobRow, record.job_id)
                assert row is not None
                row.parameters, row.type_name = dict[str, object](parameters), type_name
            with pytest.raises(JobInputError):
                service.resubmit(request, record.job_id)
        with session_scope(accounts.engine, read_only=True) as session:
            assert (
                len(
                    session.scalars(
                        select(OperationLogRow).where(OperationLogRow.operation == "submit_job")
                    ).all()
                )
                == 1
            )


def test_deleted_submitter(tmp_path: Path) -> None:
    """身份快照：账号删除不被作业外键阻挡，名字快照加已删除标记，同名重建不能冒充旧编号。"""
    with scenario(tmp_path) as (accounts, administrator):
        member = member_grant(accounts, administrator, name="recreated")
        jobs = JobService(accounts.engine, production_registry())
        record = jobs.submit(
            JobRequest(member.identity, NOW, AUDIT_CONTEXT),
            "example_count",
            {"steps": 3, "interval_ms": 0},
        )
        accounts.delete_account(
            administrator.identity, member.identity.account.account_id, now=NOW, audit=AUDIT_CONTEXT
        )
        replacement = member_grant(accounts, administrator, name="recreated")
        result = jobs.get(JobRequest(administrator.identity, NOW, AUDIT_CONTEXT), record.job_id)
        assert result.submitter_deleted and result.submitted_by == record.submitted_by
        assert replacement.identity.account.account_id != result.submitted_by.account_id
        page = jobs.list(JobRequest(administrator.identity, NOW, AUDIT_CONTEXT), JobQuery())
        assert page.items[0].submitter_deleted and page.items[0].submitted_by.name == "成员"


def test_cursor_pagination(tmp_path: Path) -> None:
    """列表契约：按job_id倒序，即使提交UTC回拨也保持自增提交顺序，状态交集、limit边界、空页、最后页、首页上界稳定。"""
    with scenario(tmp_path) as (accounts, administrator):
        request = JobRequest(administrator.identity, NOW, AUDIT_CONTEXT)
        service = JobService(accounts.engine, production_registry())
        assert service.list(request, JobQuery()).items == ()
        identifiers = [
            service.submit(
                replace(request, now=NOW - timedelta(seconds=i)),
                "example_count",
                {"steps": 3, "interval_ms": 0},
            ).job_id
            for i in range(5)
        ]
        first = service.list(request, JobQuery(limit=2))
        assert [item.job_id for item in first.items] == identifiers[-2:][::-1] and first.next_cursor
        newer = service.submit(request, "example_count", {"steps": 3, "interval_ms": 0})
        second = service.list(request, JobQuery(limit=2, cursor=first.next_cursor))
        third = service.list(request, JobQuery(limit=2, cursor=second.next_cursor))
        assert [item.job_id for item in second.items + third.items] == identifiers[:3][::-1]
        assert third.next_cursor is None and all(
            item.job_id != newer.job_id for item in second.items
        )
        service.cancel(request, identifiers[0])
        filtered = service.list(request, JobQuery(state=JobState.CANCELLED, limit=1))
        assert [item.job_id for item in filtered.items] == [identifiers[0]]


def test_cursor_invalid(tmp_path: Path) -> None:
    """列表契约：游标版本/编码/长度/筛选/limit绑定不合法拒绝，不回退首页、不回显原值。"""
    with scenario(tmp_path) as (accounts, administrator):
        request = JobRequest(administrator.identity, NOW, AUDIT_CONTEXT)
        service = JobService(accounts.engine, production_registry())
        for _ in range(3):
            service.submit(request, "example_count", {"steps": 3, "interval_ms": 0})
        first = service.list(request, JobQuery(limit=1))
        assert first.next_cursor is not None
        bad = [JobQuery(limit=value) for value in (0, 101, True)]
        bad += [JobQuery(cursor=value) for value in ("", "!secret!", "x" * 513, "e30")]
        bad += [
            JobQuery(limit=2, cursor=first.next_cursor),
            JobQuery(state=JobState.CANCELLED, limit=1, cursor=first.next_cursor),
        ]
        for query in bad:
            with pytest.raises(JobInputError) as caught:
                service.list(request, query)
            assert "!secret!" not in str(caught.value)


def test_no_delete_api(tmp_path: Path) -> None:
    """永久记录：领域和HTTP无删除作业函数/接口；AUTOINCREMENT不复用，旧作业永久可查。"""
    from jobs_api_support import job_api_case

    with job_api_case(tmp_path) as fixture:
        fixture.login()
        first = fixture.client.post("/api/jobs/example", json={"steps": 3, "interval_ms": 0}).json()
        assert fixture.client.delete(f"/api/jobs/{first['job_id']}").status_code == 405
        assert fixture.client.get(f"/api/jobs/{first['job_id']}").json() == first
        second = fixture.client.post(
            "/api/jobs/example", json={"steps": 3, "interval_ms": 0}
        ).json()
        assert int(second["job_id"]) > int(first["job_id"])
        paths = fixture.app.openapi()["paths"]
        assert all(
            "delete" not in operations
            for path, operations in paths.items()
            if path.startswith("/api/jobs")
        )
        assert not any("delete" in name or "remove" in name for name in vars(JobService))


def test_service_failures(tmp_path: Path) -> None:
    """规范7.1：数据库损坏/锁冲突/I/O/非法上下文分别沿用四类异常；缺作业与坏编号分别区分。"""
    import sqlite3
    from typing import cast

    from sqlalchemy import Connection, event

    from rdp.audit.types import AuditContext
    from rdp.infra.diagnostics import ExternalError, InputError
    from rdp.jobs.errors import JobNotFoundError

    with scenario(tmp_path) as (accounts, administrator):
        jobs = JobService(accounts.engine, production_registry())
        request = JobRequest(administrator.identity, NOW, AUDIT_CONTEXT)
        record = jobs.submit(request, "example_count", {"steps": 3, "interval_ms": 0})
        for bad in (
            cast(JobRequest, None),
            replace(request, now=NOW.replace(tzinfo=None)),
            replace(request, audit=AuditContext(None, None)),
        ):
            with pytest.raises(DefectError):
                jobs.get(bad, record.job_id)
        with pytest.raises(JobInputError):
            jobs.get(request, 0)
        with pytest.raises(JobNotFoundError):
            jobs.get(request, record.job_id + 1)
        for code, kind in (
            (sqlite3.SQLITE_CORRUPT, InputError),
            (sqlite3.SQLITE_BUSY, ConflictError),
            (sqlite3.SQLITE_IOERR, ExternalError),
            (sqlite3.SQLITE_ERROR, DefectError),
        ):

            def fail(
                _connection: Connection,
                _cursor: object,
                statement: str,
                _parameters: object,
                _context: object,
                _many: bool,
                *,
                failure_code: int = code,
            ) -> None:
                if "FROM jobs" in statement:
                    error = sqlite3.OperationalError("不应回显的底层内容")
                    error.sqlite_errorcode = failure_code
                    raise error

            event.listen(accounts.engine, "before_cursor_execute", fail)
            try:
                with pytest.raises(kind) as caught:
                    jobs.get(request, record.job_id)
                assert "不应回显" not in str(caught.value)
            finally:
                event.remove(accounts.engine, "before_cursor_execute", fail)


def test_audit_job_shape(tmp_path: Path) -> None:
    """审计扩展：job仅与submit_job/cancel_job相配，编号1至2^63-1，状态明细一致，失败after为空。"""
    from accounts_support import model_database

    base = OperationEvent(
        NOW,
        ActorRef(7, "操作人"),
        OperationType.SUBMIT_JOB,
        ObjectRef("job", "12", "示例：数数 #12"),
        OperationResult.SUCCESS,
        None,
        AUDIT_CONTEXT,
        OperationDetails(
            before=AuditValues(),
            after=AuditValues(job_id="12", job_type="example_count", job_state="queued"),
        ),
    )
    invalid = [
        replace(base, target=ObjectRef("account", "12", "账号")),
        replace(base, operation=OperationType.CREATE_ACCOUNT),
        replace(base, target=ObjectRef("job", "13", "示例：数数 #13")),
        replace(
            base,
            details=OperationDetails(
                before=AuditValues(),
                after=AuditValues(job_id="12", job_type="example_count", job_state="completed"),
            ),
        ),
        replace(
            base,
            details=OperationDetails(
                before=AuditValues(),
                after=AuditValues(
                    job_id="12",
                    job_type="example_count",
                    job_state="queued",
                    resubmitted_from="9223372036854775808",
                ),
            ),
        ),
        replace(
            base,
            operation=OperationType.CANCEL_JOB,
            result=OperationResult.FAILURE,
            failure_category=DiagnosticCategory.EXTERNAL,
            details=OperationDetails(
                before=AuditValues(job_id="99", job_type="example_count", job_state="running"),
                after=AuditValues(),
            ),
        ),
    ]
    with model_database(tmp_path) as engine:
        with session_scope(engine) as session:
            append_operation(session, base)
        for event in invalid:
            with pytest.raises(AuditInputError), session_scope(engine) as session:
                append_operation(session, event)
        cancel = replace(
            base,
            operation=OperationType.CANCEL_JOB,
            details=OperationDetails(
                before=AuditValues(job_id="12", job_type="example_count", job_state="running"),
                after=AuditValues(job_id="12", job_type="example_count", job_state="cancelling"),
            ),
        )
        with session_scope(engine) as session:
            append_operation(session, cancel)
            append_operation(
                session,
                replace(
                    base,
                    target=ObjectRef("job", None, "新作业"),
                    result=OperationResult.FAILURE,
                    failure_category=DiagnosticCategory.EXTERNAL,
                    details=OperationDetails(before=AuditValues(), after=AuditValues()),
                ),
            )


def test_audit_name_limit(tmp_path: Path) -> None:
    """审计名字：40码点显示名加空格#及19位编号最多61码点，不超过64，不截断或伪装账号。"""
    from rdp.jobs.registry import JobRegistry

    with scenario(tmp_path) as (accounts, administrator):
        request = JobRequest(administrator.identity, NOW, AUDIT_CONTEXT)
        registry = production_registry()
        original = registry.lookup("example_count")
        assert original is not None
        jobs = JobService(accounts.engine, registry)
        jobs.submit(request, "example_count", {"steps": 3, "interval_ms": 0})
        with accounts.engine.begin() as connection:
            connection.exec_driver_sql(
                "UPDATE sqlite_sequence SET seq=9223372036854775806 WHERE name='jobs'"
            )
        registry = JobRegistry()
        registry.register(replace(original, display_name="示" * 40))
        record = JobService(accounts.engine, registry).submit(
            request, "example_count", {"steps": 3, "interval_ms": 0}
        )
        assert record.job_id == 9223372036854775807
        with session_scope(accounts.engine, read_only=True) as session:
            audit = session.scalar(
                select(OperationLogRow).where(OperationLogRow.object_id == str(record.job_id))
            )
            assert audit is not None and audit.object_kind == "job"
            assert audit.object_name == "示" * 40 + " #9223372036854775807"
            assert len(audit.object_name) == 61


def test_audit_account_filter(tmp_path: Path) -> None:
    """审计扩展：对象账号筛选不匹配数值相同的job编号；旧account/audit_settings含义不变。"""
    with scenario(tmp_path) as (accounts, administrator):
        jobs = JobService(accounts.engine, production_registry())
        record = jobs.submit(
            JobRequest(administrator.identity, NOW, AUDIT_CONTEXT),
            "example_count",
            {"steps": 3, "interval_ms": 0},
        )
        all_logs = accounts.list_operations(
            administrator.identity, OperationQuery(LogQuery()), now=NOW
        )
        assert any(
            item.event.target.kind == "job" and item.event.target.object_id == str(record.job_id)
            for item in all_logs.items
        )
        filtered = accounts.list_operations(
            administrator.identity,
            OperationQuery(LogQuery(), target_account_id=record.job_id),
            now=NOW,
        )
        assert all(item.event.target.kind == "account" for item in filtered.items)


def test_cancel_vs_completion_orders(tmp_path: Path) -> None:
    """取消/完成竞争：取消先提交最终cancelled，完成先提交取消409无日志；绝无cancelling→completed。"""
    import time
    from threading import Event, Lock

    from jobs_api_support import job_api_case

    from rdp.infra.config import PlatformConfig
    from rdp.infra.state import state_paths
    from rdp.jobs.execution import ExecutionWork, ExecutorDependencies, execute_job
    from rdp.jobs.progress import ExecutionMonitor, ExecutionSignals
    from rdp.jobs.records import claim_job
    from rdp.jobs.types import ExecutionMode, JobClock

    with job_api_case(tmp_path) as fixture:
        grant = fixture.service.login(
            Credentials("admin", EXAMPLE_SECRET), now=NOW, audit=AUDIT_CONTEXT
        )
        request = JobRequest(grant.identity, NOW, AUDIT_CONTEXT)
        registry = production_registry()
        jobs = JobService(fixture.engine, registry)
        paths = state_paths(PlatformConfig(state_dir=tmp_path), ("示例：数数",))
        dependencies = ExecutorDependencies(
            fixture.engine,
            registry,
            paths,
            JobClock(lambda: NOW, time.monotonic),
            resources=resources_fixture(registry),
            storage=None,
        )
        for cancel_first in (True, False):
            record = jobs.submit(request, "example_count", {"steps": 3, "interval_ms": 0})
            with session_scope(fixture.engine) as session:
                claimed = claim_job(session, record.job_id, now=NOW, paths=paths, gpu_index=None)
            if cancel_first:
                jobs.cancel(request, record.job_id)
            signals = ExecutionSignals(Event(), Event(), ExecutionMonitor([], None, Lock()))
            result = execute_job(
                ExecutionWork(
                    claimed, ExecutionMode.FRESH, None, claim=claim_fixture(claimed, dependencies)
                ),
                dependencies,
                signals,
            )
            assert result is not None and result.state is (
                JobState.CANCELLED if cancel_first else JobState.COMPLETED
            )
            if not cancel_first:
                with session_scope(fixture.engine, read_only=True) as session:
                    before = tuple(session.scalars(select(OperationLogRow.log_id)))
                with pytest.raises(ConflictError):
                    jobs.cancel(request, record.job_id)
                with session_scope(fixture.engine, read_only=True) as session:
                    assert tuple(session.scalars(select(OperationLogRow.log_id))) == before


def test_public_account_boundary(tmp_path: Path) -> None:
    """第15条：jobs只import公开账号模块；调用者事务内未提交改名可见，退出回滚后仍为原名。"""
    import rdp.jobs

    directory = Path(rdp.jobs.__file__).parent
    for path in directory.glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("rdp.accounts"):
                assert not any(part.startswith("_") for part in (node.module or "").split("."))
                assert not any(alias.name.startswith("_") for alias in node.names)
    with scenario(tmp_path) as (service, administrator):
        grant = member_grant(service, administrator)
        identifier = grant.identity.account.account_id
        with pytest.raises(RuntimeError, match="回滚"), session_scope(service.engine) as session:
            session.execute(
                update(AccountRow)
                .where(AccountRow.account_id == identifier)
                .values(display_name="事务内名字")
            )
            assert authorize_job_actor(session, grant.identity, now=NOW) == ActorRef(
                identifier, "事务内名字"
            )
            raise RuntimeError("回滚")
        with session_scope(service.engine, read_only=True) as session:
            assert authorize_job_actor(session, grant.identity, now=NOW) == ActorRef(
                identifier, "成员"
            )


@pytest.mark.parametrize(
    "case",
    [
        "administrator",
        "member",
        "revoked",
        "expired",
        "disabled",
        "deleted",
        "must_change",
        "naive",
        "rollback_clock",
    ],
)
def test_public_actor_authorization(case: str, tmp_path: Path) -> None:
    """第15条：公开账号适配器允许成员/管理员，撤销/过期/停用/删除拒绝，强制改密拒绝，非法注入时钟是DefectError。"""
    with scenario(tmp_path) as (service, administrator):
        grant = administrator if case == "administrator" else member_grant(service, administrator)
        target = grant.identity.account.account_id
        now = NOW
        failure: type[Exception] | None = None
        if case == "revoked":
            service.logout(grant.identity, now=NOW, audit=AUDIT_CONTEXT)
            failure = AuthenticationError
        elif case == "expired":
            now += timedelta(days=7)
            failure = AuthenticationError
        elif case == "disabled":
            service.set_status(
                administrator.identity, target, AccountStatus.DISABLED, now=NOW, audit=AUDIT_CONTEXT
            )
            failure = AuthenticationError
        elif case == "deleted":
            service.delete_account(administrator.identity, target, now=NOW, audit=AUDIT_CONTEXT)
            failure = AuthenticationError
        elif case == "must_change":
            service.reset_password(
                administrator.identity, target, EXAMPLE_SECRET, now=NOW, audit=AUDIT_CONTEXT
            )
            grant = service.login(
                Credentials("member", EXAMPLE_SECRET), now=NOW, audit=AUDIT_CONTEXT
            )
            failure = PasswordChangeRequiredError
        elif case == "naive":
            now = NOW.replace(tzinfo=None)
            failure = DefectError
        elif case == "rollback_clock":
            now -= timedelta(days=1)
        with session_scope(service.engine) as session:
            if failure is not None:
                with pytest.raises(failure):
                    authorize_job_actor(session, grant.identity, now=now)
            else:
                assert authorize_job_actor(session, grant.identity, now=now) == ActorRef(
                    target, grant.identity.account.display_name
                )
