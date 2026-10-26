"""账号接日志的隔离契约清单（07），按事务、权限和来源逐项验证，保留第6张现有测试。"""

import sqlite3
import time
from collections.abc import Callable, Generator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import replace
from datetime import timedelta
from importlib.util import find_spec
from inspect import Parameter, signature
from pathlib import Path
from threading import Barrier
from typing import Any

import pytest
from accounts_support import (
    AUDIT_CONTEXT,
    EXAMPLE_SECRET,
    NOW,
    HeldHasher,
    HookHasher,
    fail_write_commit,
    member_grant,
    model_row,
    persisted_account_state,
    scenario,
)
from audit_account_support import account_action, operations
from pydantic import SecretStr
from sqlalchemy import Connection, delete, event, update

from rdp.accounts.errors import (
    AccountNotFoundError,
    AuthenticationError,
    AuthorizationError,
    CurrentPasswordError,
    LoginWaitError,
)
from rdp.accounts.models import AccountRow, SessionRow
from rdp.accounts.security import PasswordCodec
from rdp.accounts.service import AccountService, existing_account_ids
from rdp.accounts.types import (
    AccountStatus,
    ActorRef,
    Credentials,
    NewAccount,
    PasswordChange,
    Role,
    SessionGrant,
)
from rdp.audit.policy import AUDIT_APPEND_FAILED
from rdp.audit.records import query_logins
from rdp.audit.types import (
    OPS_AUDIT_CONTEXT,
    AuditContext,
    LoginKind,
    LoginQuery,
    LoginResult,
    LoginView,
    LogQuery,
    OperationQuery,
    OperationResult,
)
from rdp.infra.db.connection import session_scope
from rdp.infra.diagnostics import ConflictError, DefectError, ExternalError, InputError


@pytest.mark.parametrize(
    "case",
    [
        "create_account",
        "set_role",
        "disable",
        "enable",
        "reset_password",
        "delete_account",
        "change_password",
        "create_first_admin",
        "reset_password_from_ops",
    ],
)
def test_success_atomic(case: str, tmp_path: Path) -> None:
    """验收2：每个账号写操作追加对应成功事件，日志插入故障回滚账号和会话的全部变化。"""
    expected = {"disable": "disable_account", "enable": "enable_account"}.get(case, case)
    with account_action(tmp_path / "success", case) as (service, action):
        before = len(operations(service))
        action()
        after = operations(service)
        assert len(after) == before + 1
        assert after[0].event.operation.value == expected
        assert after[0].event.result is OperationResult.SUCCESS
    with account_action(tmp_path / "failure", case) as (service, action):
        before_state = persisted_account_state(service.engine)
        before_logs = operations(service)

        def fail(_connection: Connection, _cursor: Any, statement: str, *_args: Any) -> None:
            if statement.startswith("INSERT INTO operation_logs"):
                error = sqlite3.OperationalError("模拟日志写入失败")
                error.sqlite_errorcode = sqlite3.SQLITE_IOERR
                raise error

        event.listen(service.engine, "before_cursor_execute", fail)
        try:
            with pytest.raises(ExternalError):
                action()
        finally:
            event.remove(service.engine, "before_cursor_execute", fail)
        assert persisted_account_state(service.engine) == before_state
        assert operations(service) == before_logs


@pytest.mark.parametrize(
    "case",
    [
        "create_account",
        "set_role",
        "set_status",
        "reset_password",
        "delete_account",
        "change_password",
        "create_first_admin",
        "reset_password_from_ops",
        "set_retention",
    ],
)
def test_execution_boundary(case: str, tmp_path: Path) -> None:
    """H3：预检通过后的业务写入故障要在回滚后补一条失败事件，不能留下成功日志。"""
    actual = "disable" if case == "set_status" else case
    with account_action(tmp_path, actual) as (service, action):
        before = operations(service)

        def fail(_connection: Connection, _cursor: Any, statement: str, *_args: Any) -> None:
            if statement.startswith(
                (
                    "INSERT INTO accounts",
                    "UPDATE accounts",
                    "DELETE FROM accounts",
                    "DELETE FROM account_sessions",
                    "INSERT INTO audit_settings",
                )
            ):
                error = sqlite3.OperationalError("业务执行失败")
                error.sqlite_errorcode = sqlite3.SQLITE_IOERR
                raise error

        event.listen(service.engine, "before_cursor_execute", fail)
        try:
            with pytest.raises(ExternalError):
                action()
        finally:
            event.remove(service.engine, "before_cursor_execute", fail)
        after = operations(service)
        assert len(after) == len(before) + 1
        assert after[0].event.result is OperationResult.FAILURE


@pytest.mark.parametrize(
    "case",
    [
        "unauthenticated",
        "unauthorized",
        "must_change",
        "bad_parameter",
        "precheck_missing_target",
        "precheck_existing_admin",
        "write_begin_timeout",
        "precheck_wait",
        "same_role",
        "same_status",
    ],
)
def test_rejection_not_logged(case: str, tmp_path: Path) -> None:
    """H3：身份角色参数、开始前目标/首管理员/G2预检拒绝及无变化请求不记，未进入写事务的获锁失败不记。"""
    with scenario(tmp_path) as (service, grant):
        identity = grant.identity
        if case == "unauthenticated":
            identity = replace(identity, token_digest="0" * 64)
        if case == "unauthorized":
            identity = member_grant(service, grant).identity
        if case == "must_change":
            service.create_account(
                grant.identity,
                NewAccount(Credentials("forced", EXAMPLE_SECRET), "待改密", Role.ADMINISTRATOR),
                now=NOW,
                audit=AUDIT_CONTEXT,
            )
            identity = service.login(
                Credentials("forced", EXAMPLE_SECRET), now=NOW, audit=AUDIT_CONTEXT
            ).identity
        if case == "precheck_wait":
            with session_scope(service.engine) as session:
                session.execute(
                    update(AccountRow)
                    .where(AccountRow.account_id == 1)
                    .values(failed_attempts=5, blocked_until=NOW + timedelta(seconds=60))
                )
        before = operations(service)
        actions: dict[str, Callable[[], object]] = {
            "unauthenticated": lambda: service.set_role(
                identity, 1, Role.ADMINISTRATOR, now=NOW, audit=AUDIT_CONTEXT
            ),
            "unauthorized": lambda: service.set_role(
                identity, 1, Role.ADMINISTRATOR, now=NOW, audit=AUDIT_CONTEXT
            ),
            "must_change": lambda: service.set_role(
                identity, 1, Role.ADMINISTRATOR, now=NOW, audit=AUDIT_CONTEXT
            ),
            "bad_parameter": lambda: service.set_role(
                identity, True, Role.ADMINISTRATOR, now=NOW, audit=AUDIT_CONTEXT
            ),
            "precheck_missing_target": lambda: service.delete_account(
                identity, 999, now=NOW, audit=AUDIT_CONTEXT
            ),
            "precheck_existing_admin": lambda: service.create_first_admin(
                NewAccount(Credentials("other", EXAMPLE_SECRET), "其他", Role.ADMINISTRATOR),
                now=NOW,
                audit=OPS_AUDIT_CONTEXT,
            ),
            "write_begin_timeout": lambda: service.set_role(
                identity, 1, Role.ADMINISTRATOR, now=NOW, audit=AUDIT_CONTEXT
            ),
            "precheck_wait": lambda: service.change_password(
                identity,
                PasswordChange(EXAMPLE_SECRET, SecretStr("new-password-value")),
                now=NOW,
                audit=AUDIT_CONTEXT,
            ),
            "same_role": lambda: service.set_role(
                identity, 1, Role.ADMINISTRATOR, now=NOW, audit=AUDIT_CONTEXT
            ),
            "same_status": lambda: service.set_status(
                identity, 1, AccountStatus.ENABLED, now=NOW, audit=AUDIT_CONTEXT
            ),
        }
        if case in {"same_role", "same_status"}:
            actions[case]()
        elif case == "write_begin_timeout":
            with session_scope(service.engine), pytest.raises(ConflictError):
                actions[case]()
        else:
            with pytest.raises((InputError, ConflictError)):
                actions[case]()
        assert operations(service) == before


