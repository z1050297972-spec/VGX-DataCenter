"""演示第 10 张：web 模式建临时状态、迁移、首个管理员，按参数登记本机两块盘并起服务。

用法：demo10.py <状态目录> <前端dist> <端口> <dataset2 的 UUID>
只读本机挂载表和 /dev/disk/by-uuid，不访问存储根里的文件。
"""
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import uvicorn

from rdp.accounts.security import PasswordCodec
from rdp.accounts.service import AccountService
from rdp.api import create_app
from rdp.api.jobs import configure_jobs
from rdp.api.storage import configure_storage
from rdp.infra.config import JobsConfig, PlatformConfig, StorageRootConfig
from rdp.infra.db.connection import create_database_engine
from rdp.infra.db.migration import migrate
from rdp.infra.state import initialize_state, state_paths
from rdp.infra.storage import LinuxMountSource, MountInspector
from rdp.jobs.registry import production_registry
from rdp.jobs.schedules import local_timezone, production_schedules
from rdp.jobs.scheduling import resolve_scheduling
from rdp.jobs.scheduling_types import SchedulingCatalog
from rdp.ops.accounts import create_first_admin

root, dist, port, uuid2 = Path(sys.argv[1]), Path(sys.argv[2]), int(sys.argv[3]), sys.argv[4]
mnt = Path("/", "mnt")
roots = (
    StorageRootConfig(name="dataset1", path=mnt / "dataset1", uuid="2d3a48d6-3785-47fe-8c8f-a20857fdc41a"),
    StorageRootConfig(name="dataset2", path=mnt / "dataset2", uuid=uuid2),
)
registry = production_registry()
config = PlatformConfig(state_dir=root, jobs=JobsConfig(), storage_roots=roots)
paths = state_paths(config, [d.display_name for d in registry.definitions()])
catalog = SchedulingCatalog(
    resolve_scheduling(config.jobs, registry), production_schedules(registry), local_timezone(Path("/etc/localtime"))
)
initialize_state(paths)
print(migrate(paths, now=datetime.now(UTC)), flush=True)
engine = create_database_engine(paths.database)
try:
    answers = iter(["Admin-pass-2026!", "Admin-pass-2026!"])
    create_first_admin(AccountService(engine, PasswordCodec()), "admin", "管理员",
                       now=datetime.now(UTC), read_password=lambda _p: next(answers))
except Exception as error:  # 重启时管理员已存在
    print("首个管理员已存在：", type(error).__name__, flush=True)
app = create_app(dist, database=engine)
configure_jobs(app, paths, registry, scheduling=catalog)
source = LinuxMountSource()
configure_storage(app, inspector=MountInspector(config.storage_roots, source.read_mountinfo,
                                                source.resolve_uuid_device, lambda: datetime.now(UTC)))
uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
