"""运维测试的显式系统边界；配置、数据库、挂载表和home全部位于临时目录。"""

import json
import time
from datetime import UTC, datetime
from pathlib import Path

from rdp.infra.config import load_config
from rdp.infra.db.migration import migrate
from rdp.infra.logging import LogTime
from rdp.infra.state import initialize_state, state_paths
from rdp.infra.storage import LinuxMountSource
from rdp.infra.version import DeploymentLayout
from rdp.jobs.types import JobClock
from rdp.ops.runtime import RuntimeInputs

NOW = datetime(2026, 10, 28, 12, tzinfo=UTC)


def runtime_inputs(root: Path, *, migrated: bool = True) -> RuntimeInputs:
    """只建立测试需要的部署结构；不使用真实HOME或读取真实挂载表。"""
    home = root / "home"
    home.mkdir(parents=True)
    config = root / "config.toml"
    tools = root / "tools"
    tools.mkdir()
    config.write_text(
        'state_dir = "~/state"\nnav_root = "~/nav"\n[jobs]\ngpus = []\n'
        + f"[tools]\nregistry_dir = {json.dumps(str(tools))}\nlibrary_root = {json.dumps(str(root / 'library'))}\n"
    )
    dist = root / "src/web/dist"
    dist.mkdir(parents=True)
    (dist / "index.html").write_text("<html>平台</html>")
    build = root / "rdp-build.json"
    build.write_text(json.dumps({"commit": "a" * 40}))
    localtime = root / "localtime"
    localtime.write_bytes(Path("/usr/share/zoneinfo/UTC").read_bytes())
    mountinfo = root / "mountinfo"
    mountinfo.write_text("")
    inputs = RuntimeInputs(
        {"RDP_CONFIG": str(config)},
        home,
        DeploymentLayout(root, dist, build),
        JobClock(lambda: NOW, time.monotonic),
        LogTime(lambda: NOW, lambda: UTC),
        localtime,
        LinuxMountSource(mountinfo, root / "by-uuid"),
        lambda _: None,
        lambda _: "0.1.0",
    )
    if migrated:
        paths = state_paths(load_config(environ=inputs.environ, home=home).config, ())
        initialize_state(paths)
        migrate(paths, now=NOW)
    return inputs
