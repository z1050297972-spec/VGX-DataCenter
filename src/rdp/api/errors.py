"""入口层的 problem+json 与唯一错误报告边界（M0 工单 04，E2/E3）。

使用 FastAPI/Pydantic 的响应、模型和校验异常，以及标准库 traceback 的栈提取能力；
直接沿用标准库异常消息和源码行，不打印局部变量；参数校验不回显原值，
自己的 Pydantic 模型均 hide_input_in_errors=True，不新增依赖或自行解析栈。
状态码简表以主仓库 docs/standards/CODING_STANDARDS.md 6.2 为准；新增状态码先更新规范。
| 状态码 | 类别 | 用途 | 响应 |
|---|---|---|---|
| 400 | 输入或数据问题 | 请求内容或数据有问题 | problem+json，带诊断 |
| 404 | 输入或数据问题 | 要操作的对象不存在 | problem+json，带诊断 |
| 422 | 输入或数据问题 | 参数类型、范围或缺项不合格；不回显原值 | problem+json，带诊断 |
| 409 | 冲突 | 与当前状态冲突 | problem+json，带诊断 |
| 502 | 外部失败 | 外部依赖失败；口令哈希资源繁忙、排队超时 | problem+json，带诊断 |
| 500 | 程序缺陷 | 平台 bug 或未归入前三类的异常 | problem+json，安全摘要与错误编号 |
| 401 | 输入或数据问题 | 未登录、会话失效或登录凭据错误 | problem+json，带诊断并清会话 cookie |
| 403 | 输入或数据问题 | 角色不足、必须先改口令或 Origin 拒绝 | problem+json，带诊断 |
| 429 | 输入或数据问题 | G2 等待 | problem+json，带诊断；Retry-After 为向上取整的剩余秒数 |
| 404 | （框架格式） | /api 路径不存在，由 S1 兜底返回 | 保持框架 JSON 格式；前端显示"请求失败" |
| 405 | （框架格式） | /api 路径存在但方法不对，由 S1 兜底返回 | 保持框架 JSON 格式，带 Allow 头 |
| 405 | （框架） | /api 以外页面路径使用非 GET 方法 | 保持框架原格式；前端显示"请求失败" |

/api 的 S1 兜底位于全局访问检查之后，遵循 6.2 的 Origin、白名单、认证、强制改密、角色、路由顺序。

RFC 9457 使用 about:blank；诊断模型来自基础层，不存数据库、traceback 或请求载荷。
只报告一次需要 ASGI 外层配合：本地 starlette/middleware/errors.py 的 ServerErrorMiddleware
无条件重抛 Exception，uvicorn/protocols/http/h11_impl.py 的 run_asgi 会记录逃逸 traceback。
所以顺序是 RequestIdMiddleware → ErrorBoundary → 完整 FastAPI 栈；不改第 3 张的透传契约。
create_app 通过 install_error_handlers 安装统一处理，OpenAPI 在请求生成时合并模型和响应。
"""

import asyncio
import logging
import traceback
from datetime import UTC, datetime
from http import HTTPStatus
from itertools import chain
from types import UnionType
from typing import Annotated, Any, Literal, Self, Union, cast, get_args, get_origin

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic.json_schema import models_json_schema
from sqlalchemy import Engine

from rdp.accounts.errors import LoginWaitError
from rdp.api._asgi import ASGIApp, ASGIMessage, Receive, Send
from rdp.api.account_auth import clear_session_cookie
from rdp.api.audit import report_audit_append_failure
from rdp.api.shutdown import TrackedReport
from rdp.infra.db.connection import BUSY_TIMEOUT_MS, session_scope
from rdp.infra.db.records import ErrorRecord, write_error
from rdp.infra.db.validation import invalid_field
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

# 兼容既有导入名；契约以 rdp.infra.exception_report.format_exception_report 为准。
from rdp.infra.exception_report import format_exception_report as format_exception_report
from rdp.infra.ids import REQUEST_ID_PATTERN, is_request_id
from rdp.infra.logging import request_id_context
from rdp.infra.timeutil import ensure_utc

