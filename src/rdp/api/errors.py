"""入口层的 problem+json 与唯一错误报告边界（M0 工单 04，E2/E3）。

使用 FastAPI/Pydantic 的响应、模型和校验异常，以及标准库 traceback 的栈提取能力；
D2 直接沿用标准库异常消息和源码行，不打印局部变量；参数校验不回显原值，
自己的 Pydantic 模型均 hide_input_in_errors=True，不新增依赖或自行解析栈。
状态码以主仓库 CODING_STANDARDS.md 6.2 为准；新状态码先改那张表，再改代码。
| 状态码 | 类别 | 什么时候用 | 响应 |
|---|---|---|---|
| 400 | 输入或数据问题 | 默认：请求合格，但内容或数据有问题，例如数据集缺文件 | problem+json，带诊断 |
| 404 | 输入或数据问题 | 要操作的对象不存在，例如数据集、账号、作业编号查不到 | problem+json，带诊断 |
| 422 | 输入或数据问题 | 请求参数不合格（类型、范围、缺项）；不回显原值 | problem+json，带诊断 |
| 409 | 冲突 | 和当前状态冲突，例如预览之后数据集被别的作业改过 | problem+json，带诊断 |
| 502 | 外部失败 | 依赖的外部东西出错，例如存储根离线、外部工具失败 | problem+json，带诊断 |
| 500 | 程序缺陷 | 平台自己的 bug，以及任何没被归入前三类的异常 | problem+json，一句话加错误编号，不带内部细节 |
| 401、403 | （第 6 张定） | 没登录、没权限 | 第 6 张「账号与登录」补进本表 |
| 404、405 | （框架） | 接口路径不存在、方法不对，由 Starlette 直接返回 | 保持框架原格式；前端显示"请求失败" |

RFC 9457 使用 about:blank；诊断模型来自基础层，不存数据库、traceback 或请求载荷。
只报告一次需要 ASGI 外层配合：本地 starlette/middleware/errors.py 的 ServerErrorMiddleware
无条件重抛 Exception，uvicorn/protocols/http/h11_impl.py 的 run_asgi 会记录逃逸 traceback。
所以顺序是 RequestIdMiddleware → ErrorBoundary → 完整 FastAPI 栈；不改第 3 张的透传契约。
create_app 通过 install_error_handlers 安装统一处理，OpenAPI 在请求生成时合并模型和响应。
"""

import logging
import sys
import traceback
from http import HTTPStatus
from itertools import chain
from types import UnionType
from typing import Annotated, Any, Literal, Self, Union, cast, get_args, get_origin
from uuid import UUID

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic.json_schema import models_json_schema

from rdp.api._asgi import ASGIApp, ASGIMessage, Receive, Send
from rdp.infra.diagnostics import (
    ALLOWED_HTTP_STATUSES,
    ConflictError,
    DefectError,
    Diagnostic,
    DiagnosticCategory,
    DiagnosticLevel,
    DiagnosticObject,
    DiagnosticText,
    ExternalError,
    InputError,
    render_diagnostic,
)
from rdp.infra.logging import request_id_context

logger = logging.getLogger(__name__)


