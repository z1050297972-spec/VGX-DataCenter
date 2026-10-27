"""演示第 9 张：web 模式建临时状态、迁移、首个管理员并起服务；worker 模式用真实 nvidia-smi 起独立 worker。"""
import shutil
import signal
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from threading import Event

import uvicorn

from rdp.accounts.security import PasswordCodec
from rdp.accounts.service import AccountService
from rdp.api import create_app
from rdp.api.jobs import configure_jobs
from rdp.infra.config import JobsConfig, PlatformConfig
from rdp.infra.db.connection import create_database_engine
from rdp.infra.db.migration import migrate
from rdp.infra.logging import LoggingSettings
from rdp.infra.state import initialize_state, state_paths
from rdp.jobs.execution import ExecutorDependencies
from rdp.jobs.registry import production_registry
from rdp.jobs.schedules import local_timezone, production_schedules
from rdp.jobs.scheduling import WorkerScheduling, resolve_scheduling
from rdp.jobs.scheduling_types import SchedulingCatalog
from rdp.jobs.types import JobClock
from rdp.ops.accounts import create_first_admin
from rdp.ops.worker import run_worker

mode, root = sys.argv[1], Path(sys.argv[2])
registry = production_registry()
config = PlatformConfig(state_dir=root, jobs=JobsConfig(gpus=(0, 1), concurrency={"example_gpu": 3, "example_navigation": 2}))
paths = state_paths(config, [d.display_name for d in registry.definitions()])
catalog = SchedulingCatalog(
    resolve_scheduling(config.jobs, registry), production_schedules(registry), local_timezone(Path("/etc/localtime"))
)
if mode == "web":
    dist, port = Path(sys.argv[3]), int(sys.argv[4])
    initialize_state(paths)
    print(migrate(paths, now=datetime.now(UTC)), flush=True)
    engine = create_database_engine(paths.database)
    answers = iter(["Admin-pass-2026!", "Admin-pass-2026!"])
    create_first_admin(AccountService(engine, PasswordCodec()), "admin", "管理员",
                       now=datetime.now(UTC), read_password=lambda _p: next(answers))
    app = create_app(dist, database=engine)
    configure_jobs(app, paths, registry, scheduling=catalog)
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
else:
    engine = create_database_engine(paths.database)
    stop = Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    smi = Path(shutil.which("nvidia-smi") or "/usr/bin/nvidia-smi")
    result = run_worker(
        ExecutorDependencies(engine, registry, paths, JobClock(lambda: datetime.now(UTC), time.monotonic), resources=None),
        stop, LoggingSettings("worker", paths.logs),
        scheduling=WorkerScheduling(catalog, smi, config.errors.retention_days),
    )
    print("worker exit:", result, flush=True)
    sys.exit(result.code)
