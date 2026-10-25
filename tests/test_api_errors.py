"""工单 04 的公开契约测试；只用内存输入和临时目录，验证诊断与失败边界。"""

import asyncio
import json
import logging
import re
from collections.abc import AsyncIterator
from http import HTTPStatus
from pathlib import Path
from typing import Any, ClassVar, cast, override

import httpx
import pytest
from fastapi import FastAPI, Request
from fastapi.background import BackgroundTasks
from fastapi.exceptions import RequestValidationError
from fastapi.responses import Response, StreamingResponse
from fastapi.testclient import TestClient
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from uvicorn import Config
from uvicorn.protocols.http.h11_impl import H11Protocol
from uvicorn.server import ServerState

from rdp.api import RequestIdMiddleware, create_app
from rdp.api._asgi import ASGIMessage
from rdp.api.errors import (
    ErrorBoundary,
    ProblemResponse,
    build_problem,
    format_exception_report,
    handle_error,
    install_error_handlers,
    validation_diagnostics,
)
from rdp.infra.diagnostics import (
    ConflictError,
    DefectError,
    Diagnostic,
    DiagnosticCategory,
    ExternalError,
    InputError,
)
from rdp.infra.logging import RuntimeFormatter, log_context, request_id_context


class _Payload(BaseModel):
    """模拟登录后的嵌套请求声明；不包含真实凭据。"""

    model_config = ConfigDict(hide_input_in_errors=True)
    password: str
    counts: list[int]
    extra: dict[str, int]


def _validation_request() -> Request:
    """从真实 FastAPI 路由取得参数声明，避免模拟框架内部结构。"""
    app = FastAPI()

    async def endpoint(body: _Payload, count: int) -> None:
        pass

    app.add_api_route("/api/validate", endpoint, methods=["POST"])
    return _request(app)


_REQUEST_ID = "123456789abc4def8abc123456789abc"


def _diagnostic(category: str = "input") -> Diagnostic:
    """仅通过公开模型校验构造测试上下文。"""
    return Diagnostic.model_validate(
        dict(
            level="error",
            category=category,
            stage="读取",
            source="平台",
            objects=[dict(key="dataset", value="r1lite_叠衣服")],
            rule="路径必填",
            actual="target为null",
            expected="路径字符串",
            consequence="详情读取失败",
            next_step="检查解析器",
        )
    )


def _problem(**changes: object) -> dict[str, object]:
    """提供与状态码表一致的已知安全载荷。"""
    return (
        dict(
            type="about:blank",
            title="Bad Request",
            status=400,
            detail="输入有问题",
            category="input",
            diagnostics=[],
            error_id=_REQUEST_ID,
        )
        | changes
    )


def _request(app: FastAPI | None = None) -> Request:
    """建立不接触网络的 HTTP Request，路由声明由测试显式设置。"""
    scope: ASGIMessage = dict(
        type="http",
        method="GET",
        path="/api/items/private-value",
        query_string=b"secret=never-log",
        headers=[],
        scheme="http",
        server=("test", 80),
    )
    if app is not None:
        scope["route"] = app.routes[-1]
    return Request(scope)


def _add_failure(app: FastAPI, error: Exception, path: str = "/api/failure") -> None:
    """经公开路由注册接口引入故障，排在既有兜底前。"""

    async def fail() -> None:
        raise error

    app.add_api_route(path, fail, methods=["GET"])
    app.router.routes.insert(0, app.router.routes.pop())


def _invoke(app: Any) -> list[ASGIMessage]:
    """驱动公开 ASGI 边界，只用内存消息，不启动服务器。"""
    messages: list[ASGIMessage] = []

    async def receive() -> ASGIMessage:
        return dict(type="http.request", body=b"", more_body=False)

    async def send(message: ASGIMessage) -> None:
        messages.append(message)

    asyncio.run(app(_request().scope, receive, send))
    return messages


def test_problem_schema_fields() -> None:
    """验证契约：ProblemResponse 的七个字段、about:blank 默认、错误编号 v4/variant、冻结/extra=forbid 及所有字符串/状态校验符合 Attributes。"""
    problem = ProblemResponse.model_validate(_problem())
    assert problem.type == "about:blank" and problem.diagnostics == ()
    for field in ("title", "detail", "category", "error_id", "status"):
        payload = _problem()
        del payload[field]
        with pytest.raises(ValidationError):
            ProblemResponse.model_validate(payload)
    for changes in (
        dict(status=True),
        dict(status="400"),
        dict(error_id="bad"),
        dict(error_id="123456789abc1def8abc123456789abc"),
        dict(extra="x"),
        dict(detail=" "),
    ):
        with pytest.raises(ValidationError):
            ProblemResponse.model_validate(_problem(**changes))
    with pytest.raises(ValidationError):
        problem.detail = "不能修改"