class ProblemResponse(BaseModel):
    """RFC 9457 的不可变错误载荷；字段固定，不包含 traceback、错误链或请求内容。

    Attributes:
        type: 问题类型 URI，固定 about:blank，无单位，默认 about:blank；不虚构文档 URI。
        title: 对应 HTTPStatus.phrase 的标准英文状态短语，非空白，无单位，必填，无默认值；
            中文说明放 detail，符合 about:blank 约定。
        status: HTTP 状态码，严格整数，仅 400/404/422/409/502/500；拒绝 bool；
            无单位，必填，无默认值。INPUT 对应前三种，其余类别依次对应后三种。
        detail: 一句安全的中文摘要，非空白，无单位，必填，无默认值；程序缺陷固定为
            “平台内部错误，请把错误编号交给维护者。”，不回显 str(error)。
        category: 四类 DiagnosticCategory 之一，无单位，必填，无默认值。
        diagnostics: 有序 Diagnostic 元组，默认空元组；单位条；程序缺陷必须为空，
            其他类别与顶层一致；通用载荷允许为空，但 build_problem 的领域异常/校验失败至少一条。
        error_id: 服务端请求编号，32 位小写 uuid4.hex，匹配 v4/variant 位；无单位，必填，
            无默认值；来自 request_id_context，与 X-Request-ID 一致，不接收客户端编号。
    """

    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)

    type: Literal["about:blank"] = "about:blank"
    title: DiagnosticText
    status: int = Field(strict=True, ge=400, le=599)
    detail: DiagnosticText
    category: DiagnosticCategory
    diagnostics: tuple[Diagnostic, ...] = ()
    error_id: str = Field(strict=True, pattern=r"^[0-9a-f]{12}4[0-9a-f]{3}[89ab][0-9a-f]{15}$")

    @model_validator(mode="after")
    def _validate_problem(self) -> Self:
        """拒绝状态/标题/类别不匹配、跨类别诊断和缺陷载荷中的诊断，包装为 ValidationError。"""
        if (
            self.status not in ALLOWED_HTTP_STATUSES[self.category]
            or self.title != HTTPStatus(self.status).phrase
        ):
            raise ValueError("状态码、标题与类别不一致")
        if any(item.category is not self.category for item in self.diagnostics):
            raise ValueError("诊断类别与响应不一致")
        if self.category is DiagnosticCategory.DEFECT and self.diagnostics:
            raise ValueError("程序缺陷响应不能包含内部诊断")
        return self


def validation_diagnostics(
    request: Request, error: RequestValidationError
) -> tuple[Diagnostic, ...]:
    """把参数校验失败转换为逐字段诊断，避免回显未来登录接口的凭据。

    Args:
        request: 当前 HTTP 请求，仅用于读取已匹配路由的声明字段；不读取请求体或凭据。
        error: FastAPI 参数校验异常；errors() 可以为空，不信任其中的 input/msg/ctx/body。

    Returns:
        按 errors() 原顺序每项一条 INPUT/ERROR 诊断，不合并同一字段的不同错误。
        stage=“请求校验”，source=“平台”，objects 的 field 为声明字段的位置（如 body.password），
        数组下标保留；动态字典键与未声明的字符串位置段用“未声明字段”代替，禁止回显任意键。
        rule=“请求字段必须满足接口声明”，actual=“字段缺失或格式不符合要求（原值不回显）”，
        expected=“符合接口声明的类型和约束”，consequence=“请求被拒绝，操作未执行”，
        next_step=“对照接口字段定义修正后重试”。空 errors() 返回一条 field=“请求”兜底诊断。
        不使用 input/msg/ctx/body 或异常字符串，因校验器消息也可能拼入口令。

    Raises:
        无。

    Side Effects:
        无（只读路由声明和异常元数据）；不消费请求流、不写日志。

    Time Semantics:
        同步转换，不读时钟或重试；保持框架报告顺序。
    """
    return tuple(
        Diagnostic(
            level=DiagnosticLevel.ERROR,
            category=DiagnosticCategory.INPUT,
            stage="请求校验",
            source="平台",
            objects=(
                DiagnosticObject(
                    key="field", value=_validation_location(request, item.get("loc", ()))
                ),
            ),
            rule="请求字段必须满足接口声明",
            actual="字段缺失或格式不符合要求（原值不回显）",
            expected="符合接口声明的类型和约束",
            consequence="请求被拒绝，操作未执行",
            next_step="对照接口字段定义修正后重试",
        )
        for item in (error.errors() or [{}])
    )


