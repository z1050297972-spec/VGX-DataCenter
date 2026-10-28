"""部署脚本的外部命令替身；所有写入限定在测试临时目录，未知命令直接失败。"""

import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TypedDict, cast


class Call(TypedDict):
    """外部命令的独立可观察调用记录。"""

    command: str
    args: list[str]
    cwd: str
    home: str
    virtual_env: str | None
    config: str | None
    program: str


@dataclass
class DeploymentCase:
    """一次测试拥有的源码副本、假命令、部署目标和独立HOME。"""

    root: Path
    source: Path
    home: Path
    bin: Path
    log: Path
    deploy: Path

    def run(
        self, script: str, *args: str, answer: str = "y\n", overrides: dict[str, str] | None = None
    ) -> subprocess.CompletedProcess[str]:
        """执行源码副本中的脚本，显式隔离HOME/PATH，子进程最多十秒。"""
        environment = dict(os.environ)
        environment.pop("RDP_CONFIG", None)
        environment.update(
            HOME=str(self.home),
            PATH=f"{self.bin}:/usr/bin:/bin",
            DEPLOY_TEST_ROOT=str(self.root),
            TMPDIR=str(self.root / "tmp"),
        )
        if script == "upgrade.sh":
            environment["FAKE_TARGET"] = "c" * 40
        environment.update(overrides or {})
        # 参数来自测试固定脚本名；所有部署外部命令由临时PATH替换。
        return subprocess.run(  # noqa: S603
            ["/bin/bash", str(self.source / "scripts" / script), *args],
            cwd=self.root,
            env=environment,
            input=answer,
            text=True,
            capture_output=True,
            timeout=10,
            check=False,
        )

    def calls(self) -> list[Call]:
        """读取假命令追加的JSON行，未执行命令时返回空列表。"""
        if not self.log.exists():
            return []
        return [cast(Call, json.loads(line)) for line in self.log.read_text().splitlines()]


def deployment_case(root: Path) -> DeploymentCase:
    """复制待测脚本与单元；不复制真实仓库、虚拟环境或用户配置。"""
    source, home, binary = root / "source", root / "home", root / "bin"
    for path in (source / "scripts/systemd", home, binary, root / "tmp"):
        path.mkdir(parents=True)
    repository = Path(__file__).parents[1]
    for name in (
        "install.sh",
        "upgrade.sh",
        "systemd/rdp-web.service",
        "systemd/rdp-worker.service",
    ):
        shutil.copyfile(repository / "scripts" / name, source / "scripts" / name)
    dispatcher = binary / "fake-command"
    dispatcher.write_text(f"#!{sys.executable}\n" + _FAKE_COMMAND)
    dispatcher.chmod(0o700)
    for name in ("git", "uv", "pnpm", "systemctl", "rdp", "loginctl"):
        (binary / name).symlink_to(dispatcher)
    return DeploymentCase(root, source, home, binary, root / "calls.jsonl", home / ".local/opt/rdp")


