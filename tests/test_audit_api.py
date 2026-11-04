"""日志HTTP验收清单（07），使用应用内测试客户端及临时数据库，不开启真实网络或用户目录。"""

import logging
import sqlite3
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from typing import Annotated, Any

import pytest
from account_api_support import add_actor, api_case
from accounts_support import EXAMPLE_SECRET, NOW
from audit_support import operation_event
from fastapi import Request, Security
from sqlalchemy import Connection, event, select

from rdp.accounts.models import SessionRow
from rdp.accounts.types import Role
from rdp.api.account_auth import SESSION_COOKIE, AccountRequestContext, get_admin_context
from rdp.api.audit import report_audit_append_failure, request_audit_context
from rdp.audit.policy import AUDIT_APPEND_FAILED
from rdp.audit.records import append_operation
from rdp.audit.types import AuditContext, ObjectRef
from rdp.infra.actors import ActorRef
from rdp.infra.db.connection import session_scope
from rdp.infra.diagnostics import DefectError
from rdp.infra.logging import log_context, request_id_context
from rdp.ops.audit import report_audit_append_failure as report_ops_failure


@pytest.mark.parametrize("case", ["operations", "logins", "get_retention", "put_retention"])
def test_authorization_order(case: str, tmp_path: Path) -> None:
    """验收6/6.2：四接口按Origin、认证、强制改密、角色、方法、参数固定顺序，不让坏JSON绕过403。"""
    path = {
        "operations": "/api/audit/operations",
        "logins": "/api/audit/logins",
        "get_retention": "/api/audit/retention",
        "put_retention": "/api/audit/retention",
    }[case]
    method = "PUT" if case == "put_retention" else "GET"
    with api_case(tmp_path) as fixture:
        assert fixture.client.request(method, path, content="{bad").status_code == 401
        assert fixture.login().status_code == 200
        response = fixture.client.request(
            method, path, json={"days": 7} if method == "PUT" else None
        )
        assert response.status_code == 200
        forced = add_actor(fixture, name="forced", role=Role.ADMINISTRATOR, ready=False)
        headers = {"Cookie": "rdp_session=" + forced.token.get_secret_value()}
        assert (
            fixture.client.request(method, path, content="{bad", headers=headers).status_code == 403
        )


@pytest.mark.parametrize("case", ["normal", "wrong_method", "invalid_query", "invalid_json"])
def test_member_denied(case: str, tmp_path: Path) -> None:
    """验收6：成员对两个列表和保留期均403，错误方法或非法query/body仍先403。"""
    with api_case(tmp_path) as fixture:
        member = add_actor(fixture)
        headers = {"Cookie": "rdp_session=" + member.token.get_secret_value()}
        for path in ("/api/audit/operations", "/api/audit/logins", "/api/audit/retention"):
            method = (
                "POST" if case == "wrong_method" else ("PUT" if case == "invalid_json" else "GET")
            )
            suffix = "?limit=invalid" if case == "invalid_query" else ""
            response = fixture.client.request(
                method, path + suffix, headers=headers, content="{bad"
            )
            assert response.status_code == 403


@pytest.mark.parametrize("case", ["missing", "null", "cross_origin", "valid"])
def test_origin_required(case: str, tmp_path: Path) -> None:
    """验收6：PUT保留期要求同源Origin；缺失null跨源403且不写设置或日志。"""
    with api_case(tmp_path, origin=False) as fixture:
        fixture.client.headers["Origin"] = "http://testserver"
        assert fixture.login().status_code == 200
        del fixture.client.headers["Origin"]
        headers = (
            {}
            if case == "missing"
            else {
                "Origin": {
                    "null": "null",
                    "cross_origin": "http://elsewhere",
                    "valid": "http://testserver",
                }[case]
            }
        )
        response = fixture.client.put("/api/audit/retention", json={"days": 7}, headers=headers)
        assert response.status_code == (200 if case == "valid" else 403)
        assert fixture.client.get("/api/audit/retention").json() == {
            "days": 7 if case == "valid" else 30
        }


def test_no_single_row_mutation(tmp_path: Path) -> None:
    """验收1：OpenAPI没有单条日志修改删除或清除接口，已知列表错误方法405，成员先403。"""
    with api_case(tmp_path) as fixture:
        schema = fixture.app.openapi()
        assert {path for path in schema["paths"] if path.startswith("/api/audit/")} == {
            "/api/audit/operations",
            "/api/audit/logins",
            "/api/audit/retention",
        }
        assert fixture.login().status_code == 200
        assert fixture.client.delete("/api/audit/operations").status_code == 405
        assert fixture.client.delete("/api/audit/logins").status_code == 405
        member = add_actor(fixture)
        assert (
            fixture.client.delete(
                "/api/audit/operations",
                headers={"Cookie": "rdp_session=" + member.token.get_secret_value()},
            ).status_code
            == 403
        )


