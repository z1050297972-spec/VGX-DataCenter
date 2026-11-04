"""一键部署的独立进程边界；临时源码副本和HOME隔离所有写入与外部命令。"""

import hashlib
import io
import json
import os
import pty
import re
import select
import shutil
import signal
import subprocess
import sys
import tarfile
import time
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class SetupCase:
    """保存单次测试资源；不执行真实仓库中的安装入口。"""

    root: Path
    source: Path
    home: Path
    binary: Path

    def environment(self, overrides: dict[str, str] | None = None) -> dict[str, str]:
        """给所有子进程前置假命令，明确HOME和临时文件位置。"""
        environment = dict(os.environ)
        environment.pop("RDP_CONFIG", None)
        environment.update(
            HOME=str(self.home),
            PATH=str(self.binary),
            TMPDIR=str(self.root / "tmp"),
            SETUP_TEST_ROOT=str(self.root),
        )
        environment.update(overrides or {})
        return environment

    def run(
        self,
        *args: str,
        overrides: dict[str, str] | None = None,
        stop_signal: int = signal.SIGTERM,
    ) -> subprocess.CompletedProcess[str]:
        """固定脚本副本入口，最长十秒；超时由subprocess回收子进程。"""
        process = subprocess.Popen(  # noqa: S603  # 理由：固定bash与临时副本，外部命令全部替换。
            ["/bin/bash", str(self.source / "scripts/setup.sh"), *args],
            cwd=self.root,
            env=self.environment(overrides),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
        try:
            output, errors = _wait_setup(
                process, foreground="--no-systemd" in args, stop_signal=stop_signal
            )
            return subprocess.CompletedProcess(process.args, process.returncode, output, errors)
        finally:
            _reap_group(process)

    def interactive(
        self,
        *args: str,
        answers: str = "n\n",
        prompts: tuple[str, ...] = (),
        overrides: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        """用PTY只承载输入；有界等待并在失败时kill/wait，不安装测试进程信号处理器。"""
        master, slave = pty.openpty()
        process = subprocess.Popen(  # noqa: S603  # 理由：固定脚本副本和临时命令环境。
            ["/bin/bash", str(self.source / "scripts/setup.sh"), *args],
            cwd=self.root,
            env=self.environment(overrides),
            stdin=slave,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            start_new_session=True,
        )
        try:
            prefix = ""
            if prompts:
                assert process.stdout is not None
                deadline = time.monotonic() + 10
                for prompt, answer in zip(prompts, answers.splitlines(), strict=True):
                    while prompt not in prefix:
                        remaining = deadline - time.monotonic()
                        if (
                            remaining <= 0
                            or not select.select([process.stdout], [], [], remaining)[0]
                        ):
                            raise TimeoutError("交互提示超时：" + prefix)
                        chunk = os.read(process.stdout.fileno(), 4096)
                        if not chunk:
                            raise AssertionError("进程提前结束：" + prefix)
                        prefix += chunk.decode()
                    os.write(master, (answer + "\n").encode())
                    prefix = prefix.replace(prompt, "", 1)
            else:
                os.write(master, answers.encode())
            output, _ = _wait_setup(process, foreground="--no-systemd" in args)
            output = prefix + output
            return subprocess.CompletedProcess(process.args, process.returncode, output, "")
        finally:
            _reap_group(process)
            os.close(master)
            os.close(slave)

    def config(self, path: Path | None = None, *, gpus: str = "[]") -> Path:
        """只在临时HOME写合法已有配置，不初始化状态目录或挂载根。"""
        target = path or self.home / ".config/rdp/config.toml"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            f'state_dir = "~/state"\nnav_root = "~/nav"\n[jobs]\ngpus = {gpus}\n[web]\nhost = "127.0.0.1"\nport = 9123\n'
        )
        target.chmod(0o600)
        return target

    def calls(self, command: str | None = None) -> list[dict[str, Any]]:
        """只读取测试自有JSONL调用记录。"""
        log = self.root / "calls.jsonl"
        calls = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
        return [call for call in calls if command is None or call["command"] == command]


def _wait_setup(
    process: subprocess.Popen[str], *, foreground: bool, stop_signal: int = signal.SIGTERM
) -> tuple[str, str]:
    """前台就绪后发TERM模拟操作者停止；全程十秒上限，保留完整诊断。"""
    deadline = time.monotonic() + 10
    stopping = False
    while time.monotonic() < deadline:
        try:
            output, errors = process.communicate(timeout=0.05)
            return output, errors or ""
        except subprocess.TimeoutExpired as error:
            partial = error.output or b""
            if foreground and not stopping and "部署健康".encode() in partial:
                process.send_signal(stop_signal)
                stopping = True
    raise TimeoutError("部署测试超过十秒")


def _reap_group(process: subprocess.Popen[str]) -> None:
    """清理测试创建的整个会话，包括脚本异常退出留下的替身子进程。"""
    with suppress(ProcessLookupError):
        os.killpg(process.pid, signal.SIGKILL)
    process.wait(timeout=2)


def setup_case(root: Path) -> SetupCase:
    """创建脚本副本、用户目录和拒绝未知操作的命令替身。"""
    source, home, binary = root / "source 中文", root / "home", root / "bin"
    for path in (source / "scripts", home, binary, root / "tmp"):
        path.mkdir(parents=True)
    shutil.copyfile(Path(__file__).parents[1] / "scripts/setup.sh", source / "scripts/setup.sh")
    contracts = root / "contracts"
    contracts.mkdir()
    shutil.copyfile(Path(__file__).parents[1] / "scripts/install.sh", contracts / "install.sh")
    # 白名单提供无副作用基础工具；系统管理/硬件/下载命令绝无真实PATH后备。
    for name in (
        "bash",
        "dirname",
        "readlink",
        "mktemp",
        "mkdir",
        "rm",
        "mv",
        "ln",
        "chmod",
        "stat",
        "head",
        "awk",
        "wc",
        "cp",
        "sha256sum",
        "tar",
        "gzip",
        "timeout",
        "flock",
        "cat",
    ):
        (binary / name).symlink_to(Path("/usr/bin") / name)
    dispatcher = binary / "dispatch"
    dispatcher.write_text(f"#!{sys.executable}\n" + _COMMAND)
    dispatcher.chmod(0o700)
    for name in (
        "git",
        "uv",
        "node",
        "pnpm",
        "curl",
        "systemctl",
        "loginctl",
        "nvidia-smi",
        "findmnt",
        "ip",
        "rdp",
        "uname",
        "getconf",
        "id",
        "python",
        "install.sh",
        "sleep",
    ):
        (binary / name).symlink_to(dispatcher)
    (source / "scripts/install.sh").write_text('#!/bin/bash\nexec install.sh "$@"\n')
    return SetupCase(root, source, home, binary)


def tool_downloads(case: SetupCase, *, corrupt: bool = False, traversal: bool = False) -> None:
    """本地构造官方响应形状与可执行工具替身，不读取真实发行归档。"""
    payload = (
        f"#!{sys.executable}\nimport os,sys\nfrom pathlib import Path\n"
        'Path(os.environ["SETUP_TEST_ROOT"], "executed-tool").write_text("node")\n'
        'if sys.argv[1:] == ["--version"]: print("v22.23.2")\n'
        'else: os.execv("/usr/bin/node", ["node", *sys.argv[1:]])\n'
    ).encode()
    archive = case.root / "node.tar.gz"
    with tarfile.open(archive, "w:gz") as stream:
        entry = tarfile.TarInfo("../escape" if traversal else "node-v22.23.2-linux-x64/bin/node")
        entry.mode, entry.size = 0o755, len(payload)
        stream.addfile(entry, io.BytesIO(payload))
    digest = "0" * 64 if corrupt else hashlib.sha256(archive.read_bytes()).hexdigest()
    manifest = case.root / "SHASUMS256.txt"
    manifest.write_text(digest + "  node-v22.23.2-linux-x64.tar.gz\n")
    (case.root / "downloads.json").write_text(
        json.dumps(
            {
                "https://nodejs.org/dist/v22.23.2/SHASUMS256.txt": str(manifest),
                "https://nodejs.org/dist/v22.23.2/node-v22.23.2-linux-x64.tar.gz": str(archive),
            }
        )
    )


def release_url(tool: str, machine: str = "x86_64") -> str:
    """独立构造测试期望的官方发行地址，不读取生产脚本生成期望。"""
    if tool == "uv":
        return f"https://github.com/astral-sh/uv/releases/download/0.13.5/uv-{machine}-unknown-linux-gnu.tar.gz"
    arch = "x64" if machine == "x86_64" else "arm64"
    return f"https://github.com/pnpm/pnpm/releases/download/v11.22.0/pnpm-linux-{arch}.tar.gz"


def pin_release_digest(
    case: SetupCase, tool: str, *, machine: str = "x86_64", digest: str | None = None
) -> None:
    """只替换临时脚本副本的摘要来核验本地归档；生产四个摘要由独立测试逐字核对。"""
    asset = case.root / release_url(tool, machine).rsplit("/", 1)[1]
    expected = hashlib.sha256(asset.read_bytes()).hexdigest() if digest is None else digest
    script = case.source / "scripts/setup.sh"
    pattern = r"(\[" + re.escape(tool + ":" + machine) + r"\]=')[^']*(')"
    text, count = re.subn(pattern, lambda match: match[1] + expected + match[2], script.read_text())
    assert count == 1, "临时脚本必须恰有一个对应摘要项"
    script.write_text(text)


def release_downloads(
    case: SetupCase,
    tool: str,
    *,
    digest: str | None = "valid",
    package_layout: str = "root",
    machine: str = "x86_64",
) -> None:
    """本地构造两种归档结构并固定测试副本摘要；curl只返回这些归档，不模拟API元数据。"""
    version = "0.13.5" if tool == "uv" else "11.22.0"
    url = release_url(tool, machine)
    display_version = f"uv {version} ({machine}-unknown-linux-gnu)" if tool == "uv" else version
    executable = (
        f"#!/bin/sh\nif [ \"$1\" = --version ]; then printf '%s\n' '{display_version}'; "
        f'else exec "$SETUP_TEST_ROOT/bin/{tool}" "$@"; fi\n'
    ).encode()
    asset = case.root / url.rsplit("/", 1)[1]
    with tarfile.open(asset, "w:gz") as stream:
        name = (
            f"uv-{machine}-unknown-linux-gnu/uv"
            if tool == "uv"
            else ("pnpm" if package_layout == "root" else package_layout + "/pnpm")
        )
        entry = tarfile.TarInfo(name)
        entry.mode, entry.size = 0o755, len(executable)
        stream.addfile(entry, io.BytesIO(executable))
    pin_release_digest(
        case, tool, machine=machine, digest=None if digest == "valid" else (digest or "")
    )
    mappings_file = case.root / "downloads.json"
    mappings: dict[str, str] = (
        json.loads(mappings_file.read_text()) if mappings_file.exists() else {}
    )
    mappings[url] = str(asset)
    mappings_file.write_text(json.dumps(mappings))


_COMMAND = """import json, os, sys
from pathlib import Path
root = Path(os.environ["SETUP_TEST_ROOT"])
command, args = Path(sys.argv[0]).name, sys.argv[1:]
with (root / "calls.jsonl").open("a") as stream:
    stream.write(json.dumps({"command":command,"args":args,"cwd":str(Path.cwd()),
      "home":os.environ["HOME"], "config":os.environ.get("RDP_CONFIG"),
      "venv":os.environ.get("UV_PROJECT_ENVIRONMENT"), "virtual_env":os.environ.get("VIRTUAL_ENV"),
      "proxy":os.environ.get("HTTPS_PROXY")}) + "\\n")
if command == "uname":
    print(os.environ.get("FAKE_OS", "Linux") if args == ["-s"] else os.environ.get("FAKE_ARCH", "x86_64")); sys.exit(0)
if command == "getconf":
    print("glibc 2.39"); sys.exit(0)
if command == "git":
    if args[:1] == ["-C"]: args = args[2:]
    if args == ["rev-parse", "--show-toplevel"]: print(root / "source 中文"); sys.exit(0)
    if args[:2] == ["rev-parse", "--verify"]: print("a"*40); sys.exit(0)
if command in ("node", "uv", "pnpm") and args == ["--version"]:
    print(os.environ.get("FAKE_VERSION_" + command.upper(), {"node":"v22.23.2","uv":"uv 0.13.5 (x86_64-unknown-linux-gnu)","pnpm":"11.22.0"}[command])); sys.exit(0)
if command == "git" and args == ["worktree", "list", "--porcelain"]:
    print("worktree " + str(root / "home/.local/opt/rdp")); sys.exit(0)
if command == "rdp":
    # 每次调用先走生产解析器，替身不维护另一份宽松语法，也不执行生产动作。
    from rdp.ops.cli import Console, parse_command
    parse_command(args, console=Console(sys.stdout, sys.stderr, lambda _: ""))
if command == "rdp" and args == ["--version"]:
    if os.environ.get("FAKE_STATUS_FAIL"): sys.exit(19)
    print("0.1.0 (aaaaaaa)"); sys.exit(0)
if command == "rdp" and args == ["status", "--worker-stopped"]:
    sys.exit(int(os.environ.get("FAKE_WORKER_STATUS", "3")))
if command == "rdp" and args == ["status", "--active-jobs"]:
    sys.exit(int(os.environ.get("FAKE_ACTIVE_STATUS", "0")))
if command == "node":
    os.execv("/usr/bin/node", ["node", *args])
if command == "sleep": sys.exit(0)
if command == "curl" and args[-1].startswith("http://"):
    Path(args[args.index("--output") + 1]).write_text(os.environ.get("FAKE_HEALTH_BODY", '{"status":"ok"}'))
    print(os.environ.get("FAKE_HEALTH_STATUS", "200")); sys.exit(0)
if command == "curl":
    import shutil, time
    url = args[-1]
    assert not url.startswith("https://api.github.com/"), "部署禁止请求GitHub API"
    scenario = root / "responses.json"
    responses = json.loads(scenario.read_text()).get(url, []) if scenario.exists() else []
    calls = [json.loads(line) for line in (root / "calls.jsonl").read_text().splitlines()]
    index = sum(call["command"] == "curl" and call["args"][-1] == url for call in calls) - 1
    response = responses[min(index, len(responses) - 1)] if responses else {}
    time.sleep(response.get("delay_s", 0))
    code = str(response.get("code", "200"))
    if "--dump-header" in args:
        Path(args[args.index("--dump-header") + 1]).write_text(
            "HTTP/2 " + code + "\\n" + response.get("headers", "") + "\\n")
    if response.get("exit"):
        print(response.get("code", "000")); print("模拟TLS连接错误", file=sys.stderr); sys.exit(response["exit"])
    destination = Path(args[args.index("--output") + 1])
    if "body" in response:
        destination.write_text(response["body"])
    else:
        mappings = json.loads((root / "downloads.json").read_text())
        if url not in mappings: sys.exit(22)
        shutil.copyfile(mappings[url], destination)
    if "--write-out" in args:
        redirect = response.get("redirect") or os.environ.get("FAKE_REDIRECT")
        if redirect:
            print("302\\n" + redirect)
        else: print(code)
    sys.exit(0)
if command == "id" and args == ["-un"]:
    print("operator"); sys.exit(0)
if command == "systemctl" and args == ["--user", "show-environment"]:
    sys.exit(1 if os.environ.get("FAKE_BUS_FAIL") else 0)
if command == "loginctl":
    if args == ["show-user", "operator", "--property=Linger", "--value"]:
        print(os.environ.get("FAKE_LINGER", "yes")); sys.exit(0)
    if args == ["enable-linger", "operator"]:
        sys.exit(1 if os.environ.get("FAKE_LINGER_FAIL") else 0)
if command == "git" and args[:1] == ["archive"]:
    import tarfile, io
    destination = Path(args[args.index("--output") + 1])
    with tarfile.open(destination, "w") as stream:
        for name in ("pyproject.toml", "uv.lock", "src/rdp/ops/setup_queries.py"):
            if os.environ.get("FAKE_NO_QUERIES") and name.endswith("setup_queries.py"): continue
            entry = tarfile.TarInfo(name); entry.size = 1
            stream.addfile(entry, io.BytesIO(b" "))
    sys.exit(0)
if command == "uv" and args == ["sync", "--frozen", "--no-dev"]:
    folder = Path(os.environ["UV_PROJECT_ENVIRONMENT"]) / "bin"
    folder.mkdir(parents=True)
    (folder / "python").symlink_to(root / "bin/python")
    sys.exit(0)
if command == "python" and args[:1] == ["-c"]:
    os.execv(sys.executable, [sys.executable, *args])
if command == "python" and args[:2] == ["-m", "rdp.ops.setup_queries"]:
    if args[2] == "validate-config" and os.environ.get("FAKE_CONFIG_RACE"):
        import subprocess
        result = subprocess.run([sys.executable, *args], capture_output=True, timeout=3)
        config = root / "home/.config/rdp/config.toml"
        config.parent.mkdir(parents=True, exist_ok=True)
        if os.environ["FAKE_CONFIG_RACE"] == "symlink":
            target = root / "protected"
            target.write_text("other owner")
            config.symlink_to(target)
        else: config.write_text("other owner")
        sys.stdout.buffer.write(result.stdout); sys.stderr.buffer.write(result.stderr)
        sys.exit(result.returncode)
    if args[2] == "administrator":
        from io import StringIO
        from rdp.ops.setup_queries import run_setup_query
        code = run_setup_query(args[2:], home=Path.home(), stdout=StringIO(), stderr=sys.stderr)
        if code: sys.exit(code)
        print(json.dumps({"status": os.environ.get("FAKE_ADMIN", "absent" if (root / "installed").exists() else "database_missing")})); sys.exit(0)
    os.execv(sys.executable, [sys.executable, *args])
if command == "install.sh":
    # source仅定义函数，使用实际安装入口的参数解析；不执行main或任何安装步骤。
    import subprocess
    result = subprocess.run(["/bin/bash", "-c", 'source "$1"; shift; operation=install; _parse_arguments "$@"',
                             "parse-install", str(root / "contracts/install.sh"), *args],
                            timeout=3)
    if result.returncode: sys.exit(result.returncode)
    deploy = Path(args[args.index("--deploy-dir") + 1])
    (deploy / ".venv/bin").mkdir(parents=True)
    for name in ("rdp", "python"):
        (deploy / ".venv/bin" / name).symlink_to(root / "bin" / name)
    (deploy / "rdp-build.json").write_text(json.dumps({"commit": "a"*40}))
    (root / "installed").write_text(str(deploy))
    if os.environ.get("FAKE_INSTALL_FAIL"):
        (deploy / "backup").write_text("preserve"); sys.exit(17)
    sys.exit(0)
if command == "rdp" and args[:1] == ["create-admin"]:
    import getpass
    first, second = getpass.getpass("密码：", stream=sys.stderr), getpass.getpass("再次密码：", stream=sys.stderr)
    if first != second: sys.exit(1)
    (root / "admin-audit").write_text("one operation")
    sys.exit(0)
if command == "systemctl" and args == ["--user", "is-active", "rdp-web.service", "rdp-worker.service"]:
    code = int(os.environ.get("FAKE_UNITS_STATUS", "0"))
    print("active\\nactive" if code == 0 else "inactive\\ninactive")
    sys.exit(code)
if command == "systemctl" and args[:3] == ["--user", "is-active", "--quiet"]:
    sys.exit(1 if os.environ.get("FAKE_SERVICE_FAIL") == args[-1] else 0)
if command == "systemctl" and args[:2] == ["--user", "stop"]:
    assert set(args[2:]) <= {"rdp-web.service", "rdp-worker.service"}; sys.exit(0)
if command == "ip" and args == ["-j", "address", "show"]:
    if os.environ.get("FAKE_IP_FAIL"): sys.exit(7)
    print(os.environ.get("FAKE_IP", '[{"ifname":"eth0","addr_info":[{"family":"inet","local":"192.0.2.55","scope":"global"}]}]')); sys.exit(0)
if command == "rdp" and args in (["web", "--no-stderr"], ["worker", "--no-stderr"]):
    import signal, threading, time
    name = args[0]
    if os.environ.get("FAKE_CHILD_FAIL") == name:
        # 该故障场景验证另一已启动服务被正常回收；等其安装信号处理器，不能依赖进程启动快慢。
        # 32个pytest worker并行时，立即失败可能在另一解释器导入期间触发TERM，来不及写stopped。
        peer = "web" if name == "worker" else "worker"
        deadline = time.monotonic() + 3
        while not (root / (peer + ".pid")).exists():
            if time.monotonic() >= deadline: sys.exit(98)
            time.sleep(0.005)
        sys.exit(19)
    stopped = threading.Event()
    def stop(signum, frame):
        if os.environ.get("FAKE_IGNORE_TERM") != name: stopped.set()
    signal.signal(signal.SIGTERM, stop); signal.signal(signal.SIGINT, stop)
    (root / (name + ".pid")).write_text(str(os.getpid()))
    if not stopped.wait(20): sys.exit(20)
    (root / (name + ".stopped")).write_text("0"); sys.exit(0)
if command == "findmnt":
    print(os.environ.get("FAKE_MOUNTS", '{"filesystems":[]}')); sys.exit(0)
if command == "nvidia-smi":
    if os.environ.get("FAKE_GPU_FAIL"): sys.exit(8)
    print(os.environ.get("FAKE_GPUS", "0\\n2")); sys.exit(0)
print("拒绝未声明假命令：" + command + repr(args), file=sys.stderr)
sys.exit(97)
"""