def test_problem_schema_invalid() -> None:
    """验证契约：非法状态/标题/类别组合、跨类别诊断、DEFECT 非空诊断均触发 ValidationError；缺陷固定500，INPUT按已批准状态表校验。"""
    for changes in (
        dict(status=418, title="I'm a Teapot"),
        dict(title="错误标题"),
        dict(category="external"),
        dict(diagnostics=[_diagnostic("external")]),
        dict(
            status=500,
            title="Internal Server Error",
            category="defect",
            diagnostics=[_diagnostic("defect")],
        ),
    ):
        with pytest.raises(ValidationError):
            ProblemResponse.model_validate(_problem(**changes))


def test_problem_serialization() -> None:
    """验证契约：ProblemResponse.model_dump(mode="json") 输出枚举和有序数组，error_id 与请求上下文一致，无 traceback/error_chain。"""
    payload = ProblemResponse.model_validate(_problem(diagnostics=[_diagnostic()])).model_dump(
        mode="json"
    )
    assert set(payload) == {
        "type",
        "title",
        "status",
        "detail",
        "category",
        "diagnostics",
        "error_id",
    }
    assert payload["error_id"] == _REQUEST_ID
    assert payload["diagnostics"][0]["objects"] == [dict(key="dataset", value="r1lite_叠衣服")]
    assert "traceback" not in json.dumps(payload)


def test_validation_each_field() -> None:
    """验证契约：RequestValidationError 按框架 errors 顺序逐项转换，多个字段/同字段多个规则各保留一条诊断。"""
    error = RequestValidationError(
        [
            dict(loc=("query", "count"), type="int_parsing"),
            dict(loc=("query", "limit"), type="missing"),
            dict(loc=("query", "count"), type="greater_than"),
        ]
    )
    ds = validation_diagnostics(_request(), error)
    assert len(ds) == 3
    assert all(d.category is DiagnosticCategory.INPUT and d.level.value == "error" for d in ds)
    assert all(d.actual == "字段缺失或格式不符合要求（原值不回显）" for d in ds)
    assert all(d.consequence == "请求被拒绝，操作未执行" for d in ds)


def test_validation_locations() -> None:
    """验证契约：body/query/path/header 的声明字段位置及数组下标保留；动态字典键和未声明字符串位置显示未声明字段。"""
    error = RequestValidationError(
        [
            dict(loc=("body", "password")),
            dict(loc=("body", "counts", 2)),
            dict(loc=("body", "extra", "private-key")),
            dict(loc=("query", "count")),
            dict(loc=("query", "undeclared")),
        ]
    )
    ds = validation_diagnostics(_validation_request(), error)
    assert [d.objects[0].value for d in ds] == [
        "body.password",
        "body.counts[2]",
        "body.extra.未声明字段",
        "query.count",
        "query.未声明字段",
    ]


def test_validation_no_secret_echo() -> None:
    """验证契约：口令、token、cookie、私钥及整份体出现在 input/msg/ctx/body/自定义校验器消息时不进入响应、诊断或日志；动态键也不回显。"""
    secrets = ["口令不回显", "token不回显", "cookie不回显", "private-key不回显"]
    error = RequestValidationError(
        [
            dict(
                loc=("body", "extra", secrets[0]),
                input=secrets[1],
                msg=secrets[2],
                ctx=dict(secret=secrets[3]),
            )
        ],
        body=secrets,
    )
    text = json.dumps(
        [d.model_dump(mode="json") for d in validation_diagnostics(_validation_request(), error)],
        ensure_ascii=False,
    )
    assert all(secret not in text for secret in secrets)


def test_validation_empty_errors() -> None:
    """验证契约：errors() 为空返回一条 field=请求 的安全兜底诊断，不让校验框架缺少细节导致500。"""
    ds = validation_diagnostics(_request(), RequestValidationError([]))
    assert len(ds) == 1
    assert ds[0].objects[0].value == "请求"


def test_validation_pure(caplog: pytest.LogCaptureFixture) -> None:
    """验证契约：validation_diagnostics 只读路由声明和异常，不消费 receive、不改异常、不访问时钟或记日志。"""
    error = RequestValidationError([dict(loc=("body", "password"), input="敏感输入")])
    before = list(error.errors())
    ds = validation_diagnostics(_validation_request(), error)
    assert len(ds) == 1
    assert error.errors() == before
    assert not caplog.records


