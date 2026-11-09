"""入口层的 API 访问屏障，放在框架读取请求体之前，同步数据库工作交线程池。"""

from fastapi import Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response

from rdp.accounts.types import SessionGrant
from rdp.api._asgi import ASGIApp, ASGIMessage, Receive, Send
from rdp.api.account_auth import AccountRequestContext, enforce_api_access, set_session_cookie


class AccountSecurityBoundary:
    """所有 API 和 Lichtblick 资源默认认证，平台 SPA 仍由前端导航规则处理。"""

    def __init__(self, app: ASGIApp) -> None:
        """只保存下游，不在构造时读数据库或请求。"""
        self._app = app

    async def __call__(self, scope: ASGIMessage, receive: Receive, send: Send) -> None:
        """未通过安全决策就不读取 body，取消也不吞掉。"""
        path = scope.get("path", "")
        if scope["type"] != "http" or not (
            path == "/api" or path.startswith(("/api/", "/lichtblick/"))
        ):
            await self._app(scope, receive, send)
            return
        request = Request(scope, receive=receive)
        await run_in_threadpool(enforce_api_access, request)

        async def send_with_renewal(message: ASGIMessage) -> None:
            # 只有本请求已提交刷新才续期；业务签发、登出和错误边界的清除优先。
            if message["type"] == "http.response.start" and message["status"] != 401:
                context = getattr(request.state, "account_context", None)
                headers = list(message.get("headers", []))
                has_cookie = any(
                    key.lower() == b"set-cookie" and value.startswith(b"rdp_session=")
                    for key, value in headers
                )
                if (
                    isinstance(context, AccountRequestContext)
                    and context.identity is not None
                    and context.identity.activity_refreshed
                    and not has_cookie
                ):
                    response = Response()
                    set_session_cookie(
                        response, SessionGrant(context.identity, request.state.account_cookie)
                    )
                    headers.extend(
                        (key, value) for key, value in response.raw_headers if key == b"set-cookie"
                    )
                    message = {**message, "headers": headers}
            await send(message)

        fallback = getattr(request.state, "account_fallback", None)
        if isinstance(fallback, Response):
            await fallback(scope, receive, send_with_renewal)
        else:
            await self._app(scope, receive, send_with_renewal)
