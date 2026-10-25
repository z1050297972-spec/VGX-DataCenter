"""演示第 6 张：临时状态目录、迁移、首个管理员、起服务。"""
import sys
from datetime import UTC, datetime
from pathlib import Path

import uvicorn

from rdp.accounts.security import PasswordCodec
from rdp.accounts.service import AccountService
from rdp.api import create_app
from rdp.infra.config import PlatformConfig
from rdp.infra.db.connection import create_database_engine
from rdp.infra.db.migration import migrate
from rdp.infra.state import initialize_state, state_paths
from rdp.ops.accounts import create_first_admin

root = Path(sys.argv[1]); dist = Path(sys.argv[2]); port = int(sys.argv[3])
paths = state_paths(PlatformConfig(state_dir=root), [])
initialize_state(paths)
print(migrate(paths, now=datetime.now(UTC)), flush=True)
engine = create_database_engine(paths.database)
service = AccountService(engine, PasswordCodec())
answers = iter(["Admin-pass-2026!", "Admin-pass-2026!"])
view = create_first_admin(service, "admin", "管理员", now=datetime.now(UTC), read_password=lambda _p: next(answers))
print("first admin:", view, flush=True)
uvicorn.run(create_app(dist, database=engine), host="127.0.0.1", port=port, log_level="warning")