def build_problem(request: Request, error: Exception) -> ProblemResponse:
    """将请求异常转换成安全的 problem 载荷，不记录日志或发送响应。

    Args:
        request: 当前 HTTP 请求；request_id_context 必须已由 RequestIdMiddleware 绑定。
        error: 四类异常、RequestValidationError 或任意意外 Exception；不修改异常链。

    Returns:
        四类映射为 INPUT 的 400/404/422（基类 400）、CONFLICT 409、EXTERNAL 502、DEFECT 500。
        输入/冲突/外部失败保留全部诊断和顺序，不用聚合样例替代；detail 固定为
        “输入或数据不符合要求，请查看诊断。”、“操作发生冲突，请查看诊断。”、
        “外部服务或工具失败，请查看诊断。”。参数校验映射 INPUT 422，使用
        validation_diagnostics；detail=“请求参数不符合要求，请查看诊断。”。
        未知异常和显式 DefectError 均返回固定的缺陷 detail、空 diagnostics；不泄漏诊断内容。
        type=about:blank，title 为 HTTPStatus.phrase，error_id 为当前请求编号。
        Starlette HTTPException 不进入此函数：保留原 404/405 等响应及头；业务使用四类异常。

    Raises:
        RuntimeError: 请求编号上下文缺失或非法；这是接入顺序错误，不伪造错误编号。

    Side Effects:
        无；不读取请求体、查询串、headers、cookie，不改上下文或异常。

    Time Semantics:
        同步转换，必须在请求绑定范围内调用；不读时钟。
    """
    request_id = request_id_context.get()
    try:
        valid = (
            request_id is not None
            and UUID(request_id).version == 4
            and UUID(request_id).hex == request_id
        )
    except (ValueError, AttributeError):
        valid = False
    if not valid or request_id is None:
        raise RuntimeError("请求编号上下文缺失或非法")
    status = HTTPStatus.INTERNAL_SERVER_ERROR
    category = DiagnosticCategory.DEFECT
    diagnostics: tuple[Diagnostic, ...] = ()
    detail = "平台内部错误，请把错误编号交给维护者。"
    if isinstance(error, (InputError, ConflictError, ExternalError)):
        status, category, diagnostics = error.http_status, error.category, error.diagnostics
        detail = {
            DiagnosticCategory.INPUT: "输入或数据不符合要求，请查看诊断。",
            DiagnosticCategory.CONFLICT: "操作发生冲突，请查看诊断。",
            DiagnosticCategory.EXTERNAL: "外部服务或工具失败，请查看诊断。",
        }[category]
    if isinstance(error, RequestValidationError):
        status, category = HTTPStatus.UNPROCESSABLE_ENTITY, DiagnosticCategory.INPUT
        diagnostics = validation_diagnostics(request, error)
        detail = "请求参数不符合要求，请查看诊断。"
    return ProblemResponse(
        title=status.phrase,
        status=status,
        detail=detail,
        category=category,
        diagnostics=diagnostics,
        error_id=request_id,
    )


def format_exception_report(error: BaseException) -> str:
    """生成保留异常消息和源码行、不打印局部变量的完整异常报告。

    Args:
        error: 当前异常及 cause/context 链，也支持 BaseExceptionGroup；不接受 None。

    Returns:
        按标准库 traceback 的格式保留每层异常的类型和消息、栈帧文件/函数/行号及源码行，
        __notes__ 沿用标准库行为，不打印局部变量。遵循显式 cause 和 suppress_context，
        不遗漏所选链的根因；异常组不截断宽度或深度，循环引用标明已出现。
        无 traceback 时仍输出异常类型和消息；D2 不再替换异常消息或隐藏源码行。

    Raises:
        无。

    Side Effects:
        无（只读栈帧对应源文件以取得源码行）；不改变异常、traceback 或 logging 状态，不写日志。

    Time Semantics:
        同步转换，不读取时钟，不请求数据库或外部系统。
    """
    report = traceback.TracebackException.from_exception(
        error, capture_locals=False, max_group_width=sys.maxsize, max_group_depth=sys.maxsize
    )
    result = "".join(report.format(chain=True))
    if _has_exception_cycle(error, frozenset()):
        result += "循环引用：已出现的异常不重复展开。\n"
    return result


