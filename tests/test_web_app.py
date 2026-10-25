"""工单 02 的公开边界回归测试，只使用临时目录与受控的外部依赖替身。"""

import asyncio
import logging
from collections.abc import Awaitable, Callable, MutableMapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch
from uuid import UUID

import pytest
from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.responses import RedirectResponse, StreamingResponse
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient, Client, Response
from pydantic import ValidationError

from rdp.api import RequestIdMiddleware, create_app
from rdp.api.health import HealthResponse
from rdp.infra.logging import (
    LoggingSettings,
    LogTime,
    configure_logging,
    job_id_context,
    log_context,
    request_id_context,
)


def _request(app: FastAPI, path: str, method: str = "GET") -> Response:
    """用真实 TestClient 观察 HTTP 边界；类型桥接只适配 Starlette 的 httpx 回退。"""
    with TestClient(app) as client:
        return cast(Client, client).request(method, path)


def test_health_response() -> None:
    """使用 TestClient 验证 /api/health 返回 200 和固定 ok JSON。"""
    response = _request(create_app(None, database=None), "/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert response.headers["content-type"] == "application/json"


def test_health_openapi(tmp_path: Path) -> None:
    """验证关闭在线文档后，离线 OpenAPI 仍包含健康响应模型且仅允许 ok。"""
    app = create_app(None, database=None)
    assert app.docs_url is None and app.redoc_url is None and app.openapi_url is None
    schema = app.openapi()
    health = schema["paths"]["/api/health"]["get"]["responses"]["200"]
    assert health["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/HealthResponse"
    }
    assert (
        schema["components"]["schemas"]["HealthResponse"]["properties"]["status"]["const"] == "ok"
    )
    with pytest.raises(ValidationError):
        HealthResponse.model_validate({"status": "failed"})


def test_api_only_root(tmp_path: Path) -> None:
    """使用 TestClient 验证 web_dist=None 时首页返回 404。"""
    response = _request(create_app(None, database=None), "/")
    assert response.status_code == 404
    assert response.json() == {"detail": "Not Found"}


def test_spa_root(tmp_path: Path) -> None:
    """使用 TestClient 验证 tmp_path 构建目录首页返回 index.html。"""
    (tmp_path / "index.html").write_text("<main>平台首页</main>", encoding="utf-8")
    response = _request(create_app(tmp_path, database=None), "/")
    assert response.status_code == 200
    assert response.text == "<main>平台首页</main>"
    assert response.headers["content-type"].startswith("text/html")


def test_spa_nested_route(tmp_path: Path) -> None:
    """使用 TestClient 验证不存在的嵌套路由 GET 返回 index.html。"""
    (tmp_path / "index.html").write_text("<main>前端路由入口</main>", encoding="utf-8")
    response = _request(create_app(tmp_path, database=None), "/datasets/x")
    assert response.status_code == 200
    assert response.text == "<main>前端路由入口</main>"


def test_static_file(tmp_path: Path) -> None:
    """使用 TestClient 验证 tmp_path 中静态文件原样返回。"""
    (tmp_path / "index.html").write_text("首页", encoding="utf-8")
    expected = b"console.log('static asset');\n"
    (tmp_path / "app.js").write_bytes(expected)
    response = _request(create_app(tmp_path, database=None), "/app.js")
    assert response.status_code == 200
    assert response.content == expected
    assert "javascript" in response.headers["content-type"]


def test_unknown_api(tmp_path: Path) -> None:
    """使用 TestClient 验证 /api 和未知 /api/ 路径是 404 JSON，不回退 HTML。"""
    (tmp_path / "index.html").write_text("不能返回的首页", encoding="utf-8")
    (tmp_path / "api").mkdir()
    (tmp_path / "api" / "asset.txt").write_text("不能作为 API 返回", encoding="utf-8")
    for directory in (None, tmp_path):
        app = create_app(directory, database=None)
        for path in ("/api", "/api/不存在", "/api/asset.txt"):
            response = _request(app, path)
            assert response.status_code == 404
            assert response.json() == {"detail": "Not Found"}


def test_api_404_preserves_detail(tmp_path: Path) -> None:
    """验证 API 404 契约：接口抛出的业务 detail 和响应头原样保留，不回退为首页。"""
    (tmp_path / "index.html").write_text("不能返回的首页", encoding="utf-8")
    app = create_app(tmp_path, database=None)

    def missing_record() -> None:
        """通过真实接口抛出带业务上下文的 404。"""
        raise HTTPException(
            status_code=404,
            detail={"reason": "记录不存在", "record_id": "missing"},
            headers={"X-Error-Source": "record"},
        )

    app.add_api_route("/api/missing-record", missing_record, methods=["GET"])
    # 后加的测试接口须排在兜底路由与静态挂载之前，确保请求真正进入抛错接口。
    app.router.routes.insert(0, app.router.routes.pop())
    response = _request(app, "/api/missing-record")
    assert response.status_code == 404
    assert response.json() == {"detail": {"reason": "记录不存在", "record_id": "missing"}}
    assert response.headers["content-type"] == "application/json"
    assert response.headers["X-Error-Source"] == "record"


def test_non_get_no_fallback(tmp_path: Path) -> None:
    """使用 TestClient 验证非 GET 请求不使用 SPA 回退。"""
    (tmp_path / "index.html").write_text("首页", encoding="utf-8")
    app = create_app(tmp_path, database=None)
    for method in ("POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"):
        response = _request(app, "/datasets/x", method)
        assert response.status_code in (404, 405)
        assert response.content != "首页".encode()


def test_static_boundary(tmp_path: Path) -> None:
    """使用 TestClient 验证路径穿越及越界软链接不能读取构建目录外文件。"""
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("安全首页", encoding="utf-8")
    secret = tmp_path / "secret.txt"
    secret.write_text("目录外内容不可读取", encoding="utf-8")
    (dist / "escape.txt").symlink_to(secret)
    app = create_app(dist, database=None)
    for path in ("/%2e%2e/secret.txt", "/escape.txt"):
        response = _request(app, path)
        assert "目录外内容不可读取" not in response.text
        assert response.status_code in (200, 404)
    assert secret.read_text(encoding="utf-8") == "目录外内容不可读取"


def test_missing_dist(tmp_path: Path) -> None:
    """验证不存在的构建目录在 create_app 调用时抛 FileNotFoundError。"""
    with pytest.raises(FileNotFoundError):
        create_app(tmp_path / "missing", database=None)


def test_dist_is_file(tmp_path: Path) -> None:
    """验证构建路径是普通文件时在创建阶段抛 NotADirectoryError。"""
    target = tmp_path / "dist"
    target.write_text("不是目录", encoding="utf-8")
    with pytest.raises(NotADirectoryError):
        create_app(target, database=None)


def test_missing_index(tmp_path: Path) -> None:
    """验证缺少 index.html 时在创建阶段抛 FileNotFoundError。"""
    with pytest.raises(FileNotFoundError):
        create_app(tmp_path, database=None)


def test_index_is_directory(tmp_path: Path) -> None:
    """验证 index.html 是目录时在创建阶段抛 ValueError。"""
    (tmp_path / "index.html").mkdir()
    with pytest.raises(ValueError, match="index.html"):
        create_app(tmp_path, database=None)


def test_index_symlink_outside(tmp_path: Path) -> None:
    """验证 index.html 软链接指向构建目录外时创建应用抛 ValueError。"""
    dist = tmp_path / "dist"
    dist.mkdir()
    outside = tmp_path / "outside.html"
    outside.write_text("外部页面", encoding="utf-8")
    (dist / "index.html").symlink_to(outside)
    with pytest.raises(ValueError, match="index.html"):
        create_app(dist, database=None)


def test_dist_permission_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """验证构建目录状态读取失败时保留 OSError，不伪装为缺失。"""
    original_stat = Path.stat

    def denied(path: Path, *, follow_symlinks: bool = True):
        """只在文件系统边界模拟权限失败，避免依赖测试执行账号的权限。"""
        if path == tmp_path:
            raise PermissionError("构建目录不可读")
        return original_stat(path, follow_symlinks=follow_symlinks)

    monkeypatch.setattr(Path, "stat", denied)
    with pytest.raises(PermissionError, match="构建目录不可读"):
        create_app(tmp_path, database=None)


def test_relative_dist(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """验证相对构建路径以创建时工作目录解释。"""
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("创建时的页面", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    app = create_app(Path("dist"), database=None)
    monkeypatch.chdir(dist)
    response = _request(app, "/")
    assert response.status_code == 200
    assert response.text == "创建时的页面"


def test_independent_apps(tmp_path: Path) -> None:
    """验证多个应用的托管目录相互独立且创建不写文件或建立 socket。"""
    first = tmp_path / "first"
    second = tmp_path / "second"
    for directory, text in ((first, "第一份"), (second, "第二份")):
        directory.mkdir()
        (directory / "index.html").write_text(text, encoding="utf-8")
    before = {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    # 只在创建阶段拦截系统边界；TestClient 本身的本地线程通信不属于应用创建。
    with patch("socket.socket", side_effect=AssertionError("创建应用不得建立 socket")):
        first_app = create_app(first, database=None)
        second_app = create_app(second, database=None)
    assert _request(first_app, "/").text == "第一份"
    assert _request(second_app, "/").text == "第二份"
    assert {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()} == before


def test_api_namespace_all_methods(tmp_path: Path) -> None:
    """验证 API 命名空间契约：非 GET 也不能读取同名静态文件，未知接口返回 JSON 404。"""
    (tmp_path / "index.html").write_text("首页", encoding="utf-8")
    (tmp_path / "api").mkdir()
    (tmp_path / "api" / "asset.txt").write_text("静态内容", encoding="utf-8")
    app = create_app(tmp_path, database=None)
    for method in ("HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "TRACE"):
        for path in ("/api", "/api/不存在", "/api/asset.txt"):
            response = _request(app, path, method)
            assert response.status_code == 404
            assert response.headers["content-type"] == "application/json"
            if method != "HEAD":
                assert response.json() == {"detail": "Not Found"}


def test_custom_404_does_not_override_spa(tmp_path: Path) -> None:
    """验证 SPA 回退契约：构建目录自带 404.html 也不能代替首页处理前端路由。"""
    (tmp_path / "index.html").write_text("首页路由入口", encoding="utf-8")
    (tmp_path / "404.html").write_text("不能回退到这里", encoding="utf-8")
    response = _request(create_app(tmp_path, database=None), "/datasets/x")
    assert response.status_code == 200
    assert response.text == "首页路由入口"


def test_request_middleware_construction(tmp_path: Path) -> None:
    """验证工单 03 契约：RequestIdMiddleware.__init__：只保存下游应用，不调用它、不绑定编号、不保存请求级状态。"""

    async def downstream(
        scope: MutableMapping[str, Any],
        receive: Callable[[], Awaitable[MutableMapping[str, Any]]],
        send: Callable[[MutableMapping[str, Any]], Awaitable[None]],
    ) -> None:
        """构造阶段不可调用 ASGI 应用。"""
        raise AssertionError("不得调用下游")

    before = request_id_context.get()
    first = RequestIdMiddleware(downstream)
    second = RequestIdMiddleware(downstream)
    assert first is not second
    assert request_id_context.get() == before


def test_response_request_id(tmp_path: Path) -> None:
    """验证工单 03 契约：验收 7：TestClient 请求 /api/health，两次响应均带唯一合法 uuid4.hex 编号且互不相同。"""
    app = create_app(None, database=None)
    first = _request(app, "/api/health").headers["X-Request-ID"]
    second = _request(app, "/api/health").headers["X-Request-ID"]
    assert first != second
    for value in (first, second):
        parsed = UUID(value)
        assert parsed.version == 4 and parsed.hex == value and len(value) == 32
    assert request_id_context.get() is None


def test_client_request_id_ignored(tmp_path: Path) -> None:
    """验证工单 03 契约：RequestIdMiddleware：客户端合法、非法或重复 X-Request-ID 均忽略，响应使用服务端新编号。"""
    app = create_app(None, database=None)
    for headers in (
        {"X-Request-ID": "bad"},
        {"X-Request-ID": "123456789abc4def8123456789abcdef"},
        [("X-Request-ID", "first"), ("X-Request-ID", "second")],
    ):
        with TestClient(app) as client:
            response = cast(Client, client).get("/api/health", headers=headers)
        value = response.headers["X-Request-ID"]
        assert UUID(value).version == 4
        assert value not in ("bad", "123456789abc4def8123456789abcdef", "first", "second")


def test_response_and_log_id_match(tmp_path: Path) -> None:
    """验证工单 03 契约：验收 7：测试路由在请求内写业务日志，日志 request_id 与响应头逐字相同；中间件不自动造访问日志。"""
    moment = datetime(2026, 10, 21, 8, tzinfo=UTC)
    configure_logging(
        LoggingSettings("web", tmp_path), time_source=LogTime(lambda: moment, lambda: UTC)
    )
    app = create_app(None, database=None)

    async def business() -> dict[str, str]:
        """只在测试中提供会写业务日志的接口，不为演示增加访问日志。"""
        logging.getLogger("rdp.test.business").info("业务完成")
        return {"status": "ok"}

    app.add_api_route("/api/business", business)
    app.router.routes.insert(0, app.router.routes.pop())
    response = _request(app, "/api/business")
    assert response.status_code == 200
    text = (tmp_path / "web.log").read_text(encoding="utf-8")
    assert f"request_id={response.headers['X-Request-ID']}" in text
    assert "INFO rdp.test.business 业务完成" in text


def test_concurrent_request_ids(tmp_path: Path) -> None:
    """验证工单 03 契约：验收 4：交错两个并发请求，中间阻塞点前后业务日志与各自响应编号一致，退出不污染其他请求。"""
    moment = datetime(2026, 10, 21, 8, tzinfo=UTC)
    configure_logging(
        LoggingSettings("web", tmp_path), time_source=LogTime(lambda: moment, lambda: UTC)
    )
    business_logger = logging.getLogger("rdp.test.concurrent")

    async def scenario() -> None:
        """交错两个真实 ASGI 请求，验证绑定跨 await 保持独立。"""
        app = create_app(None, database=None)
        events = [asyncio.Event(), asyncio.Event()]
        observed: dict[int, list[str | None]] = {}

        async def business(slot: int) -> dict[str, str]:
            observed[slot] = [request_id_context.get()]
            business_logger.info("并发业务", extra={"fields": {"slot": slot, "stage": "before"}})
            events[slot].set()
            await events[1 - slot].wait()
            observed[slot].append(request_id_context.get())
            business_logger.info("并发业务", extra={"fields": {"slot": slot, "stage": "after"}})
            return {"status": "ok"}

        app.add_api_route("/api/pair/{slot}", business)
        app.router.routes.insert(0, app.router.routes.pop())
        async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
            responses = await asyncio.gather(client.get("/api/pair/0"), client.get("/api/pair/1"))
        ids = [response.headers["X-Request-ID"] for response in responses]
        assert ids[0] != ids[1]
        assert observed == {0: [ids[0], ids[0]], 1: [ids[1], ids[1]]}
        lines = [
            line
            for line in (tmp_path / "web.log").read_text(encoding="utf-8").splitlines()
            if "rdp.test.concurrent 并发业务" in line
        ]
        assert len(lines) == 4
        for slot in (0, 1):
            for stage in ("before", "after"):
                matching = [line for line in lines if f"slot={slot} stage={stage} " in line]
                assert len(matching) == 1
                assert matching[0].endswith(f"request_id={ids[slot]}")
                assert ids[1 - slot] not in matching[0]
        assert request_id_context.get() is None

    asyncio.run(asyncio.wait_for(scenario(), timeout=5))


def test_request_ids_on_all_response_statuses(tmp_path: Path) -> None:
    """验证工单 03 契约：create_app 新契约：API、静态文件、SPA、重定向、404、校验错误及框架 500 响应均带编号。"""
    (tmp_path / "index.html").write_text("首页", encoding="utf-8")
    (tmp_path / "asset.txt").write_text("文件", encoding="utf-8")
    app = create_app(tmp_path, database=None)

    async def redirect() -> RedirectResponse:
        return RedirectResponse("/api/health")

    async def validate(count: int) -> dict[str, int]:
        return {"count": count}

    async def broken() -> None:
        raise RuntimeError("框架 500")

    for path, endpoint in (
        ("/api/redirect", redirect),
        ("/api/validate", validate),
        ("/api/broken", broken),
    ):
        app.add_api_route(path, endpoint)
        app.router.routes.insert(0, app.router.routes.pop())
    with TestClient(app, raise_server_exceptions=False) as client:
        for path, status in (
            ("/api/health", 200),
            ("/asset.txt", 200),
            ("/frontend", 200),
            ("/api/missing", 404),
            ("/api/redirect", 307),
            ("/api/validate?count=bad", 422),
            ("/api/broken", 500),
        ):
            response = cast(Client, client).get(path, follow_redirects=False)
            assert response.status_code == status
            assert UUID(response.headers["X-Request-ID"]).version == 4


def test_response_id_header_replaced(tmp_path: Path) -> None:
    """验证工单 03 契约：RequestIdMiddleware：覆盖下游所有同名响应头只留一个，不修改下游原消息或 scope。"""
    original: _Message = {
        "type": "http.response.start",
        "status": 200,
        "headers": [
            (b"X-Request-ID", b"first"),
            (b"x-request-id", b"second"),
            (b"x-keep", b"keep"),
        ],
    }
    scope: _Message = {"type": "http", "headers": [(b"x-request-id", b"client")]}

    async def app(scope: _Message, receive: _Receive, send: _Send) -> None:
        await send(original)

    messages = asyncio.run(_exchange(RequestIdMiddleware(app), scope))
    headers = messages[0]["headers"]
    ids = [value for key, value in headers if key.lower() == b"x-request-id"]
    assert len(ids) == 1 and UUID(ids[0].decode()).version == 4
    assert (b"x-keep", b"keep") in headers
    assert original["headers"][0] == (b"X-Request-ID", b"first")
    assert scope["headers"] == [(b"x-request-id", b"client")]


def test_health_has_no_access_log(tmp_path: Path) -> None:
    """验证工单 03 契约：验收 7：TestClient 调用健康接口不产生访问日志，uvicorn.access 记录也被日志配置丢弃。"""
    moment = datetime(2026, 10, 21, tzinfo=UTC)
    configure_logging(
        LoggingSettings("web", tmp_path), time_source=LogTime(lambda: moment, lambda: UTC)
    )
    assert _request(create_app(None, database=None), "/api/health").status_code == 200
    logging.getLogger("uvicorn.access").info("GET /api/health 200")
    text = (tmp_path / "web.log").read_text(encoding="utf-8")
    assert "uvicorn.access" not in text
    assert "rdp.api" not in text


def test_request_context_restored_after_failure(tmp_path: Path) -> None:
    """验证工单 03 契约：RequestIdMiddleware Raises：下游、receive、send 的异常原样传播，退出恢复原 request_id 和 job_id。"""

    async def scenario(failure: str) -> None:
        error = RuntimeError("下游失败")

        async def receive() -> _Message:
            raise error

        async def send(message: _Message) -> None:
            raise error

        async def app(scope: _Message, receive: _Receive, send: _Send) -> None:
            assert request_id_context.get() != "123456789abc4def8123456789abcdef"
            if failure == "receive":
                await receive()
            elif failure == "send":
                await send({"type": "http.response.start", "status": 200, "headers": []})
            else:
                raise error

        with log_context(job_id=10, request_id="123456789abc4def8123456789abcdef"):
            with pytest.raises(RuntimeError) as caught:
                await RequestIdMiddleware(app)({"type": "http"}, receive, send)
            assert caught.value is error
            assert request_id_context.get() == "123456789abc4def8123456789abcdef"
            assert job_id_context.get() == 10

    for failure in ("app", "receive", "send"):
        asyncio.run(scenario(failure))


def test_request_context_restored_after_cancel(tmp_path: Path) -> None:
    """验证工单 03 契约：RequestIdMiddleware Raises：请求取消保留取消异常且恢复上下文，不重复记录错误。"""

    async def app(scope: _Message, receive: _Receive, send: _Send) -> None:
        assert request_id_context.get() is not None
        raise asyncio.CancelledError

    async def scenario() -> None:
        with pytest.raises(asyncio.CancelledError):
            await _exchange(RequestIdMiddleware(app), {"type": "http"})
        assert request_id_context.get() is None

    asyncio.run(scenario())


def test_streaming_and_background_context(tmp_path: Path) -> None:
    """验证工单 03 契约：RequestIdMiddleware 时间语义：流式响应与后台任务内日志保留请求编号，整个下游调用完成才恢复。"""
    app = create_app(None, database=None)
    observed: list[str | None] = []

    async def background() -> None:
        observed.append(request_id_context.get())

    async def stream():
        observed.append(request_id_context.get())
        yield b"first"
        observed.append(request_id_context.get())
        yield b"second"

    async def endpoint(tasks: BackgroundTasks) -> StreamingResponse:
        tasks.add_task(background)
        return StreamingResponse(stream())

    app.add_api_route("/api/stream", endpoint)
    app.router.routes.insert(0, app.router.routes.pop())
    response = _request(app, "/api/stream")
    assert response.content == b"firstsecond"
    assert observed == [response.headers["X-Request-ID"]] * 3
    assert request_id_context.get() is None


def test_non_http_scope_passthrough(tmp_path: Path) -> None:
    """验证工单 03 契约：RequestIdMiddleware 返回：WebSocket/lifespan 消息原样透传，不生成编号、不改上下文。"""
    for kind in ("websocket", "lifespan"):
        scope: _Message = {"type": kind}
        response: _Message = {"type": "passthrough"}

        async def app(
            received_scope: _Message,
            receive: _Receive,
            send: _Send,
            expected_scope: _Message = scope,
            expected_response: _Message = response,
        ) -> None:
            assert received_scope is expected_scope
            assert request_id_context.get() is None
            await send(expected_response)

        with patch("rdp.api.uuid4", side_effect=AssertionError("非 HTTP 不生成编号")):
            messages = asyncio.run(_exchange(RequestIdMiddleware(app), scope))
        assert messages == [response] and messages[0] is response


def test_failure_before_response_start(tmp_path: Path) -> None:
    """验证工单 03 契约：RequestIdMiddleware：下游未发送响应即失败时不自造响应，异常原样传播，框架已发出的 500 则带编号。"""
    sent: list[_Message] = []

    async def receive() -> _Message:
        return {"type": "http.request"}

    async def send(message: _Message) -> None:
        sent.append(message)

    async def app(scope: _Message, receive: _Receive, send: _Send) -> None:
        raise RuntimeError("没有响应")

    with pytest.raises(RuntimeError, match="没有响应"):
        asyncio.run(RequestIdMiddleware(app)({"type": "http"}, receive, send))
    assert sent == [] and request_id_context.get() is None


def test_request_wrapper_outside_error_stack(tmp_path: Path) -> None:
    """验证工单 03 契约：_RequestContextApp.build_middleware_stack 返回：包装完整父类栈，框架 500 在上下文内且不改变路由/OpenAPI。"""
    app = create_app(None, database=None)
    assert isinstance(app.build_middleware_stack(), RequestIdMiddleware)
    assert request_id_context.get() is None
    response = _request(app, "/api/health")
    assert response.status_code == 200
    assert "/api/health" in app.openapi()["paths"]
    assert "X-Request-ID" in response.headers


def test_app_does_not_configure_logging(tmp_path: Path) -> None:
    """验证工单 03 契约：create_app 副作用：创建多个应用不安装全局 handler、不写日志文件；请求关联中间件实例互相独立。"""
    before = (logging.getLogger().handlers[:], logging.getLogger().level, logging.raiseExceptions)
    first = create_app(None, database=None)
    second = create_app(None, database=None)
    assert first is not second
    assert (
        logging.getLogger().handlers,
        logging.getLogger().level,
        logging.raiseExceptions,
    ) == before
    assert not list(tmp_path.iterdir())
    assert (
        _request(first, "/api/health").headers["X-Request-ID"]
        != _request(second, "/api/health").headers["X-Request-ID"]
    )


# ASGI 是此票已批准的中间件边界；不直接依赖 Starlette 的私有类型。
type _Message = MutableMapping[str, Any]
type _Receive = Callable[[], Awaitable[_Message]]
type _Send = Callable[[_Message], Awaitable[None]]
type _Application = Callable[[_Message, _Receive, _Send], Awaitable[None]]


async def _exchange(app: _Application, scope: _Message) -> list[_Message]:
    """在进程内驱动 ASGI 边界，收集实际发送的消息，不创建网络连接。"""
    messages: list[_Message] = []

    async def receive() -> _Message:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: _Message) -> None:
        messages.append(message)

    await app(scope, receive, send)
    return messages
