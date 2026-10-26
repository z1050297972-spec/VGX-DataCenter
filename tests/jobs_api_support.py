"""作业HTTP专用装配；账号夹具已启动客户端，故这里在TestClient启动前装配显式路径与登记表。"""

from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from typing import cast

from account_api_support import ApiCase, Clock
from accounts_support import EXAMPLE_SECRET, NOW
from argon2 import PasswordHasher
from fastapi.testclient import TestClient
from httpx import Client

from rdp.accounts.security import PasswordCodec
from rdp.accounts.service import AccountService
from rdp.accounts.types import Credentials, NewAccount, Role
from rdp.api import create_app
from rdp.api.jobs import configure_jobs
from rdp.audit.types import OPS_AUDIT_CONTEXT
from rdp.infra.config import PlatformConfig
from rdp.infra.db.connection import create_database_engine
from rdp.infra.db.migration import migrate
from rdp.infra.state import initialize_state, state_paths
from rdp.jobs.registry import JobRegistry, production_registry


@contextmanager
def job_api_case(root: Path, *, registry: JobRegistry | None = None) -> Generator[ApiCase]:
    """真实应用与临时迁移库，HTTP请求通过ASGI传输，不启动网络监听。"""
    paths = state_paths(PlatformConfig(state_dir=root), ("示例：数数",))
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
        clock = Clock()
        app = create_app(None, database=engine, clock=clock)
        app.state.account_service = service
        configure_jobs(app, paths, production_registry() if registry is None else registry)
        with TestClient(
            app, raise_server_exceptions=False, headers={"Origin": "http://testserver"}
        ) as client:
            yield ApiCase(app, service, engine, clock, cast(Client, client))
    finally:
        engine.dispose()