async def handle_error(request: Request, error: Exception) -> JSONResponse:
    """统一转换错误响应，并在已处理异常的边界报告一次。

    Args:
        request: 已绑定服务端编号的 HTTP 请求，禁止在请求上下文之外调用。
        error: 注册的四类异常、参数校验异常或 Exception 兜底异常。

    Returns:
        status_code 与载荷 status 相同、Content-Type=application/problem+json 的 JSONResponse；
        X-Request-ID 由最外层 RequestIdMiddleware 统一添加，不能重造编号。
        显式四类异常和校验失败由本处理器在 rdp.api.errors 记录一条 ERROR；诊断以五段追加。
        DefectError 的响应不含诊断，日志包含安全完整异常报告；其他领域异常有 cause 时
        同样附安全错误链。没有 traceback 的参数校验不记录框架异常正文。
        未知 Exception 这里只构造响应、不记录日志，等待 ServerErrorMiddleware 重抛后
        由 ErrorBoundary 记录；包括流式响应已经开始、框架不会发送该返回值的情况。

    Raises:
        RuntimeError: 请求编号未绑定或非法，由 build_problem 传播；不发送半个错误响应。

    Side Effects:
        无（仅运行日志）；不写数据库，不直接调用 send，不读取请求体或凭据。
        参数校验失败将安全的字段位置和五段诊断追加到同一条 ERROR；
        不格式化 RequestValidationError，不记录请求原值。
        日志 fields 只含 method 和 path，不含查询串；路径使用匹配路由模板，
        无已匹配模板时写“未匹配路径”，避免敏感值藏在路径参数或未知路径里。
        request_id 由 contextvars 自动带入；不记录 headers、cookie、账号或异常原始载荷。

    Time Semantics:
        请求作用域内运行，无轮询或重试；日志时间交给 RuntimeFormatter。
    """
    problem = build_problem(request, error)
    if isinstance(
        error, (InputError, ConflictError, ExternalError, DefectError, RequestValidationError)
    ):
        _report_error(request, error, problem)
    return JSONResponse(
        problem.model_dump(mode="json"),
        status_code=problem.status,
        media_type="application/problem+json",
    )


class ErrorBoundary:
    """在请求上下文以内、完整框架栈以外拦截重抛，避免 uvicorn 重复 traceback。"""

    def __init__(self, app: ASGIApp) -> None:
        """保存完整下游栈，不提前调用。

        Args:
            app: 完整 FastAPI 中间件栈；无单位，必须可异步调用。

        Returns:
            无；创建独立实例，不保存跨请求的错误或响应状态。

        Raises:
            无。

        Side Effects:
            无。

        Time Semantics:
            构造不读取时钟，不生成请求编号。
        """
        self._app = app

    async def __call__(self, scope: ASGIMessage, receive: Receive, send: Send) -> None:
        """覆盖整个 HTTP 调用，在未知异常逃离服务器之前完成唯一报告。

        Args:
            scope: ASGI scope；HTTP 请求必须已由外层绑定 request_id；其他协议原样透传。
            receive: 原 ASGI 接收回调；不额外读取消息或缓存请求体。
            send: 原 ASGI 发送回调；仅跟踪响应是否开始/完成，不修改消息或响应内容。

        Returns:
            正常调用返回 None。HTTP 的意外 Exception（含异常组）在 rdp.api.errors 以 ERROR
            记录一次 format_exception_report，使用 handle_error 同样的安全请求 fields，
            然后消费异常，防止它到达 RequestIdMiddleware 和 uvicorn 的 traceback 分支。
            响应未开始时补发 build_problem 生成的 500；已开始时不发送第二个 start，
            不伪造成功结尾。流式中途失败保留已发前缀且返回，让 uvicorn 的“响应未完成”
            协议分支关闭连接；该分支可能另写一条无 traceback 的协议日志。
            完成后的后台任务异常同样报告一次，保留已经完成的响应，不再发送 body。
            框架已处理的领域异常不逃逸，本层不再报告；Exception 处理器本身不报告未知异常。

        Raises:
            BaseException: HTTP 的取消、KeyboardInterrupt、SystemExit 等非 Exception 原样传播；
                非 HTTP 的全部异常也原样传播，不转换为程序缺陷。
            Exception: 发送补救 500 时 send 失败，或报告依赖本身失败；原样传播给服务器，
                不循环尝试报错、不再次渲染原异常。此基础设施失效不承诺可交付日志/响应。

        Side Effects:
            调用下游一次；HTTP 未开始响应即失败时发送一份 500，失败发送可能留下前缀。
            只保存调用内响应状态；不修改 scope、contextvars 或全局 logger 配置。
            不读取查询串/请求体，不吞取消；不全局屏蔽 uvicorn 日志。

        Time Semantics:
            覆盖下游流式迭代和后台任务直至退出；必须在 request_id 解绑前报告。
            不增加超时、重试或等待；下游耗时由下游控制。
        """
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return
        started = False

        async def track_send(message: ASGIMessage) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self._app(scope, receive, track_send)
        except Exception as error:
            request = Request(scope, receive=receive)
            problem = build_problem(request, error)
            _report_error(request, error, problem)
            # 已发送前缀不能改写成另一份响应，也不能伪造成功的流式结尾。
            if not started:
                response = JSONResponse(
                    problem.model_dump(mode="json"),
                    status_code=problem.status,
                    media_type="application/problem+json",
                )
                await response(scope, receive, send)


