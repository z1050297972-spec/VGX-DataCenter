"""演示第 8 张：web 模式建临时状态、迁移、首个管理员并起服务；worker 模式起独立 worker。"""
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
from rdp.infra.config import PlatformConfig
from rdp.infra.db.connection import create_database_engine
from rdp.infra.db.migration import migrate
from rdp.infra.logging import LoggingSettings
from rdp.infra.state import initialize_state, state_paths
from rdp.jobs.execution import ExecutorDependencies
from rdp.jobs.registry import production_registry
from rdp.jobs.types import JobClock
from rdp.ops.accounts import create_first_admin
from rdp.ops.worker import run_worker

mode, root = sys.argv[1], Path(sys.argv[2])
registry = production_registry()
paths = state_paths(PlatformConfig(state_dir=root), [d.display_name for d in registry.definitions()])
if mode == "web":
    dist, port = Path(sys.argv[3]), int(sys.argv[4])
    initialize_state(paths)
    print(migrate(paths, now=datetime.now(UTC)), flush=True)
    engine = create_database_engine(paths.database)
    answers = iter(["Admin-pass-2026!", "Admin-pass-2026!"])
    create_first_admin(AccountService(engine, PasswordCodec()), "admin", "管理员",
                       now=datetime.now(UTC), read_password=lambda _p: next(answers))
    app = create_app(dist, database=engine)
    configure_jobs(app, paths, registry)
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
else:
    engine = create_database_engine(paths.database)
    stop = Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    result = run_worker(
        ExecutorDependencies(engine, registry, paths, JobClock(lambda: datetime.now(UTC), time.monotonic)),
        stop, LoggingSettings("worker", paths.logs),
    )
    print("worker exit:", result, flush=True)
    sys.exit(result.code)