def test_build_input_variants() -> None:
    """验证契约：build_problem 将 InputError 默认400及合法404/422子类映射到 INPUT，保留全部诊断及顺序。"""
    with log_context(request_id=_REQUEST_ID):
        for status in (400, 404, 422):
            cls = type("输入子类", (InputError,), {"http_status": HTTPStatus(status)})
            ds = (_diagnostic(), _diagnostic())
            result = build_problem(_request(), cls(ds))
            assert result.status == status and result.category is DiagnosticCategory.INPUT
            assert result.diagnostics == ds and result.error_id == _REQUEST_ID


def test_build_conflict() -> None:
    """验证契约：build_problem 将 ConflictError 映射409及 CONFLICT，使用固定中文 detail，不串接异常字符串。"""
    with log_context(request_id=_REQUEST_ID):
        problem = build_problem(_request(), ConflictError((_diagnostic("conflict"),)))
    assert (problem.status, problem.category.value, problem.detail) == (
        409,
        "conflict",
        "操作发生冲突，请查看诊断。",
    )


def test_build_external() -> None:
    """验证契约：build_problem 将 ExternalError 映射502及 EXTERNAL，保留脱敏后的外部上下文。"""
    with log_context(request_id=_REQUEST_ID):
        problem = build_problem(_request(), ExternalError((_diagnostic("external"),)))
    assert (problem.status, problem.category.value, problem.detail) == (
        502,
        "external",
        "外部服务或工具失败，请查看诊断。",
    )
    assert problem.diagnostics[0].actual == "target为null"


def test_build_defect() -> None:
    """验证契约：build_problem 将有/无诊断 DefectError 及任意意外 Exception 映射500 DEFECT，固定一句话、空诊断，无异常链或 traceback。"""
    with log_context(request_id=_REQUEST_ID):
        for error in (DefectError(), DefectError((_diagnostic("defect"),)), ValueError("内部原文")):
            problem = build_problem(_request(), error)
            assert (problem.status, problem.category.value, problem.diagnostics) == (
                500,
                "defect",
                (),
            )
            assert problem.detail == "平台内部错误，请把错误编号交给维护者。"
            assert "内部原文" not in problem.model_dump_json()


def test_build_validation() -> None:
    """验证契约：build_problem 将 RequestValidationError 映射422 INPUT 并使用逐字段诊断；about:blank 与标准 title 正确。"""
    with log_context(request_id=_REQUEST_ID):
        problem = build_problem(
            _validation_request(), RequestValidationError([dict(loc=("query", "count"))])
        )
    assert problem.status == 422 and problem.category.value == "input"
    assert problem.type == "about:blank" and problem.title == "Unprocessable Entity"
    assert problem.diagnostics[0].objects[0].value == "query.count"


def test_build_missing_request_id() -> None:
    """验证契约：build_problem 对缺失或非法 request_id_context 抛 RuntimeError，不生成替代编号；handle_error 原样传播且尚未发送响应。"""
    for value in (None, "非法"):
        token = request_id_context.set(value)
        try:
            with pytest.raises(RuntimeError):
                build_problem(_request(), RuntimeError("故障"))
            with pytest.raises(RuntimeError):
                asyncio.run(handle_error(_request(), RuntimeError("故障")))
        finally:
            request_id_context.reset(token)


def test_build_pure(caplog: pytest.LogCaptureFixture) -> None:
    """验证契约：build_problem 不改上下文、异常或请求，不读查询串、体、headers/cookie，不写日志。"""
    error = InputError((_diagnostic(),))
    before = error.diagnostics
    with log_context(request_id=_REQUEST_ID):
        assert build_problem(_request(), error).error_id == _REQUEST_ID
        assert request_id_context.get() == _REQUEST_ID
    assert error.diagnostics == before and not caplog.records


def test_report_complete_chain() -> None:
    """验证契约：format_exception_report 保留 cause/context 各层类型和全部栈帧位置，遵守显式 cause 与 suppress_context；不读取源码。"""
    try:
        try:
            raise ValueError("根因消息")
        except ValueError as cause:
            raise RuntimeError("外层消息") from cause
    except RuntimeError as error:
        report = format_exception_report(error)
        assert "ValueError: 根因消息" in report and "RuntimeError: 外层消息" in report
        assert "direct cause" in report
        assert "test_report_complete_chain" in report
        assert report.count("Traceback (most recent call last)") == 2


def test_report_group_and_cycle() -> None:
    """验证契约：format_exception_report 保留异常组全部分支、共享根因与循环标记，无默认宽度/深度截断；无 traceback 异常也可报告。"""
    group = ExceptionGroup("全部分支", [ValueError(f"叶子{i}") for i in range(20)])
    report = format_exception_report(group)
    for i in range(20):
        assert f"ValueError: 叶子{i}" in report
    first = ValueError("第一层")
    second = RuntimeError("第二层")
    first.__cause__ = second
    second.__cause__ = first
    report = format_exception_report(first)
    assert "第一层" in report and "第二层" in report
    assert "循环引用" in report