def test_ops_failure_notice(caplog: pytest.LogCaptureFixture) -> None:
    """H3/6.3：运维边界消费固定标记只报一次ERROR，保留原异常身份且不输出其秘密注释。"""
    assert report_ops_failure is report_audit_append_failure
    error = DefectError()
    error.add_note(AUDIT_APPEND_FAILED)
    error.add_note("秘密")
    with caplog.at_level(logging.ERROR):
        report_ops_failure(error)
        report_ops_failure(error)
    assert len([record for record in caplog.records if record.name == "rdp.audit.reporting"]) == 1
    assert "秘密" not in caplog.text
    assert error.__notes__ == ["秘密"]


@pytest.mark.parametrize(
    "case", ["ipv4", "ipv6", "missing", "invalid", "scoped_ipv6", "spoofed_forwarded"]
)
def test_source_ip(case: str) -> None:
    """验收3：来源只取ASGI client，转发头被忽略；IPv6规范化，缺失或非法来源为空。"""
    addresses = {
        "ipv4": "192.0.2.7",
        "ipv6": "2001:0db8::1",
        "missing": None,
        "invalid": "example.test",
        "scoped_ipv6": "fe80::1%eth0",
        "spoofed_forwarded": "127.0.0.1",
    }
    expected = {
        "ipv4": "192.0.2.7",
        "ipv6": "2001:db8::1",
        "missing": None,
        "invalid": None,
        "scoped_ipv6": None,
        "spoofed_forwarded": "127.0.0.1",
    }
    address = addresses[case]
    request = Request(
        {
            "type": "http",
            "client": None if address is None else (address, 1),
            "headers": [(b"x-forwarded-for", b"203.0.113.99")],
        }
    )
    with log_context(request_id="123e4567e89b42d3a456426614174000"):
        result = request_audit_context(request)
    assert result.source_ip == expected[case]
    assert result.request_id == "123e4567e89b42d3a456426614174000"


def test_request_id() -> None:
    """验收2：来源取服务端上下文而非X-Request-ID；编号缺失或损坏是DefectError，并恢复contextvar。"""
    request = Request(
        {"type": "http", "client": None, "headers": [(b"x-request-id", b"untrusted")]}
    )
    with log_context(request_id="123e4567e89b42d3a456426614174000"):
        assert request_audit_context(request).request_id == "123e4567e89b42d3a456426614174000"
    for value in (None, "invalid"):
        token = request_id_context.set(value)
        try:
            with pytest.raises(DefectError):
                request_audit_context(request)
        finally:
            request_id_context.reset(token)


def test_response_types(tmp_path: Path) -> None:
    """验收1/4：OpenAPI生成查询和安全响应类型，64位编号为字符串，UTC微秒不丢，绝无秘密字段。"""
    with api_case(tmp_path) as fixture:
        assert fixture.login().status_code == 200
        with session_scope(fixture.engine) as session:
            append_operation(
                session,
                replace(
                    operation_event(),
                    actor=ActorRef(9007199254740993, "旧账号"),
                    target=ObjectRef("account", "9007199254740995", "旧对象"),
                ),
            )
        response = fixture.client.get(
            "/api/audit/operations", params={"account_id": "9007199254740993"}
        )
        assert response.status_code == 200
        row = response.json()["items"][0]
        assert row["actor"] == {"account_id": "9007199254740993", "name": "旧账号", "deleted": True}
        assert row["target"]["object_id"] == "9007199254740995"
        assert row["occurred_at"] == "2026-10-25T12:30:10.123456Z"
        assert (
            EXAMPLE_SECRET.get_secret_value() not in response.text
            and "$argon2" not in response.text
        )
        assert fixture.client.get("/api/audit/logins").status_code == 200


