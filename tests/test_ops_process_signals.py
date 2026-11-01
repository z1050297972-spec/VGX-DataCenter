"""真实CLI子进程的停止契约；源码副本、配置、构建目录和HOME全部位于临时目录。"""

import json
import shutil
import signal
import socket
import subprocess
import sys
import time
from collections.abc import Callable, Generator
from contextlib import closing, contextmanager, suppress
from dataclasses import dataclass
from http.client import HTTPConnection, HTTPException
from pathlib import Path
from typing import Literal

import pytest

import rdp
from rdp.ops.status import check_worker_stopped

# 实际启动含迁移与Argon2初始化，十秒给繁忙测试机留余量；停止也须在十秒内返回。
_START_TIMEOUT_S = 10.0
_STOP_TIMEOUT_S = 10.0
# 本地健康探测单次最多200毫秒；轮询间隔20毫秒，不访问任何外部主机。
_HEALTH_TIMEOUT_S = 0.2
_POLL_INTERVAL_S = 0.02
# 超时后SIGKILL回收最多五秒，不能把孤儿子进程留给后续测试。
_REAP_TIMEOUT_S = 5.0


@dataclass(frozen=True)
class _Deployment:
    """一次真实进程测试的私有部署位置及显式环境。"""

    root: Path
    home: Path
    port: int
    environment: dict[str, str]

    def log(self, name: str) -> str:
        """读取本次进程的文件日志，尚未创建时返回空文本供就绪轮询。"""
        path = self.home / "state/logs" / f"{name}.log"
        return path.read_text() if path.exists() else ""


@pytest.fixture
def deployment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> _Deployment:
    """复制当前包并迁移临时库，确保生产入口发现临时dist，不依赖工作目录已有前端构建。"""
    home, root = tmp_path / "home", tmp_path / "deployment"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    shutil.copytree(
        Path(rdp.__file__).parent, root / "src/rdp", ignore=shutil.ignore_patterns("__pycache__")
    )
    # 子进程保留真实 worker 生命周期，但镜像检查必须使用内存传输，不能访问外网。
    (root / "src/sitecustomize.py").write_text(
        "from rdp.jobs.downloads.plan import HttpResponse, UrllibTransport\n"
        "def _fake(self, method, url, *, headers, timeout_s):\n"
        "    return HttpResponse(200, {}, b'')\n"
        "UrllibTransport.request = _fake\n"
    )
    dist = root / "src/web/dist"
    dist.mkdir(parents=True)
    (dist / "index.html").write_text("<html>进程退出测试</html>")
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    config = home / "config.toml"
    config.write_text(
        'state_dir = "~/state"\nnav_root = "~/nav"\nstorage_roots = []\n'
        f'[web]\nhost = "127.0.0.1"\nport = {port}\n[jobs]\ngpus = []\n'
    )
    environment = {
        "HOME": str(home),
        "RDP_CONFIG": str(config),
        "PYTHONPATH": str(root / "src"),
        "PYTHONNOUSERSITE": "1",
    }
    # 只运行当前解释器和本项目CLI；显式HOME、配置与包路径均指向本次临时目录。
    subprocess.run(
        [sys.executable, "-m", "rdp", "migrate"],
        cwd=root,
        env=environment,
        capture_output=True,
        timeout=_START_TIMEOUT_S,
        check=True,
    )
    return _Deployment(root, home, port, environment)