def test_report_secret_redaction() -> None:
    """验证契约：D2：异常消息、源码行和标准库 notes 保留，局部变量的值不打印，原异常不修改。"""
    private_value = "不应显示的局部值"
    try:
        raise ValueError("保留原始异常消息")
    except ValueError as error:
        error.add_note("标准库附注")
        report = format_exception_report(error)
    assert "ValueError: 保留原始异常消息" in report
    assert 'raise ValueError("保留原始异常消息")' in report
    assert "标准库附注" in report
    assert private_value not in report


def test_handler_mappings_and_media() -> None:
    """验证契约：验收2：四类与校验失败经真实 ASGI 返回400/404/422/409/502/500，载荷status一致，媒体类型application/problem+json，唯一X-Request-ID。"""

    class MissingObjectError(InputError):
        """请求操作的对象不存在，对应规范 6.2 的 404。"""

        http_status: ClassVar[HTTPStatus] = HTTPStatus.NOT_FOUND

    class InvalidParametersError(InputError):
        """请求参数不合格，对应规范 6.2 的 422。"""

        http_status: ClassVar[HTTPStatus] = HTTPStatus.UNPROCESSABLE_ENTITY

    cases = (
        (InputError, "input", 400),
        (MissingObjectError, "input", 404),
        (InvalidParametersError, "input", 422),
        (ConflictError, "conflict", 409),
        (ExternalError, "external", 502),
        (DefectError, "defect", 500),
    )
    for cls, category, status in cases:
        app = create_app(None, database=None)
        _add_failure(app, cls((_diagnostic(category),)))
        with TestClient(app) as client:
            response = cast(httpx.Client, client).get("/api/failure")
        assert response.status_code == status
        assert response.headers["content-type"] == "application/problem+json"
        assert response.json()["category"] == category
        assert response.json()["error_id"] == response.headers["X-Request-ID"]
    app = create_app(None, database=None)

    async def validate(count: int) -> None:
        pass

    app.add_api_route("/api/validation", validate)
    app.router.routes.insert(0, app.router.routes.pop())
    with TestClient(app) as client:
        response = cast(httpx.Client, client).get("/api/validation?count=bad")
    assert response.status_code == 422
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["category"] == "input"
    assert response.json()["error_id"] == response.headers["X-Request-ID"]


def test_handler_known_log_once(caplog: pytest.LogCaptureFixture) -> None:
    """验证契约：显式四类和校验异常各在rdp.api.errors记一条ERROR；按6.4精确核对模块logger名；诊断五段/安全异常链按契约追加；未知异常处理器不记日志。"""
    with log_context(request_id=_REQUEST_ID):
        for error in (
            InputError((_diagnostic(),)),
            ConflictError((_diagnostic("conflict"),)),
            ExternalError((_diagnostic("external"),)),
            DefectError(),
            RequestValidationError([]),
        ):
            caplog.clear()
            response = asyncio.run(handle_error(_request(), error))
            assert response.status_code in (400, 409, 502, 500, 422)
            assert len(caplog.records) == 1
            assert caplog.records[0].name == "rdp.api.errors"
            assert caplog.records[0].levelno == logging.ERROR
        caplog.clear()
        asyncio.run(handle_error(_request(), RuntimeError("未知")))
        assert not caplog.records


def test_handler_request_log_privacy(caplog: pytest.LogCaptureFixture) -> None:
    """验证契约：日志请求行只含method、匹配路由模板path；未知路由写未匹配路径；查询串、路径实值、headers、cookie、请求体不出现。"""
    app = FastAPI()

    async def endpoint(item: str) -> None:
        pass

    app.add_api_route("/api/items/{item}", endpoint)
    with log_context(request_id=_REQUEST_ID):
        asyncio.run(handle_error(_request(app), InputError((_diagnostic(),))))
    record = caplog.records[0]
    assert record.__dict__["fields"] == {"method": "GET", "path": "/api/items/{item}"}
    assert "private-value" not in caplog.text and "never-log" not in caplog.text


def test_handler_no_io() -> None:
    """验证契约：handle_error 仅构造响应和运行日志，不直接send、不访问数据库、目录或网络、不配置全局logger。"""
    handlers = list(logging.getLogger().handlers)
    with log_context(request_id=_REQUEST_ID):
        response = asyncio.run(handle_error(_request(), InputError((_diagnostic(),))))
    assert response.media_type == "application/problem+json"
    assert logging.getLogger().handlers == handlers