@pytest.mark.parametrize("case", ["input", "conflict", "external", "defect", "validation"])
def test_api_errors(case: str, tmp_path: Path) -> None:
    """规范7.1：新接口输入冲突外部失败缺陷沿用400/409/502/500，422拒绝值不回显，错误编号一致。"""
    with api_case(tmp_path) as fixture:
        assert fixture.login().status_code == 200
        codes = {
            "input": (sqlite3.SQLITE_CORRUPT, 400),
            "conflict": (sqlite3.SQLITE_BUSY, 409),
            "external": (sqlite3.SQLITE_IOERR, 502),
            "defect": (sqlite3.SQLITE_ERROR, 500),
        }
        injected = False

        def fail(_connection: Connection, _cursor: Any, statement: str, *_args: Any) -> None:
            nonlocal injected
            if case != "validation" and "FROM operation_logs" in statement:
                injected = True
                error = sqlite3.DatabaseError("不能回显的秘密")
                error.sqlite_errorcode = codes[case][0]
                raise error

        event.listen(fixture.engine, "before_cursor_execute", fail)
        try:
            response = fixture.client.get(
                "/api/audit/operations",
                params={"limit": "不能回显的秘密"} if case == "validation" else {},
            )
        finally:
            event.remove(fixture.engine, "before_cursor_execute", fail)
        assert case == "validation" or injected
        assert response.status_code == (422 if case == "validation" else codes[case][1])
        assert response.json()["error_id"] == response.headers["X-Request-ID"]
        assert "不能回显的秘密" not in response.text