logger = logging.getLogger(__name__)


class ProblemResponse(BaseModel):
    """RFC 9457 的不可变错误载荷；字段固定，不包含 traceback、错误链或请求内容。

    Attributes:
        type: 问题类型 URI，固定 about:blank，无单位，默认 about:blank；不虚构文档 URI。
        title: 对应 HTTPStatus.phrase 的标准英文状态短语，非空白，无单位，必填，无默认值；
            中文说明放 detail，符合 about:blank 约定。
        status: HTTP 状态码，严格整数，仅 400/404/422/401/403/429/409/502/500；拒绝 bool；
            无单位，必填，无默认值。INPUT 对应前六种，其余类别依次对应后三种。
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
    error_id: str = Field(strict=True, pattern=REQUEST_ID_PATTERN)

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
        四类映射为 INPUT 的 400/404/422/401/403/429（基类 400）、CONFLICT 409、EXTERNAL 502、DEFECT 500。
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
    if not is_request_id(request_id) or request_id is None:
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
        已处理异常使用 await report_error_with_database；未知异常仍由
        ErrorBoundary 调用它，一次请求只报告/存表一次。
        账号边界：账号业务请求及任何路由认证阶段的未知异常先经 sanitize_account_error；两个响应出口均调用
        account_error_headers 输出 429 Retry-After，并在 401 清 cookie；账号报错的 occurred_at
        复用注入的请求 now，不重新读取系统时钟。

    Raises:
        RuntimeError: 请求编号未绑定或非法，由 build_problem 传播；不发送半个错误响应。

    Side Effects:
        缺陷使用独立报错事务，失败语义见
        report_error_with_database；不直接调用 send，不读取请求体或凭据。
        参数校验失败将安全的字段位置和五段诊断追加到同一条 ERROR；
        不格式化 RequestValidationError，不记录请求原值。
        日志 fields 只含 method 和 path，不含查询串；路径使用匹配路由模板，
        无已匹配模板时写“未匹配路径”，避免敏感值藏在路径参数或未知路径里。
        request_id 由 contextvars 自动带入；不记录 headers、cookie、账号或异常原始载荷。

    Time Semantics:
        请求作用域内运行，无轮询或重试；日志时间交给 RuntimeFormatter。
        缺陷持久化额外等待最多约 ERROR_PERSIST_TIMEOUT_S，其他类别不等数据库。
    """
    report_audit_append_failure(error)
    original = error
    handled = isinstance(
        error, (InputError, ConflictError, ExternalError, DefectError, RequestValidationError)
    )
    error = _safe_request_error(request, error)
    problem = build_problem(request, error)
    response = _problem_response(problem, error)
    if handled:
        await report_error_with_database(request, error, problem, occurred_at=_report_time(request))
        request.state.reported_error_id = id(original)
    return response


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
            未知缺陷统一 await report_error_with_database，独立工作线程写表；
            保留原 500/已发响应前缀，持久化失败不进入本类的“报告依赖失败”重抛分支。
            账号边界：账号入口与 handle_error 共用秘密脱敏和 Retry-After/401 cookie 处理；
            范围包括所有路由在认证阶段抛出的异常，读取只含阶段的请求标记，不能只匹配账号路径；
            未开始的 401 响应清 cookie，已发送响应不再发头。认证通过后的非账号业务仍保留完整报告。

        Time Semantics:
            覆盖下游流式迭代和后台任务直至退出；必须在 request_id 解绑前报告。
            缺陷报告等待最多约 ERROR_PERSIST_TIMEOUT_S，
            无额外重试，下游耗时仍由下游控制。
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
            report_audit_append_failure(error)
            original = error
            error = _safe_request_error(request, error)
            problem = build_problem(request, error)
            if getattr(request.state, "reported_error_id", None) != id(original):
                await report_error_with_database(
                    request, error, problem, occurred_at=_report_time(request)
                )
            # 已发送前缀不能改写成另一份响应，也不能伪造成功的流式结尾。
            if not started:
                await _problem_response(problem, error)(scope, receive, send)


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
        OpenAPI 登记 ProblemResponse 及其引用的组件；每个 /api 已知路由的 400/401/403/404/409/422/429/502/500
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


