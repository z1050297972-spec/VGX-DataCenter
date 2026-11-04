"""工单06 HTTP、鉴权与OpenAPI契约清单；实施时只用临时库、固定时钟和本地ASGI传输。"""

import json
import logging
import sqlite3
import time
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone
from http import HTTPStatus
from pathlib import Path
from threading import get_ident
from typing import Annotated, Any, cast

import pytest
from account_api_support import ORIGIN, add_actor, api_case, boundary_response, request_for
from accounts_support import (
    AUDIT_CONTEXT,
    EXAMPLE_SECRET,
    NOW,
    CallbackHasher,
    HeldHasher,
    account_view,
    close_workers,
)
from argon2 import PasswordHasher
from fastapi import APIRouter, Depends, FastAPI
from fastapi.responses import Response
from fastapi.routing import iter_route_contexts
from fastapi.testclient import TestClient
from httpx import Client
from pydantic import SecretStr, ValidationError
from sqlalchemy import Connection, event, select

from rdp.accounts._issues import problem
from rdp.accounts.errors import AuthenticationError, AuthorizationError, LoginWaitError
from rdp.accounts.models import AccountRow
from rdp.accounts.security import PasswordCodec
from rdp.accounts.service import AccountService
from rdp.accounts.types import ActorRef, Credentials, NewAccount, Role
from rdp.api import create_app
from rdp.api.account_auth import (
    account_api_fallback,
    check_origin,
    clear_session_cookie,
    enforce_api_access,
    get_account_now,
    get_admin_context,
    get_authenticated_context,
    get_login_context,
    install_account_security,
    set_session_cookie,
)
from rdp.api.account_schemas import (
    AccountListResponse,
    ChangePasswordRequest,
    CreateAccountRequest,
    LoginRequest,
    ResetPasswordRequest,
    RoleRequest,
    StatusRequest,
    account_response,
)
from rdp.api.errors import (
    ProblemResponse,
    account_error_headers,
    format_exception_report,
    sanitize_account_error,
)
from rdp.api.openapi_export import export_openapi
from rdp.audit.types import OPS_AUDIT_CONTEXT
from rdp.infra.config import PlatformConfig
from rdp.infra.db.connection import create_database_engine, session_scope
from rdp.infra.db.migration import migrate
from rdp.infra.db.models import ErrorReportRow
from rdp.infra.db.records import ErrorRecord, find_error, write_error
from rdp.infra.diagnostics import (
    DefectError,
    Diagnostic,
    DiagnosticCategory,
    DiagnosticLevel,
)
from rdp.infra.ids import MAX_SQLITE_INTEGER
from rdp.infra.state import initialize_state, state_paths


def test_context_clock(tmp_path: Path) -> None:
    """验证契约：create_app(clock=固定aware回调) 同请求只取一次，跨请求不复用，None默认为UTC，不接受客户端时刻。"""
    with api_case(tmp_path) as case:
        assert case.login().status_code == 200
        assert case.clock.calls == 1
        assert case.client.get("/api/auth/me?now=1900-01-01").status_code == 200
        assert case.clock.calls == 2
        assert case.client.get("/api/accounts").status_code == 200
        assert case.clock.calls == 3


def test_context_login(tmp_path: Path) -> None:
    """验证契约：get_login_context只校验Origin并返回identity=None，不读取旧cookie或改数据库。"""
    with api_case(tmp_path) as case:
        request = request_for(
            case.app,
            method="POST",
            path="/api/auth/login",
            headers=[
                (b"host", b"testserver"),
                (b"origin", b"http://testserver"),
                (b"cookie", b"rdp_session=invalid"),
            ],
        )
        first = get_login_context(request)
        assert first.identity is None and first.service is case.service
        assert get_login_context(request) is first
        assert case.clock.calls == 1


def test_context_authenticated(tmp_path: Path) -> None:
    """验证契约：get_authenticated_context声明SessionCookie并复用全局结果，无重复刷新/时钟读取。"""
    with api_case(tmp_path) as case:
        grant = case.service.login(
            Credentials("admin", EXAMPLE_SECRET), now=NOW, audit=AUDIT_CONTEXT
        )
        request = request_for(
            case.app,
            headers=[(b"cookie", ("rdp_session=" + grant.token.get_secret_value()).encode())],
        )
        first = get_authenticated_context(request, None)
        assert first.identity is not None
        assert get_authenticated_context(request, None) is first
        assert case.clock.calls == 1


def test_context_failure(tmp_path: Path) -> None:
    """验证契约：缺数据库502、无效时钟/回调失败500、服务错误500，不按匿名放行业务。"""
    with api_case(tmp_path) as case:
        assert case.login().status_code == 200
        case.app.state.account_service = object()
        assert case.client.get("/api/auth/me").status_code == 500
        case.app.state.account_service = None
        assert case.client.get("/api/auth/me").status_code == 502


def test_install_default_deny(tmp_path: Path) -> None:
    """验证契约：遍历所有已注册/api路由，除精确GET健康/POST登录外均有身份需求，后来注册路由也不能绕过。"""
    with api_case(tmp_path) as case:
        for route in iter_route_contexts(case.app.routes):
            if (
                route.path is None
                or not route.path.startswith("/api")
                or "{unknown:path}" in route.path
            ):
                continue
            path = route.path.replace("{account_id}", "1").replace("{error_id}", "1")
            for method in route.methods or ():
                if (method, path) in [("GET", "/api/health"), ("POST", "/api/auth/login")]:
                    continue
                assert case.client.request(method, path, json={}).status_code == 401

        def late() -> dict[str, bool]:
            return {"unsafe": True}

        case.app.add_api_route("/api/later", late, methods=["GET"])
        assert case.client.get("/api/later").status_code == 401


def test_install_rollback() -> None:
    """验证契约：已启动、重复安装或装配不完整为DefectError，不留下部分安全边界。"""
    app = create_app(None, database=None)
    before = list(app.user_middleware)
    with pytest.raises(DefectError):
        install_account_security(app)
    assert app.user_middleware == before
    broken = FastAPI()
    with pytest.raises(DefectError):
        install_account_security(broken)
    assert not broken.user_middleware and not hasattr(broken.state, "account_security_installed")
    started = FastAPI()
    started.middleware_stack = started.build_middleware_stack()
    with pytest.raises(DefectError):
        install_account_security(started)
    assert not started.user_middleware


def test_install_missing_database() -> None:
    """验证契约：未配置数据库不能运行账号业务，离线OpenAPI只声明路由。"""
    app = create_app(None, database=None)
    assert app.state.account_service is None
    assert "/api/auth/login" in app.openapi()["paths"]
    with TestClient(app) as raw_client:
        client = cast(Client, raw_client)
        response = client.post(
            "/api/auth/login",
            headers={"Origin": ORIGIN},
            json={"login_name": "admin", "password": EXAMPLE_SECRET.get_secret_value()},
        )
        assert response.status_code == 502


def test_access_anonymous(tmp_path: Path) -> None:
    """验证契约：Origin检查已通过的非白名单/api及/api/*匿名401，未知业务路径也不绕过认证；公开路径错方法按405处理。"""
    with api_case(tmp_path) as case:
        for method, path in (
            ("GET", "/api/auth/me"),
            ("GET", "/api/errors/1"),
            ("POST", "/api/accounts"),
            ("PUT", "/api/missing"),
        ):
            response = case.client.request(method, path, json={})
            assert response.status_code == 401
            assert response.headers["content-type"].startswith("application/problem+json")
            assert response.json()["error_id"] == response.headers["X-Request-ID"]
            assert response.json()["diagnostics"]


def test_access_health(tmp_path: Path) -> None:
    """验证契约：GET/api/health无需登录且行为不变，白名单不匹配相似前缀/编码绕过。"""
    with api_case(tmp_path, origin=False) as case:
        assert case.client.get("/api/health").status_code == 200
        for path in ("/api/healthx", "/api/health/extra", "/api/%68ealthx"):
            assert case.client.get(path).status_code == 401
        assert case.clock.calls == 0


def test_access_errors(tmp_path: Path) -> None:
    """验证契约：所有已登录且已改密账号含成员均能GET/api/errors/{id}，匿名401，验收5。"""
    with api_case(tmp_path) as case:
        record = ErrorRecord(
            error_id="1",
            occurred_at=NOW,
            category=DiagnosticCategory.DEFECT,
            summary="安全摘要",
            report="安全报告",
            source_kind="job",
        )
        with session_scope(case.engine) as session:
            write_error(session, record)
        assert case.client.get("/api/errors/1").status_code == 401
        member = add_actor(case)
        response = case.client.get(
            "/api/errors/1", headers={"Cookie": "rdp_session=" + member.token.get_secret_value()}
        )
        assert response.status_code == 200 and response.json()["report"] == "安全报告"


def test_access_role(tmp_path: Path) -> None:
    """验证契约：管理员接口成员403；管理员通过，不能伪造角色或操作者。"""
    with api_case(tmp_path) as case:
        grant = add_actor(case)
        response = case.client.get(
            "/api/accounts?role=administrator",
            headers={
                "Cookie": "rdp_session=" + grant.token.get_secret_value(),
                "X-Role": "administrator",
            },
        )
        assert response.status_code == 403
        assert case.login().status_code == 200
        assert case.client.get("/api/accounts").status_code == 200


