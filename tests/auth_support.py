"""旧 HTTP 契约测试的真实登录前置条件；认证与被测业务存储故障相互隔离。

只在调用者的 tmp_path 下短暂创建认证数据库，退出请求后删除；不绕过全局守卫。
业务数据库仍由原测试拥有，保持只读/写入/报错持久化等原断言的观察范围。
"""

from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import cast

from accounts_support import EXAMPLE_SECRET, NOW, model_database
from argon2 import PasswordHasher
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx import Client

from rdp.accounts.security import PasswordCodec
from rdp.accounts.service import AccountService
from rdp.accounts.types import Credentials, NewAccount, Role


@contextmanager
def authenticated_context(app: FastAPI, root: Path) -> Generator[dict[str, str]]:
    """真实领域登录产生cookie，并恢复应用服务/时钟；临时库在请求结束后删除。"""
    previous_service = getattr(app.state, "account_service", None)
    previous_clock = getattr(app.state, "accounts_clock", None)
    with (
        TemporaryDirectory(prefix="account-auth-", dir=root) as directory,
        model_database(Path(directory)) as engine,
    ):
        service = AccountService(
            engine, PasswordCodec(PasswordHasher(time_cost=1, memory_cost=1024, parallelism=1))
        )
        service.create_first_admin(
            NewAccount(Credentials("test_admin", EXAMPLE_SECRET), "测试管理员", Role.ADMINISTRATOR),
            now=NOW,
        )
        grant = service.login(Credentials("test_admin", EXAMPLE_SECRET), now=NOW)
        app.state.account_service = service
        app.state.accounts_clock = lambda: NOW
        try:
            yield {
                "Cookie": "rdp_session=" + grant.token.get_secret_value(),
                "Origin": "http://testserver",
            }
        finally:
            app.state.account_service = previous_service
            app.state.accounts_clock = previous_clock


@contextmanager
def authenticated_client(
    app: FastAPI, root: Path, *, raise_server_exceptions: bool = True
) -> Generator[Client]:
    """保留真实 ASGI 传输和安全检查，只补已验证会话与本站 Origin。"""
    with (
        authenticated_context(app, root) as headers,
        TestClient(app, headers=headers, raise_server_exceptions=raise_server_exceptions) as raw,
    ):
        yield cast(Client, raw)