def install_error_handlers(app: FastAPI) -> None:
    """在应用启动前登记错误处理及文档，由 create_app 调用。

    Args:
        app: create_app 正在创建的 FastAPI 应用；尚未构建中间件栈或服务请求。

    Returns:
        无；登记四类异常、RequestValidationError 和 Exception → handle_error；
        不覆盖 Starlette HTTPException、404 的 SPA 处理器或 _unknown_api，保留其 JSON/头。
        _RequestContextApp.build_middleware_stack 返回
        RequestIdMiddleware(ErrorBoundary(super().build_middleware_stack()))，
        请求编号中间件包在错误报告边界之外，保持工厂签名。
        OpenAPI 登记 ProblemResponse 及其引用的组件；每个 /api 已知路由的 400/404/409/422/502/500
        responses 增加 application/problem+json 的 $ref，同时保留原有合法 application/json
        错误（如框架 404）。使用 FastAPI responses 元数据和 Pydantic schema，不手写字段。
        生成 schema 时合并，支持后挂的测试路由；重复安装幂等，不重复包裹或记日志。

    Raises:
        RuntimeError: 应用中间件栈已构建；注册前检查，失败不留下部分处理器。

    Side Effects:
        修改该 app 的内存处理器和 OpenAPI 生成配置、清除 schema 缓存；不注册演示路由，
        不加配置项，不安装全局日志 handler，不写文件或启动服务。

    Time Semantics:
        在挂好正式路由后、首次服务请求前调用；测试挂路由后须清空 OpenAPI 缓存再生成。
    """
    if app.middleware_stack is not None:
        raise RuntimeError("错误处理器必须在应用启动之前安装")
    for error_type in (
        InputError,
        ConflictError,
        ExternalError,
        DefectError,
        RequestValidationError,
        Exception,
    ):
        app.add_exception_handler(error_type, handle_error)
    if not getattr(app.state, "rdp_errors_installed", False):
        original_openapi = app.openapi

        def openapi() -> dict[str, Any]:
            """用模型生成组件，保留 FastAPI 的缓存与路由文档。"""
            schema = original_openapi()
            _, definitions = models_json_schema(
                [(ProblemResponse, "serialization")], ref_template="#/components/schemas/{model}"
            )
            schema.setdefault("components", {}).setdefault("schemas", {}).update(
                definitions["$defs"]
            )
            _document_problem_responses(schema)
            return schema

        app.openapi = openapi
        app.state.rdp_errors_installed = True
    app.openapi_schema = None