def test_access_forced(tmp_path: Path) -> None:
    """验证契约：强制改密账号只可me/改密/登出，其余含报错详情403，成功改密后放行。"""
    with api_case(tmp_path) as case:
        grant = add_actor(case, ready=False)
        cookie = {"Cookie": "rdp_session=" + grant.token.get_secret_value()}
        assert case.client.get("/api/auth/me", headers=cookie).status_code == 200
        assert case.client.get("/api/errors/" + "a" * 32, headers=cookie).status_code == 403
        response = case.client.post(
            "/api/auth/password",
            headers=cookie,
            json={
                "current_password": EXAMPLE_SECRET.get_secret_value(),
                "new_password": "replacement-value",
            },
        )
        assert response.status_code == 200
        assert case.client.get("/api/unknown").status_code == 404


def test_access_revocation(tmp_path: Path) -> None:
    """验证契约：账号停用/删除/重置后旧cookie下一请求401，验收3。"""
    for operation in ("status", "password", "delete"):
        with api_case(tmp_path / operation) as case:
            member = add_actor(case)
            cookie = {"Cookie": "rdp_session=" + member.token.get_secret_value()}
            assert case.login().status_code == 200
            target = "/api/accounts/" + str(member.identity.account.account_id)
            if operation == "delete":
                assert case.client.delete(target).status_code == 204
            elif operation == "status":
                assert (
                    case.client.patch(target + "/status", json={"status": "disabled"}).status_code
                    == 200
                )
            else:
                assert (
                    case.client.post(
                        target + "/password", json={"password": "replacement-value"}
                    ).status_code
                    == 200
                )
            assert case.client.get("/api/auth/me", headers=cookie).status_code == 401


def test_access_database_errors(tmp_path: Path) -> None:
    """验证契约：认证中的损坏库400、初始读锁409、I/O502、装配500带安全诊断；刷新获锁忙不返回409。"""
    with api_case(tmp_path) as case:
        assert case.login().status_code == 200
        for code, expected in [
            (sqlite3.SQLITE_CORRUPT, 400),
            (sqlite3.SQLITE_BUSY, 409),
            (sqlite3.SQLITE_IOERR, 502),
            (sqlite3.SQLITE_ERROR, 500),
        ]:

            def failing(
                connection: Connection,
                cursor: object,
                statement: str,
                *args: object,
                code: int = code,
            ) -> None:
                if statement.startswith("SELECT") and "account_sessions" in statement:
                    error = sqlite3.OperationalError("测试数据库故障")
                    error.sqlite_errorcode = code
                    raise error

            event.listen(case.engine, "before_cursor_execute", failing)
            try:
                response = case.client.get("/api/auth/me")
                assert response.status_code == expected
                assert response.headers["content-type"].startswith("application/problem+json")
            finally:
                event.remove(case.engine, "before_cursor_execute", failing)


def test_access_order(tmp_path: Path) -> None:
    """验证契约：写请求Origin失败在认证刷新、登录计数或业务写入前拒绝，读取密码体前执行。"""
    with api_case(tmp_path) as case:
        assert case.login().status_code == 200
        case.clock.value += timedelta(seconds=60)
        calls = case.clock.calls
        response = case.client.post(
            "/api/auth/password", headers={"Origin": "http://other.test"}, content=b"{bad"
        )
        assert response.status_code == 403 and case.clock.calls == calls
        response = case.client.get("/api/auth/me")
        assert response.status_code == 200 and "Max-Age=604800" in response.headers["set-cookie"]


def test_access_thread(tmp_path: Path) -> None:
    """验证契约：同步SQL/Argon2在线程边界，不阻塞事件循环或共享业务读写Session。"""
    with api_case(tmp_path) as case:
        loop_threads: list[int] = []
        sql_threads: list[int] = []

        async def probe() -> dict[str, bool]:
            loop_threads.append(get_ident())
            return {"ok": True}

        case.app.add_api_route("/api/thread", probe, methods=["GET"])
        case.app.router.routes.insert(0, case.app.router.routes.pop())

        def observed(connection: Connection, cursor: object, statement: str, *args: object) -> None:
            sql_threads.append(get_ident())

        event.listen(case.engine, "before_cursor_execute", observed)
        try:
            assert case.login().status_code == 200
            assert case.client.get("/api/thread").status_code == 200
        finally:
            event.remove(case.engine, "before_cursor_execute", observed)
        assert sql_threads and loop_threads
        assert set(sql_threads).isdisjoint(loop_threads)


def test_origin_same() -> None:
    """验证契约：合法同scheme/host/有效端口Origin通过，主机大小写和默认80/443端口规范化。"""
    for origin, host in [
        ("http://testserver", "testserver"),
        ("http://TESTSERVER:80", "testserver"),
        ("http://testserver", "TESTSERVER:80"),
        ("http://testserver:8123", "testserver:8123"),
    ]:
        check_origin(
            request_for(
                FastAPI(),
                method="POST",
                headers=[(b"origin", origin.encode()), (b"host", host.encode())],
            )
        )


def test_origin_different() -> None:
    """验证契约：不同scheme/host/端口均403，带规则/后果/下一步且不回显头，验收6。"""
    for origin in ["https://testserver", "http://other.test", "http://testserver:81"]:
        with pytest.raises(AuthorizationError) as caught:
            check_origin(
                request_for(
                    FastAPI(),
                    method="POST",
                    headers=[(b"origin", origin.encode()), (b"host", b"testserver")],
                )
            )
        assert caught.value.http_status == 403
        assert origin not in format_exception_report(caught.value)
        assert caught.value.diagnostics[0].consequence and caught.value.diagnostics[0].next_step


def test_origin_missing() -> None:
    """验证契约：POST等不安全方法缺Origin/null/重复/多值拒绝403，命令行也必须显式提供。"""
    for origins in [
        [],
        [(b"origin", b"null")],
        [(b"origin", b"http://testserver"), (b"origin", b"http://testserver")],
        [(b"origin", b"http://testserver http://other.test")],
    ]:
        with pytest.raises(AuthorizationError):
            check_origin(
                request_for(FastAPI(), method="POST", headers=[(b"host", b"testserver"), *origins])
            )


def test_origin_malformed() -> None:
    """验证契约：Origin带用户信息/路径/query/fragment或非法/缺失Host均拒绝。"""
    for origin in [
        "http://user@testserver",
        "http://testserver/",
        "http://testserver?q=1",
        "http://testserver#x",
        "http://testserver:0",
        "http://testserver:65536",
        "http://testserver:bad",
        "http://testserver\\evil",
    ]:
        with pytest.raises(AuthorizationError):
            check_origin(
                request_for(
                    FastAPI(),
                    method="POST",
                    headers=[(b"host", b"testserver"), (b"origin", origin.encode())],
                )
            )
    for host in [None, b"bad host", b"testserver:0"]:
        headers = [(b"origin", b"http://testserver")]
        if host is not None:
            headers.append((b"host", host))
        with pytest.raises(AuthorizationError):
            check_origin(request_for(FastAPI(), method="POST", headers=headers))


def test_origin_safe_methods(tmp_path: Path) -> None:
    """验证契约：GET/HEAD/OPTIONS免Origin检查但不因此免业务身份；公开路径错方法只返回405，POST登录也必须检查Origin。"""
    with api_case(tmp_path, origin=False) as case:
        for method in ("GET", "HEAD", "OPTIONS"):
            assert case.client.request(method, "/api/auth/me").status_code == 401
        assert case.client.head("/api/health").status_code == 405
        assert case.client.post("/api/auth/login", json={}).status_code == 403


def test_origin_proxy(tmp_path: Path) -> None:
    """验证契约：不信任客户端X-Forwarded-*覆盖本站，不能把攻击者Origin当本站。"""
    with api_case(tmp_path) as case:
        response = case.client.post(
            "/api/auth/login",
            headers={
                "Origin": "https://attacker.test",
                "X-Forwarded-Host": "attacker.test",
                "X-Forwarded-Proto": "https",
            },
            json={},
        )
        assert response.status_code == 403


def test_cookie_set(tmp_path: Path) -> None:
    """验证契约：set_session_cookie仅在提交后设置rdp_session，HttpOnly/Lax/Path=/，无Domain，Secure=False，Max-Age604800。"""
    with api_case(tmp_path) as case:
        response = case.login()
        assert response.status_code == 200
        cookie = response.headers["set-cookie"]
        assert all(
            attribute in cookie
            for attribute in (
                "rdp_session=",
                "HttpOnly",
                "Path=/",
                "SameSite=lax",
                "Max-Age=604800",
            )
        )
        assert "Secure" not in cookie and "Domain" not in cookie


def test_cookie_renew(tmp_path: Path) -> None:
    """验证契约：仅登录/改密成功或活动刷新实际提交时续Max-Age；未到间隔、BUSY或并发已刷不重发；登出/401清除优先。"""
    with api_case(tmp_path) as case:
        assert case.login().status_code == 200
        token = case.client.cookies["rdp_session"]
        assert "set-cookie" not in case.client.get("/api/auth/me").headers
        case.clock.value += timedelta(seconds=60)
        refreshed = case.client.get("/api/auth/me")
        assert refreshed.status_code == 200
        assert "Max-Age=604800" in refreshed.headers["set-cookie"]
        assert case.client.cookies["rdp_session"] == token
        assert "set-cookie" not in case.client.get("/api/auth/me").headers
        case.clock.value += timedelta(seconds=60)
        ended = case.client.post("/api/auth/logout")
        assert ended.status_code == 204
        assert "Max-Age=0" in ended.headers["set-cookie"]
        assert "Max-Age=604800" not in ended.headers["set-cookie"]


