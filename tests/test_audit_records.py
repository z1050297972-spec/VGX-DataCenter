"""日志领域契约清单（07）；仅使用 tmp_path 数据库和固定 aware 时间，不碰真实状态目录。"""

import sqlite3
from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest
from accounts_support import AUDIT_CONTEXT, NOW, model_database, model_row
from audit_support import operation_event
from fastapi.routing import APIRoute
from sqlalchemy import Engine, create_engine, delete, event, text
from sqlalchemy.orm import Session

from rdp.accounts.models import AccountRow
from rdp.accounts.service import existing_account_ids
from rdp.audit.errors import AuditInputError
from rdp.audit.records import (
    append_login,
    append_operation,
    change_retention,
    get_retention,
    query_logins,
    query_operations,
)
from rdp.audit.service import (
    AuditMaintenance,
    append_failed_login,
    append_failed_operation,
    append_missing_login,
)
from rdp.audit.types import (
    AuditContext,
    AuditValues,
    LoginEvent,
    LoginKind,
    LoginQuery,
    LoginResult,
    LogQuery,
    ObjectRef,
    OperationDetails,
    OperationQuery,
    OperationResult,
    OperationType,
    RetentionChange,
)
from rdp.infra.actors import ActorRef
from rdp.infra.db.connection import session_scope
from rdp.infra.diagnostics import (
    ConflictError,
    DefectError,
    DiagnosticCategory,
    ExternalError,
    InputError,
)


def test_append_only() -> None:
    """验收1：公开领域/API没有修改或删除单条日志入口，仅允许按保留期清除。"""
    from rdp.api.audit import router

    exposed = {
        (route.path, tuple(sorted(route.methods or set())))
        for route in router.routes
        if isinstance(route, APIRoute)
    }
    assert exposed == {
        ("/api/audit/operations", ("GET",)),
        ("/api/audit/logins", ("GET",)),
        ("/api/audit/retention", ("GET",)),
        ("/api/audit/retention", ("PUT",)),
    }
    from rdp.audit import records

    assert not any(name.startswith(("delete_", "update_")) for name in vars(records))