# 工单 05：SQLite 锁等待 BUSY_TIMEOUT_MS（5000 毫秒）之外留 1 秒调度余量，单位秒；不无限等线程池。
ERROR_PERSIST_TIMEOUT_S = BUSY_TIMEOUT_MS / 1000 + 1.0


async def report_error_with_database(
    request: Request, error: Exception, problem: ProblemResponse, *, occurred_at: datetime
) -> None:
    """在接口唯一报告边界写运行日志，并尽力保存程序缺陷的同一报告。

    Args:
        request: 已绑定 request_id 的请求；app.state.database_engine 可缺失，表示离线模式。
        error: 原异常；含未知 Exception、DefectError、其他领域异常和参数校验异常。
        problem: build_problem 的结果，无单位，error_id 必须等于当前请求编号。
        occurred_at: 边界注入的 aware 发生时刻，微秒，内部转 UTC；实现调用方取一次当前时刻，
            测试传固定时钟，不在数据库里重新读时钟。

    Returns:
        无；原错误按现有 _report_error 的规则只写一条 ERROR；仅未知异常或 DefectError
        在配置引擎时写一条报错，其他三类/参数校验或无引擎只记日志。
        格式化一次，日志的 traceback 段和 ErrorRecord.report 逐字相同（含超长标记），
        摘要使用固定 problem.detail，来源 request、编号 problem.error_id；保留 D2 的
        异常消息和源码行、不打印 locals，不增加请求体、query、headers、cookie 或凭据。

    Raises:
        InputError: occurred_at 无时区或 UTC 换算溢出；报告之前拒绝，不产生半份报错。
        DefectError: problem 编号与请求上下文不符时在报告前拒绝，不伪造关联号；
            程序缺陷的格式化报告为空时拒绝保存完整报错。
        BaseException: 取消等非 Exception 原样传播，不吞取消。
        Exception: 日志 handler 或格式化本身失败，沿用第 04 张边界故障语义；不递归报告。
            数据库写入、线程调度和等待超时异常不传播，不能盖掉原始 500。

    Side Effects:
        handle_error 处理显式缺陷、ErrorBoundary 处理未知缺陷，两处共用此边界函数；
        在 request.state 标记已报告，重入不重复写日志/表。先完成业务会话回滚再写报错。
        通过标准库 asyncio.to_thread 执行整个独立 session_scope + write_error，
        不把业务 Session 跨线程传入，不阻塞事件循环；业务回滚不会删除独立报错。
        asyncio.wait_for 限定等待 ERROR_PERSIST_TIMEOUT_S；持久化失败只额外记一次 ERROR，
        fields 仅原 error_id 和安全阶段/失败类别，不格式化第二个 traceback、不回显 SQL 或报告；
        不再尝试保存该失败，不重试，不改变原响应。失败事务回滚，可能查不到该编号。
        超时后不等待线程，线程不能被 Python 强杀；可能稍后成功留下一条记录或失败回滚，
        迟到线程不再记录日志。第 11 张关闭引擎须等在途线程结束；磁盘永久阻塞不承诺线程可回收。

    Time Semantics:
        发生时刻取原异常边界时刻，UTC；锁等待约 5 秒，异步等待最多约 6 秒加调度开销，
        不含原有同步日志 I/O。等待期间事件循环可服务其他请求；流式/后台异常可在响应开始后落表。
        已发完 500 的未知异常可能尚在落表，立刻查询可短暂 404；客户端不自动轮询。
    """
    try:
        occurred_at = ensure_utc(occurred_at)
    except (ValueError, OverflowError) as error_time:
        time_problem = invalid_field("occurred_at", "带时区且可表示的 UTC 时刻")
        raise time_problem from error_time
    request_id = request_id_context.get()
    if request_id != problem.error_id:
        identity_error = _report_identity_error(request_id, problem.error_id)
        raise identity_error
    if getattr(request.state, "rdp_error_reported", False):
        return
    request.state.rdp_error_reported = True
    if problem.category is not DiagnosticCategory.DEFECT:
        _report_error(request, error, problem)
        return
    report = _logged_report(request, error, problem)
    if not report:
        formatting_error = _empty_report_error(problem.error_id)
        raise formatting_error
    # 纯 ASGI 边界也可独立使用；scope 尚无 FastAPI app 时沿用第 04 张只写日志的行为。
    app_state = getattr(request.scope.get("app"), "state", None)
    engine = getattr(app_state, "database_engine", None)
    if engine is None:
        return
    try:
        record = ErrorRecord(
            error_id=problem.error_id,
            occurred_at=occurred_at,
            category=problem.category,
            summary=problem.detail,
            report=report,
            source_kind="request",
        )
        tracked = TrackedReport(request.app, lambda: _persist_report(engine, record))
        try:
            await asyncio.wait_for(asyncio.to_thread(tracked.run), timeout=ERROR_PERSIST_TIMEOUT_S)
        finally:
            # 只撤销未启动登记；超时后仍在运行的写入由Web关闭流程继续等待。
            tracked.cancel_if_pending()
    except Exception as persistence_error:
        # 报错表本身不可用时只追加安全摘要，不递归保存，也不替换原来的 500。
        logger.error(
            "完整报错持久化失败",
            extra={
                "fields": {
                    "error_id": problem.error_id,
                    "stage": "保存报错",
                    "failure": type(persistence_error).__name__,
                }
            },
        )