@pytest.mark.parametrize("case", ["input", "conflict", "external", "defect"])
def test_failure_append_preserves_error(case: str, tmp_path: Path) -> None:
    """H3：业务和补记都失败时保留原错误类别，附追加失败标记且不泄漏驱动文本。"""
    codes = {
        "input": (sqlite3.SQLITE_CORRUPT, InputError),
        "conflict": (sqlite3.SQLITE_CONSTRAINT, ConflictError),
        "external": (sqlite3.SQLITE_IOERR, ExternalError),
        "defect": (sqlite3.SQLITE_ERROR, DefectError),
    }
    code, expected = codes[case]
    with account_action(tmp_path, "set_role") as (service, action):
        before = operations(service)
        state = persisted_account_state(service.engine)

        def fail(_connection: Connection, _cursor: Any, statement: str, *_args: Any) -> None:
            primary = statement.startswith("UPDATE accounts")
            secondary = statement.startswith("INSERT INTO operation_logs")
            if primary or secondary:
                error = sqlite3.DatabaseError("秘密驱动错误")
                error.sqlite_errorcode = code if primary else sqlite3.SQLITE_IOERR
                raise error

        event.listen(service.engine, "before_cursor_execute", fail)
        try:
            with pytest.raises(expected) as caught:
                action()
        finally:
            event.remove(service.engine, "before_cursor_execute", fail)
        assert persisted_account_state(service.engine) == state
        after = operations(service)
        assert after == before
        assert AUDIT_APPEND_FAILED in caught.value.__notes__
        assert "秘密" not in str(getattr(caught.value, "__notes__", ()))


@pytest.mark.parametrize("case", ["input", "conflict", "external", "defect"])
def test_failure_category(case: str, tmp_path: Path) -> None:
    """H3：业务数据库故障回滚后追加一条失败事件，保留原类别且 after 为空。"""
    codes = {
        "input": (sqlite3.SQLITE_CORRUPT, InputError),
        "conflict": (sqlite3.SQLITE_CONSTRAINT, ConflictError),
        "external": (sqlite3.SQLITE_IOERR, ExternalError),
        "defect": (sqlite3.SQLITE_ERROR, DefectError),
    }
    code, expected = codes[case]
    with account_action(tmp_path, "set_role") as (service, action):
        before = operations(service)
        state = persisted_account_state(service.engine)

        def fail(_connection: Connection, _cursor: Any, statement: str, *_args: Any) -> None:
            if statement.startswith("UPDATE accounts"):
                error = sqlite3.DatabaseError("秘密驱动错误")
                error.sqlite_errorcode = code
                raise error

        event.listen(service.engine, "before_cursor_execute", fail)
        try:
            with pytest.raises(expected) as caught:
                action()
        finally:
            event.remove(service.engine, "before_cursor_execute", fail)
        assert persisted_account_state(service.engine) == state
        after = operations(service)
        assert len(after) == len(before) + 1
        assert after[0].event.result is OperationResult.FAILURE
        assert after[0].event.failure_category is caught.value.category
        assert after[0].event.details.after.model_dump(exclude_none=True) == {}
        assert "秘密" not in str(getattr(caught.value, "__notes__", ()))


@pytest.mark.parametrize(
    "case",
    ["success", "wrong_password", "fifth_wrong_password", "disabled", "waiting", "account_missing"],
)
def test_login_outcomes(case: str, tmp_path: Path) -> None:
    """验收3：每类登录结果恰有一条且带ASGI来源IP；第五次错口令仍记wrong_password。"""
    with scenario(tmp_path) as (service, _grant):
        wrong = Credentials("admin", SecretStr("wrong-password-value"))
        if case in {"fifth_wrong_password", "waiting"}:
            for _ in range(4 if case == "fifth_wrong_password" else 5):
                with pytest.raises(InputError):
                    service.login(wrong, now=NOW, audit=AUDIT_CONTEXT)
        if case == "disabled":
            with session_scope(service.engine) as session:
                session.execute(update(AccountRow).values(status="disabled"))
        before = _logins(service)
        credentials = (
            Credentials("unknown_secret_name", EXAMPLE_SECRET)
            if case == "account_missing"
            else (
                wrong
                if case in {"wrong_password", "fifth_wrong_password", "waiting"}
                else Credentials("admin", EXAMPLE_SECRET)
            )
        )
        if case == "success":
            service.login(credentials, now=NOW, audit=AUDIT_CONTEXT)
        else:
            with pytest.raises(
                LoginWaitError
                if case in {"fifth_wrong_password", "waiting"}
                else AuthenticationError
            ):
                service.login(credentials, now=NOW, audit=AUDIT_CONTEXT)
        rows = _logins(service)
        assert len(rows) == len(before) + 1
        expected = "wrong_password" if case == "fifth_wrong_password" else case
        assert rows[0].event.result.value == expected
        assert rows[0].event.context.source_ip == "127.0.0.1"
        if case == "account_missing":
            assert rows[0].event.account is None and rows[0].event.login_name is None
            assert rows[0].event.context.request_id is None