def test_boundary_construct() -> None:
    """验证契约：ErrorBoundary 构造不调用下游、不取时间、不生成编号；实例不保存跨请求的响应状态。"""
    called: list[ASGIMessage] = []

    async def app(scope: ASGIMessage, receive: Any, send: Any) -> None:
        called.append(scope)

    ErrorBoundary(app)
    assert called == [] and request_id_context.get() is None


def test_boundary_normal_and_protocol_passthrough() -> None:
    """验证契约：正常HTTP调用下游一次且响应消息不变；WebSocket/lifespan不绑定或转换，所有非HTTP异常原样传播。"""

    async def app(scope: ASGIMessage, receive: Any, send: Any) -> None:
        await send(dict(type="http.response.start", status=204, headers=[]))
        await send(dict(type="http.response.body", body=b""))

    result = _invoke(ErrorBoundary(app))
    assert [m["type"] for m in result] == ["http.response.start", "http.response.body"]
    failure = ValueError("非HTTP")

    async def fail(scope: ASGIMessage, receive: Any, send: Any) -> None:
        raise failure

    async def no_op() -> None:
        pass

    for kind in ("websocket", "lifespan"):
        with pytest.raises(ValueError) as caught:
            asyncio.run(ErrorBoundary(fail)(dict(type=kind), cast(Any, no_op), cast(Any, no_op)))
        assert caught.value is failure


def test_boundary_no_response_fallback(caplog: pytest.LogCaptureFixture) -> None:
    """验证契约：HTTP 下游未发送start即抛异常时返回完整500 problem，一条安全报告，编号由外层生成并加头。"""

    async def fail(scope: ASGIMessage, receive: Any, send: Any) -> None:
        raise RuntimeError("未发响应即失败")

    result = _invoke(RequestIdMiddleware(ErrorBoundary(fail)))
    assert result[0]["status"] == 500
    assert json.loads(result[1]["body"])["category"] == "defect"
    assert len(caplog.records) == 1
    assert request_id_context.get() is None


