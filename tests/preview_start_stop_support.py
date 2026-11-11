"""M5-09 假机器人：本机 bash、临时 HOME、假 Python/探针，真实 flock/setsid。"""

import hashlib
import os
import signal
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
assert os.environ['LANG'] == 'C.UTF-8'
assert os.environ['TEST_ROS_SETUP'] == '1'
assert os.environ['ROS_LOCALHOST_ONLY'] == '0'
assert 'ROS_DOMAIN_ID' not in os.environ
assert os.environ['PYTHONDONTWRITEBYTECODE'] == '1'
assert os.environ['PYTHONUNBUFFERED'] == '1'
root = Path.home() / 'rdp_viz'
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
    # 假 venv Python 只替换安装边界；运行模块及 XML 处理仍使用系统 Python。
    wrapper = root / "venv-python"
    wrapper.write_text("""#!/usr/bin/python3
import os, sys
from pathlib import Path
root = Path.home() / 'rdp_viz'
a = sys.argv[1:]
if a[:2] == ['-m', 'pip']:
    assert a[2:5] == ['install', '--no-index', '--no-deps']
    assert os.environ['TMPDIR'] == str(root / 'tmp')
    assert os.environ['PIP_NO_CACHE_DIR'] == '1'
    assert os.environ['PIP_DISABLE_PIP_VERSION_CHECK'] == '1'
    assert Path(a[-1]).read_bytes() == b'test-wheel'
    (root / 'sdk-installed').touch()
elif a and a[0] == '-c' and 'importlib.metadata' in a[1]:
    sys.exit(0 if (root / 'sdk-installed').exists() else 1)
else:
    os.execv('/usr/bin/python3', ['/usr/bin/python3', *a])
""")
    wrapper.chmod(0o700)
    python = probes / "python3"
    python.write_text(
        "#!/usr/bin/python3\nimport os, sys, shutil\nfrom pathlib import Path\na=sys.argv[1:]\n"
        "if a[:2] == ['-m', 'venv']:\n"
        "    assert a[2] == '--system-site-packages'\n"
        "    assert os.environ['TMPDIR'] == str(Path.home() / 'rdp_viz/tmp')\n"
        "    target = Path(a[3]) / 'bin/python'\n"
        "    target.parent.mkdir(parents=True)\n"
        f"    shutil.copyfile({str(wrapper)!r}, target)\n"
        "    target.chmod(0o700)\n"
        "else: os.execv('/usr/bin/python3', ['/usr/bin/python3', *a])\n"
    )
    python.chmod(0o700)
    # 厂商环境是只读输入，刻意含 shell 注入片段，证明只按路径字面量 source。
    vendor = root / "vendor"
    vendor.mkdir()
    setup = vendor / "setup'; touch injected #.bash"
    setup.write_text("export TEST_ROS_SETUP=1\n")
    xml = vendor / "discovery.xml"
    xml.write_text("<profiles><address>10.0.0.1</address><address>10.0.0.2</address></profiles>")
    profiles = root / "profiles"
    profiles.mkdir()
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
    monkeypatch.setattr(viz_relay, "WHEEL_SHA256", hashlib.sha256(b"test-wheel").hexdigest())
    return ssh, profiles, source


def install_wheel(api: ApiCase) -> Path:
    """工作站小 wheel 夹具，与注入的摘要一致。"""
    path = api.app.state.job_paths.root / "viz_relay/wheels" / viz_relay.WHEEL_FILENAME
    path.parent.mkdir(parents=True)
    path.write_bytes(b"test-wheel")
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