def test_cookie_clear() -> None:
    """验证契约：登出提交后和401清除同名同path cookie，Max-Age0，属性一致。"""
    response = Response()
    clear_session_cookie(response)
    value = response.headers["set-cookie"]
    assert "rdp_session=" in value and "Max-Age=0" in value
    assert "HttpOnly" in value and "Path=/" in value and "SameSite=lax" in value
    assert "Secure" not in value and "Domain" not in value


def test_cookie_secret(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """验证契约：原文只在Set-Cookie，响应JSON/诊断/OpenAPI示例/日志/报错表不含秘密。"""
    with api_case(tmp_path) as case:
        caplog.clear()
        response = case.login()
        token = case.client.cookies["rdp_session"]
        assert token not in response.text and EXAMPLE_SECRET.get_secret_value() not in response.text
        assert token not in json.dumps(case.app.openapi())
        assert token not in caplog.text and EXAMPLE_SECRET.get_secret_value() not in caplog.text
        with session_scope(case.engine, read_only=True) as session:
            assert not session.scalars(select(ErrorReportRow)).all()


def test_cookie_failures(tmp_path: Path) -> None:
    """验证契约：非法grant或非法响应对象给安全DefectError，不能回显令牌；发送失败不回滚已提交会话。"""
    with api_case(tmp_path) as case:
        grant = case.service.login(
            Credentials("admin", EXAMPLE_SECRET), now=NOW, audit=AUDIT_CONTEXT
        )
        response = Response()
        invalid_token = SecretStr("invalid-private-token")
        with pytest.raises(DefectError) as caught:
            set_session_cookie(response, replace(grant, token=invalid_token))
        assert "set-cookie" not in response.headers
        assert "invalid-private-token" not in format_exception_report(caught.value)
        assert (
            case.service.authenticate(grant.token, now=NOW, audit=AUDIT_CONTEXT).account.account_id
            == 1
        )
        with pytest.raises(DefectError):
            clear_session_cookie(cast(Response, object()))


def test_fallback_health_method(tmp_path: Path) -> None:
    """验证契约：带正确Origin的匿名POST/api/health返回405且Allow含GET，S1验收。"""
    with api_case(tmp_path) as case:
        response = case.client.post("/api/health")
        assert response.status_code == 405
        assert response.headers["allow"] == "GET"
        assert case.clock.calls == 0


def test_fallback_missing(tmp_path: Path) -> None:
    """验证契约：已登录GET/api/不存在返回404 JSON，不能回退SPA。"""
    with api_case(tmp_path) as case:
        assert case.login().status_code == 200
        response = case.client.get("/api/does-not-exist")
        assert response.status_code == 404 and response.json() == {"detail": "Not Found"}


def test_fallback_known_method(tmp_path: Path) -> None:
    """验证契约：已知静态或动态路径方法错405，Allow去重排序包含全部已登记方法，不含兜底方法。"""
    with api_case(tmp_path) as case:
        assert case.login().status_code == 200
        for path, allowed in [
            ("/api/accounts", "GET, POST"),
            ("/api/accounts/1/role", "PATCH"),
            ("/api/auth/me", "GET"),
        ]:
            response = case.client.put(path)
            assert response.status_code == 405 and response.headers["allow"] == allowed


def test_fallback_query(tmp_path: Path) -> None:
    """验证契约：query不改变路径匹配，HEAD/OPTIONS/TRACE不绕过保留命名空间。"""
    with api_case(tmp_path) as case:
        assert case.login().status_code == 200
        for method in ("HEAD", "OPTIONS", "TRACE"):
            response = case.client.request(method, "/api/accounts?role=member")
            assert response.status_code == 405 and response.headers["allow"] == "GET, POST"
        assert case.client.get("/api/missing?path=/api/accounts").status_code == 404


def test_fallback_broken() -> None:
    """验证契约：路由装配损坏归DefectError，不把无法判断伪装为404。"""
    app = create_app(None, database=None)
    app.router.routes.append(cast(Any, object()))
    with pytest.raises(DefectError):
        account_api_fallback(request_for(app, path="/api/missing"))


def test_schema_requests() -> None:
    """验证契约：所有请求禁止额外字段；登录名ASCII边界、密码10/128码点、显示名64上限与Role/Status枚举正确。"""
    models = [
        (LoginRequest, {"login_name": "abc", "password": "x" * 10}),
        (
            CreateAccountRequest,
            {
                "login_name": "abc",
                "password": "x" * 128,
                "display_name": "名" * 64,
                "role": "member",
            },
        ),
        (RoleRequest, {"role": "administrator"}),
        (StatusRequest, {"status": "enabled"}),
        (ResetPasswordRequest, {"password": "🙂" * 10}),
        (ChangePasswordRequest, {"current_password": "x" * 10, "new_password": "y" * 10}),
    ]
    for model, payload in models:
        assert model.model_validate(payload)
        with pytest.raises(ValidationError):
            model.model_validate({**payload, "unexpected": "secret"})
    for name in ("ab", "a" * 33, "ABC", "abc ", "中文名"):
        with pytest.raises(ValidationError):
            LoginRequest.model_validate(dict(login_name=name, password="x" * 10))
    for secret in ("x" * 9, "x" * 129):
        with pytest.raises(ValidationError):
            LoginRequest.model_validate(dict(login_name="abc", password=secret))
    for display in ("", "名" * 65):
        with pytest.raises(ValidationError):
            CreateAccountRequest.model_validate(
                dict(login_name="abc", password="x" * 10, display_name=display, role="member")
            )


def test_schema_secret_validation(tmp_path: Path) -> None:
    """验证契约：422只显示声明字段名，不回显input/msg/ctx/body；秘密字段无repr或OpenAPI示例。"""
    with api_case(tmp_path) as case:
        input_text = "private-invalid-value"
        response = case.client.post(
            "/api/auth/login",
            json={
                "login_name": "admin",
                "password": {"inside": input_text},
                input_text: input_text,
            },
        )
        assert response.status_code == 422 and input_text not in response.text
        assert "body.password" in response.text
        model = LoginRequest.model_validate(dict(login_name="admin", password=input_text))
        assert input_text not in repr(model)
        assert "examples" not in str(LoginRequest.model_json_schema())


def test_schema_ids(tmp_path: Path) -> None:
    """验证契约：响应及路径编号用规范十进制文本，2^53以上精度保留；2^63-1合法、上限加一拒绝422。"""
    for number in (9007199254740993, MAX_SQLITE_INTEGER):
        assert account_response(replace(account_view(), account_id=number)).account_id == str(
            number
        )
    with pytest.raises(DefectError):
        account_response(replace(account_view(), account_id=MAX_SQLITE_INTEGER + 1))
    with api_case(tmp_path) as case:
        assert case.login().status_code == 200
        assert case.client.delete("/api/accounts/9223372036854775808").status_code == 422
        assert case.client.delete("/api/accounts/9223372036854775807").status_code == 404


def test_schema_response() -> None:
    """验证契约：account_response保持UTC微秒、操作者快照和完整字段，无任何哈希、会话或失败计数。"""
    original = replace(account_view(), created_by=ActorRef(9007199254740993, "当时名字"))
    response = account_response(original)
    assert response.created_at == NOW and response.created_at.tzinfo is UTC
    assert response.updated_at.microsecond == 123456
    assert (
        response.created_by.account_id == "9007199254740993"
        and response.created_by.name == "当时名字"
    )
    assert set(response.model_dump()) == {
        "account_id",
        "login_name",
        "display_name",
        "role",
        "status",
        "must_change_password",
        "created_at",
        "updated_at",
        "created_by",
        "updated_by",
    }
    assert response.login_name == "admin" and response.display_name == "显示名"
    assert original.created_by.name == "当时名字"


def test_schema_bad_view() -> None:
    """验证契约：account_response遇损坏快照/时间/编号给安全DefectError，不返回部分响应。"""
    for changes in (
        {"account_id": 0},
        {"account_id": True},
        {"created_at": NOW.replace(tzinfo=None)},
        {"updated_at": NOW - timedelta(seconds=1)},
        {"login_name": "PRIVATE-VALUE"},
        {"role": "invalid"},
        {"must_change_password": 1},
        {"created_by": ActorRef(0, "名字")},
    ):
        with pytest.raises(DefectError) as caught:
            account_response(replace(account_view(), **changes))
        assert "PRIVATE-VALUE" not in format_exception_report(caught.value)


def test_schema_list() -> None:
    """验证契约：一页最多100项，空页合法，next_after_id可null，不把游标转浮点。"""
    response = account_response(account_view())
    assert AccountListResponse(items=(), next_after_id=None).model_dump() == {
        "items": (),
        "next_after_id": None,
    }
    page = AccountListResponse(items=(response,) * 100, next_after_id="9007199254740993")
    assert page.next_after_id == "9007199254740993"
    with pytest.raises(ValidationError):
        AccountListResponse(items=(response,) * 101, next_after_id=None)


def test_error_contract_statuses() -> None:
    """验证契约：InputError及ProblemResponse接受401/403/429正确类别/标题，拒绝错类别/标题和未知状态。"""
    for status in (401, 403, 429):
        values = {
            "title": HTTPStatus(status).phrase,
            "status": status,
            "detail": "安全摘要",
            "category": DiagnosticCategory.INPUT,
            "error_id": "00000000000040008000000000000000",
        }
        assert ProblemResponse.model_validate(values).status == status
        for change in (
            {"category": DiagnosticCategory.CONFLICT},
            {"title": "wrong"},
            {"status": 418},
        ):
            with pytest.raises(ValidationError):
                ProblemResponse.model_validate(values | change)


def test_error_contract_wait_constructor() -> None:
    """验证契约：LoginWaitError接受1至60整数秒；0/61/bool/空或错类别诊断给ValueError且不回显输入。"""
    diagnostic = Diagnostic(
        level=DiagnosticLevel.ERROR,
        category=DiagnosticCategory.INPUT,
        stage="登录",
        source="平台",
        objects=(),
        rule="等待结束后重试",
        actual="等待中",
        expected="等待结束",
        consequence="本次登录未执行",
        next_step="稍后重试",
    )
    for seconds in (1, 60):
        error = LoginWaitError((diagnostic,), retry_after_s=seconds)
        assert error.retry_after_s == seconds and error.http_status == 429
    for seconds in (0, 61, True):
        with pytest.raises(ValueError):
            LoginWaitError((diagnostic,), retry_after_s=seconds)
    with pytest.raises(ValueError):
        LoginWaitError((), retry_after_s=1)


def test_error_contract_headers() -> None:
    """验证契约：account_error_headers对LoginWaitError返回仅Retry-After，其他异常空字典，损坏剩余秒为DefectError。"""
    diagnostic = Diagnostic(
        level=DiagnosticLevel.ERROR,
        category=DiagnosticCategory.INPUT,
        stage="登录",
        source="平台",
        objects=(),
        rule="等待结束",
        actual="等待中",
        expected="允许重试",
        consequence="未登录",
        next_step="稍后重试",
    )
    error = LoginWaitError((diagnostic,), retry_after_s=12)
    assert account_error_headers(error) == {"Retry-After": "12"}
    assert account_error_headers(ValueError("private-value")) == {}
    error.retry_after_s = True
    with pytest.raises(DefectError):
        account_error_headers(error)


def test_error_contract_both_paths(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """验证契约：handle_error与ErrorBoundary均输出429 Retry-After和同一X-Request-ID，只报告一次。"""
    caplog.set_level(logging.INFO, logger="rdp.api.errors")
    diagnostic = Diagnostic(
        level=DiagnosticLevel.ERROR,
        category=DiagnosticCategory.INPUT,
        stage="登录",
        source="平台",
        objects=(),
        rule="等待结束",
        actual="等待中",
        expected="允许重试",
        consequence="未登录",
        next_step="稍后重试",
    )
    error = LoginWaitError((diagnostic,), retry_after_s=12)
    caplog.clear()
    status, headers, payload = boundary_response(error)
    assert status == 429 and headers["retry-after"] == "12"
    assert payload["error_id"] == headers["x-request-id"]
    assert (
        len([r for r in caplog.records if r.name == "rdp.api.errors" and r.levelname == "INFO"])
        == 1
    )
    with api_case(tmp_path) as case:
        assert case.login().status_code == 200

        def endpoint() -> None:
            raise LoginWaitError((diagnostic,), retry_after_s=12)

        case.app.add_api_route("/api/wait-probe", endpoint, methods=["GET"])
        case.app.router.routes.insert(0, case.app.router.routes.pop())
        caplog.clear()
        response = case.client.get("/api/wait-probe")
        assert response.status_code == 429 and response.headers["Retry-After"] == "12"
        assert (
            len([r for r in caplog.records if r.name == "rdp.api.errors" and r.levelname == "INFO"])
            == 1
        )


def test_error_contract_sanitize() -> None:
    """验证契约：sanitize_account_error保留可信安全领域异常/RequestValidationError，未知异常转换固定DefectError且无原message/cause/context/notes。"""
    original = RuntimeError("secret-in-original")
    original.add_note("secret-note")
    safe = sanitize_account_error(original)
    assert isinstance(safe, DefectError) and safe is not original
    assert safe.__cause__ is None and safe.__context__ is None
    assert "secret-in-original" not in format_exception_report(safe)
    assert "secret-note" not in format_exception_report(safe)
    trusted = DefectError()
    assert sanitize_account_error(trusted) is trusted


def test_error_contract_privacy(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """验证契约：模拟含密码/cookie/令牌/哈希的未知失败，响应、日志和error_reports都无原文，其他业务完整报告保持原契约。"""
    with api_case(tmp_path) as case:
        assert case.login().status_code == 200
        secrets = [
            EXAMPLE_SECRET.get_secret_value(),
            case.client.cookies["rdp_session"],
            "cookie-private-value",
            "$argon2id$private-value",
        ]

        def failing() -> None:
            original = RuntimeError(" ".join(secrets))
            original.add_note(" ".join(secrets))
            raise original

        case.app.add_api_route("/api/auth/privacy", failing, methods=["GET"])
        case.app.router.routes.insert(0, case.app.router.routes.pop())
        caplog.clear()
        response = case.client.get("/api/auth/privacy")
        assert response.status_code == 500
        with session_scope(case.engine, read_only=True) as session:
            record = find_error(session, response.json()["error_id"])
        assert record is not None
        for secret in secrets:
            assert (
                secret not in response.text
                and secret not in caplog.text
                and secret not in record.report
            )
        assert "failing" in record.report
        assert (
            len(
                [r for r in caplog.records if r.name == "rdp.api.errors" and r.levelname == "ERROR"]
            )
            == 1
        )


def test_openapi_paths() -> None:
    """验证契约：十个账号操作的方法/路径/请求/响应和200/201/204状态全部进入OpenAPI。"""
    schema = create_app(None, database=None).openapi()
    expected = [
        ("/api/auth/login", "post", "200"),
        ("/api/auth/logout", "post", "204"),
        ("/api/auth/me", "get", "200"),
        ("/api/auth/password", "post", "200"),
        ("/api/accounts", "get", "200"),
        ("/api/accounts", "post", "201"),
        ("/api/accounts/{account_id}/role", "patch", "200"),
        ("/api/accounts/{account_id}/status", "patch", "200"),
        ("/api/accounts/{account_id}/password", "post", "200"),
        ("/api/accounts/{account_id}", "delete", "204"),
    ]
    for path, method, status in expected:
        operation = schema["paths"][path][method]
        assert status in operation["responses"]
        if method in ("post", "patch") and path != "/api/auth/logout":
            assert "requestBody" in operation
        if status != "204":
            assert operation["responses"][status]["content"]["application/json"]["schema"]["$ref"]


def test_openapi_security() -> None:
    """验证契约：除登录和健康外所有API含SessionCookie安全需求，401/403/429的problem schema及Retry-After头明确。"""
    schema = create_app(None, database=None).openapi()
    for path, item in schema["paths"].items():
        for method, operation in item.items():
            if method not in ("get", "post", "patch", "delete"):
                continue
            if (method, path) in [("get", "/api/health"), ("post", "/api/auth/login")]:
                assert not operation.get("security")
            else:
                assert operation["security"] == [{"SessionCookie": []}]
            for status in ("401", "403", "429"):
                assert "application/problem+json" in operation["responses"][status]["content"]
    assert (
        "Retry-After" in schema["paths"]["/api/auth/login"]["post"]["responses"]["429"]["headers"]
    )


def test_openapi_generation(tmp_path: Path) -> None:
    """验证契约：make api-types生成确定文件，组件中无秘密响应字段或凭据示例，离线导出不连接真实数据库。"""
    first, second = tmp_path / "first.json", tmp_path / "second.json"
    export_openapi(first)
    export_openapi(second)
    assert first.read_bytes() == second.read_bytes()
    schema = json.loads(first.read_text())
    assert schema == create_app(None, database=None).openapi()
    response = schema["components"]["schemas"]["AccountResponse"]
    assert (
        not {"password", "password_hash", "token", "token_digest", "cookie"}
        & response["properties"].keys()
    )
    assert "examples" not in json.dumps(schema["components"]["schemas"]["LoginRequest"])


def test_login_success(tmp_path: Path) -> None:
    """验证契约：200安全账号与新cookie，失败不发新cookie，登录不复用旧令牌。"""
    paths = state_paths(PlatformConfig(state_dir=tmp_path), ())
    initialize_state(paths)
    migrate(paths, now=NOW)
    engine = create_database_engine(paths.database)
    try:
        service = AccountService(
            engine, PasswordCodec(PasswordHasher(time_cost=1, memory_cost=1024, parallelism=1))
        )
        service.create_first_admin(
            NewAccount(Credentials("admin", EXAMPLE_SECRET), "管理员", Role.ADMINISTRATOR),
            now=NOW,
            audit=OPS_AUDIT_CONTEXT,
        )
        app = create_app(None, database=engine, clock=lambda: NOW)
        app.state.account_service = service
        with TestClient(app) as raw_client:
            client = cast(Client, raw_client)
            response = client.post(
                "/api/auth/login",
                headers={"Origin": "http://testserver"},
                json={"login_name": "admin", "password": EXAMPLE_SECRET.get_secret_value()},
            )
            assert response.status_code == 200
            assert response.json()["login_name"] == "admin"
            assert "rdp_session=" in response.headers["set-cookie"]
            assert "password" not in response.json()
    finally:
        engine.dispose()


def test_login_failure(tmp_path: Path) -> None:
    """验证契约：错密码/未知/停用统一401，G2等待429及向上取整Retry-After，Origin403、输入422。"""
    with api_case(tmp_path) as case:
        replies = [case.login("missing"), case.login(secret=SecretStr("incorrect-value"))]
        assert all(response.status_code == 401 for response in replies)
        assert replies[0].json()["diagnostics"] == replies[1].json()["diagnostics"]
        for expected in (401, 401, 401, 429):
            response = case.login(secret=SecretStr("incorrect-value"))
            assert response.status_code == expected
        assert response.headers["Retry-After"] == "60"
        case.clock.value += timedelta(microseconds=1)
        response = case.login()
        assert response.status_code == 429 and response.headers["Retry-After"] == "60"
        assert case.client.post("/api/auth/login", json={}).status_code == 422


def test_login_commit(tmp_path: Path) -> None:
    """验证契约：失败计数先提交再抛错误，提交失败不发cookie，验收1/2/7。"""
    with api_case(tmp_path) as case:
        response = case.login(secret=SecretStr("incorrect-value"))
        assert response.status_code == 401
        with session_scope(case.engine, read_only=True) as session:
            row = session.get(AccountRow, 1)
            assert row is not None and row.failed_attempts == 1

        def fail_commit(connection: Connection) -> None:
            raise sqlite3.OperationalError("测试提交失败")

        event.listen(case.engine, "commit", fail_commit)
        try:
            response = case.login()
            assert response.status_code == 500 and "set-cookie" not in response.headers
        finally:
            event.remove(case.engine, "commit", fail_commit)
        with session_scope(case.engine, read_only=True) as session:
            row = session.get(AccountRow, 1)
            assert row is not None and row.failed_attempts == 1


def test_logout_success(tmp_path: Path) -> None:
    """验证契约：POST登出204无体，服务端撤销后清cookie。"""
    with api_case(tmp_path) as case:
        assert case.login().status_code == 200
        response = case.client.post("/api/auth/logout")
        assert response.status_code == 204 and response.content == b""
        assert "Max-Age=0" in response.headers["set-cookie"]
        assert case.client.get("/api/auth/me").status_code == 401


def test_logout_second(tmp_path: Path) -> None:
    """验证契约：同cookie下次401并清cookie，网络或数据库失败不能宣称退出成功。"""
    with api_case(tmp_path) as case:
        assert case.login().status_code == 200
        token = case.client.cookies["rdp_session"]
        assert case.client.post("/api/auth/logout").status_code == 204
        response = case.client.post("/api/auth/logout", headers={"Cookie": "rdp_session=" + token})
        assert response.status_code == 401 and "Max-Age=0" in response.headers["set-cookie"]


def test_who_am_i_success(tmp_path: Path) -> None:
    """验证契约：GET返回200当前安全身份，强制改密可访问，匿名/过期401。"""
    with api_case(tmp_path) as case:
        assert case.client.get("/api/auth/me").status_code == 401
        assert case.login().status_code == 200
        response = case.client.get("/api/auth/me")
        assert response.status_code == 200 and response.json()["login_name"] == "admin"
        forced = add_actor(case, ready=False)
        response = case.client.get(
            "/api/auth/me", headers={"Cookie": "rdp_session=" + forced.token.get_secret_value()}
        )
        assert response.status_code == 200 and response.json()["must_change_password"]


def test_change_password_success(tmp_path: Path) -> None:
    """验证契约：本人修改200、清must_change_password、撤销旧会话并发新cookie。"""
    with api_case(tmp_path) as case:
        assert case.login().status_code == 200
        old = case.client.cookies["rdp_session"]
        response = case.client.post(
            "/api/auth/password",
            json={
                "current_password": EXAMPLE_SECRET.get_secret_value(),
                "new_password": "replacement-credential",
            },
        )
        assert response.status_code == 200 and not response.json()["must_change_password"]
        assert case.client.cookies["rdp_session"] != old
        assert (
            case.client.get("/api/auth/me", headers={"Cookie": "rdp_session=" + old}).status_code
            == 401
        )


def test_change_password_failures(tmp_path: Path) -> None:
    """验证契约：旧密码错先提交G2计数再400并保留cookie，第五次429；新旧相同422，真正失效才401。"""
    with api_case(tmp_path) as case:
        assert case.login().status_code == 200
        token = case.client.cookies["rdp_session"]
        same = EXAMPLE_SECRET.get_secret_value()
        assert (
            case.client.post(
                "/api/auth/password", json={"current_password": same, "new_password": same}
            ).status_code
            == 422
        )
        for expected in (400, 400, 400, 400, 429):
            response = case.client.post(
                "/api/auth/password",
                json={"current_password": "incorrect-value", "new_password": "replacement-value"},
            )
            assert response.status_code == expected
            assert "set-cookie" not in response.headers
            assert case.client.cookies["rdp_session"] == token
        assert response.headers["Retry-After"] == "60"
        assert case.client.get("/api/auth/me").status_code == 200


def test_list_accounts_success(tmp_path: Path) -> None:
    """验证契约：管理员200分页，成员403，空页/末页合法。"""
    with api_case(tmp_path) as case:
        assert case.login().status_code == 200
        response = case.client.get("/api/accounts")
        assert response.status_code == 200 and response.json()["next_after_id"] is None
        assert [x["account_id"] for x in response.json()["items"]] == ["1"]
        member = add_actor(case)
        assert (
            case.client.get(
                "/api/accounts",
                headers={"Cookie": "rdp_session=" + member.token.get_secret_value()},
            ).status_code
            == 403
        )


def test_list_accounts_invalid(tmp_path: Path) -> None:
    """验证契约：非法游标包括bool形式/前导零/越界422，JSON不含秘密。"""
    with api_case(tmp_path) as case:
        assert case.login().status_code == 200
        for value in ("true", "01", "-1", "9223372036854775808", ""):
            response = case.client.get("/api/accounts", params={"after_id": value})
            assert response.status_code == 422
            assert "password_hash" not in response.text and "token_digest" not in response.text
        response = case.client.get("/api/accounts", params={"after_id": "9223372036854775807"})
        assert response.json() == {"items": [], "next_after_id": None}


def test_create_account_success(tmp_path: Path) -> None:
    """验证契约：管理员201，默认启用/强制改密，不为新账号发cookie。"""
    with api_case(tmp_path) as case:
        assert case.login().status_code == 200
        response = case.client.post(
            "/api/accounts",
            json={
                "login_name": "member",
                "display_name": "成员",
                "role": "member",
                "password": EXAMPLE_SECRET.get_secret_value(),
            },
        )
        assert response.status_code == 201 and response.json()["account_id"] == "2"
        assert response.json()["must_change_password"] and response.json()["status"] == "enabled"
        assert "set-cookie" not in response.headers


def test_create_account_failure(tmp_path: Path) -> None:
    """验证契约：重名409，字段422，权限403，事务失败不留账号。"""
    with api_case(tmp_path) as case:
        assert case.login().status_code == 200
        payload = {
            "login_name": "admin",
            "display_name": "重名",
            "role": "member",
            "password": EXAMPLE_SECRET.get_secret_value(),
        }
        assert case.client.post("/api/accounts", json=payload).status_code == 409
        for field, value in [
            ("login_name", "UPPER"),
            ("display_name", " "),
            ("role", "superuser"),
            ("password", "short"),
        ]:
            assert (
                case.client.post("/api/accounts", json={**payload, field: value}).status_code == 422
            )
        assert len(case.client.get("/api/accounts").json()["items"]) == 1


def test_set_account_role_success(tmp_path: Path) -> None:
    """验证契约：200快照，实际改变撤销目标会话，相同值不写。"""
    with api_case(tmp_path) as case:
        assert case.login().status_code == 200
        member = add_actor(case)
        key = str(member.identity.account.account_id)
        response = case.client.patch(
            "/api/accounts/" + key + "/role", json={"role": "administrator"}
        )
        assert response.status_code == 200 and response.json()["role"] == "administrator"
        assert (
            case.client.get(
                "/api/auth/me", headers={"Cookie": "rdp_session=" + member.token.get_secret_value()}
            ).status_code
            == 401
        )


def test_set_account_role_failure(tmp_path: Path) -> None:
    """验证契约：最后管理员409、目标不存在404、字段422，失败不部分改角色。"""
    with api_case(tmp_path) as case:
        assert case.login().status_code == 200
        assert case.client.patch("/api/accounts/1/role", json={"role": "member"}).status_code == 409
        assert (
            case.client.patch("/api/accounts/999/role", json={"role": "member"}).status_code == 404
        )
        assert (
            case.client.patch("/api/accounts/1/role", json={"role": "invalid"}).status_code == 422
        )
        assert case.client.get("/api/auth/me").json()["role"] == "administrator"


def test_set_account_status_success(tmp_path: Path) -> None:
    """验证契约：启停200，停用原子撤销全部会话，启用不恢复旧会话。"""
    with api_case(tmp_path) as case:
        assert case.login().status_code == 200
        member = add_actor(case)
        key = str(member.identity.account.account_id)
        response = case.client.patch(
            "/api/accounts/" + key + "/status", json={"status": "disabled"}
        )
        assert response.status_code == 200 and response.json()["status"] == "disabled"
        response = case.client.patch("/api/accounts/" + key + "/status", json={"status": "enabled"})
        assert response.status_code == 200 and response.json()["status"] == "enabled"
        assert (
            case.client.get(
                "/api/auth/me", headers={"Cookie": "rdp_session=" + member.token.get_secret_value()}
            ).status_code
            == 401
        )


def test_set_account_status_failure(tmp_path: Path) -> None:
    """验证契约：最后管理员409、不存在404、字段422，失败不部分改状态。"""
    with api_case(tmp_path) as case:
        assert case.login().status_code == 200
        assert (
            case.client.patch("/api/accounts/1/status", json={"status": "disabled"}).status_code
            == 409
        )
        assert (
            case.client.patch("/api/accounts/999/status", json={"status": "disabled"}).status_code
            == 404
        )
        assert (
            case.client.patch("/api/accounts/1/status", json={"status": "invalid"}).status_code
            == 422
        )
        assert case.client.get("/api/auth/me").json()["status"] == "enabled"


def test_reset_account_password_success(tmp_path: Path) -> None:
    """验证契约：200，强制改密、清G2、删全部会话，不返回目标令牌。"""
    with api_case(tmp_path) as case:
        assert case.login().status_code == 200
        member = add_actor(case)
        key = str(member.identity.account.account_id)
        response = case.client.post(
            "/api/accounts/" + key + "/password", json={"password": "replacement-credential"}
        )
        assert response.status_code == 200 and response.json()["must_change_password"]
        assert "set-cookie" not in response.headers
        assert (
            case.client.get(
                "/api/auth/me", headers={"Cookie": "rdp_session=" + member.token.get_secret_value()}
            ).status_code
            == 401
        )


def test_reset_account_password_failure(tmp_path: Path) -> None:
    """验证契约：不存在404、非法密码422、成员403、存储失败全回滚。"""
    with api_case(tmp_path) as case:
        assert case.login().status_code == 200
        assert (
            case.client.post(
                "/api/accounts/999/password", json={"password": "replacement-value"}
            ).status_code
            == 404
        )
        assert (
            case.client.post("/api/accounts/1/password", json={"password": "short"}).status_code
            == 422
        )
        member = add_actor(case)
        response = case.client.post(
            "/api/accounts/1/password",
            headers={"Cookie": "rdp_session=" + member.token.get_secret_value()},
            json={"password": "replacement-value"},
        )
        assert response.status_code == 403
        assert response.json()["diagnostics"][0]["actual"] == "需要管理员权限"
        assert case.client.get("/api/auth/me").json()["must_change_password"] is False


def test_delete_account_success(tmp_path: Path) -> None:
    """验证契约：204无体，删除全部会话，历史名字保留。"""
    with api_case(tmp_path) as case:
        assert case.login().status_code == 200
        member = add_actor(case)
        key = str(member.identity.account.account_id)
        response = case.client.delete("/api/accounts/" + key)
        assert response.status_code == 204 and response.content == b""
        listing = case.client.get("/api/accounts").json()
        assert all(item["account_id"] != key for item in listing["items"])
        assert (
            case.client.get(
                "/api/auth/me", headers={"Cookie": "rdp_session=" + member.token.get_secret_value()}
            ).status_code
            == 401
        )


def test_delete_account_failure(tmp_path: Path) -> None:
    """验证契约：最后管理员409、不存在404、非法编号422，失败全回滚。"""
    with api_case(tmp_path) as case:
        assert case.login().status_code == 200
        assert case.client.delete("/api/accounts/1").status_code == 409
        assert case.client.delete("/api/accounts/999").status_code == 404
        assert case.client.delete("/api/accounts/01").status_code == 422
        assert len(case.client.get("/api/accounts").json()["items"]) == 1


def test_install_password_initialization(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """验证契约：安装时构造默认编码器和领域服务，假哈希初始化失败安全拒绝且不部分安装；离线不哈希。"""
    with api_case(tmp_path) as case:
        assert isinstance(case.app.state.account_service, AccountService)
        assert PasswordCodec().hasher.memory_cost == PasswordHasher().memory_cost

        def broken_hash(self: PasswordHasher, password: str | bytes, **kwargs: object) -> str:
            raise RuntimeError("private-initialization-value")

        monkeypatch.setattr(PasswordHasher, "hash", broken_hash)
        app = FastAPI()
        app.add_api_route("/api/health", lambda: None)
        app.add_api_route("/api/auth/login", lambda: None, methods=["POST"])
        app.state.database_engine = case.engine
        with pytest.raises(DefectError) as caught:
            install_account_security(app)
        assert not app.user_middleware and not hasattr(app.state, "account_security_installed")
        assert "private-initialization-value" not in format_exception_report(caught.value)
        assert create_app(None, database=None).state.account_service is None


def test_origin_missing_every_path(tmp_path: Path) -> None:
    """验证契约：所有非安全方法缺Origin在健康/登录/业务/未知路径均先403，不查身份、不判405、不改数据库。"""
    with api_case(tmp_path, origin=False) as case:
        for path in ("/api/health", "/api/auth/login", "/api/accounts", "/api/missing", "/api"):
            for method in ("POST", "PUT", "PATCH", "DELETE"):
                response = case.client.request(method, path, content=b"invalid-json")
                assert response.status_code == 403
        assert case.clock.calls == 0


def test_anonymous_write_with_origin(tmp_path: Path) -> None:
    """验证契约：正确Origin的匿名业务写请求返回401；Origin错误则403优先，不能先报业务路由404/405。"""
    with api_case(tmp_path) as case:
        for path in ("/api/accounts", "/api/missing"):
            assert case.client.post(path, content=b"invalid-json").status_code == 401
            assert (
                case.client.post(
                    path, headers={"Origin": "http://attacker.test"}, content=b"invalid-json"
                ).status_code
                == 403
            )


def test_fallback_login_method(tmp_path: Path) -> None:
    """验证契约：公开登录路径错误方法通过Origin检查后405/Allow；不执行登录或哈希，缺Origin的写方法仍403。"""
    with api_case(tmp_path) as case:
        for method in ("GET", "PUT", "DELETE"):
            response = case.client.request(method, "/api/auth/login")
            assert response.status_code == 405 and response.headers["allow"] == "POST"
        assert case.clock.calls == 0
        case.client.headers.pop("origin")
        assert case.client.put("/api/auth/login").status_code == 403


def test_forced_before_routing(tmp_path: Path) -> None:
    """验证契约：有效但必须改密的账号访问未知业务路径或错误方法先403，完成改密后先检查角色；成员访问管理员路径403，权限通过才404/405。"""
    with api_case(tmp_path) as case:
        grant = add_actor(case, ready=False)
        cookie = {"Cookie": "rdp_session=" + grant.token.get_secret_value()}
        for method, path in [
            ("GET", "/api/missing"),
            ("PUT", "/api/accounts"),
            ("PUT", "/api/auth/me"),
        ]:
            assert case.client.request(method, path, headers=cookie).status_code == 403


def test_error_boundary_clear_cookie() -> None:
    """验证契约：ErrorBoundary在尚未发送响应的401出口清除相同name/path属性的cookie，与handle_error一致；已开始响应不重发头。"""
    status, headers, payload = boundary_response(problem(AuthenticationError, "请先登录"))
    assert status == 401 and payload["status"] == 401
    assert "rdp_session=" in headers["set-cookie"] and "Max-Age=0" in headers["set-cookie"]
    assert "Path=/" in headers["set-cookie"] and "HttpOnly" in headers["set-cookie"]


def test_authentication_secrets_all_routes(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """验证契约：非账号业务/错误详情/未知路径在认证阶段抛含密码、令牌、cookie的异常，两个出口都脱敏，异常/诊断/日志/报错表均无原文。"""
    with api_case(tmp_path) as case:
        assert case.login().status_code == 200
        secrets = [
            EXAMPLE_SECRET.get_secret_value(),
            case.client.cookies["rdp_session"],
            "rdp_session=private-cookie",
        ]

        def invalid_clock() -> datetime:
            raise RuntimeError(" ".join(secrets))

        case.app.state.accounts_clock = invalid_clock
        for path in ("/api/accounts", "/api/errors/1", "/api/unknown", "/api/auth/me"):
            caplog.clear()
            response = case.client.get(path)
            assert response.status_code == 500
            with session_scope(case.engine, read_only=True) as session:
                record = find_error(session, response.json()["error_id"])
            assert record is not None
            for secret in secrets:
                assert (
                    secret not in response.text
                    and secret not in caplog.text
                    and secret not in record.report
                )
            assert (
                len(
                    [
                        r
                        for r in caplog.records
                        if r.name == "rdp.api.errors" and r.levelname == "ERROR"
                    ]
                )
                == 1
            )


def test_authentication_phase_marker(tmp_path: Path) -> None:
    """验证契约：读取cookie前设置安全阶段标记；认证失败保留供脱敏，成功清除后非账号业务仍按第4张完整报告契约。"""
    with api_case(tmp_path) as case:
        request = request_for(case.app, path="/api/unknown")
        with pytest.raises(AuthenticationError):
            enforce_api_access(request)
        assert request.state.account_auth_phase is True
        grant = case.service.login(
            Credentials("admin", EXAMPLE_SECRET), now=NOW, audit=AUDIT_CONTEXT
        )
        request = request_for(
            case.app,
            path="/api/unknown",
            headers=[(b"cookie", ("rdp_session=" + grant.token.get_secret_value()).encode())],
        )
        enforce_api_access(request)
        assert request.state.account_auth_phase is False

        def failing() -> None:
            raise RuntimeError("nonaccount-public-diagnostic")

        case.app.add_api_route("/api/business", failing, methods=["GET"])
        case.app.router.routes.insert(0, case.app.router.routes.pop())
        response = case.client.get(
            "/api/business", headers={"Cookie": "rdp_session=" + grant.token.get_secret_value()}
        )
        assert response.status_code == 500
        with session_scope(case.engine, read_only=True) as session:
            report = find_error(session, response.json()["error_id"])
        assert report is not None and "nonaccount-public-diagnostic" in report.report


def test_administrator_self_changes(tmp_path: Path) -> None:
    """验证契约：有其他启用管理员时管理员停用/删除/降级自己成功，带当前cookie的下一次请求401并清cookie。"""
    for operation in ("role", "status", "delete"):
        with api_case(tmp_path / operation) as case:
            add_actor(case, role=Role.ADMINISTRATOR)
            assert case.login().status_code == 200
            if operation == "delete":
                response = case.client.delete("/api/accounts/1")
                assert response.status_code == 204
            else:
                value = "member" if operation == "role" else "disabled"
                response = case.client.patch(
                    "/api/accounts/1/" + operation, json={operation: value}
                )
                assert response.status_code == 200
            expired = case.client.get("/api/auth/me")
            assert expired.status_code == 401 and "Max-Age=0" in expired.headers["set-cookie"]


def test_argon2_capacity_response(tmp_path: Path) -> None:
    """验证契约：登录/本人改密/管理员建号及重置的Argon2容量超时返回502安全problem，不给G2的429或Retry-After，不计失败。"""
    for operation in ("login", "own", "create", "reset"):
        with api_case(tmp_path / operation) as case:
            assert case.login().status_code == 200
            hasher = HeldHasher()
            codec = PasswordCodec(hasher)
            hasher.hold.set()
            pool = ThreadPoolExecutor(max_workers=2)
            workers: list[Future[str]] = []
            try:
                for _ in range(2):
                    workers.append(pool.submit(codec.hash, EXAMPLE_SECRET))
                assert hasher.wait_entered(2)
                if operation == "login":
                    response = case.login()
                elif operation == "own":
                    response = case.client.post(
                        "/api/auth/password",
                        json={
                            "current_password": EXAMPLE_SECRET.get_secret_value(),
                            "new_password": "replacement-credential",
                        },
                    )
                elif operation == "create":
                    response = case.client.post(
                        "/api/accounts",
                        json={
                            "login_name": "member",
                            "display_name": "成员",
                            "role": "member",
                            "password": EXAMPLE_SECRET.get_secret_value(),
                        },
                    )
                else:
                    response = case.client.post(
                        "/api/accounts/1/password", json={"password": "replacement-credential"}
                    )
                assert response.status_code == 502 and "retry-after" not in response.headers
                assert response.json()["category"] == "external"
            finally:
                close_workers(pool, hasher)
            for worker in workers:
                assert worker.result(timeout=1)
            with session_scope(case.engine, read_only=True) as session:
                row = session.get(AccountRow, 1)
                assert row is not None and row.failed_attempts == 0
            assert case.client.get("/api/auth/me").status_code == 200


def test_cookie_no_touch_no_renewal(tmp_path: Path) -> None:
    """验证契约：未到60秒、刷新BUSY或已被其他请求刷新的普通响应均无Set-Cookie续期；只有本次刷新提交才可续期。"""
    with api_case(tmp_path) as case:
        assert case.login().status_code == 200
        raw = case.client.cookies["rdp_session"]
        assert "set-cookie" not in case.client.get("/api/auth/me").headers
        case.clock.value += timedelta(seconds=60)
        with case.engine.connect() as blocker:
            blocker.begin()
            try:
                response = case.client.get("/api/auth/me")
                assert response.status_code == 200 and "set-cookie" not in response.headers
            finally:
                blocker.rollback()
        other = case.service.authenticate(SecretStr(raw), now=case.clock.value, audit=AUDIT_CONTEXT)
        assert other.activity_refreshed
        assert "set-cookie" not in case.client.get("/api/auth/me").headers


def test_renewal_committed_only(tmp_path: Path) -> None:
    """验证契约：活动刷新回滚/提交失败不续cookie；刷新已提交也不能覆盖登出、换密的新cookie或401清除。"""
    with api_case(tmp_path) as case:
        assert case.login().status_code == 200
        case.clock.value += timedelta(seconds=60)

        def fail_commit(connection: Connection) -> None:
            raise sqlite3.OperationalError("测试刷新提交失败")

        event.listen(case.engine, "commit", fail_commit)
        try:
            response = case.client.get("/api/auth/me")
            assert response.status_code == 500 and "set-cookie" not in response.headers
        finally:
            event.remove(case.engine, "commit", fail_commit)
        old = case.client.cookies["rdp_session"]
        response = case.client.post(
            "/api/auth/password",
            json={
                "current_password": EXAMPLE_SECRET.get_secret_value(),
                "new_password": "replacement-value",
            },
        )
        assert response.status_code == 200 and case.client.cookies["rdp_session"] != old
        assert len(response.headers.get_list("set-cookie")) == 1
        case.clock.value += timedelta(seconds=60)
        response = case.client.post("/api/auth/logout")
        assert response.status_code == 204 and "Max-Age=0" in response.headers["set-cookie"]
        assert len(response.headers.get_list("set-cookie")) == 1


def test_documentation_routes_disabled(tmp_path: Path) -> None:
    """验证契约：有无数据库和静态目录时都不注册FastAPI文档或schema路由；API-only下三个URL均404，离线导出仍与app.openapi一致。"""
    web = tmp_path / "web"
    web.mkdir()
    (web / "index.html").write_text("<html>测试页面</html>")
    for root in (None, web):
        app = create_app(root, database=None)
        paths = {route.path for route in iter_route_contexts(app.routes)}
        assert not paths & {"/docs", "/redoc", "/openapi.json"}
        assert app.openapi()["paths"]["/api/health"]
        if root is None:
            with TestClient(app) as raw_client:
                client = cast(Client, raw_client)
                for path in ("/docs", "/redoc", "/openapi.json"):
                    assert client.get(path).status_code == 404
    with api_case(tmp_path / "database") as case:
        assert not {route.path for route in iter_route_contexts(case.app.routes)} & {
            "/docs",
            "/redoc",
            "/openapi.json",
        }


def test_admin_dependency_declared() -> None:
    """验证契约：所有管理员操作声明get_admin_context，只有Request/cookie依赖而无待校验body/path/query参数；错误详情不要求管理员。"""
    app = create_app(None, database=None)
    for route in iter_route_contexts(app.routes):
        if route.path is not None and route.path.startswith("/api/accounts"):
            assert any(
                dependency.call is get_admin_context for dependency in route.dependant.dependencies
            )
        if route.path == "/api/errors/{error_id}":
            assert all(
                dependency.call is not get_admin_context
                for dependency in route.dependant.dependencies
            )


def test_member_bad_body_precedes_validation(tmp_path: Path) -> None:
    """验证契约：成员以正确Origin和合法POST/PATCH方法调用管理员接口，缺字段/错误字段/额外字段/坏JSON均先403而非422，未解析或回显body。"""
    with api_case(tmp_path) as case:
        grant = add_actor(case)
        cookie = {"Cookie": "rdp_session=" + grant.token.get_secret_value()}
        for method, path in [
            ("POST", "/api/accounts"),
            ("PATCH", "/api/accounts/1/role"),
            ("POST", "/api/accounts/1/password"),
        ]:
            for content in (b"{}", b'{"role":"wrong"}', b'{"extra":"secret"}', b"{"):
                response = case.client.request(method, path, headers=cookie, content=content)
                assert response.status_code == 403
                assert "secret" not in response.text


def test_member_bad_method_precedes_routing(tmp_path: Path) -> None:
    """验证契约：成员带正确Origin以PUT/api/accounts或错误方法访问管理员模板先403；管理员同请求才405且有Allow。"""
    with api_case(tmp_path) as case:
        grant = add_actor(case)
        cookie = {"Cookie": "rdp_session=" + grant.token.get_secret_value()}
        for path in ("/api/accounts", "/api/accounts/1/role"):
            assert case.client.put(path, headers=cookie).status_code == 403
        assert case.login().status_code == 200
        for path in ("/api/accounts", "/api/accounts/1/role"):
            response = case.client.put(path)
            assert response.status_code == 405 and response.headers["allow"]


def test_member_invalid_target_precedes_validation(tmp_path: Path) -> None:
    """验证契约：成员访问/api/accounts/非法编号/role先403，不先422；管理员以合法方法和正确Origin才得到参数422。"""
    with api_case(tmp_path) as case:
        grant = add_actor(case)
        path = "/api/accounts/not-an-id/role"
        assert (
            case.client.patch(
                path,
                headers={"Cookie": "rdp_session=" + grant.token.get_secret_value()},
                json={"role": "member"},
            ).status_code
            == 403
        )
        assert case.login().status_code == 200
        assert case.client.patch(path, json={"role": "member"}).status_code == 422


def test_access_order_all_stages(tmp_path: Path) -> None:
    """验证契约：按Origin、白名单、认证、强制改密、角色、路由、参数顺序；缺Origin403优先、匿名业务401优先、强制改密403先于角色路由。"""
    with api_case(tmp_path) as case:
        assert (
            case.client.put("/api/accounts", headers={"Origin": "null"}, content=b"{").status_code
            == 403
        )
        assert case.client.put("/api/accounts", content=b"{").status_code == 401
        member = add_actor(case, ready=False)
        cookie = {"Cookie": "rdp_session=" + member.token.get_secret_value()}
        assert case.client.put("/api/accounts", headers=cookie, content=b"{").status_code == 403
        assert case.login().status_code == 200
        assert case.client.put("/api/accounts", content=b"{").status_code == 405
        assert case.client.post("/api/accounts", content=b"{").status_code == 422


def test_admin_context_cached(tmp_path: Path) -> None:
    """验证契约：get_admin_context复用同请求已验证身份和时刻，不重复触摸；角色检查后领域写事务仍重新核验权限。"""
    with api_case(tmp_path) as case:
        grant = case.service.login(
            Credentials("admin", EXAMPLE_SECRET), now=NOW, audit=AUDIT_CONTEXT
        )
        request = request_for(
            case.app,
            path="/api/accounts",
            headers=[(b"cookie", ("rdp_session=" + grant.token.get_secret_value()).encode())],
        )
        first = get_admin_context(request, None)
        assert first is get_admin_context(request, None)
        assert first.identity is not None
        assert first.identity.account.role is Role.ADMINISTRATOR
        assert case.clock.calls == 1


def test_get_account_now_valid() -> None:
    """验证契约：get_account_now将合法带偏移时刻规范成UTC且同请求只调用一次，默认UTC墙钟、有效回拨不视为错误。"""
    app = FastAPI()
    calls: list[int] = []

    def clock() -> datetime:
        calls.append(1)
        return NOW.astimezone(timezone(timedelta(hours=-6)))

    app.state.accounts_clock = clock
    request = request_for(app)
    assert get_account_now(request) == NOW and get_account_now(request).tzinfo is UTC
    assert calls == [1]
    app.state.accounts_clock = lambda: NOW - timedelta(days=2)
    assert get_account_now(request_for(app)) == NOW - timedelta(days=2)
    app.state.accounts_clock = None
    assert get_account_now(request_for(app)).tzinfo is UTC


def test_get_account_now_invalid() -> None:
    """验证契约：时钟返回非datetime、naive、无偏移、UTC换算或LOGIN_WAIT加时溢出均DefectError500，不是422，返回值不出现在报告。"""
    for value in (
        "private-clock-value",
        None,
        NOW.replace(tzinfo=None),
        datetime.max.replace(tzinfo=UTC),
    ):
        app = FastAPI()
        app.state.accounts_clock = lambda value=value: value
        request = request_for(app)
        with pytest.raises(DefectError) as caught:
            get_account_now(request)
        assert "private-clock-value" not in format_exception_report(caught.value)
        assert not hasattr(request.state, "account_now")


def test_get_account_now_callback_failure() -> None:
    """验证契约：时钟回调抛Exception转换安全DefectError且不缓存失败值；取消控制流不吞掉，不执行数据库或哈希。"""
    app = FastAPI()

    def broken() -> datetime:
        raise ValueError("clock-secret")

    app.state.accounts_clock = broken
    request = request_for(app)
    with pytest.raises(DefectError) as caught:
        get_account_now(request)
    assert "clock-secret" not in format_exception_report(caught.value)
    assert not hasattr(request.state, "account_now")

    def interrupted() -> datetime:
        raise KeyboardInterrupt()

    app.state.accounts_clock = interrupted
    with pytest.raises(KeyboardInterrupt):
        get_account_now(request)


def test_clock_errors_not_user_errors(tmp_path: Path) -> None:
    """验证契约：入口只将非法服务端时钟归500，不把用户密码长度/角色/编号错误转500；这些字段仍422，旧密码错误仍400。"""
    with api_case(tmp_path) as case:
        assert case.login().status_code == 200
        case.app.state.accounts_clock = lambda: "private-invalid-clock"
        response = case.client.get("/api/auth/me")
        assert response.status_code == 500 and "private-invalid-clock" not in response.text
        case.app.state.accounts_clock = case.clock
        assert case.client.post("/api/accounts", json={}).status_code == 422
        assert (
            case.client.patch("/api/accounts/1/role", json={"role": "invalid"}).status_code == 422
        )
        assert case.client.delete("/api/accounts/01").status_code == 422


def test_password_mismatch_response(tmp_path: Path) -> None:
    """验证契约：当前密码错误返回400 problem及当前密码不正确诊断，不发送清cookie头，G2第5次429；真实会话失效401仍清cookie。"""
    with api_case(tmp_path) as case:
        assert case.login().status_code == 200
        response = case.client.post(
            "/api/auth/password",
            json={"current_password": "incorrect-value", "new_password": "replacement-value"},
        )
        assert response.status_code == 400 and response.headers["content-type"].startswith(
            "application/problem+json"
        )
        assert "当前密码不正确" in response.text and "set-cookie" not in response.headers
        case.client.cookies.clear()
        response = case.client.post("/api/auth/password", json={})
        assert response.status_code == 401 and "Max-Age=0" in response.headers["set-cookie"]


def test_credential_conflict_response(tmp_path: Path) -> None:
    """验证契约：哈希或非等待G2竞争变化返回409提示账号状态已变化请重试，不清cookie、不自动重试、不计G2；已在等待429。"""
    with api_case(tmp_path) as case:
        assert case.login().status_code == 200
        replacement = PasswordHasher(time_cost=1, memory_cost=1024, parallelism=1).hash(
            "another-credential"
        )

        def race() -> None:
            with session_scope(case.engine) as session:
                row = session.get(AccountRow, 1)
                assert row is not None
                row.password_hash = replacement

        case.service.passwords = PasswordCodec(CallbackHasher(race))
        response = case.client.post(
            "/api/auth/password",
            json={
                "current_password": EXAMPLE_SECRET.get_secret_value(),
                "new_password": "replacement-credential",
            },
        )
        assert response.status_code == 409 and "账号状态已变化" in response.text
        assert "set-cookie" not in response.headers and "retry-after" not in response.headers
        with session_scope(case.engine, read_only=True) as session:
            row = session.get(AccountRow, 1)
            assert row is not None and row.failed_attempts == 0 and row.password_hash == replacement
        assert case.client.get("/api/auth/me").status_code == 200


def test_short_touch_timeout(tmp_path: Path) -> None:
    """验证契约：身份刷新只在独立连接将BEGIN忙等待改为100毫秒；拿不到锁本请求照常通过且不续cookie，后续普通事务仍5000毫秒。"""
    with api_case(tmp_path) as case:
        assert case.login().status_code == 200
        case.clock.value += timedelta(seconds=60)
        with case.engine.connect() as blocker:
            blocker.begin()
            try:
                started = time.monotonic()
                response = case.client.get("/api/auth/me")
                elapsed = time.monotonic() - started
                assert response.status_code == 200 and "set-cookie" not in response.headers
                assert elapsed < 2
            finally:
                blocker.rollback()
        response = case.client.get("/api/auth/me")
        assert response.status_code == 200 and "Max-Age=604800" in response.headers["set-cookie"]
        with session_scope(case.engine, read_only=True) as session:
            assert session.connection().exec_driver_sql("PRAGMA busy_timeout").scalar_one() == 5000


def test_admin_included_router_classification(tmp_path: Path) -> None:
    """验证契约：权限分类用iter_route_contexts展开嵌套include_router及前缀，后注册管理员路由也不能漏掉403优先检查。"""
    with api_case(tmp_path) as case:
        member = add_actor(case)
        inner = APIRouter()

        def endpoint(context: Annotated[object, Depends(get_admin_context)]) -> dict[str, bool]:
            return {"ok": True}

        inner.add_api_route("/item/{key}", endpoint, methods=["POST"])
        outer = APIRouter(prefix="/api/late")
        outer.include_router(inner, prefix="/nested")
        case.app.include_router(outer)
        cookie = {"Cookie": "rdp_session=" + member.token.get_secret_value()}
        response = case.client.put("/api/late/nested/item/bad", headers=cookie, content=b"{")
        assert response.status_code == 403
        assert case.login().status_code == 200
        response = case.client.put("/api/late/nested/item/bad")
        assert response.status_code == 405 and response.headers["allow"] == "POST"