def _report_identity_error(request_id: str | None, error_id: str) -> DefectError:
    """指出上下文与待报告编号的差异，非法上下文原值不回显。"""
    visible_request_id = (
        request_id if request_id is not None and is_request_id(request_id) else "未绑定或格式非法"
    )
    return DefectError(
        (
            Diagnostic(
                level=DiagnosticLevel.ERROR,
                category=DiagnosticCategory.DEFECT,
                stage="错误报告",
                source="平台",
                objects=(
                    DiagnosticObject(key="request_id", value=visible_request_id),
                    DiagnosticObject(key="error_id", value=error_id),
                ),
                rule="错误编号必须等于当前请求编号",
                actual=f"当前请求编号={visible_request_id}；待报告错误编号={error_id}",
                expected="请求编号与错误编号相同",
                consequence="拒绝报告，未写入运行日志或报错表",
                next_step="检查统一错误报告入口的请求上下文传递和问题响应构造",
            ),
        )
    )


def _empty_report_error(error_id: str) -> DefectError:
    """保留错误编号并说明格式化失败的后果，不保存空报告或递归报告自身故障。"""
    return DefectError(
        (
            Diagnostic(
                level=DiagnosticLevel.ERROR,
                category=DiagnosticCategory.DEFECT,
                stage="错误报告",
                source="平台",
                objects=(DiagnosticObject(key="error_id", value=error_id),),
                rule="程序缺陷报告必须非空",
                actual="异常格式化结果为空",
                expected="包含异常类型和消息的非空报告",
                consequence="完整报错未写入报错表；运行日志可能仅有摘要",
                next_step="检查异常格式化器和统一错误报告入口",
            ),
        )
    )


def _persist_report(engine: Engine, record: ErrorRecord) -> None:
    """整个独立事务在线程内完成；超时后可能仍运行，但不在迟到线程里重复报告。"""
    with session_scope(engine) as session:
        write_error(session, record)


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
    _logged_report(request, error, problem)


def _logged_report(request: Request, error: Exception, problem: ProblemResponse) -> str | None:
    """日志和持久化复用一次格式化结果，保留第 04 张安全请求字段和诊断顺序。"""
    messages = [problem.detail]
    report: str | None = None
    if isinstance(error, RequestValidationError):
        messages.extend(render_diagnostic(item) for item in problem.diagnostics)
    elif isinstance(error, (InputError, ConflictError, ExternalError, DefectError)):
        messages.extend(render_diagnostic(item) for item in error.diagnostics)
    if not isinstance(error, RequestValidationError) and (
        isinstance(error, DefectError)
        or not isinstance(error, (InputError, ConflictError, ExternalError))
        or error.__cause__ is not None
    ):
        report = format_exception_report(error)
        messages.append(report)
    route = request.scope.get("route")
    path = route.path if isinstance(route, APIRoute) else "未匹配路径"
    logger.error(
        "%s", "\n".join(messages), extra={"fields": {"method": request.method, "path": path}}
    )

    return report


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