@pytest.mark.parametrize("case", ["g2_increment", "g2_wait", "success", "rehash", "commit_failure"])
def test_login_atomic(case: str, tmp_path: Path) -> None:
    """验收2/3：G2递增/等待设置/成功清零及会话签发与登录日志原子提交，日志失败不得签cookie。"""
    from argon2 import PasswordHasher

    from rdp.accounts.security import PasswordCodec

    with scenario(tmp_path) as (service, _grant):
        wrong = Credentials("admin", SecretStr("wrong-password-value"))
        if case in {"g2_wait", "success"}:
            for _ in range(4 if case == "g2_wait" else 2):
                with pytest.raises(AuthenticationError):
                    service.login(wrong, now=NOW, audit=AUDIT_CONTEXT)
        before = _logins(service)
        state = persisted_account_state(service.engine)
        if case == "rehash":
            service.passwords = PasswordCodec(
                PasswordHasher(time_cost=2, memory_cost=1024, parallelism=1)
            )
        if case == "commit_failure":
            with fail_write_commit(service.engine), pytest.raises(ExternalError):
                service.login(Credentials("admin", EXAMPLE_SECRET), now=NOW, audit=AUDIT_CONTEXT)
            assert persisted_account_state(service.engine) == state
            assert _logins(service) == before
        else:
            if case in {"g2_increment", "g2_wait"}:
                with pytest.raises(InputError):
                    service.login(wrong, now=NOW, audit=AUDIT_CONTEXT)
            else:
                service.login(Credentials("admin", EXAMPLE_SECRET), now=NOW, audit=AUDIT_CONTEXT)
            assert len(_logins(service)) == len(before) + 1
            with session_scope(service.engine, read_only=True) as session:
                row = session.get(AccountRow, 1)
                assert row is not None
                assert row.failed_attempts == (
                    1 if case == "g2_increment" else (5 if case == "g2_wait" else 0)
                )
                assert (row.blocked_until is not None) == (case == "g2_wait")
                if case == "rehash":
                    assert "t=2" in row.password_hash


def test_missing_login_privacy(tmp_path: Path) -> None:
    """验收3/4/H2：未知登录名疑似口令也不落库或报错，仅时间类型结果IP，未建账号且不计G2。"""
    with scenario(tmp_path) as (service, _grant):
        state = persisted_account_state(service.engine)
        with pytest.raises(AuthenticationError) as caught:
            service.login(
                Credentials("secret_in_login_field", EXAMPLE_SECRET), now=NOW, audit=AUDIT_CONTEXT
            )
        assert persisted_account_state(service.engine) == state
        row = _logins(service)[0].event
        assert row.result is LoginResult.ACCOUNT_MISSING
        assert row.account is None and row.login_name is None and row.context.request_id is None
        assert "secret_in_login_field" not in repr(row)
        assert "secret_in_login_field" not in str(caught.value.diagnostics)


@pytest.mark.parametrize("case", ["disabled", "waiting", "deleted", "same_name_recreated"])
def test_login_rejection_race(case: str, tmp_path: Path) -> None:
    """验收3：等待/停用单独短事务重读同一编号，删除转未知身份脱敏；同名新账号不能接管快照。"""
    with scenario(tmp_path) as (service, _grant):
        with session_scope(service.engine) as session:
            row = session.get(AccountRow, 1)
            assert row is not None
            if case == "waiting":
                row.failed_attempts, row.blocked_until = 5, NOW + timedelta(seconds=60)
            else:
                row.status = "disabled"
        before = _logins(service)
        changed = False

        def race(_connection: Connection, _cursor: Any, statement: str, *_args: Any) -> None:
            nonlocal changed
            if (
                statement == "BEGIN IMMEDIATE"
                and not changed
                and case in {"deleted", "same_name_recreated"}
            ):
                changed = True
                with session_scope(service.engine) as session:
                    session.execute(delete(AccountRow).where(AccountRow.account_id == 1))
                    if case == "same_name_recreated":
                        session.add(model_row("admin", display_name="新的同名账号"))

        event.listen(service.engine, "before_cursor_execute", race)
        try:
            with pytest.raises(LoginWaitError if case == "waiting" else AuthenticationError):
                service.login(Credentials("admin", EXAMPLE_SECRET), now=NOW, audit=AUDIT_CONTEXT)
        finally:
            event.remove(service.engine, "before_cursor_execute", race)
        rows = _logins(service)
        assert len(rows) == len(before) + 1
        assert rows[0].event.result.value == (
            "account_missing" if case in {"deleted", "same_name_recreated"} else case
        )
        if case in {"deleted", "same_name_recreated"}:
            assert changed and rows[0].event.account is None


def test_logout_atomic(tmp_path: Path) -> None:
    """验收2/3：登出删除与日志一起提交；重入不重复记，日志失败时会话仍可认证。"""
    with scenario(tmp_path) as (service, grant):
        before = _logins(service)

        def fail(_connection: Connection, _cursor: Any, statement: str, *_args: Any) -> None:
            if statement.startswith("INSERT INTO login_logs"):
                error = sqlite3.OperationalError("登出日志失败")
                error.sqlite_errorcode = sqlite3.SQLITE_IOERR
                raise error

        event.listen(service.engine, "before_cursor_execute", fail)
        try:
            with pytest.raises(ExternalError):
                service.logout(grant.identity, now=NOW, audit=AUDIT_CONTEXT)
        finally:
            event.remove(service.engine, "before_cursor_execute", fail)
        assert (
            service.authenticate(grant.token, now=NOW, audit=AUDIT_CONTEXT).account.account_id == 1
        )
        assert _logins(service) == before
        service.logout(grant.identity, now=NOW, audit=AUDIT_CONTEXT)
        rows = _logins(service)
        assert len(rows) == len(before) + 1 and rows[0].event.kind is LoginKind.LOGOUT
        assert rows[0].event.context == AUDIT_CONTEXT
        service.logout(grant.identity, now=NOW, audit=AUDIT_CONTEXT)
        assert _logins(service) == rows