@pytest.mark.parametrize("case", ["marked", "unmarked", "logging_failure"])
def test_api_failure_notice(
    case: str, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """H3/6.3：补记标记最多触发一次安全ERROR，日志器自身失败也不抛出或泄漏原异常。"""
    error = DefectError()
    error.add_note("不可信的秘密上下文")
    if case != "unmarked":
        error.add_note(AUDIT_APPEND_FAILED)
    before = error.diagnostics
    if case == "logging_failure":

        def fail(*_args: object, **_kwargs: object) -> None:
            raise OSError("日志磁盘错误含秘密")

        monkeypatch.setattr(logging.getLogger("rdp.audit.reporting"), "error", fail)
    with caplog.at_level(logging.ERROR):
        report_audit_append_failure(error)
        report_audit_append_failure(error)
    assert error.diagnostics == before
    assert AUDIT_APPEND_FAILED not in error.__notes__
    assert "不可信的秘密上下文" in error.__notes__
    records = [record for record in caplog.records if record.name == "rdp.audit.reporting"]
    assert len(records) == (1 if case == "marked" else 0)
    assert "秘密" not in caplog.text


@pytest.mark.parametrize(
    "case",
    [
        "actor_only",
        "target_only",
        "both",
        "target_overflow",
        "target_leading_zero",
        "cursor_filter_change",
    ],
)
def test_operation_account_query_api(case: str, tmp_path: Path) -> None:
    """修订7：真实应用解析两个账号query字段，合法时交集筛选并保留64位文本；非法目标编号/游标按6.2返回422。"""
    with api_case(tmp_path) as fixture:
        assert fixture.login().status_code == 200
        with session_scope(fixture.engine) as session:
            append_operation(session, operation_event())
            append_operation(session, replace(operation_event(), actor=ActorRef(8, "其他操作人")))
            append_operation(
                session, replace(operation_event(), target=ObjectRef("account", "12", "其他对象"))
            )
        queries = {
            "actor_only": {"account_id": "7"},
            "target_only": {"target_account_id": "11"},
            "both": {"account_id": "7", "target_account_id": "11"},
            "target_overflow": {"target_account_id": str(2**63)},
            "target_leading_zero": {"target_account_id": "011"},
        }
        if case == "cursor_filter_change":
            first = fixture.client.get("/api/audit/operations", params={"limit": 1}).json()
            params = {"limit": "1", "cursor": first["next_cursor"], "target_account_id": "11"}
        else:
            params = queries[case]
        response = fixture.client.get("/api/audit/operations", params=params)
        if case in {"target_overflow", "target_leading_zero", "cursor_filter_change"}:
            assert response.status_code == 422
        else:
            assert response.status_code == 200
            assert len(response.json()["items"]) == (1 if case == "both" else 2)


def test_invalid_domain_audit_returns_server_error(tmp_path: Path) -> None:
    """修订5：入口误传非法AuditContext，真实应用返回500安全缺陷响应而非422，不回显来源或请求载荷。"""
    with api_case(tmp_path) as fixture:
        assert fixture.login().status_code == 200
        assert fixture.client.put("/api/audit/retention", json={"days": 8}).status_code == 200

        def broken_context(
            request: Request, cookie: Annotated[str | None, Security(SESSION_COOKIE)]
        ) -> AccountRequestContext:
            context = get_admin_context(request, cookie)
            return replace(context, audit=AuditContext("非法平台来源", context.audit.request_id))

        fixture.app.dependency_overrides[get_admin_context] = broken_context
        try:
            response = fixture.client.put("/api/audit/retention", json={"days": 7})
        finally:
            fixture.app.dependency_overrides.clear()
        assert response.status_code == 500
        assert "非法平台来源" not in response.text


def test_expiry_busy_is_unauthorized(tmp_path: Path) -> None:
    """负责人批准的第6张变更：过期删除短锁BUSY最多100毫秒，真实应用返回401并清cookie，库中会话和日志均未改。"""
    with api_case(tmp_path) as case:
        assert case.login().status_code == 200
        case.clock.value = NOW + timedelta(days=7)
        with session_scope(case.engine):
            response = case.client.get("/api/auth/me")
            assert response.status_code == 401
            assert "Max-Age=0" in response.headers["set-cookie"]
        with session_scope(case.engine, read_only=True) as session:
            assert session.scalar(select(SessionRow)) is not None


def test_failure_report_is_connected(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """H3：真实接口的业务日志及失败补记均失败时，边界额外报一次ERROR且保留原502。"""
    with api_case(tmp_path) as fixture:
        assert fixture.login().status_code == 200

        def fail(_connection: Connection, _cursor: Any, statement: str, *_args: Any) -> None:
            if statement.startswith("INSERT INTO operation_logs"):
                error = sqlite3.OperationalError("秘密")
                error.sqlite_errorcode = sqlite3.SQLITE_IOERR
                raise error

        event.listen(fixture.engine, "before_cursor_execute", fail)
        try:
            with caplog.at_level(logging.ERROR):
                response = fixture.client.put("/api/audit/retention", json={"days": 7})
        finally:
            event.remove(fixture.engine, "before_cursor_execute", fail)
        assert response.status_code == 502
        assert (
            len([record for record in caplog.records if record.name == "rdp.audit.reporting"]) == 1
        )
        assert "秘密" not in caplog.text
        assert fixture.client.get("/api/audit/retention").json() == {"days": 30}


def test_ops_failure_report_is_connected(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """运维入口保留原ExternalError，并对失败补记恰好额外报告一次，不输出新密码。"""
    from audit_account_support import account_action

    from rdp.infra.diagnostics import ExternalError
    from rdp.ops.accounts import reset_account_password

    with account_action(tmp_path, "reset_password_from_ops") as (service, _action):

        def fail(_connection: Connection, _cursor: Any, statement: str, *_args: Any) -> None:
            if statement.startswith("INSERT INTO operation_logs"):
                error = sqlite3.OperationalError("秘密")
                error.sqlite_errorcode = sqlite3.SQLITE_IOERR
                raise error

        event.listen(service.engine, "before_cursor_execute", fail)
        try:
            with caplog.at_level(logging.ERROR), pytest.raises(ExternalError):
                reset_account_password(
                    service, "member", now=NOW, read_password=lambda _prompt: "replacement-value"
                )
        finally:
            event.remove(service.engine, "before_cursor_execute", fail)
        assert (
            len([record for record in caplog.records if record.name == "rdp.audit.reporting"]) == 1
        )
        assert "replacement-value" not in caplog.text and "秘密" not in caplog.text


@pytest.mark.parametrize("case", ["rejected", "hash_failure"])
def test_login_append_failure_reports_login_kind(
    case: str, tmp_path: Path, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """补记报告：未知账号拒绝或假哈希故障后补记也失败，边界只报登录日志失败并保持原状态及脱敏。"""
    with api_case(tmp_path) as fixture:
        if case == "hash_failure":

            def fail_verify(*_args: object, **_kwargs: object) -> None:
                raise RuntimeError("哈希故障含秘密")

            monkeypatch.setattr(type(fixture.service.passwords.hasher), "verify", fail_verify)

        def fail_insert(_connection: Connection, _cursor: Any, statement: str, *_args: Any) -> None:
            if statement.startswith("INSERT INTO login_logs"):
                error = sqlite3.OperationalError("登录日志存储故障含秘密")
                error.sqlite_errorcode = sqlite3.SQLITE_IOERR
                raise error

        event.listen(fixture.engine, "before_cursor_execute", fail_insert)
        try:
            with caplog.at_level(logging.ERROR):
                response = fixture.login("private_unknown_login")
        finally:
            event.remove(fixture.engine, "before_cursor_execute", fail_insert)
        assert response.status_code == (401 if case == "rejected" else 500)
        notices = [
            record.getMessage() for record in caplog.records if "补记失败" in record.getMessage()
        ]
        assert notices == ["登录日志补记失败"]
        assert "private_unknown_login" not in caplog.text + response.text
        assert "秘密" not in caplog.text + response.text