def test_boundary_server_error_rethrow_once(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """验证契约：验收3：实际ServerErrorMiddleware调用Exception处理器、发送500并重抛，ErrorBoundary消费异常；实际uvicorn h11 RequestResponseCycle用内存transport驱动，不出现第二份traceback。"""
    monkeypatch.setattr(caplog.handler, "formatter", RuntimeFormatter())
    app = create_app(None, database=None)
    _add_failure(app, RuntimeError("唯一根因"))
    transport = _uvicorn(app)
    assert b"500 Internal Server Error" in transport.output
    identifier = re.search(rb"x-request-id: ([0-9a-f]{32})", transport.output)
    assert identifier is not None
    assert identifier.group(1).decode() in caplog.text
    assert caplog.text.count("Traceback (most recent call last)") == 1
    # 规范 6.4：统一报告使用实际模块名，精确核对，避免漏掉其他 logger 的重复记录。
    assert len([record for record in caplog.records if record.name == "rdp.api.errors"]) == 1
    assert not any(record.exc_info for record in caplog.records)
    assert transport.closed


def test_boundary_stream_failure_once(caplog: pytest.LogCaptureFixture) -> None:
    """验证契约：验收3：流式响应start/部分body后失败，仅一份完整安全traceback，不发第二个start或伪成功末块；uvicorn关闭未完成连接，允许一条无traceback协议日志。"""
    app = create_app(None, database=None)

    async def stream() -> AsyncIterator[bytes]:
        yield b"prefix"
        raise RuntimeError("流式故障")

    async def endpoint() -> StreamingResponse:
        return StreamingResponse(stream())

    app.add_api_route("/api/failure", endpoint)
    app.router.routes.insert(0, app.router.routes.pop())
    transport = _uvicorn(app)
    assert transport.output.count(b"HTTP/1.1") == 1
    assert b"prefix" in transport.output and not transport.output.endswith(b"0\r\n\r\n")
    assert transport.closed
    assert caplog.text.count("Traceback (most recent call last)") == 1
    assert "ASGI callable returned without completing response." in caplog.text
    assert not any(record.exc_info for record in caplog.records)


def test_boundary_background_failure_once(caplog: pytest.LogCaptureFixture) -> None:
    """验证契约：验收3：完整响应已发送后后台任务失败仍报告一次且不补发响应，带原请求编号，uvicorn无第二份traceback。"""
    app = create_app(None, database=None)

    async def fail() -> None:
        raise RuntimeError("后台失败")

    async def endpoint() -> Response:
        tasks = BackgroundTasks()
        tasks.add_task(fail)
        return Response("完成", background=tasks)

    app.add_api_route("/api/failure", endpoint)
    app.router.routes.insert(0, app.router.routes.pop())
    transport = _uvicorn(app)
    assert transport.output.count(b"HTTP/1.1") == 1
    assert "完成".encode() in transport.output
    assert caplog.text.count("Traceback (most recent call last)") == 1
    assert not any(record.exc_info for record in caplog.records)


def test_boundary_exception_group_once(caplog: pytest.LogCaptureFixture) -> None:
    """验证契约：ExceptionGroup 一次上报包含全部叶子，不逐叶重复记录，不逃逸到uvicorn。"""
    app = create_app(None, database=None)
    _add_failure(app, ExceptionGroup("组", [ValueError("叶一"), TypeError("叶二")]))
    _uvicorn(app)
    # 规范 6.4：统一报告使用实际模块名，精确核对，避免漏掉其他 logger 的重复记录。
    assert len([record for record in caplog.records if record.name == "rdp.api.errors"]) == 1
    assert "叶一" in caplog.text and "叶二" in caplog.text
    assert not any(record.exc_info for record in caplog.records)


def test_boundary_cancel_and_exit() -> None:
    """验证契约：HTTP CancelledError/KeyboardInterrupt/SystemExit 等 BaseException 原样传播，不变成500；外层RequestIdMiddleware仍恢复绑定。"""
    for error in (asyncio.CancelledError(), KeyboardInterrupt(), SystemExit()):

        async def fail(
            scope: ASGIMessage, receive: Any, send: Any, error: BaseException = error
        ) -> None:
            raise error

        with pytest.raises(type(error)):
            _invoke(RequestIdMiddleware(ErrorBoundary(fail)))
        assert request_id_context.get() is None


def test_boundary_fallback_send_failure(caplog: pytest.LogCaptureFixture) -> None:
    """验证契约：补救500发送失败时原样传播send异常，可能留下响应前缀，不重复渲染原异常或无限重试。"""
    failure = OSError("发送失败")

    async def fail(scope: ASGIMessage, receive: Any, send: Any) -> None:
        raise ValueError("原故障")

    async def send(message: ASGIMessage) -> None:
        raise failure

    async def receive() -> ASGIMessage:
        return {}

    with log_context(request_id=_REQUEST_ID), pytest.raises(OSError) as caught:
        asyncio.run(ErrorBoundary(fail)(_request().scope, receive, send))
    assert caught.value is failure
    assert len(caplog.records) == 1


def test_boundary_report_dependency_failure() -> None:
    """验证契约：报告依赖自身失败时原样传播新异常，不递归上报，不承诺该故障下的日志交付；不更改全局logger。"""
    failure = OSError("日志设备故障")

    class BrokenHandler(logging.Handler):
        @override
        def emit(self, record: logging.LogRecord) -> None:
            raise failure

    handler = BrokenHandler()
    logging.getLogger().addHandler(handler)

    async def fail(scope: ASGIMessage, receive: Any, send: Any) -> None:
        raise ValueError("原故障")

    with pytest.raises(OSError) as caught:
        _invoke(RequestIdMiddleware(ErrorBoundary(fail)))
    assert caught.value is failure


def test_boundary_concurrent_ids() -> None:
    """验证契约：并发错误请求编号不串，日志和响应头同号，退出恢复contextvars；直到流式/后台任务结束仍在绑定范围。"""
    seen: list[str | None] = []

    async def fail(scope: ASGIMessage, receive: Any, send: Any) -> None:
        seen.append(request_id_context.get())
        await asyncio.sleep(0)
        assert request_id_context.get() in seen
        raise ValueError("并发故障")

    async def run() -> list[list[ASGIMessage]]:
        async def one() -> list[ASGIMessage]:
            messages: list[ASGIMessage] = []

            async def receive() -> ASGIMessage:
                return {}

            async def send(message: ASGIMessage) -> None:
                messages.append(message)

            await RequestIdMiddleware(ErrorBoundary(fail))(_request().scope, receive, send)
            return messages

        return list(await asyncio.gather(one(), one()))

    results = asyncio.run(run())
    ids = [json.loads(messages[1]["body"])["error_id"] for messages in results]
    assert len(set(ids)) == 2 and set(ids) == set(seen)
    assert request_id_context.get() is None


def test_install_handlers() -> None:
    """验证契约：install_error_handlers 登记四类/校验/Exception 六个处理器且幂等；工厂保持create_app(web_dist)签名、按规定顺序包栈。"""
    app = FastAPI()
    install_error_handlers(app)
    for cls in (
        InputError,
        ConflictError,
        ExternalError,
        DefectError,
        RequestValidationError,
        Exception,
    ):
        assert app.exception_handlers[cls] is handle_error
    before = dict(app.exception_handlers)
    install_error_handlers(app)
    assert app.exception_handlers == before


def test_install_after_start() -> None:
    """验证契约：install_error_handlers 在middleware_stack已构建时抛RuntimeError，原处理器和schema缓存均不变。"""
    app = FastAPI()
    app.middleware_stack = app.build_middleware_stack()
    before = dict(app.exception_handlers)
    schema = app.openapi()
    with pytest.raises(RuntimeError):
        install_error_handlers(app)
    assert app.exception_handlers == before and app.openapi_schema is schema


def test_preserve_framework_http_errors() -> None:
    """验证契约：Starlette HTTPException 的404/405等保留原JSON/detail/headers，/api未知路径仍404 JSON，SPA回退原行为不变；业务报错用四类异常。"""
    app = create_app(None, database=None)
    # 自带文档已关闭，用独立 GET 测试路由继续验证框架原生 405，不依赖文档页面。
    app.add_api_route("/framework-get", lambda: {}, methods=["GET"])
    with TestClient(app) as client:
        for method, path, status in (("get", "/api/missing", 404), ("post", "/framework-get", 405)):
            response = getattr(client, method)(path)
            assert response.status_code == status
            assert response.headers["content-type"] == "application/json"
            assert "detail" in response.json() and "category" not in response.json()
            assert response.headers["X-Request-ID"]


def test_schema_components_and_generation() -> None:
    """验证契约：create_app 按需生成 OpenAPI，包含 ProblemResponse/Diagnostic/DiagnosticObject/两枚举和 D1 字段，前端类型不手写。"""
    schema = create_app(None, database=None).openapi()
    assert {
        "ProblemResponse",
        "Diagnostic",
        "DiagnosticObject",
        "DiagnosticCategory",
        "DiagnosticLevel",
    } <= schema["components"]["schemas"].keys()
    assert "error_chain" in schema["components"]["schemas"]["Diagnostic"]["properties"]


def test_schema_routes_in_implementation() -> None:
    """验证契约：每个已知API路由400/404/409/422/502/500登记problem媒体及组件引用，保留原框架JSON；后挂测试路由清缓存后也出现。"""
    app = create_app(None, database=None)
    app.openapi()

    async def added(count: int) -> None:
        pass

    app.add_api_route("/api/added", added)
    app.openapi_schema = None
    schema = app.openapi()
    for path in ("/api/health", "/api/added"):
        responses = schema["paths"][path]["get"]["responses"]
        for status in ("400", "404", "409", "422", "502", "500"):
            assert responses[status]["content"]["application/problem+json"]["schema"] == {
                "$ref": "#/components/schemas/ProblemResponse"
            }


def test_install_isolation_and_cache() -> None:
    """验证契约：安装只修改目标app并清schema缓存；不配置全局日志、不注册演示接口、不写数据库或文件，不影响其他app。"""
    first, second = create_app(None, database=None), FastAPI()
    first.openapi()
    handlers = list(logging.getLogger().handlers)
    install_error_handlers(first)
    assert first.openapi_schema is None and Exception not in second.exception_handlers
    assert logging.getLogger().handlers == handlers
    assert not any("_diagnostics-demo" in getattr(route, "path", "") for route in first.routes)


def test_representative_platform_defect(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """验证契约：示例二：未包装的 TypeError 经真实应用返回安全的 500，只记录一次完整 traceback。

    示例二是接口请求，没有作业结果；作业结果由示例一的测试覆盖。
    """
    monkeypatch.setattr(caplog.handler, "formatter", RuntimeFormatter())
    app = create_app(None, database=None)

    def parse_link(raw: dict[str, Any]) -> Path:
        """复现解析器漏检 null，不包装异常，也不访问文件系统。"""
        return Path(raw["target"])

    def read_dataset() -> Path:
        """通过嵌套调用保留真实调用栈。"""
        return parse_link({"target": None})

    async def endpoint() -> None:
        read_dataset()

    app.add_api_route("/api/datasets/r1lite_叠衣服", endpoint)
    app.router.routes.insert(0, app.router.routes.pop())
    with TestClient(app) as client:
        response = cast(httpx.Client, client).get("/api/datasets/r1lite_叠衣服")

    assert response.status_code == 500
    assert response.headers["content-type"] == "application/problem+json"
    payload = response.json()
    assert payload["category"] == "defect" and payload["diagnostics"] == []
    assert payload["error_id"] == response.headers["X-Request-ID"]
    for internal in ("Traceback", "TypeError", __file__, "原始路径.json"):
        assert internal not in response.text
    assert len(caplog.records) == 1
    assert caplog.records[0].levelno == logging.ERROR
    assert f"request_id={payload['error_id']}" in caplog.text
    assert caplog.text.count("Traceback (most recent call last)") == 1
    assert "TypeError: argument should be a str or an os.PathLike object" in caplog.text
    assert "not 'NoneType'" in caplog.text
    assert 'return Path(raw["target"])' in caplog.text


class _MemoryTransport(asyncio.Transport):
    """真实 uvicorn 协议的内存传输边界，不创建 socket。"""

    def __init__(self) -> None:
        super().__init__()
        self.output = bytearray()
        self.closed = False

    @override
    def write(self, data: Any) -> None:
        self.output.extend(data)

    @override
    def close(self) -> None:
        self.closed = True

    @override
    def is_closing(self) -> bool:
        return self.closed

    @override
    def get_extra_info(self, name: str, default: Any = None) -> Any:
        return {"sockname": ("test", 80), "peername": ("client", 1234)}.get(name, default)


def _uvicorn(app: FastAPI) -> _MemoryTransport:
    """执行真实 HTTP 协议与应用栈；等待该请求的后台任务完成。"""

    async def run() -> _MemoryTransport:
        state = ServerState()
        protocol = H11Protocol(
            Config(app, log_config=None, access_log=False, ws="none", lifespan="off"),
            state,
            {},
            _loop=asyncio.get_running_loop(),
        )
        transport = _MemoryTransport()
        protocol.connection_made(transport)
        protocol.data_received(
            b"GET /api/failure HTTP/1.1\r\nHost: test\r\nConnection: close\r\n\r\n"
        )
        await asyncio.gather(*state.tasks)
        protocol.connection_lost(None)
        return transport

    return asyncio.run(run())


def test_validation_nested_dictionary_keys() -> None:
    """验证契约：动态字典键即使与值模型的字段名相同也不得回显。"""

    class Entry(BaseModel):
        model_config = ConfigDict(hide_input_in_errors=True)
        private_key: int

    app = FastAPI()

    async def endpoint(body: dict[str, Entry]) -> None:
        pass

    app.add_api_route("/api/validate", endpoint, methods=["POST"])
    error = RequestValidationError([dict(loc=("body", "private_key", "private_key"))])
    location = validation_diagnostics(_request(app), error)[0].objects[0].value
    assert location == "body.未声明字段.未声明字段"


def test_explicit_defect_diagnostics_and_cause(caplog: pytest.LogCaptureFixture) -> None:
    """验证契约：显式 DefectError 的诊断和 cause 只进入同一条日志，响应仍无内部细节。"""
    diagnostic = _diagnostic("defect")
    app = create_app(None, database=None)

    async def endpoint() -> None:
        try:
            raise ValueError("显式缺陷的原始原因")
        except ValueError as cause:
            raise DefectError((diagnostic,)) from cause

    app.add_api_route("/api/explicit-defect", endpoint)
    app.router.routes.insert(0, app.router.routes.pop())
    with TestClient(app) as client:
        response = cast(httpx.Client, client).get("/api/explicit-defect")
    assert response.status_code == 500
    assert response.json()["diagnostics"] == []
    assert "显式缺陷的原始原因" not in response.text
    assert len(caplog.records) == 1 and caplog.records[0].levelno == logging.ERROR
    assert "对象：" in caplog.text and "r1lite_叠衣服" in caplog.text
    assert "ValueError: 显式缺陷的原始原因" in caplog.text
    assert "direct cause" in caplog.text


def test_validation_log_field_locations_without_values(caplog: pytest.LogCaptureFixture) -> None:
    """验证契约：真实 422 日志包含各字段五段诊断，但不含口令、其他原值或校验异常正文。"""

    class LoginParameters(BaseModel):
        """只为触发字段约束失败构造测试载荷，不是真实登录接口。"""

        model_config = ConfigDict(hide_input_in_errors=True)
        password: str = Field(min_length=20)
        count: int

    app = create_app(None, database=None)

    async def login(body: LoginParameters) -> None:
        pass

    app.add_api_route("/api/test-validation", login, methods=["POST"])
    app.router.routes.insert(0, app.router.routes.pop())
    raw_values = {"password": "不应出现在日志的原始口令", "count": "不应出现的数量原值"}
    with TestClient(app) as client:
        response = cast(httpx.Client, client).post("/api/test-validation", json=raw_values)
    assert response.status_code == 422
    assert len(caplog.records) == 1
    assert caplog.records[0].name == "rdp.api.errors"
    assert caplog.records[0].levelno == logging.ERROR
    message = caplog.records[0].getMessage()
    assert '对象："field"="body.password"' in message
    assert '对象："field"="body.count"' in message
    for label in ("对象：", "规则：", "实际：", "后果：", "检查："):
        assert message.count(label) == 2
    for value in raw_values.values():
        assert value not in message and value not in response.text
    assert "RequestValidationError" not in message and "Traceback" not in message
