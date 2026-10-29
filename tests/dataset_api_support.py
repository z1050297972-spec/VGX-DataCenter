"""数据集HTTP测试装配：真实扫描索引、账号认证和ASGI，所有文件都在临时目录。"""

from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from typing import cast

from account_api_support import ApiCase, Clock
from accounts_support import EXAMPLE_SECRET, NOW
from argon2 import PasswordHasher
from datasets_execution_support import dataset_case
from fastapi.testclient import TestClient
from httpx import Client
from jobs_scheduling_support import catalog_fixture
from nav_manifest import FakeNavigation

from rdp.accounts.security import PasswordCodec
from rdp.accounts.service import AccountService
from rdp.accounts.types import Credentials, NewAccount, Role
from rdp.api import create_app
from rdp.api.datasets import configure_datasets
from rdp.api.jobs import configure_jobs
from rdp.audit.types import OPS_AUDIT_CONTEXT
from rdp.jobs.dataset_browser.schemas import RobotModelOption
from rdp.jobs.dataset_browser.service import DatasetBrowserService
from rdp.jobs.registry import production_registry

ENTRY = "按任务/libero_10"
FORMAT_ENTRY = "按格式/lerobot/3.0/libero_10"


@contextmanager
def browser_case(
    root: Path,
    nav: FakeNavigation,
    models: list[RobotModelOption] | None = None,
) -> Generator[ApiCase]:
    """以真实公开扫描接口准备索引，模型目录作为尚未实现M3的外部读取边界注入。"""
    with dataset_case(root, nav) as scan:
        scan.run()
        accounts = AccountService(
            scan.engine, PasswordCodec(PasswordHasher(time_cost=1, memory_cost=1024, parallelism=1))
        )
        accounts.create_first_admin(
            NewAccount(Credentials("admin", EXAMPLE_SECRET), "管理员", Role.ADMINISTRATOR),
            now=NOW,
            audit=OPS_AUDIT_CONTEXT,
        )
        clock = Clock()
        app = create_app(None, database=scan.engine, clock=clock)
        app.state.account_service = accounts
        configured_registry = production_registry()
        configure_jobs(
            app, scan.paths, configured_registry, scheduling=catalog_fixture(configured_registry)
        )
        configure_datasets(
            app,
            DatasetBrowserService(
                scan.engine,
                nav.nav_root,
                app.state.job_service,
                lambda _session: tuple(models or ()),
            ),
        )
        with TestClient(
            app, raise_server_exceptions=False, headers={"Origin": "http://testserver"}
        ) as client:
            case = ApiCase(app, accounts, scan.engine, clock, cast(Client, client))
            assert case.login().status_code == 200
            yield case


def set_meta(
    case: ApiCase,
    path: str,
    label: str | None,
    fps: float | None = None,
    rounded: int | None = None,
) -> None:
    """准备第02张将发布的索引观察；HTTP断言不使用SQL读取结果作期望。"""
    from sqlalchemy import update

    from rdp.infra.db.connection import session_scope
    from rdp.jobs.datasets.models import SourceRow

    with session_scope(case.engine) as session:
        session.execute(
            update(SourceRow)
            .where(SourceRow.entry_path == path)
            .values(
                robot_type=label,
                fps=fps,
                fps_rounded=rounded,
                meta_checked_at=NOW,
            )
        )


def historical_migrations(root: Path) -> Path:
    """冻结0007迁移包，用真实迁移入口验证0008升级而非手写旧表。"""
    import shutil

    from rdp.infra.db.migration import migration_config

    source = Path(migration_config().get_main_option("script_location") or "")
    target = root / "historical/migrations"
    (target / "versions").mkdir(parents=True)
    shutil.copyfile(source / "env.py", target / "env.py")
    for script in (source / "versions").glob("*.py"):
        if script.name < "v0008":
            shutil.copyfile(script, target / "versions" / script.name)
    return target