@pytest.mark.parametrize("case", ["managed", "unmanaged", "non_sqlite"])
def test_maintenance_engine_contract(
    case: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """规范7.1：维护构造只接受受管SQLite，不连接数据库或安排清除任务。"""
    with model_database(tmp_path) as engine:
        calls: list[None] = []

        def observe(*_args: object) -> None:
            calls.append(None)

        event.listen(engine, "connect", observe)
        try:
            if case == "managed":
                assert AuditMaintenance(engine).engine is engine
            elif case == "non_sqlite":
                monkeypatch.setattr(engine.dialect, "name", "postgresql")
                with pytest.raises(DefectError):
                    AuditMaintenance(engine)
            else:
                unmanaged = create_engine("sqlite://")
                try:
                    with pytest.raises(DefectError):
                        AuditMaintenance(unmanaged)
                finally:
                    unmanaged.dispose()
            assert calls == []
        finally:
            event.remove(engine, "connect", observe)


@pytest.mark.parametrize(
    "case", ["known_failure", "unknown_identity_failure", "missing_category", "unexpected_category"]
)
def test_login_failure_category(case: str, tmp_path: Path) -> None:
    """验收3/4：执行失败必须带类别，其他结果不得带；未确认身份只保留时间类型结果IP。"""
    from accounts_support import AUDIT_CONTEXT

    value = LoginEvent(
        NOW,
        ActorRef(7, "管理员甲"),
        "admin",
        LoginKind.LOGIN,
        LoginResult.FAILURE,
        AUDIT_CONTEXT,
        DiagnosticCategory.EXTERNAL,
    )
    if case == "unknown_identity_failure":
        value = replace(
            value, account=None, login_name=None, context=AuditContext("127.0.0.1", None)
        )
    if case == "missing_category":
        value = replace(value, failure_category=None)
    if case == "unexpected_category":
        value = replace(value, result=LoginResult.SUCCESS)
    with model_database(tmp_path) as engine, session_scope(engine) as session:
        if case in {"missing_category", "unexpected_category"}:
            with pytest.raises(AuditInputError):
                append_login(session, value)
        else:
            assert append_login(session, value) == 1
            assert session.execute(
                text("SELECT result,failure_category FROM login_logs")
            ).one() == ("failure", "external")


@pytest.mark.parametrize("case", ["failure_login", "missing_login"])
def test_independent_login_failure_storage(case: str, tmp_path: Path) -> None:
    """验收3/H3：匿名或执行故障登录只写独立日志，不建账号/G2/会话，短锁失败不留下行。"""
    result = LoginResult.ACCOUNT_MISSING if case == "missing_login" else LoginResult.FAILURE
    category = None if case == "missing_login" else DiagnosticCategory.EXTERNAL
    value = LoginEvent(
        NOW, None, None, LoginKind.LOGIN, result, AuditContext("192.0.2.7", None), category
    )
    append = append_missing_login if case == "missing_login" else append_failed_login
    with model_database(tmp_path) as engine:
        with session_scope(engine), pytest.raises(ConflictError):
            append(engine, value)
        append(engine, value)
        with session_scope(engine, read_only=True) as session:
            assert session.execute(
                text("SELECT result,source_ip,account_id,login_name,request_id FROM login_logs")
            ).one() == (result.value, "192.0.2.7", None, None, None)
            assert session.execute(text("SELECT COUNT(*) FROM accounts")).scalar_one() == 0
            assert session.execute(text("SELECT COUNT(*) FROM account_sessions")).scalar_one() == 0


def test_operation_roundtrip(tmp_path: Path) -> None:
    """验收1/2：追加返回编号且flush后同会话可读，提交保留完整事件，第二次追加不覆盖第一条。"""
    with model_database(tmp_path) as engine:
        with session_scope(engine) as session:
            first = append_operation(session, operation_event())
            assert first == 1
            assert session.execute(
                text(
                    "SELECT actor_id,actor_name,object_id,object_name,result FROM operation_logs WHERE log_id=1"
                )
            ).one() == (7, "管理员甲", "11", "成员乙", "success")
        with session_scope(engine) as session:
            assert (
                append_operation(
                    session, replace(operation_event(), target=ObjectRef("account", "12", "成员丙"))
                )
                == 2
            )
        with session_scope(engine, read_only=True) as session:
            assert session.execute(
                text("SELECT object_name FROM operation_logs ORDER BY log_id")
            ).scalars().all() == ["成员乙", "成员丙"]


def test_operation_rollback(tmp_path: Path) -> None:
    """验收2：追加成功日志后业务抛错，两者在同一事务回滚，独立失败补记不复活成功行。"""
    with model_database(tmp_path) as engine:
        with pytest.raises(ValueError, match="业务失败"), session_scope(engine) as session:
            append_operation(session, operation_event())
            raise ValueError("业务失败")
        with session_scope(engine, read_only=True) as session:
            assert session.execute(text("SELECT COUNT(*) FROM operation_logs")).scalar_one() == 0


@pytest.mark.parametrize(
    "case",
    [
        "naive_time",
        "utc_overflow",
        "bad_actor_id",
        "bad_actor_name",
        "bad_target_kind",
        "bad_target_id",
        "success_with_category",
        "failure_without_category",
        "failure_with_after",
        "unknown_operation",
        "version_bool",
        "unknown_version",
        "too_large_details",
    ],
)
def test_operation_validation(case: str, tmp_path: Path) -> None:
    """验收4：非法操作字段在插入前抛AuditInputError，诊断只含字段身份且不回显被拒绝内容。"""
    changes: dict[str, dict[str, object]] = {
        "naive_time": {"occurred_at": NOW.replace(tzinfo=None)},
        "utc_overflow": {"occurred_at": datetime.min.replace(tzinfo=timezone(timedelta(hours=1)))},
        "bad_actor_id": {"actor": ActorRef(True, "秘密")},
        "bad_actor_name": {"actor": ActorRef(1, " 秘密 ")},
        "bad_target_kind": {"target": replace(ObjectRef("account", "1", "秘密"), kind="bad")},
        "bad_target_id": {"target": ObjectRef("account", "0", "秘密")},
        "success_with_category": {"failure_category": DiagnosticCategory.CONFLICT},
        "failure_without_category": {"result": OperationResult.FAILURE},
        "failure_with_after": {
            "result": OperationResult.FAILURE,
            "failure_category": DiagnosticCategory.INPUT,
        },
        "unknown_operation": {"operation": "secret_unknown"},
        "version_bool": {
            "details": OperationDetails.model_construct(
                version=True, before=AuditValues(), after=AuditValues()
            )
        },
        "unknown_version": {
            "details": OperationDetails.model_construct(
                version=2, before=AuditValues(), after=AuditValues()
            )
        },
        "too_large_details": {
            "details": OperationDetails.model_construct(
                version=1,
                before=AuditValues(),
                after=AuditValues.model_construct(display_name="秘密" * 20000),
            )
        },
    }
    with model_database(tmp_path) as engine, session_scope(engine) as session:
        with pytest.raises(AuditInputError) as caught:
            append_operation(session, replace(operation_event(), **changes[case]))
        assert "秘密" not in str(caught.value.diagnostics)
        assert session.execute(text("SELECT COUNT(*) FROM operation_logs")).scalar_one() == 0


@pytest.mark.parametrize(
    "case",
    [
        "password",
        "password_hash",
        "token",
        "token_digest",
        "cookie",
        "nested_secret",
        "unknown_field",
        "role_on_password_operation",
    ],
)
def test_detail_whitelist(case: str, tmp_path: Path) -> None:
    """验收4：各操作只接受自己的白名单，秘密字段及未知字段拒绝，持久化和错误均不泄漏。"""
    value = operation_event()
    if case == "role_on_password_operation":
        value = replace(
            value,
            operation=OperationType.RESET_PASSWORD,
            details=OperationDetails(before=AuditValues(role="member"), after=AuditValues()),
        )
    else:
        data = (
            {case: "不能落日志的秘密"}
            if case != "nested_secret"
            else {"display_name": {"token": "不能落日志的秘密"}}
        )
        value = replace(value, details=value.details.model_copy(update={"before": data}))
    with model_database(tmp_path) as engine, session_scope(engine) as session:
        with pytest.raises(AuditInputError) as caught:
            append_operation(session, value)
        assert "不能落日志的秘密" not in str(caught.value.diagnostics)
        assert session.execute(text("SELECT COUNT(*) FROM operation_logs")).scalar_one() == 0


@pytest.mark.parametrize(
    "case",
    [
        "create_empty_before",
        "delete_empty_after",
        "failure_empty_after",
        "role_values",
        "status_values",
        "password_flag_only",
        "retention_values",
    ],
)
def test_detail_shape(case: str, tmp_path: Path) -> None:
    """验收4：v1明细严格保留before/after语义，给M1撤回留下结构。"""
    import json

    cases: dict[str, tuple[OperationType, dict[str, object], dict[str, object]]] = {
        "create_empty_before": (OperationType.CREATE_ACCOUNT, {}, {"role": "member"}),
        "delete_empty_after": (OperationType.DELETE_ACCOUNT, {"role": "member"}, {}),
        "failure_empty_after": (OperationType.SET_ROLE, {"role": "member"}, {}),
        "role_values": (OperationType.SET_ROLE, {"role": "member"}, {"role": "administrator"}),
        "status_values": (
            OperationType.DISABLE_ACCOUNT,
            {"status": "enabled"},
            {"status": "disabled"},
        ),
        "password_flag_only": (
            OperationType.RESET_PASSWORD,
            {"must_change_password": False},
            {"must_change_password": True},
        ),
        "retention_values": (
            OperationType.SET_RETENTION,
            {"retention_days": 30},
            {"retention_days": 7},
        ),
    }
    kind, before, after = cases[case]
    expected = {"version": 1, "before": before, "after": after}
    value = replace(
        operation_event(), operation=kind, details=OperationDetails.model_validate(expected)
    )
    if case == "failure_empty_after":
        value = replace(
            value, result=OperationResult.FAILURE, failure_category=DiagnosticCategory.CONFLICT
        )
    if case == "retention_values":
        value = replace(value, target=ObjectRef("audit_settings", "retention", "日志保留期"))
    with model_database(tmp_path) as engine, session_scope(engine) as session:
        append_operation(session, value)
        assert (
            json.loads(session.execute(text("SELECT details FROM operation_logs")).scalar_one())
            == expected
        )


@pytest.mark.parametrize(
    "case",
    [
        "input_corruption",
        "constraint_conflict",
        "disk_io",
        "sql_defect",
        "read_only",
        "unmanaged_session",
        "unbound_session",
    ],
)
def test_append_storage_failure(case: str, tmp_path: Path) -> None:
    """规范7.1：追加失败归四类异常，退出工作单元完整回滚；只读会话不得写。"""
    if case == "unbound_session":
        with Session() as session, pytest.raises(DefectError):
            append_operation(session, operation_event())
        return
    if case == "unmanaged_session":
        engine = create_engine("sqlite://")
        try:
            with Session(engine) as session, pytest.raises(DefectError):
                append_operation(session, operation_event())
        finally:
            engine.dispose()
        return
    codes = {
        "input_corruption": (sqlite3.SQLITE_CORRUPT, InputError),
        "constraint_conflict": (sqlite3.SQLITE_CONSTRAINT, ConflictError),
        "disk_io": (sqlite3.SQLITE_IOERR, ExternalError),
        "sql_defect": (sqlite3.SQLITE_ERROR, DefectError),
    }
    with model_database(tmp_path) as engine:
        if case == "read_only":
            with session_scope(engine, read_only=True) as session, pytest.raises(DefectError):
                append_operation(session, operation_event())
            return
        code, expected = codes[case]

        def fail(_connection: Any, _cursor: Any, statement: str, *_args: Any) -> None:
            if statement.startswith("INSERT INTO operation_logs"):
                error = sqlite3.DatabaseError("不回显驱动秘密")
                error.sqlite_errorcode = code
                raise error

        event.listen(engine, "before_cursor_execute", fail)
        try:
            with pytest.raises(expected), session_scope(engine) as session:
                append_operation(session, operation_event())
        finally:
            event.remove(engine, "before_cursor_execute", fail)
        with session_scope(engine, read_only=True) as session:
            assert session.execute(text("SELECT COUNT(*) FROM operation_logs")).scalar_one() == 0


@pytest.mark.parametrize(
    "case",
    [
        "missing_without_identity",
        "missing_rejects_name",
        "missing_rejects_request_id",
        "known_requires_snapshot",
        "logout_requires_success",
        "expiry_requires_success",
        "invalid_kind",
        "invalid_time",
    ],
)
def test_login_shape(case: str, tmp_path: Path) -> None:
    """验收3/4：匿名身份组合、删除结果和事件时间严格校验；匿名请求编号违反入口契约归DefectError。"""
    from accounts_support import AUDIT_CONTEXT

    known = LoginEvent(
        NOW, ActorRef(7, "管理员甲"), "admin", LoginKind.LOGIN, LoginResult.SUCCESS, AUDIT_CONTEXT
    )
    unknown = replace(
        known,
        account=None,
        login_name=None,
        result=LoginResult.ACCOUNT_MISSING,
        context=AuditContext("127.0.0.1", None),
    )
    cases = {
        "missing_without_identity": unknown,
        "missing_rejects_name": replace(unknown, login_name="不应保存的秘密"),
        "missing_rejects_request_id": replace(unknown, context=AUDIT_CONTEXT),
        "known_requires_snapshot": replace(known, account=None),
        "logout_requires_success": replace(
            known, kind=LoginKind.LOGOUT, result=LoginResult.WRONG_PASSWORD
        ),
        "expiry_requires_success": replace(
            known, kind=LoginKind.SESSION_EXPIRED, result=LoginResult.WAITING
        ),
        "invalid_kind": replace(known, kind="invalid"),
        "invalid_time": replace(known, occurred_at=NOW.replace(tzinfo=None)),
    }
    with model_database(tmp_path) as engine, session_scope(engine) as session:
        if case == "missing_without_identity":
            assert append_login(session, cases[case]) == 1
            assert session.execute(
                text(
                    "SELECT account_id,account_name,login_name,request_id,source_ip FROM login_logs"
                )
            ).one() == (None, None, None, None, "127.0.0.1")
        else:
            expected = DefectError if case == "missing_rejects_request_id" else AuditInputError
            with pytest.raises(expected):
                append_login(session, cases[case])
            assert session.execute(text("SELECT COUNT(*) FROM login_logs")).scalar_one() == 0


def test_query_order(tmp_path: Path) -> None:
    """验收1：相同微秒用编号倒序，空页与末页正确，不用offset且每页上限具名。"""
    with model_database(tmp_path) as engine:
        with session_scope(engine, read_only=True) as session:
            empty = query_operations(session, OperationQuery(LogQuery()), existing_account_ids)
            assert empty.items == () and empty.next_cursor is None
        _seed_logs(engine, (NOW, NOW, NOW))
        with session_scope(engine, read_only=True) as session:
            first = query_operations(
                session, OperationQuery(LogQuery(limit=2)), existing_account_ids
            )
            assert [item.log_id for item in first.items] == [3, 2]
            assert first.next_cursor is not None
        with session_scope(engine, read_only=True) as session:
            last = query_operations(
                session,
                OperationQuery(LogQuery(limit=2, cursor=first.next_cursor)),
                existing_account_ids,
            )
            assert [item.log_id for item in last.items] == [1]
            assert last.next_cursor is None


@pytest.mark.parametrize("case", ["operations", "logins"])
def test_query_intersection(case: str, tmp_path: Path) -> None:
    """验收1：时间、账号、类型与结果严格AND匹配，分页不漏掉唯一符合的事件。"""
    with model_database(tmp_path) as engine:
        with session_scope(engine) as session:
            if case == "operations":
                append_operation(session, operation_event())
                append_operation(
                    session,
                    replace(
                        operation_event(),
                        occurred_at=NOW + timedelta(seconds=1),
                        operation=OperationType.SET_ROLE,
                        result=OperationResult.FAILURE,
                        failure_category=DiagnosticCategory.CONFLICT,
                        details=OperationDetails(
                            before=AuditValues(role="member"), after=AuditValues()
                        ),
                    ),
                )
            else:
                append_login(
                    session,
                    LoginEvent(
                        NOW,
                        ActorRef(7, "甲"),
                        "actor",
                        LoginKind.LOGIN,
                        LoginResult.SUCCESS,
                        AUDIT_CONTEXT,
                    ),
                )
                append_login(
                    session,
                    LoginEvent(
                        NOW + timedelta(seconds=1),
                        ActorRef(7, "甲"),
                        "actor",
                        LoginKind.LOGIN,
                        LoginResult.WRONG_PASSWORD,
                        AUDIT_CONTEXT,
                    ),
                )
                append_login(
                    session,
                    LoginEvent(
                        NOW + timedelta(seconds=2),
                        ActorRef(8, "乙"),
                        "other",
                        LoginKind.LOGIN,
                        LoginResult.WRONG_PASSWORD,
                        AUDIT_CONTEXT,
                    ),
                )
                append_login(
                    session,
                    LoginEvent(
                        NOW + timedelta(seconds=3),
                        ActorRef(7, "甲"),
                        "actor",
                        LoginKind.LOGOUT,
                        LoginResult.SUCCESS,
                        AUDIT_CONTEXT,
                    ),
                )
        common = LogQuery(start=NOW, end=NOW + timedelta(seconds=4), account_id=7)
        with session_scope(engine, read_only=True) as session:
            if case == "operations":
                page = query_operations(
                    session,
                    OperationQuery(
                        common,
                        operation=OperationType.SET_ROLE,
                        result=OperationResult.FAILURE,
                        target_account_id=11,
                    ),
                    existing_account_ids,
                )
                assert [item.log_id for item in page.items] == [2]
            else:
                logins = query_logins(
                    session,
                    LoginQuery(common, kind=LoginKind.LOGIN, result=LoginResult.WRONG_PASSWORD),
                    existing_account_ids,
                )
                assert [item.log_id for item in logins.items] == [2]


def test_query_bounds(tmp_path: Path) -> None:
    """验收1/时间契约：带不同时区但等价的区间按UTC比较，含start不含end，保留微秒，不改全局时区。"""
    with model_database(tmp_path) as engine:
        _seed_logs(engine, (NOW - timedelta(microseconds=1), NOW, NOW + timedelta(microseconds=1)))
        bounds = LogQuery(
            start=NOW.astimezone(timezone(timedelta(hours=-6))),
            end=(NOW + timedelta(microseconds=1)).astimezone(timezone(timedelta(hours=8))),
        )
        with session_scope(engine, read_only=True) as session:
            page = query_operations(session, OperationQuery(bounds), existing_account_ids)
            assert [item.log_id for item in page.items] == [2]
            assert page.items[0].event.occurred_at == NOW
            assert page.items[0].event.occurred_at.tzinfo is UTC


@pytest.mark.parametrize(
    "case",
    [
        "naive_start",
        "naive_end",
        "equal_range",
        "reversed_range",
        "utc_overflow",
        "account_bool",
        "account_out_of_range",
        "limit_zero",
        "limit_101",
        "limit_bool",
        "cursor_too_long",
        "cursor_bad_base64",
        "cursor_bad_json",
        "cursor_version",
        "cursor_key_range",
        "cursor_wrong_filter",
        "cursor_wrong_log_kind",
        "cursor_changed_limit",
    ],
)
def test_query_invalid(case: str, tmp_path: Path) -> None:
    """规范7.1：筛选及游标非法抛AuditInputError，不回显参数或静默查全部。"""
    import base64
    import json

    bad: dict[str, dict[str, object]] = {
        "naive_start": {"start": NOW.replace(tzinfo=None)},
        "naive_end": {"end": NOW.replace(tzinfo=None)},
        "equal_range": {"start": NOW, "end": NOW},
        "reversed_range": {"start": NOW, "end": NOW - timedelta(days=1)},
        "utc_overflow": {"start": datetime.min.replace(tzinfo=timezone(timedelta(hours=1)))},
        "account_bool": {"account_id": True},
        "account_out_of_range": {"account_id": 2**63},
        "limit_zero": {"limit": 0},
        "limit_101": {"limit": 101},
        "limit_bool": {"limit": True},
        "cursor_too_long": {"cursor": "a" * 513},
        "cursor_bad_base64": {"cursor": "%%%"},
        "cursor_bad_json": {"cursor": "eA"},
        "cursor_version": {
            "cursor": base64.urlsafe_b64encode(json.dumps({"v": 99}).encode()).decode()
        },
        "cursor_key_range": {
            "cursor": base64.urlsafe_b64encode(json.dumps({"v": 1, "i": -1}).encode()).decode()
        },
    }
    with model_database(tmp_path) as engine:
        _seed_logs(engine, (NOW, NOW))
        with session_scope(engine, read_only=True) as session:
            first = query_operations(
                session, OperationQuery(LogQuery(limit=1)), existing_account_ids
            )
            if case in bad:
                query = OperationQuery(replace(LogQuery(), **bad[case]))
            else:
                common = LogQuery(limit=1, cursor=first.next_cursor)
                if case == "cursor_wrong_filter":
                    common = replace(common, account_id=8)
                if case == "cursor_changed_limit":
                    common = replace(common, limit=2)
                query = OperationQuery(common)
            with pytest.raises(AuditInputError):
                if case == "cursor_wrong_log_kind":
                    query_logins(session, LoginQuery(query.common), existing_account_ids)
                else:
                    query_operations(session, query, existing_account_ids)


def test_query_snapshot(tmp_path: Path) -> None:
    """验收1/7：游标固定首页最大编号，并发追加含回拨旧时间不夹入后续页，保留期删除造成空缺不重复。"""
    with model_database(tmp_path) as engine:
        _seed_logs(engine, (NOW, NOW, NOW))
        with session_scope(engine, read_only=True) as session:
            first = query_operations(
                session, OperationQuery(LogQuery(limit=2)), existing_account_ids
            )
        _seed_logs(engine, (NOW - timedelta(days=10),))
        with session_scope(engine, read_only=True) as session:
            last = query_operations(
                session,
                OperationQuery(LogQuery(limit=2, cursor=first.next_cursor)),
                existing_account_ids,
            )
            assert [item.log_id for item in last.items] == [1]
            assert last.next_cursor is None
        AuditMaintenance(engine).purge_expired(NOW + timedelta(days=40))
        with session_scope(engine, read_only=True) as session:
            cleared = query_operations(
                session,
                OperationQuery(LogQuery(limit=2, cursor=first.next_cursor)),
                existing_account_ids,
            )
            assert cleared.items == () and cleared.next_cursor is None


def test_query_clock_rollback(tmp_path: Path) -> None:
    """时间契约：无上界的查询不以now过滤未来记录，翻页与当前墙钟回拨无关。"""
    with model_database(tmp_path) as engine:
        _seed_logs(engine, (NOW, NOW + timedelta(days=3650)))
        with session_scope(engine, read_only=True) as session:
            page = query_operations(session, OperationQuery(LogQuery()), existing_account_ids)
            assert [item.log_id for item in page.items] == [2, 1]


@pytest.mark.parametrize("case", ["details", "identity", "time", "io", "lock", "mapping"])
def test_query_corruption(case: str, tmp_path: Path) -> None:
    """规范7.1：存量明细/身份/时间损坏明确失败，不跳过坏行伪造完整页。"""
    with model_database(tmp_path) as engine:
        _seed_logs(engine, (NOW,))
        mutations = {
            "details": "UPDATE operation_logs SET details='{}'",
            "identity": "UPDATE operation_logs SET actor_name=' '",
            "time": "UPDATE operation_logs SET occurred_at='invalid'",
        }
        if case in mutations:
            with session_scope(engine) as session:
                session.execute(text("PRAGMA ignore_check_constraints=ON"))
                session.execute(text(mutations[case]))
        expected = {"io": ExternalError, "lock": ConflictError, "mapping": DefectError}.get(
            case, InputError
        )

        def fail(_connection: Any, _cursor: Any, statement: str, *_args: Any) -> None:
            if case in {"io", "lock", "mapping"} and "FROM operation_logs" in statement:
                error = sqlite3.DatabaseError("秘密驱动细节")
                error.sqlite_errorcode = {
                    "io": sqlite3.SQLITE_IOERR,
                    "lock": sqlite3.SQLITE_BUSY,
                    "mapping": sqlite3.SQLITE_ERROR,
                }[case]
                raise error

        event.listen(engine, "before_cursor_execute", fail)
        try:
            with (
                session_scope(engine, read_only=True) as session,
                pytest.raises(expected) as caught,
            ):
                query_operations(session, OperationQuery(LogQuery()), existing_account_ids)
            assert not isinstance(caught.value, AuditInputError)
        finally:
            event.remove(engine, "before_cursor_execute", fail)


@pytest.mark.parametrize("case", ["actor", "target", "login"])
def test_snapshot_identity(case: str, tmp_path: Path) -> None:
    """验收7：删除账号显示旧名字加已删除；AUTOINCREMENT同名重建不会接管原操作人、对象或登录记录。"""
    with model_database(tmp_path) as engine:
        with session_scope(engine) as session:
            session.add_all(
                [
                    model_row("actor", account_id=7, display_name="管理员甲"),
                    model_row("target", account_id=11, display_name="成员乙"),
                ]
            )
        _seed_logs(engine, (NOW,))
        removed = 11 if case == "target" else 7
        with session_scope(engine) as session:
            session.execute(delete(AccountRow).where(AccountRow.account_id == removed))
            fresh = model_row(
                "target" if case == "target" else "actor",
                display_name="成员乙" if case == "target" else "管理员甲",
            )
            session.add(fresh)
            session.flush()
            assert fresh.account_id != removed
        with session_scope(engine, read_only=True) as session:
            if case == "login":
                row = query_logins(session, LoginQuery(LogQuery()), existing_account_ids).items[0]
                assert row.account_deleted and row.event.account == ActorRef(7, "管理员甲")
            else:
                item = query_operations(
                    session, OperationQuery(LogQuery()), existing_account_ids
                ).items[0]
                assert item.actor_deleted == (case == "actor")
                assert item.target_deleted == (case == "target")
                assert item.event.actor == ActorRef(7, "管理员甲")
                assert item.event.target.name == "成员乙"


def test_snapshot_presence(tmp_path: Path) -> None:
    """验收7：存在性适配器只按原编号返回当前存在集合，停用仍存在，空输入不合成运维身份。"""
    with model_database(tmp_path) as engine:
        with session_scope(engine) as session:
            session.add(model_row("actor", account_id=7, status="disabled"))
        with session_scope(engine, read_only=True) as session:
            assert existing_account_ids(session, frozenset({7, 11})) == frozenset({7})
            assert existing_account_ids(session, frozenset()) == frozenset()


@pytest.mark.parametrize(
    "case", ["bad_id", "over_limit", "callback_extra_id", "callback_failure", "empty_ids"]
)
def test_presence_invalid(case: str, tmp_path: Path) -> None:
    """规范7.1：非法编号集合拒绝；查询适配器返回集合外编号或执行异常均归DefectError。"""
    with model_database(tmp_path) as engine:
        with session_scope(engine) as session:
            append_operation(session, operation_event())
        with session_scope(engine, read_only=True) as session:
            if case == "empty_ids":
                assert existing_account_ids(session, frozenset()) == frozenset()
            elif case in {"bad_id", "over_limit"}:
                values = frozenset({True}) if case == "bad_id" else frozenset(range(1, 202))
                with pytest.raises(AuditInputError):
                    existing_account_ids(session, values)
            else:

                def callback(_session: Session, _ids: frozenset[int]) -> frozenset[int]:
                    if case == "callback_failure":
                        raise RuntimeError("不允许回显")
                    return frozenset({999})

                with pytest.raises(DefectError):
                    query_operations(session, OperationQuery(LogQuery()), callback)


@pytest.mark.parametrize("case", ["unset", "persisted", "corrupt"])
def test_retention_default(case: str, tmp_path: Path) -> None:
    """验收5：无设置返回30且不建行，已存值跨事务可读，损坏值明确InputError不回退默认。"""
    with model_database(tmp_path) as engine:
        if case != "unset":
            with session_scope(engine) as session:
                if case == "corrupt":
                    session.execute(text("PRAGMA ignore_check_constraints=ON"))
                session.execute(
                    text("INSERT INTO audit_settings VALUES (1,:days)"),
                    {"days": 0 if case == "corrupt" else 7},
                )
        with session_scope(engine, read_only=True) as session:
            if case == "corrupt":
                with pytest.raises(InputError) as caught:
                    get_retention(session)
                assert not isinstance(caught.value, AuditInputError)
                assert caught.value.diagnostics[0].objects[0].value == "retention_days"
            else:
                assert get_retention(session) == (30 if case == "unset" else 7)
                assert session.execute(
                    text("SELECT COUNT(*) FROM audit_settings")
                ).scalar_one() == (0 if case == "unset" else 1)


@pytest.mark.parametrize("case", ["7", "365", "6", "366", "bool", "string", "fraction"])
def test_retention_bounds(case: str, tmp_path: Path) -> None:
    """验收5：保留期只接受非bool整数7至365天，两端可提交，非法值不改变设置或日志。"""
    values = {
        "7": 7,
        "365": 365,
        "6": 6,
        "366": 366,
        "bool": True,
        "string": "30",
        "fraction": 30.5,
    }
    command = replace(
        RetentionChange(7, ActorRef(7, "管理员甲"), AUDIT_CONTEXT, NOW), days=values[case]
    )
    with model_database(tmp_path) as engine, session_scope(engine) as session:
        if case in {"7", "365"}:
            assert change_retention(session, command) == values[case]
        else:
            with pytest.raises(AuditInputError):
                change_retention(session, command)
            assert get_retention(session) == 30
            assert session.execute(text("SELECT COUNT(*) FROM operation_logs")).scalar_one() == 0


@pytest.mark.parametrize(
    "case", ["success", "log_failure", "settings_failure", "same_value", "default_same_value"]
)
def test_retention_atomic(case: str, tmp_path: Path) -> None:
    """验收2/5：设置和SET_RETENTION日志原子提交，失败回滚两者，同值不新建行或记录。"""
    import json

    with model_database(tmp_path) as engine:
        if case == "same_value":
            with session_scope(engine) as session:
                session.execute(text("INSERT INTO audit_settings VALUES (1,7)"))
        requested = 30 if case == "default_same_value" else 7
        command = RetentionChange(requested, ActorRef(7, "管理员甲"), AUDIT_CONTEXT, NOW)

        def fail(_connection: Any, _cursor: Any, statement: str, *_args: Any) -> None:
            table = "operation_logs" if case == "log_failure" else "audit_settings"
            if statement.startswith("INSERT INTO " + table):
                error = sqlite3.OperationalError("模拟磁盘写入失败")
                error.sqlite_errorcode = sqlite3.SQLITE_IOERR
                raise error

        failing = case in {"log_failure", "settings_failure"}
        if failing:
            event.listen(engine, "before_cursor_execute", fail)
        try:
            if failing:
                with pytest.raises(ExternalError), session_scope(engine) as session:
                    change_retention(session, command)
            else:
                with session_scope(engine) as session:
                    assert change_retention(session, command) == requested
        finally:
            if failing:
                event.remove(engine, "before_cursor_execute", fail)
        with session_scope(engine, read_only=True) as session:
            assert get_retention(session) == (30 if failing or case == "default_same_value" else 7)
            rows = session.execute(text("SELECT operation,details FROM operation_logs")).all()
            if case == "success":
                assert rows[0][0] == "set_retention"
                assert json.loads(rows[0][1]) == {
                    "version": 1,
                    "before": {"retention_days": 30},
                    "after": {"retention_days": 7},
                }
            else:
                assert rows == []


def test_purge_boundary(tmp_path: Path) -> None:
    """验收1/5：两种日志删cutoff前1微秒，保留恰好cutoff及之后1微秒和未来记录，使用数据库N天。"""
    cutoff = datetime(2026, 10, 18, 12, 30, 10, 123456, tzinfo=UTC)
    with model_database(tmp_path) as engine:
        with session_scope(engine) as session:
            change_retention(
                session, RetentionChange(7, ActorRef(7, "管理员甲"), AUDIT_CONTEXT, NOW)
            )
        _seed_logs(
            engine,
            (
                cutoff - timedelta(microseconds=1),
                cutoff,
                cutoff + timedelta(microseconds=1),
                NOW + timedelta(days=1),
            ),
        )
        result = AuditMaintenance(engine).purge_expired(NOW)
        assert (
            result.operation_count,
            result.login_count,
            result.retention_days,
            result.cutoff,
        ) == (1, 1, 7, cutoff)
        with session_scope(engine, read_only=True) as session:
            assert session.execute(text("SELECT COUNT(*) FROM operation_logs")).scalar_one() == 4
            assert session.execute(text("SELECT COUNT(*) FROM login_logs")).scalar_one() == 3
            assert get_retention(session) == 7


def test_purge_rollback(tmp_path: Path) -> None:
    """验收5：第二张表删除或提交失败，两表均回滚，设置和报错表不变，不自记清除日志。"""
    with model_database(tmp_path) as engine:
        _seed_logs(engine, (NOW - timedelta(days=40),))

        def fail(_connection: Any, _cursor: Any, statement: str, *_args: Any) -> None:
            if statement.startswith("DELETE FROM login_logs"):
                error = sqlite3.OperationalError("第二表删除失败")
                error.sqlite_errorcode = sqlite3.SQLITE_IOERR
                raise error

        event.listen(engine, "before_cursor_execute", fail)
        try:
            with pytest.raises(ExternalError):
                AuditMaintenance(engine).purge_expired(NOW)
        finally:
            event.remove(engine, "before_cursor_execute", fail)
        with session_scope(engine, read_only=True) as session:
            assert session.execute(text("SELECT COUNT(*) FROM operation_logs")).scalar_one() == 1
            assert session.execute(text("SELECT COUNT(*) FROM login_logs")).scalar_one() == 1


@pytest.mark.parametrize("case", ["repeat", "rollback", "late_old_insert", "offset_and_dst"])
def test_purge_time(case: str, tmp_path: Path) -> None:
    """验收5/时间契约：重复清除幂等、回拨不误删、不使用水位遗漏新插旧记录，UTC一天固定24小时。"""
    with model_database(tmp_path) as engine:
        maintenance = AuditMaintenance(engine)
        _seed_logs(engine, (NOW - timedelta(days=29),))
        assert maintenance.purge_expired(NOW).operation_count == 0
        if case == "late_old_insert":
            _seed_logs(engine, (NOW - timedelta(days=40),))
        moment = NOW - timedelta(days=3) if case == "rollback" else NOW
        if case == "offset_and_dst":
            moment = NOW.astimezone(timezone(timedelta(hours=8)))
        result = maintenance.purge_expired(moment)
        assert result.operation_count == (1 if case == "late_old_insert" else 0)
        assert result.login_count == (1 if case == "late_old_insert" else 0)
        assert result.cutoff.tzinfo is UTC


@pytest.mark.parametrize(
    "case",
    [
        "naive",
        "utc_overflow",
        "cutoff_underflow",
        "corrupt_settings",
        "lock_timeout",
        "io",
        "sql_defect",
    ],
)
def test_purge_invalid(case: str, tmp_path: Path) -> None:
    """规范7.1：非法now/减天溢出或损坏设置先失败不删库；存储错误按四类返回。"""
    with model_database(tmp_path) as engine:
        _seed_logs(engine, (NOW - timedelta(days=40),))
        value = NOW
        expected: type[Exception] = AuditInputError
        if case == "naive":
            value = NOW.replace(tzinfo=None)
        elif case == "utc_overflow":
            value = datetime.min.replace(tzinfo=timezone(timedelta(hours=1)))
        elif case == "cutoff_underflow":
            value = datetime.min.replace(tzinfo=UTC)
        elif case == "corrupt_settings":
            expected = InputError
            with session_scope(engine) as session:
                session.execute(text("PRAGMA ignore_check_constraints=ON"))
                session.execute(text("INSERT INTO audit_settings VALUES (1,0)"))
        elif case == "lock_timeout":
            with session_scope(engine), pytest.raises(ConflictError):
                AuditMaintenance(engine).purge_expired(NOW)
            return
        else:
            expected = ExternalError if case == "io" else DefectError

        def fail(_connection: Any, _cursor: Any, statement: str, *_args: Any) -> None:
            if case in {"io", "sql_defect"} and statement.startswith("DELETE FROM"):
                error = sqlite3.DatabaseError("安全故障注入")
                error.sqlite_errorcode = (
                    sqlite3.SQLITE_IOERR if case == "io" else sqlite3.SQLITE_ERROR
                )
                raise error

        event.listen(engine, "before_cursor_execute", fail)
        try:
            with pytest.raises(expected):
                AuditMaintenance(engine).purge_expired(value)
        finally:
            event.remove(engine, "before_cursor_execute", fail)
        with session_scope(engine, read_only=True) as session:
            assert session.execute(text("SELECT COUNT(*) FROM operation_logs")).scalar_one() == 1
            assert session.execute(text("SELECT COUNT(*) FROM login_logs")).scalar_one() == 1


@pytest.mark.parametrize("case", ["success", "lock_timeout", "io", "invalid_event", "defect"])
def test_short_append(case: str, tmp_path: Path) -> None:
    """H3：失败操作独立短事务提交；锁只等100毫秒，非法成功事件或驱动失败不能留记录。"""
    import time

    value = replace(
        operation_event(),
        result=OperationResult.FAILURE,
        failure_category=DiagnosticCategory.EXTERNAL,
        target=ObjectRef("account", None, "新账号"),
        details=OperationDetails(before=AuditValues(), after=AuditValues()),
    )
    with model_database(tmp_path) as engine:
        if case == "lock_timeout":
            with session_scope(engine):
                start = time.monotonic()
                with pytest.raises(ConflictError):
                    append_failed_operation(engine, value)
                assert time.monotonic() - start < 1
        elif case == "invalid_event":
            with pytest.raises(AuditInputError):
                append_failed_operation(engine, operation_event())
        elif case == "defect":
            unmanaged = create_engine("sqlite://")
            try:
                with pytest.raises(DefectError):
                    append_failed_operation(unmanaged, value)
            finally:
                unmanaged.dispose()
        elif case == "io":

            def fail(_connection: Any, _cursor: Any, statement: str, *_args: Any) -> None:
                if statement.startswith("INSERT INTO operation_logs"):
                    error = sqlite3.OperationalError("测试IO故障")
                    error.sqlite_errorcode = sqlite3.SQLITE_IOERR
                    raise error

            event.listen(engine, "before_cursor_execute", fail)
            try:
                with pytest.raises(ExternalError):
                    append_failed_operation(engine, value)
            finally:
                event.remove(engine, "before_cursor_execute", fail)
        else:
            append_failed_operation(engine, value)
        with session_scope(engine, read_only=True) as session:
            rows = session.execute(text("SELECT result,failure_category FROM operation_logs")).all()
            assert rows == ([("failure", "external")] if case == "success" else [])


def test_purge_without_setting_uses_thirty_days(tmp_path: Path) -> None:
    """验收5/修订8：无设置行时两种日志按30天清除，删截止前1微秒，保留恰好截止及之后，仍不创建设置行。"""
    cutoff = datetime(2026, 9, 25, 12, 30, 10, 123456, tzinfo=UTC)
    with model_database(tmp_path) as engine:
        _seed_logs(engine, (cutoff - timedelta(microseconds=1), cutoff, NOW))
        result = AuditMaintenance(engine).purge_expired(NOW)
        assert (
            result.operation_count,
            result.login_count,
            result.retention_days,
            result.cutoff,
        ) == (1, 1, 30, cutoff)
        with session_scope(engine, read_only=True) as session:
            assert session.execute(text("SELECT COUNT(*) FROM audit_settings")).scalar_one() == 0
            assert session.execute(text("SELECT COUNT(*) FROM operation_logs")).scalar_one() == 2
            assert session.execute(text("SELECT COUNT(*) FROM login_logs")).scalar_one() == 2


@pytest.mark.parametrize(
    "case",
    [
        "actor_only",
        "target_only",
        "both_and",
        "deleted_target",
        "same_name_new_id",
        "exclude_settings",
        "exclude_null_target",
    ],
)
def test_operation_account_filter_roles(case: str, tmp_path: Path) -> None:
    """修订7：按操作人、对象账号独立或AND交集查询历史编号，不能以同名新号接管。"""
    with model_database(tmp_path) as engine:
        with session_scope(engine) as session:
            append_operation(session, operation_event())
            append_operation(session, replace(operation_event(), actor=ActorRef(8, "另一管理员")))
            append_operation(
                session, replace(operation_event(), target=ObjectRef("account", "12", "成员丙"))
            )
            if case == "same_name_new_id":
                session.add(model_row("recreated", account_id=20, display_name="成员乙"))
            if case == "exclude_settings":
                change_retention(
                    session, RetentionChange(7, ActorRef(7, "管理员甲"), AUDIT_CONTEXT, NOW)
                )
            if case == "exclude_null_target":
                append_operation(
                    session,
                    replace(
                        operation_event(),
                        target=ObjectRef("account", None, "新账号"),
                        result=OperationResult.FAILURE,
                        failure_category=DiagnosticCategory.EXTERNAL,
                        details=OperationDetails(before=AuditValues(), after=AuditValues()),
                    ),
                )
        actor = 7 if case in {"actor_only", "both_and"} else None
        target = None if case == "actor_only" else 11
        with session_scope(engine, read_only=True) as session:
            page = query_operations(
                session,
                OperationQuery(LogQuery(account_id=actor), target_account_id=target),
                existing_account_ids,
            )
            expected = [3, 1] if case == "actor_only" else ([1] if case == "both_and" else [2, 1])
            assert [item.log_id for item in page.items] == expected
            assert all(item.target_deleted for item in page.items)


@pytest.mark.parametrize("case", ["bool", "zero", "negative", "overflow", "string"])
def test_target_account_filter_invalid(case: str, tmp_path: Path) -> None:
    """修订7：对象账号只接受非bool的SQLite正整数，不接受文本、越界或零。"""
    values = {"bool": True, "zero": 0, "negative": -1, "overflow": 2**63, "string": "11"}
    with (
        model_database(tmp_path) as engine,
        session_scope(engine, read_only=True) as session,
        pytest.raises(AuditInputError),
    ):
        query_operations(
            session,
            replace(OperationQuery(LogQuery()), target_account_id=values[case]),
            existing_account_ids,
        )


@pytest.mark.parametrize("case", ["actor_changed", "target_changed", "actor_target_swapped"])
def test_cursor_binds_both_account_filters(case: str, tmp_path: Path) -> None:
    """修订7：游标摘要分别绑定操作人和对象账号，改变或交换任一账号条件必须拒绝旧游标。"""
    with model_database(tmp_path) as engine:
        _seed_logs(engine, (NOW, NOW))
        common = LogQuery(account_id=7, limit=1)
        with session_scope(engine, read_only=True) as session:
            page = query_operations(
                session, OperationQuery(common, target_account_id=11), existing_account_ids
            )
            actor = 8 if case == "actor_changed" else (11 if case == "actor_target_swapped" else 7)
            target = (
                12 if case == "target_changed" else (7 if case == "actor_target_swapped" else 11)
            )
            with pytest.raises(AuditInputError):
                query_operations(
                    session,
                    OperationQuery(
                        replace(common, account_id=actor, cursor=page.next_cursor),
                        target_account_id=target,
                    ),
                    existing_account_ids,
                )


@pytest.mark.parametrize(
    "operation",
    [
        "append_operation",
        "append_login",
        "change_retention",
        "append_failed_operation",
        "append_missing_login",
        "append_failed_login",
    ],
)
def test_audit_storage_context_defect(operation: str, tmp_path: Path) -> None:
    """修订5：各日志写边界接收非法AuditContext均抛DefectError，不能作为参数422拒绝且不留下日志行。"""
    bad_operation = replace(operation_event(), context=None)
    bad_login = replace(
        LoginEvent(
            NOW, None, None, LoginKind.LOGIN, LoginResult.ACCOUNT_MISSING, AuditContext(None, None)
        ),
        context=None,
    )
    with model_database(tmp_path) as engine:
        if operation == "append_failed_operation":
            with pytest.raises(DefectError):
                append_failed_operation(engine, bad_operation)
        elif operation in {"append_missing_login", "append_failed_login"}:
            function = (
                append_missing_login if operation == "append_missing_login" else append_failed_login
            )
            with pytest.raises(DefectError):
                function(engine, bad_login)
        else:
            with session_scope(engine) as session, pytest.raises(DefectError):
                if operation == "append_operation":
                    append_operation(session, bad_operation)
                elif operation == "append_login":
                    append_login(session, bad_login)
                else:
                    change_retention(
                        session,
                        replace(
                            RetentionChange(7, ActorRef(7, "管理员甲"), AUDIT_CONTEXT, NOW),
                            context=None,
                        ),
                    )


@pytest.mark.parametrize(
    "case", ["create_before", "delete_after", "settings_target", "missing_success_id"]
)
def test_detail_semantic_rejection(case: str, tmp_path: Path) -> None:
    """验收4/7：新建before空、删除after空、设置对象必须匹配、成功对象必须有永久编号。"""
    value = operation_event()
    changes: dict[str, dict[str, object]] = {
        "create_before": {
            "details": OperationDetails(before=AuditValues(role="member"), after=AuditValues())
        },
        "delete_after": {"operation": OperationType.DELETE_ACCOUNT},
        "settings_target": {
            "operation": OperationType.SET_RETENTION,
            "details": OperationDetails(
                before=AuditValues(retention_days=30), after=AuditValues(retention_days=7)
            ),
        },
        "missing_success_id": {"target": ObjectRef("account", None, "新账号")},
    }
    with (
        model_database(tmp_path) as engine,
        session_scope(engine) as session,
        pytest.raises(AuditInputError),
    ):
        append_operation(session, replace(value, **changes[case]))


@pytest.mark.parametrize("kind", [LoginKind.LOGIN, LoginKind.LOGOUT, LoginKind.SESSION_EXPIRED])
def test_login_append_roundtrip(kind: LoginKind, tmp_path: Path) -> None:
    """验收3：已知账号的登录或实际删除事件保留时间、名字、登录名、来源和请求编号，不写秘密。"""
    from accounts_support import AUDIT_CONTEXT

    value = LoginEvent(
        NOW, ActorRef(7, "管理员甲"), "admin", kind, LoginResult.SUCCESS, AUDIT_CONTEXT
    )
    with model_database(tmp_path) as engine:
        with session_scope(engine) as session:
            assert append_login(session, value) == 1
        with session_scope(engine, read_only=True) as session:
            assert session.execute(
                text(
                    "SELECT account_id,account_name,login_name,kind,result,source_ip,request_id FROM login_logs"
                )
            ).one() == (
                7,
                "管理员甲",
                "admin",
                kind.value,
                "success",
                "127.0.0.1",
                "123e4567e89b42d3a456426614174000",
            )


def _seed_logs(engine: Engine, moments: tuple[datetime, ...]) -> None:
    """通过公开追加接口建立时间样本，期望边界由测试的固定UTC字面量独立给定。"""
    with session_scope(engine) as session:
        for moment in moments:
            append_operation(session, replace(operation_event(), occurred_at=moment))
            append_login(
                session,
                LoginEvent(
                    moment,
                    ActorRef(7, "管理员甲"),
                    "admin",
                    LoginKind.LOGIN,
                    LoginResult.SUCCESS,
                    AUDIT_CONTEXT,
                ),
            )


def test_login_query_pages_and_unknown(tmp_path: Path) -> None:
    """验收3/7：登录同时间按编号倒序分页，匿名事件没有名字，未筛选未来时间仍能查询。"""
    with model_database(tmp_path) as engine:
        _seed_logs(engine, (NOW, NOW))
        with session_scope(engine) as session:
            append_login(
                session,
                LoginEvent(
                    NOW + timedelta(days=3650),
                    None,
                    None,
                    LoginKind.LOGIN,
                    LoginResult.ACCOUNT_MISSING,
                    AuditContext(None, None),
                ),
            )
        with session_scope(engine, read_only=True) as session:
            first = query_logins(session, LoginQuery(LogQuery(limit=2)), existing_account_ids)
            assert [row.log_id for row in first.items] == [3, 2]
            assert first.items[0].event.account is None and not first.items[0].account_deleted
            assert first.items[0].event.login_name is None
        with session_scope(engine, read_only=True) as session:
            last = query_logins(
                session,
                LoginQuery(LogQuery(limit=2, cursor=first.next_cursor)),
                existing_account_ids,
            )
            assert [row.log_id for row in last.items] == [1]
            assert last.next_cursor is None


@pytest.mark.parametrize("case", ["kind", "result", "naive", "cursor"])
def test_login_query_invalid(case: str, tmp_path: Path) -> None:
    """验收3：登录查询拒绝错误枚举、无时区时刻和非法游标，不能静默变成全量查询。"""
    queries = {
        "kind": replace(LoginQuery(LogQuery()), kind="invalid"),
        "result": replace(LoginQuery(LogQuery()), result="invalid"),
        "naive": LoginQuery(LogQuery(start=NOW.replace(tzinfo=None))),
        "cursor": LoginQuery(LogQuery(cursor="invalid")),
    }
    with (
        model_database(tmp_path) as engine,
        session_scope(engine, read_only=True) as session,
        pytest.raises(AuditInputError),
    ):
        query_logins(session, queries[case], existing_account_ids)
