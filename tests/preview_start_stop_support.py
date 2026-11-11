"""M5-09 假机器人：本机 bash、临时 HOME、小 wheel/假探针，真实 flock/setsid。"""

import hashlib
import io
import os
import shlex
import signal
import zipfile
from collections.abc import Generator
from contextlib import contextmanager, suppress
from pathlib import Path

import pytest
from account_api_support import ApiCase
from jobs_process_resources import adopt_orphans, reap_known
from robot_connection_support import readiness_ssh, run

from rdp.infra import viz_relay


def prepare(
    root: Path, monkeypatch: pytest.MonkeyPatch, *, missing: str = ""
) -> tuple[Path, Path, Path]:
    """建立独立厂商夹具与假转发包，任何文件都只位于测试临时目录。"""
    home = root / "robot-home"
    home.mkdir()
    probes = root / "probes"
    ssh = readiness_ssh(root, missing=missing)
    (probes / "ss").write_text(
        '#!/bin/sh\nif [ "$1" = "-Huln" ]; then echo "UNCONN 0 0 0.0.0.0:11811 0.0.0.0:*"; else test ! -f "$HOME/occupied" || echo "LISTEN 0 0 0.0.0.0:8765 0.0.0.0:*"; fi\n'
    )
    source = root / "fake-relay"
    source.mkdir()
    (source / "__init__.py").write_text("")
    (source / "__main__.py").write_text("""import json, os, signal, sys, time
from pathlib import Path
import foxglove, rdp_test_ros
assert foxglove.TEST_SDK == "offline fixture"
assert rdp_test_ros.TEST_ROS == "system ROS fixture"
assert sys.prefix == sys.base_prefix
assert os.environ['LANG'] == 'C.UTF-8'
assert os.environ['TEST_ROS_SETUP'] == '1'
assert os.environ['ROS_LOCALHOST_ONLY'] == '0'
assert 'ROS_DOMAIN_ID' not in os.environ
assert os.environ['PYTHONDONTWRITEBYTECODE'] == '1'
assert os.environ['PYTHONUNBUFFERED'] == '1'
root = Path.home() / 'rdp_viz'
assert Path(foxglove.__file__).parent == root / 'site/foxglove'
assert os.environ['ROS_HOME'] == str(root / 'ros_home')
assert os.environ['ROS_LOG_DIR'] == str(root / 'log/ros')
assert os.environ['FASTRTPS_DEFAULT_PROFILES_FILE'] == str(root / 'fastdds_local.xml')
assert '127.0.0.1' in (root / 'fastdds_local.xml').read_text()
json.loads(Path(sys.argv[sys.argv.index('--config') + 1]).read_text())
if '--self-test' in sys.argv:
    print('RDP_VIZ_SELFTEST ok', flush=True)
    (root / 'self-tested').touch()
else:
    with (root / 'test-pids').open('a') as stream: stream.write(str(os.getpid()) + '\\n')
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    print('RDP_VIZ_READY port=8765', flush=True)
    while True: time.sleep(0.05)
""")
    # 厂商环境是只读输入，刻意含 shell 注入片段，证明只按路径字面量 source。
    vendor = root / "vendor"
    vendor.mkdir()
    setup = vendor / "setup'; touch injected #.bash"
    ros = vendor / "ros"
    ros.mkdir()
    (ros / "rdp_test_ros.py").write_text('TEST_ROS = "system ROS fixture"\n')
    setup.write_text(
        f"export TEST_ROS_SETUP=1\nexport PYTHONPATH='{ros}'\n"
        + "export PATH="
        + shlex.quote(str(probes))
        + ":/usr/bin:/bin\n"
    )
    xml = vendor / "discovery.xml"
    xml.write_text("<profiles><address>10.0.0.1</address><address>10.0.0.2</address></profiles>")
    profiles = root / "profiles"
    profiles.mkdir(exist_ok=True)
    text = (
        Path("profiles/r1lite.toml")
        .read_text()
        .replace("/opt/ros/humble/setup.bash", str(setup))
        .replace("/opt/galaxea/find_server/super_client_profile.xml", str(xml))
    )
    (profiles / "r1lite.toml").write_text(text)
    ssh.write_text(
        "#!/usr/bin/python3\nimport sys, os, subprocess\nfrom pathlib import Path\n"
        "a=sys.argv[1:]\nassert a[a.index('--')+1:] == ['127.0.0.1', 'bash', '-s']\n"
        "script = sys.stdin.read()\nassert 'sudo' not in script\n"
        f"env=dict(os.environ, HOME={str(home)!r}, USER='tester', PATH={str(probes)!r}+':/usr/bin:/bin')\n"
        "sys.exit(subprocess.run(['/bin/bash','-s'], input=script, text=True, env=env, cwd=env['HOME'], timeout=35, check=False).returncode)\n"
    )
    monkeypatch.setattr(viz_relay, "WHEEL_SHA256", hashlib.sha256(wheel_bytes()).hexdigest())
    return ssh, profiles, source


def wheel_bytes() -> bytes:
    """自造固定内容的小 wheel，真实解压和版本查询无需读取离线缓存或安装依赖。"""
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as wheel:
        # 固定 ZIP 时间戳，让传输夹具与注入摘要在多次调用间一致。
        wheel.writestr(zipfile.ZipInfo("foxglove/__init__.py"), 'TEST_SDK = "offline fixture"\n')
        wheel.writestr(
            zipfile.ZipInfo("foxglove_sdk-0.30.3.dist-info/METADATA"),
            "Metadata-Version: 2.1\nName: foxglove-sdk\nVersion: 0.30.3\n",
        )
    return output.getvalue()


def install_wheel(api: ApiCase) -> Path:
    """工作站小 wheel 夹具，与注入的摘要一致。"""
    path = api.app.state.job_paths.root / "viz_relay/wheels" / viz_relay.WHEEL_FILENAME
    path.parent.mkdir(parents=True)
    path.write_bytes(wheel_bytes())
    return path


def submit_preview(api: ApiCase, robot_id: int, action: str) -> str:
    """经公开作业接口提交启停，参数只含机器人编号。"""
    response = api.client.post(
        "/api/jobs",
        json={"type_name": f"robot_preview_{action}", "parameters": {"robot_id": robot_id}},
    )
    assert response.status_code == 201, response.text
    return response.json()["job_id"]


def execute_preview(api: ApiCase, job_id: str, setup: tuple[Path, Path, Path]) -> None:
    """沿用真实执行器，只注入假 SSH、说明档和假程序来源目录。"""
    ssh, profiles, source = setup
    run(api, job_id, ssh, profiles_dir=profiles, relay_source=source)


@contextmanager
def reap_relay(home: Path) -> Generator[None]:
    """测试不论成功失败都清理脱离 SSH 会话的假转发进程组。"""
    with adopt_orphans():
        try:
            yield
        finally:
            record = home / "rdp_viz/test-pids"
            pidfile = home / "rdp_viz/run/relay.pid"
            pids: set[str] = set(record.read_text().splitlines()) if record.exists() else set()
            if pidfile.exists():
                pids.add(pidfile.read_text().strip())
            for value in pids:
                pid = int(value)
                with suppress(ProcessLookupError):
                    os.killpg(pid, signal.SIGKILL)
                reap_known(pid)