def _has_exception_cycle(error: BaseException, ancestors: frozenset[int]) -> bool:
    """标准库避免无限展开；补一个明确标记，不自行重建 traceback 文本。"""
    if id(error) in ancestors:
        return True
    path = ancestors | {id(error)}
    cause = error.__cause__ or (None if error.__suppress_context__ else error.__context__)
    children = (
        cast(BaseExceptionGroup[BaseException], error).exceptions
        if isinstance(error, BaseExceptionGroup)
        else ()
    )
    return (cause is not None and _has_exception_cycle(cause, path)) or any(
        _has_exception_cycle(child, path) for child in children
    )


def _model_fields(annotation: Any) -> dict[str, Any]:
    """只信任路由声明中的字段名；动态字典键不能借错误位置泄漏请求数据。"""
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return {
            field.alias or name: field.annotation for name, field in annotation.model_fields.items()
        }
    result: dict[str, Any] = {}
    if get_origin(annotation) not in (UnionType, Union, Annotated):
        return result
    for member in get_args(annotation):
        result.update(_model_fields(member))
    return result


def _validation_location(request: Request, location: Any) -> str:
    """逐段沿声明类型匹配位置，未声明的键只显示占位，数字下标保持。"""
    if not isinstance(location, (tuple, list)) or not location:
        return "请求"
    origin, *parts = cast(list[object] | tuple[object, ...], location)
    route = request.scope.get("route")
    if origin not in ("body", "query", "path", "header", "cookie") or not isinstance(
        route, APIRoute
    ):
        return "请求"
    fields = getattr(route.dependant, f"{origin}_params")
    known = {field.alias: field.field_info.annotation for field in fields}
    if origin == "body" and len(fields) == 1 and not getattr(fields[0].field_info, "embed", False):
        declared = _model_fields(fields[0].field_info.annotation)
        known = declared or known
    text = str(origin)
    annotation: Any = None
    for part in parts:
        if type(part) is int:
            text += f"[{part}]"
            args = get_args(annotation)
            annotation = args[0] if get_origin(annotation) in (list, tuple) and args else None
            known = _model_fields(annotation)
        else:
            name = part if isinstance(part, str) and part in known else "未声明字段"
            text += "." + name
            annotation = known.get(name)
            known = _model_fields(annotation)
    return text


def _report_error(request: Request, error: Exception, problem: ProblemResponse) -> None:
    """只记录一次；校验失败仅写安全诊断，不格式化原异常，防止原值进入日志。"""
    messages = [problem.detail]
    if isinstance(error, RequestValidationError):
        messages.extend(render_diagnostic(item) for item in problem.diagnostics)
    elif isinstance(error, (InputError, ConflictError, ExternalError, DefectError)):
        messages.extend(render_diagnostic(item) for item in error.diagnostics)
    if not isinstance(error, RequestValidationError) and (
        isinstance(error, DefectError)
        or not isinstance(error, (InputError, ConflictError, ExternalError))
        or error.__cause__ is not None
    ):
        messages.append(format_exception_report(error))
    route = request.scope.get("route")
    path = route.path if isinstance(route, APIRoute) else "未匹配路径"
    logger.error(
        "%s", "\n".join(messages), extra={"fields": {"method": request.method, "path": path}}
    )


def _document_problem_responses(schema: dict[str, Any]) -> None:
    """合并标准响应元数据，不把 FastAPI 默认的旧校验响应误留为合法格式。"""
    for path, operations in schema.get("paths", {}).items():
        if not path.startswith("/api/"):
            continue
        for method, operation in operations.items():
            if method not in {"get", "post", "put", "patch", "delete", "head", "options", "trace"}:
                continue
            for status in chain.from_iterable(ALLOWED_HTTP_STATUSES.values()):
                response = operation.setdefault("responses", {}).setdefault(
                    str(status), {"description": status.phrase}
                )
                content = response.setdefault("content", {})
                if (
                    status == 422
                    and content.get("application/json", {}).get("schema", {}).get("$ref")
                    == "#/components/schemas/HTTPValidationError"
                ):
                    content.pop("application/json")
                content["application/problem+json"] = {
                    "schema": {"$ref": "#/components/schemas/ProblemResponse"}
                }
