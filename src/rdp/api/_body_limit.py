"""HTTP 入口正文预算；复用 ASGI 接收流计数，不记录或提前解析请求内容（M0-13）。"""

from http import HTTPStatus

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from rdp.api._asgi import ASGIApp, ASGIMessage, Receive, Send
from rdp.api.errors import handle_error
from rdp.infra.diagnostics import Diagnostic, DiagnosticCategory, DiagnosticLevel, InputError

# 工单13的全局请求预算，单位字节；作业参数16KiB、确认编号列表等均在此预算以内。
MAX_REQUEST_BODY_BYTES = 16 * 1024 * 1024


class _BodyTooLargeError(InputError):
    """正文超出全局预算，保留统一五段输入诊断。"""

    http_status = HTTPStatus.REQUEST_ENTITY_TOO_LARGE


class _BodyLimitReached(HTTPException):
    """让FastAPI在读取正文时保留超限状态，不被其通用解析异常转换成400。"""


def install_body_limit(app: FastAPI) -> None:
    """把正文接收异常转换回统一的五段413诊断，其他HTTP异常保持框架行为。"""
    app.add_exception_handler(_BodyLimitReached, _handle_body_limit)


async def _handle_body_limit(request: Request, error: Exception) -> JSONResponse:
    """不回显输入流，只把明确的预算超限交给原有错误边界报告一次。"""
    return await handle_error(request, _too_large())


class RequestBodyLimit:
    """按实际接收字节数限制HTTP正文，Content-Length只能用于提前拒绝。"""

    def __init__(self, app: ASGIApp) -> None:
        """保存下游，不读取正文或修改全局配置。"""
        self._app = app

    async def __call__(self, scope: ASGIMessage, receive: Receive, send: Send) -> None:
        """有无Content-Length都累计实际正文，超过预算时不把超额块交给解析器。"""
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return
        received = 0

        async def limited_receive() -> ASGIMessage:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > MAX_REQUEST_BODY_BYTES:
                    raise _BodyLimitReached(status_code=413)
            return message

        declared = [v for k, v in scope.get("headers", []) if k.lower() == b"content-length"]
        if any(value.isdigit() and int(value) > MAX_REQUEST_BODY_BYTES for value in declared):
            response = await handle_error(Request(scope), _too_large())
            await response(scope, receive, send)
            return
        await self._app(scope, limited_receive, send)


def _too_large() -> _BodyTooLargeError:
    """不给诊断附带请求内容，允许匿名登录请求安全报告超额。"""
    return _BodyTooLargeError(
        (
            Diagnostic(
                level=DiagnosticLevel.ERROR,
                category=DiagnosticCategory.INPUT,
                stage="请求正文",
                source="平台",
                objects=(),
                rule="请求体不得超过全局上限",
                actual="请求体超过16MiB",
                expected=f"最多{MAX_REQUEST_BODY_BYTES}字节",
                consequence="请求被拒绝，操作未执行",
                next_step="减少本次提交内容后重试",
            ),
        )
    )