def test_expiry_atomic(tmp_path: Path) -> None:
    """验收2/3：访问到期会话删除及SESSION_EXPIRED日志同事务，来源是本次访问；并发仅一条。"""
    with scenario(tmp_path) as (service, grant):
        barrier = Barrier(2)
        pool = ThreadPoolExecutor(max_workers=2)
        futures = []

        def expire() -> None:
            barrier.wait(timeout=2)
            with pytest.raises(AuthenticationError):
                service.authenticate(grant.token, now=NOW + timedelta(days=7), audit=AUDIT_CONTEXT)

        try:
            futures = [pool.submit(expire), pool.submit(expire)]
            for future in futures:
                future.result(timeout=3)
        finally:
            pool.shutdown(wait=True, cancel_futures=True)
        with session_scope(service.engine, read_only=True) as session:
            page = query_logins(
                session,
                LoginQuery(LogQuery(), kind=LoginKind.SESSION_EXPIRED),
                existing_account_ids,
            )
            assert len(page.items) == 1
            assert page.items[0].event.context == AUDIT_CONTEXT
            assert page.items[0].event.result is LoginResult.SUCCESS
            assert session.get(SessionRow, grant.identity.token_digest) is None


def test_expiry_short_lock(tmp_path: Path) -> None:
    """验收3：过期删除按SESSION_TOUCH_LOCK_TIMEOUT_MS最多等100毫秒，BUSY/LOCKED不删不记且抛AuthenticationError，下次访问删并记录一次。"""
    with scenario(tmp_path) as (service, grant):
        with session_scope(service.engine):
            start = time.monotonic()
            with pytest.raises(AuthenticationError):
                service.authenticate(grant.token, now=NOW + timedelta(days=7), audit=AUDIT_CONTEXT)
            assert time.monotonic() - start < 1
        with session_scope(service.engine, read_only=True) as session:
            assert session.get(SessionRow, grant.identity.token_digest) is not None
            assert (
                query_logins(
                    session,
                    LoginQuery(LogQuery(), kind=LoginKind.SESSION_EXPIRED),
                    existing_account_ids,
                ).items
                == ()
            )
        with pytest.raises(AuthenticationError):
            service.authenticate(grant.token, now=NOW + timedelta(days=7), audit=AUDIT_CONTEXT)
        with session_scope(service.engine, read_only=True) as session:
            assert session.get(SessionRow, grant.identity.token_digest) is None
            assert (
                len(
                    query_logins(
                        session,
                        LoginQuery(LogQuery(), kind=LoginKind.SESSION_EXPIRED),
                        existing_account_ids,
                    ).items
                )
                == 1
            )


@pytest.mark.parametrize("case", ["write", "commit", "io", "defect"])
def test_expiry_other_errors(case: str, tmp_path: Path) -> None:
    """规范7.1：已获锁后的过期日志写入/提交失败全回滚并报告，不被短锁豁免吞掉。"""
    with scenario(tmp_path) as (service, grant):
        code = {
            "write": sqlite3.SQLITE_BUSY,
            "commit": sqlite3.SQLITE_IOERR,
            "io": sqlite3.SQLITE_IOERR,
            "defect": sqlite3.SQLITE_ERROR,
        }[case]
        expected = {
            "write": ConflictError,
            "commit": ExternalError,
            "io": ExternalError,
            "defect": DefectError,
        }[case]

        def fail(connection: Connection, *_args: Any) -> None:
            if not connection.get_execution_options().get("rdp_read_only"):
                error = sqlite3.OperationalError("过期写入故障")
                error.sqlite_errorcode = code
                raise error

        def statement(connection: Connection, _cursor: Any, sql: str, *_args: Any) -> None:
            if sql.startswith("INSERT INTO login_logs"):
                fail(connection)

        target = "commit" if case == "commit" else "before_cursor_execute"
        callback = fail if case == "commit" else statement
        event.listen(service.engine, target, callback)
        try:
            with pytest.raises(expected):
                service.authenticate(grant.token, now=NOW + timedelta(days=7), audit=AUDIT_CONTEXT)
        finally:
            event.remove(service.engine, target, callback)
        with session_scope(service.engine, read_only=True) as session:
            assert session.get(SessionRow, grant.identity.token_digest) is not None
            assert (
                query_logins(
                    session,
                    LoginQuery(LogQuery(), kind=LoginKind.SESSION_EXPIRED),
                    existing_account_ids,
                ).items
                == ()
            )


def test_session_rollback_clock(tmp_path: Path) -> None:
    """时间契约：负经过时长按0，回拨不刷新/过期误判、不报冲突，活动刷新不写日志。"""
    with scenario(tmp_path) as (service, grant):
        before = _logins(service)
        identity = service.authenticate(
            grant.token, now=NOW - timedelta(days=2), audit=AUDIT_CONTEXT
        )
        assert identity.last_seen_at == NOW and not identity.activity_refreshed
        assert _logins(service) == before
        assert service.authenticate(
            grant.token, now=NOW + timedelta(seconds=60), audit=AUDIT_CONTEXT
        ).activity_refreshed
        assert _logins(service) == before


@pytest.mark.parametrize("case", ["disable", "delete", "reset", "capacity", "change_password"])
def test_no_fabricated_logout(case: str, tmp_path: Path) -> None:
    """验收3：账号管理撤销/会话容量淘汰/改密轮换不冒充显式登出或过期访问。"""
    actual = {
        "delete": "delete_account",
        "reset": "reset_password",
        "capacity": "change_password",
    }.get(case, case)
    with account_action(tmp_path, actual) as (service, action):
        member = service.login(Credentials("member", EXAMPLE_SECRET), now=NOW, audit=AUDIT_CONTEXT)
        before = _logins(service)
        if case == "capacity":
            for _ in range(33):
                service.login(Credentials("admin", EXAMPLE_SECRET), now=NOW, audit=AUDIT_CONTEXT)
            assert all(row.event.kind is LoginKind.LOGIN for row in _logins(service))
        else:
            action()
            assert [(row.log_id, row.event) for row in _logins(service)] == [
                (row.log_id, row.event) for row in before
            ]
        assert member.identity.account.account_id == 2


@pytest.mark.parametrize("case", ["admin_reset", "ops_reset", "own_change", "failed_hash"])
def test_password_secrets(case: str, tmp_path: Path) -> None:
    """验收4：重置和本人改密只记强制标记，不存口令哈希令牌摘要cookie或带秘密的异常链。"""
    actual = {
        "admin_reset": "reset_password",
        "ops_reset": "reset_password_from_ops",
        "own_change": "change_password",
        "failed_hash": "reset_password",
    }[case]
    with account_action(tmp_path, actual) as (service, action):
        if case == "failed_hash":
            hasher = HookHasher()
            service.passwords = PasswordCodec(hasher)

            def fail() -> None:
                raise RuntimeError("replacement-value 秘密")

            hasher.on_hash = fail
            with pytest.raises(DefectError) as caught:
                action()
            assert caught.value.__cause__ is None and caught.value.__context__ is None
        else:
            action()
        row = operations(service)[0].event
        assert set(row.details.before.model_dump(exclude_none=True)) <= {"must_change_password"}
        assert set(row.details.after.model_dump(exclude_none=True)) <= {"must_change_password"}
        assert "replacement-value" not in repr(row) and "$argon2" not in repr(row)