# 替身只记录、拒绝；各命令的最小协议随对应公开行为测试扩展。
_FAKE_COMMAND = """import json, os, sys
from pathlib import Path
root = Path(os.environ["DEPLOY_TEST_ROOT"])
with (root / "calls.jsonl").open("a") as stream:
    stream.write(json.dumps({"command": Path(sys.argv[0]).name, "args": sys.argv[1:], "cwd": str(Path.cwd()), "home": os.environ["HOME"], "virtual_env": os.environ.get("VIRTUAL_ENV"), "config": os.environ.get("RDP_CONFIG"), "program": sys.argv[0]}) + "\\n")
command, args = Path(sys.argv[0]).name, sys.argv[1:]
failure = os.environ.get("FAKE_FAIL", "")
labels = {"uv": "uv", "pnpm": "pnpm-install" if args[:1] == ["install"] else "vite"}
if failure and labels.get(command) == failure:
    sys.exit(17)
if command == "mv":
    incoming, destination = Path(args[-2]), Path(args[-1])
    assert incoming.is_relative_to(root) and destination.is_relative_to(root)
    if destination.name == "rdp-build.json":
        assert incoming != destination and incoming.parent == destination.parent
        before = destination.read_text() if destination.exists() else None
        after = json.loads(incoming.read_text())
        (root / "atomic-observation.json").write_text(json.dumps({"before": before, "after": after}))
        if failure == "publish": sys.exit(20)
    os.replace(incoming, destination); sys.exit(0)
source = root / "source"
target = os.environ.get("FAKE_TARGET", "b" * 40)
if command == "git":
    if args[:1] == ["-C"]:
        cwd, args = Path(args[1]), args[2:]
    else:
        cwd = Path.cwd()
    if args == ["rev-parse", "--show-toplevel"]:
        print(cwd.resolve()); sys.exit(0)
    if args == ["status", "--porcelain", "--untracked-files=all", "-z"]:
        sys.stdout.write(os.environ.get("FAKE_DIRTY", "?? rdp-build.json") + "\\0")
        sys.exit(0)
    if args == ["rev-parse", "HEAD"]:
        print((root / "head").read_text()); sys.exit(0)
    if args == ["worktree", "list", "--porcelain", "-z"]:
        deploy = (root / "deployment").read_text()
        sys.stdout.write("worktree " + str(source) + "\\0branch refs/heads/main\\0\\0worktree " + deploy + "\\0detached\\0\\0")
        sys.exit(0)
    if args[:2] == ["rev-parse", "--verify"]:
        print(target); sys.exit(0)
    if args[:2] == ["checkout", "--detach"]:
        assert cwd == Path((root / "deployment").read_text())
        (root / "head").write_text(args[-1]); sys.exit(0)
    if args[:2] == ["worktree", "add"]:
        import shutil
        deploy = Path(args[-2])
        assert deploy.is_relative_to(root)
        deploy.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source / "scripts", deploy / "scripts", dirs_exist_ok=True)
        (root / "deployment").write_text(str(deploy))
        (root / "head").write_text(target)
        sys.exit(0)
if command == "uv" and args == ["sync", "--frozen"]:
    deploy = Path.cwd()
    (deploy / ".venv/bin").mkdir(parents=True, exist_ok=True)
    entry = deploy / ".venv/bin/rdp"
    if not entry.exists(): entry.symlink_to(root / "bin/rdp")
    (deploy / "src/web").mkdir(parents=True, exist_ok=True)
    sys.exit(0)
if command == "pnpm" and args in (["install", "--frozen-lockfile"], ["exec", "vite", "build"]):
    sys.exit(0)
if command == "rdp" and args == ["--version"]:
    deploy = Path((root / "deployment").read_text())
    commit = json.loads((deploy / "rdp-build.json").read_text())["commit"]
    assert commit == (root / "head").read_text()
    print("0.1.0 (" + commit[:7] + ")"); sys.exit(0)
if command == "rdp" and args == ["status", "--active-jobs"]:
    count_file = root / "active-count"
    count = int(count_file.read_text()) if count_file.exists() else 0
    count_file.write_text(str(count + 1))
    codes = os.environ.get("FAKE_ACTIVE", "0").split(",")
    sys.exit(int(codes[min(count, len(codes)-1)]))
if command == "rdp" and args == ["status", "--worker-stopped"]:
    sys.exit(int(os.environ.get("FAKE_WORKER_CODE", "0")))
if command == "rdp" and args in (["migrate"], ["status", "--check-port"]):
    deploy = Path((root / "deployment").read_text())
    assert json.loads((deploy / "rdp-build.json").read_text()) == {"commit": (root / "head").read_text()}
    if args == ["migrate"] and failure == "migrate":
        (deploy / "migration-backup").write_text("backup evidence")
        sys.exit(19)
    if args == ["status", "--check-port"]:
        sys.exit(int(os.environ.get("FAKE_PORT_CODE", "0")))
    sys.exit(0)
if command == "systemctl" and args[:2] in (["--user", "stop"], ["--user", "start"]):
    assert args[2] in ("rdp-web.service", "rdp-worker.service")
    if failure == args[1] + "-" + args[2]: sys.exit(18)
    (root / args[2]).write_text("inactive" if args[1] == "stop" else "active")
    sys.exit(0)
if command == "systemctl" and args[:4] == ["--user", "show", "--property=ActiveState", "--value"]:
    if os.environ.get("FAKE_STILL_ACTIVE") == args[4]: print("active")
    else: print((root / args[4]).read_text())
    sys.exit(0)
if command == "systemctl" and args in (["--user", "daemon-reload"], ["--user", "enable", "--now", "rdp-worker.service", "rdp-web.service"]):
    units = Path(os.environ["HOME"]) / ".config/systemd/user"
    assert (units / "rdp-web.service").is_file() and (units / "rdp-worker.service").is_file()
    if args[1] == "enable":
        (root / "rdp-worker.service").write_text("active")
        if failure == "enable": sys.exit(18)
        (root / "rdp-web.service").write_text("active")
    sys.exit(0)
print("unexpected fake command", command, args, file=sys.stderr)
sys.exit(91)
"""
