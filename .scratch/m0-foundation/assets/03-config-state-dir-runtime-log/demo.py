"""演示（验收第 9 条，P3 改过）：按第 11 张将来启动命令的顺序起 Web。只用临时配置和临时状态目录。"""
import os, sys
from pathlib import Path
import uvicorn
from rdp.api import create_app
from rdp.infra.config import load_config
from rdp.infra.logging import LoggingSettings, configure_logging, log_config_source, log_state_warnings
from rdp.infra.state import initialize_state, state_paths

loaded = load_config(environ={"RDP_CONFIG": os.environ["RDP_CONFIG"]}, home=Path(sys.argv[1]))
paths = state_paths(loaded.config, ())
loose = initialize_state(paths)
configure_logging(LoggingSettings("web", paths.logs, stderr=False, log=loaded.config.log))
log_config_source(loaded)
log_state_warnings(loose)
uvicorn.run(create_app(None), host=loaded.config.web.host, port=loaded.config.web.port, log_config=None, access_log=False)