@contextmanager
def _running(
    deployment: _Deployment, command: Literal["web", "worker"], *, probe_handlers: bool = False
) -> Generator[subprocess.Popen[bytes]]:
    """真实运行服务，所有异常/超时路径均kill并wait；不安装pytest进程的信号处理器。"""
    with (deployment.root / f"{command}-console.log").open("wb") as output:
        arguments = [sys.executable, "-m", "rdp", command, "--no-stderr"]
        if probe_handlers:
            arguments = [sys.executable, "-c", _RESTORE_PROBE, command, "--no-stderr"]
        # 只启动当前解释器及固定CLI命令；独立会话避免Ctrl+C扩散到pytest或其他进程。
        process = subprocess.Popen(  # noqa: S603
            arguments,
            cwd=deployment.root,
            env=deployment.environment,
            stdout=output,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        try:
            yield process
        finally:
            if process.poll() is None:
                with suppress(ProcessLookupError):
                    process.kill()
                process.wait(timeout=_REAP_TIMEOUT_S)


def _wait_ready(process: subprocess.Popen[bytes], ready: Callable[[], bool]) -> None:
    """在单调总预算内等待真实就绪，提前退出或到期均失败并交上下文回收子进程。"""
    deadline = time.monotonic() + _START_TIMEOUT_S
    while time.monotonic() < deadline:
        assert process.poll() is None, f"服务提前退出：{process.returncode}"
        if ready():
            return
        time.sleep(_POLL_INTERVAL_S)
    pytest.fail("服务未在启动预算内就绪")


def _healthy(port: int) -> bool:
    """只请求本机临时端口的健康接口，不读取代理环境变量。"""
    try:
        with closing(HTTPConnection("127.0.0.1", port, timeout=_HEALTH_TIMEOUT_S)) as connection:
            connection.request("GET", "/api/health")
            response = connection.getresponse()
            return response.status == 200 and json.loads(response.read(4096)) == {"status": "ok"}
    except (OSError, HTTPException):
        return False


@pytest.mark.parametrize("stop_signal", (signal.SIGTERM, signal.SIGINT), ids=("sigterm", "sigint"))
def test_web_process_graceful_stop(deployment: _Deployment, stop_signal: signal.Signals) -> None:
    """真实python -m rdp web就绪后收到停止信号必须返回0，并执行start_web的结束日志。"""
    with _running(deployment, "web") as process:
        _wait_ready(process, lambda: _healthy(deployment.port))
        process.send_signal(stop_signal)
        code = process.wait(timeout=_STOP_TIMEOUT_S)
    text = deployment.log("web")
    assert code == 0 and text.count("Web结束运行：正常停止 exit_code=0") == 1, (
        f"returncode={code}; Web结束运行={text.count('Web结束运行')}; 日志：\n{text}"
    )
    assert text.count("INFO rdp.api.production Web开始运行") == 1
    assert "Finished server process" in text
    assert "uvicorn.access" not in text


def test_worker_process_sigterm(deployment: _Deployment) -> None:
    """真实worker取得临时实例锁后收到SIGTERM，必须有界返回0并留下开始和结束日志。"""
    lock = deployment.home / "state/worker.lock"
    with _running(deployment, "worker") as process:
        _wait_ready(
            process,
            lambda: (
                "worker开始运行" in deployment.log("worker")
                and not check_worker_stopped(lock).allowed
            ),
        )
        process.send_signal(signal.SIGTERM)
        code = process.wait(timeout=_STOP_TIMEOUT_S)
    text = deployment.log("worker")
    assert code == 0, text
    assert text.count("INFO rdp.ops.worker worker开始运行") == 1
    assert text.count("INFO rdp.ops.worker worker结束运行：worker已停止 exit_code=0") == 1
    assert check_worker_stopped(lock).allowed


# 探针仍调用公开CLI main；仅在子进程安装原处理器，观察真实运行器返回后的恢复与重放行为。
_RESTORE_PROBE = """import json, signal, sys
from pathlib import Path
from rdp.cli import main
observed = []
def previous(number, frame):
    observed.append(number)
for number in (signal.SIGTERM, signal.SIGINT):
    signal.signal(number, previous)
code = main(sys.argv[1:])
restored = all(signal.getsignal(number) is previous for number in (signal.SIGTERM, signal.SIGINT))
Path("signal-handlers.json").write_text(json.dumps({"code": code, "restored": restored, "replayed": observed}))
raise SystemExit(code)
"""


@pytest.mark.parametrize("stop_signal", (signal.SIGTERM, signal.SIGINT), ids=("sigterm", "sigint"))
def test_web_restores_handlers_without_replay(
    deployment: _Deployment, stop_signal: signal.Signals
) -> None:
    """真实服务返回后恢复两个原处理器，已处理信号不能再交给原处理器重复执行。"""
    with _running(deployment, "web", probe_handlers=True) as process:
        _wait_ready(process, lambda: _healthy(deployment.port))
        process.send_signal(stop_signal)
        assert process.wait(timeout=_STOP_TIMEOUT_S) == 0
    assert json.loads((deployment.root / "signal-handlers.json").read_text()) == {
        "code": 0,
        "restored": True,
        "replayed": [],
    }
