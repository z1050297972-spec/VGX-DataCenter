"""账号 HTTP 测试的临时数据库和真实 ASGI 客户端；不启动网络服务器或使用真实状态目录。"""

from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import cast

from accounts_support import EXAMPLE_SECRET, NOW
from argon2 import PasswordHasher
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from httpx import Client, Response
from pydantic import SecretStr
from sqlalchemy import Engine

from rdp.accounts.security import PasswordCodec
from rdp.accounts.service import AccountService
from rdp.accounts.types import Credentials, NewAccount, Role
from rdp.api import create_app
from rdp.infra.config import PlatformConfig
from rdp.infra.db.connection import create_database_engine
from rdp.infra.db.migration import migrate
from rdp.infra.state import initialize_state, state_paths

ORIGIN = "http://testserver"


@dataclass
class Clock:
    """可推进的 UTC 测试时钟，计数用于确认同请求不重复读取。"""

    value: datetime = NOW
    calls: int = 0

    def __call__(self) -> datetime:
        """返回测试指定的时刻，不读机器墙钟。"""
        self.calls += 1
        return self.value


@dataclass
class ApiCase:
    """一个测试拥有的应用、服务、引擎、时钟和无网络客户端。"""

    app: FastAPI
    service: AccountService
    engine: Engine
    clock: Clock
    client: Client

    def login(self, name: str = "admin", secret: SecretStr = EXAMPLE_SECRET) -> Response:
        """通过真实登录接口设置浏览器 cookie，不绕过 HTTP 会话建立。"""
        return self.client.post(
            "/api/auth/login", json={"login_name": name, "password": secret.get_secret_value()}
        )


@contextmanager
def api_case(root: Path, *, origin: bool = True) -> Generator[ApiCase]:
    """仅在 tmp_path 下迁移并创建首号，结束时关闭客户端和引擎。"""
    paths = state_paths(PlatformConfig(state_dir=root), ())
    initialize_state(paths)
    migrate(paths, now=NOW)
    engine = create_database_engine(paths.database)
    try:
        service = AccountService(
            engine, PasswordCodec(PasswordHasher(time_cost=1, memory_cost=1024, parallelism=1))
        )
        service.create_first_admin(
            NewAccount(Credentials("admin", EXAMPLE_SECRET), "管理员", Role.ADMINISTRATOR), now=NOW
        )
        clock = Clock()
        app = create_app(None, database=engine, clock=clock)
        # 测试只替换公开的应用服务依赖，仍使用真实领域实现和临时数据库。
        app.state.account_service = service
        with TestClient(
            app, raise_server_exceptions=False, headers={"Origin": ORIGIN} if origin else {}
        ) as client:
            yield ApiCase(app, service, engine, clock, cast(Client, client))
    finally:
        engine.dispose()


def boundary_response(error: Exception) -> tuple[int, dict[str, str], dict[str, object]]:
    """通过公开 ASGI 边界直接观察响应，不启动服务器或绕开请求编号中间件。"""
    import asyncio
    import json

    from rdp.api import RequestIdMiddleware
    from rdp.api._asgi import ASGIMessage
    from rdp.api.errors import ErrorBoundary

    messages: list[ASGIMessage] = []

    async def failing(scope: ASGIMessage, receive: object, send: object) -> None:
        raise error

    async def receive() -> ASGIMessage:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: ASGIMessage) -> None:
        messages.append(message)

    scope: ASGIMessage = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "method": "GET",
        "path": "/api/auth/probe",
        "scheme": "http",
        "query_string": b"",
        "headers": [],
        "app": FastAPI(),
        "state": {},
    }
    asyncio.run(RequestIdMiddleware(ErrorBoundary(failing))(scope, receive, send))
    headers = {key.decode(): value.decode() for key, value in messages[0]["headers"]}
    body = json.loads(b"".join(message.get("body", b"") for message in messages[1:]))
    return messages[0]["status"], headers, body


def add_actor(case: ApiCase, *, name: str = "member", role: Role = Role.MEMBER, ready: bool = True):
    """通过真实领域服务建立第二身份，HTTP 测试只替换外部传输层。"""
    from rdp.accounts.types import PasswordChange

    admin = case.service.login(Credentials("admin", EXAMPLE_SECRET), now=case.clock.value)
    case.service.create_account(
        admin.identity,
        NewAccount(Credentials(name, EXAMPLE_SECRET), "成员", role),
        now=case.clock.value,
    )
    grant = case.service.login(Credentials(name, EXAMPLE_SECRET), now=case.clock.value)
    if ready:
        grant = case.service.change_password(
            grant.identity,
            PasswordChange(EXAMPLE_SECRET, SecretStr("member-updated-value")),
            now=case.clock.value,
        )
    return grant


def request_for(
    app: FastAPI,
    *,
    method: str = "GET",
    path: str = "/api/auth/me",
    headers: list[tuple[bytes, bytes]] | None = None,
) -> Request:
    """构造公开边界函数使用的请求，不读网络或真实配置。"""
    return Request(
        {
            "type": "http",
            "method": method,
            "path": path,
            "scheme": "http",
            "query_string": b"",
            "headers": headers or [],
            "app": app,
            "state": {},
        }
    )