def test_own_wrong_password(tmp_path: Path) -> None:
    """H3：错旧口令的G2与失败操作日志同提交，错误后原会话仍有效，且不误写登录日志。"""
    with scenario(tmp_path) as (service, grant):
        before, logins = operations(service), _logins(service)
        with pytest.raises(CurrentPasswordError):
            service.change_password(
                grant.identity,
                PasswordChange(SecretStr("wrong-old-value"), SecretStr("new-password-value")),
                now=NOW,
                audit=AUDIT_CONTEXT,
            )
        assert len(operations(service)) == len(before) + 1
        assert operations(service)[0].event.result is OperationResult.FAILURE
        assert operations(service)[0].event.failure_category is InputError.category
        assert _logins(service) == logins
        assert (
            service.authenticate(grant.token, now=NOW, audit=AUDIT_CONTEXT).account.account_id == 1
        )
        with session_scope(service.engine, read_only=True) as session:
            row = session.get(AccountRow, 1)
            assert row is not None and row.failed_attempts == 1


@pytest.mark.parametrize("case", ["bootstrap", "reset"])
def test_ops_actor(case: str, tmp_path: Path) -> None:
    """验收2/7：首管理员及运维重置必须显式传OPS_AUDIT_CONTEXT，操作人为ActorRef(None,运维)，来源和请求编号均空。"""
    actual = "create_first_admin" if case == "bootstrap" else "reset_password_from_ops"
    with account_action(tmp_path, actual) as (service, action):
        action()
        event = operations(service)[0].event
        assert event.actor == ActorRef(None, "运维")
        assert event.context == OPS_AUDIT_CONTEXT


def test_actor_reexport() -> None:
    """验收7/依赖：accounts.types.ActorRef与infra.actors.ActorRef是同一值对象，audit不反向import账号。"""
    from rdp.infra.actors import ActorRef as SharedActorRef

    assert ActorRef is SharedActorRef
    assert ActorRef(7, "旧名字") == SharedActorRef(7, "旧名字")


def test_failure_notice_survives_secret_boundary(tmp_path: Path) -> None:
    """H3/6.10：protect仅保留固定AUDIT_APPEND_FAILED标记，第二异常及任意notes秘密仍被丢弃。"""
    with account_action(tmp_path, "set_role") as (service, action):

        def fail(_connection: Connection, _cursor: Any, statement: str, *_args: Any) -> None:
            if statement.startswith(("UPDATE accounts", "INSERT INTO operation_logs")):
                error = sqlite3.OperationalError("秘密异常原文")
                error.sqlite_errorcode = sqlite3.SQLITE_IOERR
                error.add_note("秘密注释")
                raise error

        event.listen(service.engine, "before_cursor_execute", fail)
        try:
            with pytest.raises(ExternalError) as caught:
                action()
        finally:
            event.remove(service.engine, "before_cursor_execute", fail)
        assert AUDIT_APPEND_FAILED in caught.value.__notes__
        assert "秘密" not in str(caught.value.__notes__)
        assert caught.value.__cause__ is None and caught.value.__context__ is None


@pytest.mark.parametrize("case", ["snapshot_read", "hash_capacity", "state_race", "commit"])
def test_login_execution_failure(case: str, tmp_path: Path) -> None:
    """验收3/H3：读故障、真实哈希名额耗尽、并发G2变化和提交失败，各按原类别补登录failure。"""
    with scenario(tmp_path) as (service, _grant):
        before = _logins(service)
        expected = ConflictError if case == "state_race" else ExternalError

        def fail_read(_connection: Connection, _cursor: Any, statement: str, *_args: Any) -> None:
            if statement.startswith("SELECT") and "FROM accounts" in statement:
                error = sqlite3.OperationalError("读取故障含秘密")
                error.sqlite_errorcode = sqlite3.SQLITE_IOERR
                raise error

        def fail_commit(connection: Connection) -> None:
            if not connection.get_execution_options().get(
                "rdp_read_only"
            ) and not connection.get_execution_options().get("rdp_lock_timeout_ms"):
                error = sqlite3.OperationalError("提交故障含秘密")
                error.sqlite_errorcode = sqlite3.SQLITE_IOERR
                raise error

        if case == "state_race":
            hasher = HookHasher()
            service.passwords = PasswordCodec(hasher)
            hasher.on_verify = lambda: _mutate_g2(service)
        target = "before_cursor_execute" if case == "snapshot_read" else "commit"
        callback = fail_read if case == "snapshot_read" else fail_commit
        if case in {"snapshot_read", "commit"}:
            event.listen(service.engine, target, callback)
        try:
            if case == "hash_capacity":
                with _hold_hash_slots(service), pytest.raises(expected):
                    service.login(
                        Credentials("admin", EXAMPLE_SECRET), now=NOW, audit=AUDIT_CONTEXT
                    )
            else:
                with pytest.raises(expected):
                    service.login(
                        Credentials("admin", EXAMPLE_SECRET), now=NOW, audit=AUDIT_CONTEXT
                    )
        finally:
            if case in {"snapshot_read", "commit"}:
                event.remove(service.engine, target, callback)
        rows = _logins(service)
        assert len(rows) == len(before) + 1
        assert rows[0].event.result is LoginResult.FAILURE
        assert rows[0].event.failure_category is expected.category
        if case == "snapshot_read":
            assert rows[0].event.account is None and rows[0].event.context.request_id is None


