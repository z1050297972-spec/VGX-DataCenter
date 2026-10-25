"""演示（验收第 10 条）：执行线在沙箱外，在临时状态目录里 migrate、起应用、触发一个程序缺陷，在页面上按错误编号点开完整报错。

只用临时状态目录，不碰真实的 ~/.local/share/rdp。生产代码里没有演示接口：页面只调 /api/health，
所以本脚本按环境变量 DEMO_HEALTH=defect 把 /api/health 换成重现代表性故障示例二（Path(None) 的 TypeError）的路由。

用法：python demo.py migrate <状态目录>            # 只跑 migrate，打印 MigrationResult
      python demo.py serve <状态目录> <前端构建目录> <端口>  # 起 Web（DEMO_HEALTH=ok|defect）
"""

import os
import sys
from datetime import UTC, datetime
from pathlib import Path

import uvicorn

from rdp.api import create_app
from rdp.infra.config import PlatformConfig
from rdp.infra.db.connection import create_database_engine
from rdp.infra.db.migration import migrate
from rdp.infra.logging import LoggingSettings, configure_logging
from rdp.infra.state import initialize_state, state_paths

mode, state = sys.argv[1], Path(sys.argv[2])
paths = state_paths(PlatformConfig(state_dir=state), [])
initialize_state(paths)
if mode == "migrate":
    print(migrate(paths, now=datetime.now(UTC)))
    sys.exit(0)

dist, port = Path(sys.argv[3]), int(sys.argv[4])
configure_logging(LoggingSettings("web", paths.logs, stderr=False))
engine = create_database_engine(paths.database)


def fail_defect() -> None:
    raw: dict[str, str | None] = {"target": None}
    Path(raw["target"])  # type: ignore[arg-type]  # 故意重现示例二的 TypeError


app = create_app(dist, database=engine)
if os.environ.get("DEMO_HEALTH", "ok") == "defect":
    app.router.routes = [r for r in app.router.routes if getattr(r, "path", None) != "/api/health"]
    app.add_api_route("/api/health", fail_defect, methods=["GET"])
    app.router.routes.insert(0, app.router.routes.pop())
    app.openapi_schema = None
try:
    uvicorn.run(app, host="127.0.0.1", port=port, log_config=None, access_log=False)
finally:
    engine.dispose()