def account_error_headers(error: Exception) -> dict[str, str]:
    """为账号限流提供安全的 Retry-After 响应头。

    Args:
        error: 已由领域安全边界转换的异常；允许任意 Exception，不读取其原始字符串。

    Returns:
        LoginWaitError 返回仅有 Retry-After 的字典，值为 1-60 的整数秒文本；其他异常返回空字典。

    Raises:
        DefectError: LoginWaitError 的 retry_after_s 类型或范围损坏，拒绝把原值写入头。

    Side Effects:
        无；不改变异常，不写日志，不计算或延长等待。handle_error 与 ErrorBoundary
        两个响应出口共用本函数，不能只给其中一条路径加头。

    Time Semantics:
        使用领域已按请求 now 向上取整的剩余秒数，不重新读时钟。
    """
    if not isinstance(error, LoginWaitError):
        return {}
    seconds = error.retry_after_s
    if type(seconds) is not int or not 1 <= seconds <= 60:
        raise DefectError()
    return {"Retry-After": str(seconds)}


def sanitize_account_error(error: Exception) -> Exception:
    """隔离账号业务及所有路由认证阶段的未知异常消息。

    Args:
        error: 账号业务请求或任意路由认证阶段捕获的异常，不可空；
            调用者用安全的请求阶段标记识别认证失败，不依赖 URL 前缀，不 stringify 原对象或读取载荷。

    Returns:
        可信领域四类安全异常和 RequestValidationError 原样返回；其他异常转换为固定 DefectError，
        不保留原始 message/cause/context/notes，只保留不含局部变量的定位信息。

    Raises:
        无。

    Side Effects:
        不修改原异常、不记录日志；账号业务及任意路由认证失败的两个统一错误出口均先调用此函数，
        再用既有 report_error_with_database 报告一次，避免未知错误把口令/cookie 写入完整报错。
        口令、会话令牌、cookie 不得出现在响应、诊断、异常消息、运行日志或报错表。
        认证成功后的其他业务完整异常报告契约不变。

    Time Semantics:
        同步转换，无时钟或数据库读取。
    """
    if isinstance(
        error, (InputError, ConflictError, ExternalError, DefectError, RequestValidationError)
    ):
        return error
    safe = DefectError()
    # 只保留定位信息，不保留原 traceback 对象，以免源码行或上下文包含凭据。
    locations: list[str] = []
    for frame, line in traceback.walk_tb(error.__traceback__):
        locations.append(f"{frame.f_code.co_filename}:{line} {frame.f_code.co_name}")
        if len(locations) > 20:
            locations.pop(0)
    if locations:
        safe.add_note("定位：" + " | ".join(locations))
    return safe


def _safe_request_error(request: Request, error: Exception) -> Exception:
    """认证阶段覆盖所有路径；账号业务也必须隔离未知异常消息。"""
    path = request.url.path
    if (
        getattr(request.state, "account_auth_phase", False)
        or path.startswith("/api/auth/")
        or path == "/api/accounts"
        or path.startswith("/api/accounts/")
    ):
        return sanitize_account_error(error)
    return error


def _problem_response(problem: ProblemResponse, error: Exception) -> JSONResponse:
    """两个错误出口共用状态、重试头和401清cookie，避免分支行为漂移。"""
    response = JSONResponse(
        problem.model_dump(mode="json"),
        status_code=problem.status,
        media_type="application/problem+json",
        headers=account_error_headers(error),
    )
    if problem.status == 401:
        clear_session_cookie(response)
    return response


def _report_time(request: Request) -> datetime:
    """优先复用已校验请求时刻；时钟本身失败时仅报告使用UTC墙钟兜底。"""
    moment = getattr(request.state, "account_now", None)
    return moment if isinstance(moment, datetime) else datetime.now(UTC)