@pytest.mark.parametrize("case", ["hash_failure", "flush_then_rollback"])
def test_failed_creation_has_no_reusable_account_id(case: str, tmp_path: Path) -> None:
    """验收7：失败新建不保存回滚事务曾分配的账号编号，防止编号被后续成功账号复用而错关联。"""
    with account_action(tmp_path, "create_account") as (service, action):
        hasher = HookHasher()
        service.passwords = PasswordCodec(hasher)
        fired = False

        def fail_hash() -> None:
            raise RuntimeError("哈希失败")

        def fail_sql(_connection: Connection, _cursor: Any, statement: str, *_args: Any) -> None:
            nonlocal fired
            if statement.startswith("INSERT INTO operation_logs") and not fired:
                fired = True
                error = sqlite3.OperationalError("日志失败")
                error.sqlite_errorcode = sqlite3.SQLITE_IOERR
                raise error

        if case == "hash_failure":
            hasher.on_hash = fail_hash
        else:
            event.listen(service.engine, "before_cursor_execute", fail_sql)
        try:
            with pytest.raises(DefectError if case == "hash_failure" else ExternalError):
                action()
        finally:
            hasher.on_hash = None
            if case != "hash_failure":
                event.remove(service.engine, "before_cursor_execute", fail_sql)
        failed = operations(service)[0]
        assert (
            failed.event.result is OperationResult.FAILURE and failed.event.target.object_id is None
        )
        action()
        assert operations(service)[1].event.target.object_id is None


@pytest.mark.parametrize("case", ["operations", "logins", "retention"])
def test_read_permissions(case: str, tmp_path: Path) -> None:
    """验收6：管理员可查询，角色在数据库改变后旧快照不能绕过同事务权限重验。"""
    with scenario(tmp_path) as (service, grant):
        calls = {
            "operations": lambda: service.list_operations(
                grant.identity, OperationQuery(LogQuery()), now=NOW
            ),
            "logins": lambda: service.list_logins(grant.identity, LoginQuery(LogQuery()), now=NOW),
            "retention": lambda: service.get_log_retention(grant.identity, now=NOW),
        }
        result = calls[case]()
        if case == "retention":
            assert result == 30
        else:
            assert result is not None
        with session_scope(service.engine) as session:
            session.execute(
                update(AccountRow)
                .where(AccountRow.account_id == grant.identity.account.account_id)
                .values(role="member")
            )
        with pytest.raises(AuthorizationError):
            calls[case]()


@pytest.mark.parametrize(
    "method",
    [
        "login",
        "authenticate",
        "logout",
        "change_password",
        "create_account",
        "set_role",
        "set_status",
        "reset_password",
        "delete_account",
        "create_first_admin",
        "reset_password_from_ops",
    ],
)
def test_audit_keyword_required(method: str, tmp_path: Path) -> None:
    """验收3/修订1：公开服务含protect时漏传audit仍为绑定TypeError，不转DefectError或进入业务体。"""
    with scenario(tmp_path) as (service, _grant):
        operation = getattr(service, method)
        parameters = signature(operation).parameters
        assert parameters["audit"].kind is Parameter.KEYWORD_ONLY
        assert parameters["audit"].default is Parameter.empty
        # 其他参数给占位值以隔离audit缺参；绑定必须早于对这些值的业务验证。
        arguments = [
            None for value in parameters.values() if value.kind is Parameter.POSITIONAL_OR_KEYWORD
        ]
        with pytest.raises(TypeError, match="audit"):
            operation(*arguments, now=NOW)


@pytest.mark.parametrize(
    "method",
    [
        "login",
        "authenticate",
        "logout",
        "change_password",
        "create_account",
        "set_role",
        "set_status",
        "reset_password",
        "delete_account",
        "create_first_admin",
        "reset_password_from_ops",
    ],
)
@pytest.mark.parametrize("case", ["none", "wrong_type", "bad_ip", "bad_request_id"])
def test_invalid_audit_is_defect(method: str, case: str, tmp_path: Path) -> None:
    """修订5：非法上下文在任何SQL前归DefectError，不能以有效业务参数掩盖来源错误。"""
    invalid_cases: dict[str, object] = {
        "none": None,
        "wrong_type": {},
        "bad_ip": AuditContext("invalid", "123e4567e89b42d3a456426614174000"),
        "bad_request_id": AuditContext(None, "invalid"),
    }
    invalid = invalid_cases[case]
    with scenario(tmp_path) as (service, grant):
        calls: list[None] = []

        def observe(_connection: Connection, *_args: Any) -> None:
            calls.append(None)

        event.listen(service.engine, "before_cursor_execute", observe)
        try:
            with pytest.raises(DefectError):
                getattr(service, method)(*_audit_arguments(grant)[method], now=NOW, audit=invalid)
            assert calls == []
        finally:
            event.remove(service.engine, "before_cursor_execute", observe)


@pytest.mark.parametrize(
    "method",
    [
        "login",
        "authenticate",
        "logout",
        "change_password",
        "create_account",
        "set_role",
        "set_status",
        "reset_password",
        "delete_account",
    ],
)
def test_http_context_requires_request_id(method: str, tmp_path: Path) -> None:
    """修订1/5：HTTP领域调用的服务器请求编号不能空，OPS_AUDIT_CONTEXT不得冒充请求上下文。"""
    with scenario(tmp_path) as (service, grant), pytest.raises(DefectError):
        getattr(service, method)(*_audit_arguments(grant)[method], now=NOW, audit=OPS_AUDIT_CONTEXT)


@pytest.mark.parametrize("case", ["bootstrap", "reset"])
def test_ops_context_rejects_http_metadata(case: str, tmp_path: Path) -> None:
    """修订1：运维调用拒绝任一非空IP或请求编号，归DefectError而非执行业务。"""
    method = "create_first_admin" if case == "bootstrap" else "reset_password_from_ops"
    with scenario(tmp_path) as (service, grant):
        for audit in (
            AuditContext("127.0.0.1", None),
            AuditContext(None, "123e4567e89b42d3a456426614174000"),
        ):
            with pytest.raises(DefectError):
                getattr(service, method)(*_audit_arguments(grant)[method], now=NOW, audit=audit)


@pytest.mark.parametrize(
    "case",
    [
        "duplicate_login",
        "demote_last_admin",
        "disable_last_admin",
        "delete_last_admin",
        "create_first_admin_race",
    ],
)
def test_conflict_after_admin_precheck_is_logged(case: str, tmp_path: Path) -> None:
    """H3/修订4：管理员预检通过后写事务中的重名/最后管理员/并发首号冲突算已开始，回滚后恰有失败日志而无成功日志。"""
    if case == "create_first_admin_race":
        with account_action(tmp_path, "create_first_admin") as (service, action):
            hasher = HookHasher()
            service.passwords = PasswordCodec(hasher)

            def concurrent() -> None:
                other = AccountService(service.engine, PasswordCodec())
                other.create_first_admin(
                    NewAccount(Credentials("winner", EXAMPLE_SECRET), "赢家", Role.ADMINISTRATOR),
                    now=NOW,
                    audit=OPS_AUDIT_CONTEXT,
                )

            hasher.on_hash = concurrent
            with pytest.raises(ConflictError):
                action()
            assert operations(service)[0].event.result is OperationResult.FAILURE
        return
    with scenario(tmp_path) as (service, grant):
        actions: dict[str, Callable[[], object]] = {
            "duplicate_login": lambda: service.create_account(
                grant.identity,
                NewAccount(Credentials("admin", EXAMPLE_SECRET), "重名", Role.MEMBER),
                now=NOW,
                audit=AUDIT_CONTEXT,
            ),
            "demote_last_admin": lambda: service.set_role(
                grant.identity, 1, Role.MEMBER, now=NOW, audit=AUDIT_CONTEXT
            ),
            "disable_last_admin": lambda: service.set_status(
                grant.identity, 1, AccountStatus.DISABLED, now=NOW, audit=AUDIT_CONTEXT
            ),
            "delete_last_admin": lambda: service.delete_account(
                grant.identity, 1, now=NOW, audit=AUDIT_CONTEXT
            ),
        }
        before = operations(service)
        with pytest.raises(ConflictError):
            actions[case]()
        assert len(operations(service)) == len(before) + 1
        assert operations(service)[0].event.failure_category is ConflictError.category


@pytest.mark.parametrize("method", ["set_role", "set_status", "delete_account"])
def test_target_disappears_inside_write_is_logged(method: str, tmp_path: Path) -> None:
    """H3：预检后目标消失记失败，预检后操作者失去权限仍不记，快照不接管新账号。"""
    actual = "disable" if method == "set_status" else method
    with account_action(tmp_path, actual) as (service, action):
        before = operations(service)
        changed = False

        def mutate(_connection: Connection, _cursor: Any, statement: str, *_args: Any) -> None:
            nonlocal changed
            if statement == "BEGIN IMMEDIATE" and not changed:
                changed = True
                with session_scope(service.engine) as session:
                    if True:
                        session.execute(delete(AccountRow).where(AccountRow.account_id == 2))
                    else:
                        session.execute(
                            update(AccountRow)
                            .where(AccountRow.account_id == 1)
                            .values(role="member")
                        )

        event.listen(service.engine, "before_cursor_execute", mutate)
        try:
            with pytest.raises(AccountNotFoundError if True else AuthorizationError):
                action()
        finally:
            event.remove(service.engine, "before_cursor_execute", mutate)
        assert changed
        if True:
            assert len(operations(service)) == len(before) + 1
            assert operations(service)[0].event.result is OperationResult.FAILURE
        else:
            assert operations(service) == before


@pytest.mark.parametrize("method", ["set_role", "set_status", "delete_account"])
def test_write_reauthorization_rejection_is_not_logged(method: str, tmp_path: Path) -> None:
    """H3：预检后目标消失记失败，预检后操作者失去权限仍不记，快照不接管新账号。"""
    actual = "disable" if method == "set_status" else method
    with account_action(tmp_path, actual) as (service, action):
        before = operations(service)
        changed = False

        def mutate(_connection: Connection, _cursor: Any, statement: str, *_args: Any) -> None:
            nonlocal changed
            if statement == "BEGIN IMMEDIATE" and not changed:
                changed = True
                with session_scope(service.engine) as session:
                    if False:
                        session.execute(delete(AccountRow).where(AccountRow.account_id == 2))
                    else:
                        session.execute(
                            update(AccountRow)
                            .where(AccountRow.account_id == 1)
                            .values(role="member")
                        )

        event.listen(service.engine, "before_cursor_execute", mutate)
        try:
            with pytest.raises(AccountNotFoundError if False else AuthorizationError):
                action()
        finally:
            event.remove(service.engine, "before_cursor_execute", mutate)
        assert changed
        if False:
            assert len(operations(service)) == len(before) + 1
            assert operations(service)[0].event.result is OperationResult.FAILURE
        else:
            assert operations(service) == before


@pytest.mark.parametrize(
    "case", ["first_wrong", "fifth_wrong", "log_flush_failure", "commit_failure"]
)
def test_own_wrong_password_transaction(case: str, tmp_path: Path) -> None:
    """修订2：第五次等待也和失败操作同提交，日志/提交故障回滚G2，不独立提交旧口令错误结果。"""
    with scenario(tmp_path) as (service, grant):
        change = PasswordChange(SecretStr("wrong-old-value"), SecretStr("new-password-value"))
        if case == "fifth_wrong":
            for _ in range(4):
                with pytest.raises(CurrentPasswordError):
                    service.change_password(grant.identity, change, now=NOW, audit=AUDIT_CONTEXT)
        before = operations(service)
        state = persisted_account_state(service.engine)

        def fail(connection: Connection, *_args: Any) -> None:
            if not connection.get_execution_options().get("rdp_read_only"):
                error = sqlite3.OperationalError("失败日志事务故障")
                error.sqlite_errorcode = sqlite3.SQLITE_IOERR
                raise error

        def statement(connection: Connection, _cursor: Any, sql: str, *_args: Any) -> None:
            if sql.startswith("INSERT INTO operation_logs"):
                fail(connection)

        failing = case in {"log_flush_failure", "commit_failure"}
        target, callback = (
            ("commit", fail) if case == "commit_failure" else ("before_cursor_execute", statement)
        )
        if failing:
            event.listen(service.engine, target, callback)
        try:
            with pytest.raises(
                ExternalError
                if failing
                else (LoginWaitError if case == "fifth_wrong" else CurrentPasswordError)
            ):
                service.change_password(grant.identity, change, now=NOW, audit=AUDIT_CONTEXT)
        finally:
            if failing:
                event.remove(service.engine, target, callback)
        if failing:
            assert persisted_account_state(service.engine) == state
            assert operations(service) == before
        else:
            assert len(operations(service)) == len(before) + 1
            with session_scope(service.engine, read_only=True) as session:
                row = session.get(AccountRow, 1)
                assert row is not None and row.failed_attempts == (
                    5 if case == "fifth_wrong" else 1
                )


def test_expired_session_never_accessed_has_no_log(tmp_path: Path) -> None:
    """验收3/修订9：只推进固定时钟而不访问过期会话，不发生删除也没有SESSION_EXPIRED日志。"""
    with (
        scenario(tmp_path) as (service, grant),
        session_scope(service.engine, read_only=True) as session,
    ):
        assert session.get(SessionRow, grant.identity.token_digest) is not None
        assert (
            query_logins(
                session,
                LoginQuery(LogQuery(start=NOW + timedelta(days=8)), kind=LoginKind.SESSION_EXPIRED),
                existing_account_ids,
            ).items
            == ()
        )


def test_contract_module_removed_before_implementation() -> None:
    """修订10：契约只由唯一AccountService承载，audit_contract模块已删除，不存在第二个运行服务。"""
    assert find_spec("rdp.accounts.audit_contract") is None
    assert all(
        hasattr(AccountService, method)
        for method in ("list_operations", "list_logins", "get_log_retention", "set_log_retention")
    )


def _audit_arguments(grant: SessionGrant) -> dict[str, tuple[object, ...]]:
    """各公开方法的有效业务参数，非法上下文测试只改变audit，不让别的字段先失败。"""
    command = NewAccount(Credentials("other", EXAMPLE_SECRET), "第二账号", Role.MEMBER)
    return {
        "login": (Credentials("admin", EXAMPLE_SECRET),),
        "authenticate": (grant.token,),
        "logout": (grant.identity,),
        "change_password": (
            grant.identity,
            PasswordChange(EXAMPLE_SECRET, SecretStr("replacement-value")),
        ),
        "create_account": (grant.identity, command),
        "set_role": (grant.identity, grant.identity.account.account_id, Role.ADMINISTRATOR),
        "set_status": (grant.identity, grant.identity.account.account_id, AccountStatus.ENABLED),
        "reset_password": (
            grant.identity,
            grant.identity.account.account_id,
            SecretStr("replacement-value"),
        ),
        "delete_account": (grant.identity, grant.identity.account.account_id),
        "create_first_admin": (
            NewAccount(Credentials("first", EXAMPLE_SECRET), "首号", Role.ADMINISTRATOR),
        ),
        "reset_password_from_ops": ("admin", SecretStr("replacement-value")),
    }


def _logins(service: AccountService) -> tuple[LoginView, ...]:
    """只通过日志公开查询观察提交结果，不从被测函数生成期望。"""
    with session_scope(service.engine, read_only=True) as session:
        return query_logins(session, LoginQuery(LogQuery()), existing_account_ids).items


@contextmanager
def _hold_hash_slots(service: AccountService) -> Generator[None]:
    """在外部Argon2边界占满名额，所有等待有上限且finally释放线程及恢复编码器。"""
    previous = service.passwords
    hasher = HeldHasher()
    service.passwords = PasswordCodec(hasher)
    pool = ThreadPoolExecutor(max_workers=2)
    futures = []
    hasher.hold.set()
    try:
        futures = [pool.submit(service.passwords.hash, EXAMPLE_SECRET) for _ in range(2)]
        assert hasher.wait_entered(2)
        yield
    finally:
        hasher.release.set()
        try:
            for future in futures:
                future.result(timeout=3)
        finally:
            try:
                pool.shutdown(wait=True, cancel_futures=True)
            finally:
                service.passwords = previous


@pytest.mark.parametrize("case", ["role", "status", "retention"])
def test_noop_commit_failure_not_audited(case: str, tmp_path: Path) -> None:
    """无变化请求不记操作日志，即使结束只读业务的写事务时提交失败，也不伪造已执行改动。"""
    with scenario(tmp_path) as (service, grant):
        before = operations(service)
        calls = {
            "role": lambda: service.set_role(
                grant.identity, 1, Role.ADMINISTRATOR, now=NOW, audit=AUDIT_CONTEXT
            ),
            "status": lambda: service.set_status(
                grant.identity, 1, AccountStatus.ENABLED, now=NOW, audit=AUDIT_CONTEXT
            ),
            "retention": lambda: service.set_log_retention(
                grant.identity, 30, now=NOW, audit=AUDIT_CONTEXT
            ),
        }

        def fail(connection: Connection) -> None:
            if not connection.get_execution_options().get(
                "rdp_read_only"
            ) and not connection.get_execution_options().get("rdp_lock_timeout_ms"):
                error = sqlite3.OperationalError("无变更提交失败")
                error.sqlite_errorcode = sqlite3.SQLITE_IOERR
                raise error

        event.listen(service.engine, "commit", fail)
        try:
            with pytest.raises(ExternalError):
                calls[case]()
        finally:
            event.remove(service.engine, "commit", fail)
        assert operations(service) == before


def _mutate_g2(service: AccountService) -> None:
    """在外部哈希同步点用另一连接提交G2变化，观察快照冲突而非替换领域函数。"""
    with session_scope(service.engine) as session:
        session.execute(
            update(AccountRow).where(AccountRow.account_id == 1).values(failed_attempts=1)
        )


def test_display_name_unicode_rule_shared(tmp_path: Path) -> None:
    """回归：私用区字符 U+E000 符合账号名字规则，创建、操作快照及登录快照必须一致接受。"""
    name = "名字\ue000"
    with scenario(tmp_path) as (service, grant):
        created = service.create_account(
            grant.identity,
            NewAccount(Credentials("private_name", EXAMPLE_SECRET), name, Role.MEMBER),
            now=NOW,
            audit=AUDIT_CONTEXT,
        )
        assert created.display_name == name
        assert operations(service)[0].event.target.name == name
        member = service.login(
            Credentials("private_name", EXAMPLE_SECRET), now=NOW, audit=AUDIT_CONTEXT
        )
        assert member.identity.account.display_name == name
        with session_scope(service.engine, read_only=True) as session:
            page = query_logins(
                session,
                LoginQuery(LogQuery(account_id=created.account_id)),
                existing_account_ids,
            )
        assert page.items[0].event.account == ActorRef(created.account_id, name)


def test_missing_login_hash_capacity_failure_is_audited(tmp_path: Path) -> None:
    """H2：未知登录名假哈希排队超时仍返回原外部失败，恰补一条匿名账号不存在日志且不改业务状态。"""
    unknown_name = "private_unknown_login"
    with scenario(tmp_path) as (service, _grant):
        before = _logins(service)
        business = persisted_account_state(service.engine)
        with _hold_hash_slots(service), pytest.raises(ExternalError) as caught:
            service.login(Credentials(unknown_name, EXAMPLE_SECRET), now=NOW, audit=AUDIT_CONTEXT)
        after = _logins(service)
        assert len(after) == len(before) + 1
        event = after[0].event
        assert event.kind is LoginKind.LOGIN
        assert event.result is LoginResult.ACCOUNT_MISSING
        assert event.account is None and event.login_name is None
        assert event.context == AuditContext(AUDIT_CONTEXT.source_ip, None)
        assert event.failure_category is None
        assert unknown_name not in repr(after)
        assert unknown_name not in str(caught.value)
        assert persisted_account_state(service.engine) == business
