"""第 11 张 deploy_scripts 契约清单；只用临时目录和可注入依赖，不触碰真实部署或服务。"""

import configparser
import subprocess
from pathlib import Path

import pytest
from deploy_support import DeploymentCase, deployment_case


@pytest.fixture(autouse=True)
def isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """整个脚本测试文件的测试进程HOME都隔离，包括只读模板和语法测试。"""
    monkeypatch.setenv("HOME", str(tmp_path))


@pytest.fixture
def deployment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> DeploymentCase:
    """测试本身与子进程的HOME均指向临时目录。"""
    case = deployment_case(tmp_path)
    monkeypatch.setenv("HOME", str(case.home))
    return case


@pytest.fixture
def installed(deployment: DeploymentCase) -> DeploymentCase:
    """通过已验证安装入口准备旧部署，清空调用记录后观察一次升级。"""
    result = deployment.run("install.sh")
    assert result.returncode == 0, result.stderr
    deployment.log.unlink()
    return deployment


ROOT = Path(__file__).parents[1]


def test_shell_syntax(tmp_path: Path) -> None:
    """验证契约：make check对install.sh与upgrade.sh分别bash -n，两份均检查，绝不直接运行真实部署脚本。"""
    for script in ("install.sh", "upgrade.sh"):
        # 仅语法解析，绝不执行脚本命令；HOME始终为测试临时目录。
        result = subprocess.run(  # noqa: S603  # 理由：固定bash仅解析仓库固定脚本，HOME为临时目录。
            ["/bin/bash", "-n", str(ROOT / "scripts" / script)],
            env={"HOME": str(tmp_path)},
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        assert result.returncode == 0, result.stderr


def test_script_help(deployment: DeploymentCase) -> None:
    """验证契约：--help写清目录/提交默认值、前台模式、确认和失败处理，参数错误非0；测试只在假PATH和临时HOME执行。"""
    for script in ("install.sh", "upgrade.sh"):
        result = deployment.run(script, "--help")
        assert result.returncode == 0, result.stderr
        for required in (
            "--deploy-dir",
            "$HOME/.local/opt/rdp",
            "--commit",
            "main",
            "--no-systemd",
            "rdp web",
            "rdp worker",
            "失败",
            "RDP_CONFIG",
        ):
            assert required in result.stdout
        assert (
            "--yes" in result.stdout if script == "upgrade.sh" else "create-admin" in result.stdout
        )
        assert deployment.run(script, "--unknown").returncode == 2
        assert deployment.run(script, "--deploy-dir").returncode == 2
    assert deployment.calls() == []


def test_install_order(deployment: DeploymentCase) -> None:
    """验证契约：假git/uv/pnpm/systemctl记录：worktree --detach→uv frozen→pnpm frozen→vite build→构建信息→migrate→端口检查→单元→daemon-reload→enable --now。"""
    import json

    result = deployment.run("install.sh")
    assert result.returncode == 0, result.stderr
    calls = deployment.calls()
    actions = [(call["command"], call["args"]) for call in calls if call["command"] != "git"]
    assert actions == [
        ("uv", ["sync", "--frozen"]),
        ("pnpm", ["install", "--frozen-lockfile"]),
        ("pnpm", ["exec", "vite", "build"]),
        ("rdp", ["migrate"]),
        ("rdp", ["status", "--check-port"]),
        ("systemctl", ["--user", "daemon-reload"]),
        ("systemctl", ["--user", "enable", "--now", "rdp-worker.service", "rdp-web.service"]),
    ]
    worktree = next(call for call in calls if "worktree" in call["args"])
    assert worktree["args"][-4:] == ["--detach", "--", str(deployment.deploy), "b" * 40]
    assert json.loads((deployment.deploy / "rdp-build.json").read_text()) == {"commit": "b" * 40}
    assert next(call["cwd"] for call in calls if call["command"] == "uv") == str(deployment.deploy)
    assert all(
        call["cwd"] == str(deployment.deploy / "src/web")
        for call in calls
        if call["command"] == "pnpm"
    )


def test_install_defaults(deployment: DeploymentCase) -> None:
    """验证契约：默认目录取临时HOME/.local/opt/rdp，提交取本地main；不fetch/pull或使用开发VIRTUAL_ENV；显式RDP_CONFIG同值写入两个单元。"""
    config = deployment.home / "配置.toml"
    config.write_text("[web]\nport=9123\n")
    result = deployment.run(
        "install.sh",
        overrides={"VIRTUAL_ENV": str(deployment.source / ".venv"), "RDP_CONFIG": str(config)},
    )
    assert result.returncode == 0, result.stderr
    calls = deployment.calls()
    assert any(call["args"][-1:] == ["main^{commit}"] for call in calls)
    assert all(call["virtual_env"] is None for call in calls if call["command"] == "uv")
    assert all(call["config"] == str(config) for call in calls if call["command"] == "rdp")
    for name in ("rdp-web.service", "rdp-worker.service"):
        unit = (deployment.home / ".config/systemd/user" / name).read_text()
        assert f'Environment="RDP_CONFIG={config}"' in unit
    assert deployment.deploy.is_dir()
    assert not any("fetch" in call["args"] or "pull" in call["args"] for call in calls)


def test_install_custom_paths(deployment: DeploymentCase) -> None:
    """验证契约：中文空格、百分号和引号路径作为单参数传递并按systemd语法转义；无eval，不硬编码用户名。"""
    target = deployment.root / '部署 空格%"反\\斜 &路径'
    config = deployment.home / '配置 %"反\\斜.toml'
    config.write_text("")
    result = deployment.run(
        "install.sh",
        "--deploy-dir",
        str(target),
        "--commit",
        "release",
        overrides={"RDP_CONFIG": str(config)},
    )
    assert result.returncode == 0, result.stderr
    worktree = next(call for call in deployment.calls() if "worktree" in call["args"])
    assert worktree["args"][-2] == str(target)
    unit = (deployment.home / ".config/systemd/user/rdp-web.service").read_text()
    assert '部署 空格%%\\"反\\\\斜 &路径/.venv/bin/rdp" web --no-stderr' in unit
    assert '配置 %%\\"反\\\\斜.toml"' in unit
    assert "WorkingDirectory=" + str(target).replace("%", "%%") + "\n" in unit
    assert "@DEPLOY_DIR@" not in unit


def test_install_existing_directory(deployment: DeploymentCase) -> None:
    """验证契约：部署目录已存在或等于源码目录时，在任何worktree/构建/单元副作用前拒绝，不删除原目录。"""
    deployment.deploy.mkdir(parents=True)
    sentinel = deployment.deploy / "保留.txt"
    sentinel.write_text("不准删除")
    for path in (
        str(deployment.deploy),
        str(deployment.source),
        "relative",
        str(deployment.root / "bad\npath"),
    ):
        result = deployment.run("install.sh", "--deploy-dir", path)
        assert result.returncode != 0
    assert sentinel.read_text() == "不准删除"
    assert not any(
        "worktree" in call["args"] or call["command"] in ("uv", "pnpm", "systemctl")
        for call in deployment.calls()
    )


def test_install_port_busy(deployment: DeploymentCase) -> None:
    """验证契约：配置端口占用导致检查非0时立即停止，提示改web.port，不复制单元或启动服务；覆盖非默认端口。"""
    config = deployment.home / "config.toml"
    config.write_text("[web]\nport=9123\n")
    result = deployment.run(
        "install.sh", overrides={"FAKE_PORT_CODE": "1", "RDP_CONFIG": str(config)}
    )
    assert result.returncode != 0
    assert "web.port" in result.stderr and str(config) in result.stderr
    assert not (deployment.home / ".config/systemd/user").exists()
    assert not any(call["command"] == "systemctl" for call in deployment.calls())
    assert deployment.calls()[-1]["args"] == ["status", "--check-port"]


@pytest.mark.parametrize("failure", ("uv", "pnpm-install", "vite"))
def test_install_build_failure(deployment: DeploymentCase, failure: str) -> None:
    """验证契约：uv/pnpm/vite任一步失败后不migrate/启动，不发布半成品版本文件，保留失败worktree。"""
    result = deployment.run("install.sh", overrides={"FAKE_FAIL": failure})
    assert result.returncode == 17
    assert "失败阶段" in result.stderr
    assert deployment.deploy.is_dir()
    assert not (deployment.deploy / "rdp-build.json").exists()
    assert not any(call["command"] in ("rdp", "systemctl") for call in deployment.calls())
    assert not list(deployment.deploy.glob(".rdp-build.*"))


def test_install_no_systemd(deployment: DeploymentCase) -> None:
    """验证契约：--no-systemd安装仍构建、写版本、迁移、查端口，但从不调用systemctl、不写单元，只给前台命令。"""
    result = deployment.run("install.sh", "--no-systemd")
    assert result.returncode == 0, result.stderr
    assert not any(call["command"] == "systemctl" for call in deployment.calls())
    assert not (deployment.home / ".config/systemd").exists()
    assert (deployment.deploy / "rdp-build.json").is_file()
    assert [call["args"] for call in deployment.calls() if call["command"] == "rdp"] == [
        ["migrate"],
        ["status", "--check-port"],
    ]
    assert ".venv/bin/rdp web" in result.stdout and ".venv/bin/rdp worker" in result.stdout
    assert ".venv/bin/rdp create-admin" in result.stdout


def test_units_only_owned(deployment: DeploymentCase) -> None:
    """验证契约：安装只写临时HOME中rdp-web/worker两个单元，预置egopro-restore.service逐字不变。"""
    directory = deployment.home / ".config/systemd/user"
    directory.mkdir(parents=True)
    unrelated = directory / "egopro-restore.service"
    original = b"unrelated service\n"
    unrelated.write_bytes(original)
    result = deployment.run("install.sh")
    assert result.returncode == 0, result.stderr
    assert unrelated.read_bytes() == original
    assert sorted(path.name for path in directory.iterdir()) == [
        "egopro-restore.service",
        "rdp-web.service",
        "rdp-worker.service",
    ]
    assert all(call["home"] == str(deployment.home) for call in deployment.calls())
    assert all("egopro-restore.service" not in call["args"] for call in deployment.calls())


def test_upgrade_active(installed: DeploymentCase) -> None:
    """验证契约：验收7：旧入口status发现running/cancelling退出3，脚本停止且不stop服务、checkout、构建或迁移。"""
    result = installed.run("upgrade.sh", "--yes", overrides={"FAKE_ACTIVE": "3"})
    assert result.returncode != 0
    calls = installed.calls()
    assert [call["args"] for call in calls if call["command"] == "rdp"] == [
        ["status", "--active-jobs"]
    ]
    assert not any(
        call["command"] in ("uv", "pnpm", "systemctl") or "checkout" in call["args"]
        for call in calls
    )
    assert "作业" in result.stderr and "恢复" in result.stderr


@pytest.mark.parametrize("code", ("1", "2", "17"))
def test_upgrade_query_failure(installed: DeploymentCase, code: str) -> None:
    """验证契约：升级状态查询返回1/2或异常时失败关闭流程，不把查询故障当空闲。"""
    result = installed.run("upgrade.sh", "--yes", overrides={"FAKE_ACTIVE": code})
    assert result.returncode != 0
    assert "检查失败" in result.stderr and code in result.stderr
    assert installed.calls()[-1]["args"] == ["status", "--active-jobs"]
    assert not any(call["command"] == "systemctl" for call in installed.calls())


@pytest.mark.parametrize("answer", ("n\n", ""))
def test_upgrade_confirmation(installed: DeploymentCase, answer: str) -> None:
    """验证契约：无作业后展示旧新提交并确认；拒绝/EOF不停止服务，--yes仍不能绕过活跃作业检查。"""
    result = installed.run("upgrade.sh", answer=answer)
    assert result.returncode != 0
    assert "b" * 40 in result.stdout and "c" * 40 in result.stdout
    assert str(installed.deploy) in result.stdout and "停" in result.stdout
    assert not any(
        call["command"] == "systemctl" or "checkout" in call["args"] for call in installed.calls()
    )
    assert installed.calls()[-1]["args"] == ["status", "--active-jobs"]


def test_upgrade_order(installed: DeploymentCase) -> None:
    """验证契约：验收7：查空闲→确认→stop Web→stop worker→确认inactive→旧入口复查→checkout→uv→前端→版本文件→新入口migrate→启动。"""
    result = installed.run("upgrade.sh", "--yes")
    assert result.returncode == 0, result.stderr
    actions: list[tuple[str, list[str]]] = []
    for call in installed.calls():
        if call["command"] == "git":
            if "checkout" in call["args"]:
                actions.append(("git", call["args"][-3:]))
        else:
            actions.append((call["command"], call["args"]))
    assert actions == [
        ("rdp", ["status", "--active-jobs"]),
        ("systemctl", ["--user", "stop", "rdp-web.service"]),
        ("systemctl", ["--user", "stop", "rdp-worker.service"]),
        ("systemctl", ["--user", "show", "--property=ActiveState", "--value", "rdp-web.service"]),
        (
            "systemctl",
            ["--user", "show", "--property=ActiveState", "--value", "rdp-worker.service"],
        ),
        ("rdp", ["status", "--active-jobs"]),
        ("git", ["checkout", "--detach", "c" * 40]),
        ("uv", ["sync", "--frozen"]),
        ("pnpm", ["install", "--frozen-lockfile"]),
        ("pnpm", ["exec", "vite", "build"]),
        ("rdp", ["migrate"]),
        ("systemctl", ["--user", "daemon-reload"]),
        ("systemctl", ["--user", "start", "rdp-worker.service"]),
        (
            "systemctl",
            ["--user", "show", "--property=ActiveState", "--value", "rdp-worker.service"],
        ),
        ("systemctl", ["--user", "start", "rdp-web.service"]),
        ("systemctl", ["--user", "show", "--property=ActiveState", "--value", "rdp-web.service"]),
        ("rdp", ["--version"]),
    ]


def test_upgrade_race(installed: DeploymentCase) -> None:
    """验证契约：第一次空闲但停机后复查发现活跃行时拒绝checkout/migrate，服务保持停止，提示旧版本恢复处理。"""
    result = installed.run("upgrade.sh", "--yes", overrides={"FAKE_ACTIVE": "0,3"})
    assert result.returncode != 0
    assert "停机后二次检查" in result.stderr and "旧版本恢复" in result.stderr
    calls = installed.calls()
    assert len([call for call in calls if call["args"] == ["status", "--active-jobs"]]) == 2
    assert not any(
        "checkout" in call["args"] or "start" in call["args"] or call["command"] == "uv"
        for call in calls
    )
    assert (installed.root / "rdp-web.service").read_text() == "inactive"
    assert (installed.root / "rdp-worker.service").read_text() == "inactive"
    assert (installed.root / "head").read_text() == "b" * 40


@pytest.mark.parametrize(
    "failure", ("stop-rdp-web.service", "stop-rdp-worker.service", "still-active")
)
def test_upgrade_stop_failure(installed: DeploymentCase, failure: str) -> None:
    """验证契约：任一服务停止失败或仍active时不得更新或迁移，保留旧提交和版本文件。"""
    import json

    overrides = (
        {"FAKE_STILL_ACTIVE": "rdp-worker.service"}
        if failure == "still-active"
        else {"FAKE_FAIL": failure}
    )
    result = installed.run("upgrade.sh", "--yes", overrides=overrides)
    assert result.returncode != 0
    assert not any(
        "checkout" in call["args"] or call["args"] == ["migrate"] for call in installed.calls()
    )
    assert json.loads((installed.deploy / "rdp-build.json").read_text())["commit"] == "b" * 40
    assert "失败阶段" in result.stderr


@pytest.mark.parametrize("guard", ("worker", "port", "none"))
def test_upgrade_no_systemd(installed: DeploymentCase, guard: str) -> None:
    """验证契约：--no-systemd先检查worker锁与端口；仍运行拒绝；已停才升级，无systemctl或单元写入，无自动启动前台服务。"""
    unit_dir = installed.home / ".config/systemd/user"
    before = {path.name: path.read_bytes() for path in unit_dir.iterdir()}
    overrides = (
        {"FAKE_WORKER_CODE": "3"}
        if guard == "worker"
        else {"FAKE_PORT_CODE": "1"}
        if guard == "port"
        else {}
    )
    result = installed.run("upgrade.sh", "--no-systemd", "--yes", overrides=overrides)
    assert (result.returncode == 0) is (guard == "none"), result.stderr
    assert not any(call["command"] == "systemctl" for call in installed.calls())
    assert {path.name: path.read_bytes() for path in unit_dir.iterdir()} == before
    calls = [call["args"] for call in installed.calls() if call["command"] == "rdp"]
    assert calls[:2] == [["status", "--active-jobs"], ["status", "--worker-stopped"]]
    if guard == "none":
        assert calls[2:4] == [["status", "--check-port"], ["status", "--active-jobs"]]
        assert ".venv/bin/rdp web" in result.stdout and ".venv/bin/rdp worker" in result.stdout
    else:
        assert not any("checkout" in call["args"] for call in installed.calls())


@pytest.mark.parametrize("failure", ("uv", "pnpm-install", "vite", "migrate"))
def test_upgrade_migrate_failure(installed: DeploymentCase, failure: str) -> None:
    """验证契约：新版本构建/迁移失败不重启，保留备份和失败阶段，不自动降级或reset --hard。"""
    result = installed.run("upgrade.sh", "--yes", overrides={"FAKE_FAIL": failure})
    assert result.returncode != 0
    assert "失败阶段" in result.stderr and "不自动回滚" in result.stderr
    assert (installed.root / "head").read_text() == "c" * 40
    assert not any("start" in call["args"] or "reset" in call["args"] for call in installed.calls())
    assert (installed.root / "rdp-web.service").read_text() == "inactive"
    assert (installed.root / "rdp-worker.service").read_text() == "inactive"
    if failure == "migrate":
        assert (installed.deploy / "migration-backup").read_text() == "backup evidence"


def test_upgrade_restart_failure(installed: DeploymentCase) -> None:
    """验证契约：部分服务启动失败则停止已启动的本项目服务，保留部署证据并返回非0，不报告升级完成。"""
    result = installed.run("upgrade.sh", "--yes", overrides={"FAKE_FAIL": "start-rdp-web.service"})
    assert result.returncode != 0
    assert "升级完成" not in result.stdout
    assert (installed.root / "rdp-worker.service").read_text() == "inactive"
    assert (installed.root / "rdp-web.service").read_text() == "inactive"
    assert [call["args"] for call in installed.calls() if call["command"] == "systemctl"][-2:] == [
        ["--user", "stop", "rdp-web.service"],
        ["--user", "stop", "rdp-worker.service"],
    ]
    assert (installed.deploy / "rdp-build.json").exists()


def test_upgrade_version_changed(installed: DeploymentCase) -> None:
    """验证契约：升级成功后包元数据和原子写构建文件对应新提交，migrate到最新，--version变化。"""
    import json

    assert json.loads((installed.deploy / "rdp-build.json").read_text())["commit"] == "b" * 40
    result = installed.run("upgrade.sh", "--yes")
    assert result.returncode == 0, result.stderr
    assert "0.1.0 (ccccccc)" in result.stdout
    assert json.loads((installed.deploy / "rdp-build.json").read_text())["commit"] == "c" * 40
    assert installed.calls()[-1]["args"] == ["--version"]
    assert not list(installed.deploy.glob(".rdp-build.*"))


@pytest.mark.parametrize(
    "scenario", ("dirty", "config-conflict", "inherit", "units-disagree", "invalid-escape")
)
def test_upgrade_dirty_refused(installed: DeploymentCase, scenario: str) -> None:
    """验证契约：目标worktree有源码改动或终端RDP_CONFIG与原单元不一致时拒绝；只允许已知部署产物，不丢弃用户修改或迁移另一数据库。"""
    config = installed.home / '升级 配置%"反\\斜.toml'
    config.write_text("")
    encoded = str(installed.home) + '/升级 配置%%\\"反\\\\斜.toml'
    unit_dir = installed.home / ".config/systemd/user"
    for name in ("rdp-web.service", "rdp-worker.service"):
        path = unit_dir / name
        path.write_text(
            path.read_text().replace(
                "[Service]", '[Service]\nEnvironment="RDP_CONFIG=' + encoded + '"'
            )
        )
    overrides: dict[str, str] = {}
    if scenario == "dirty":
        overrides["FAKE_DIRTY"] = " M src/rdp/cli.py"
    elif scenario == "config-conflict":
        overrides["RDP_CONFIG"] = str(installed.home / "other.toml")
    elif scenario == "units-disagree":
        path = unit_dir / "rdp-worker.service"
        path.write_text(path.read_text().replace(encoded, str(installed.home / "different.toml")))
    if scenario == "invalid-escape":
        for name in ("rdp-web.service", "rdp-worker.service"):
            path = unit_dir / name
            path.write_text(path.read_text().replace(encoded, str(installed.home) + r"/bad\q"))
    result = installed.run("upgrade.sh", "--yes", overrides=overrides)
    if scenario == "inherit":
        assert result.returncode == 0, result.stderr
        assert all(
            call["config"] == str(config) for call in installed.calls() if call["command"] == "rdp"
        )
        assert f'Environment="RDP_CONFIG={encoded}"' in (unit_dir / "rdp-web.service").read_text()
    else:
        assert result.returncode != 0
        assert not any(
            call["command"] in ("rdp", "systemctl", "uv") or "checkout" in call["args"]
            for call in installed.calls()
        )
        assert (installed.root / "head").read_text() == "b" * 40


def test_systemd_web_template() -> None:
    """验证契约：Web模板含绝对部署占位路径、web --no-stderr、Restart=on-failure、WantedBy=default.target，无用户名/home硬编码。"""
    source = (ROOT / "scripts/systemd/rdp-web.service").read_text()
    unit = configparser.ConfigParser(interpolation=None)
    unit.read_string(source)
    assert unit["Service"]["Restart"] == "on-failure"
    assert unit["Install"]["WantedBy"] == "default.target"
    assert unit["Service"]["ExecStart"] == '"@DEPLOY_DIR@/.venv/bin/rdp" web --no-stderr'
    assert unit["Service"].getint("TimeoutStopSec") == 360
    assert "/home/" not in source and "User" not in unit["Service"]


def test_systemd_worker_template() -> None:
    """验证契约：第8张：worker模板含worker --no-stderr、KillMode=control-group与TimeoutStopSec=45≥30，失败码交systemd重启。"""
    source = (ROOT / "scripts/systemd/rdp-worker.service").read_text()
    unit = configparser.ConfigParser(interpolation=None)
    unit.read_string(source)
    assert unit["Service"]["Restart"] == "on-failure"
    assert unit["Install"]["WantedBy"] == "default.target"
    assert unit["Service"]["KillMode"] == "control-group"
    timeout = unit["Service"].getint("TimeoutStopSec")
    assert timeout is not None and timeout >= 30
    assert unit["Service"]["ExecStart"] == '"@DEPLOY_DIR@/.venv/bin/rdp" worker --no-stderr'
    assert "/home/" not in source and "User" not in unit["Service"]


def test_build_file_atomic(installed: DeploymentCase) -> None:
    """验证契约：构建信息仅含完整commit；写入/替换失败清本次临时文件且保留旧文件，不公布错误提交。"""
    import json

    (installed.bin / "mv").symlink_to(installed.bin / "fake-command")
    old = (installed.deploy / "rdp-build.json").read_bytes()
    result = installed.run("upgrade.sh", "--yes", overrides={"FAKE_FAIL": "publish"})
    assert result.returncode == 20, result.stderr
    observed = json.loads((installed.root / "atomic-observation.json").read_text())
    assert observed["before"].encode() == old
    assert observed["after"] == {"commit": "c" * 40}
    assert (installed.deploy / "rdp-build.json").read_bytes() == old
    assert not list(installed.deploy.glob(".rdp-build.*"))
    assert not any(
        call["args"] == ["migrate"] or "start" in call["args"] for call in installed.calls()
    )


def test_fake_commands_isolation(installed: DeploymentCase) -> None:
    """验证契约：所有脚本流程测试用临时HOME/假PATH；真实systemctl/loginctl不可调用，子进程finally回收、临时文件清理。"""
    import os

    assert os.environ["HOME"] == str(installed.home)
    result = installed.run("upgrade.sh", "--yes")
    assert result.returncode == 0, result.stderr
    calls = installed.calls()
    assert {call["command"] for call in calls} == {"git", "uv", "pnpm", "systemctl", "rdp"}
    for call in calls:
        assert Path(call["program"]).resolve() == installed.bin / "fake-command"
        assert Path(call["cwd"]).is_relative_to(installed.root)
        assert call["home"] == str(installed.home)
    assert all(call["command"] != "loginctl" for call in calls)


def test_literal_dollar_in_exec_start(deployment: DeploymentCase) -> None:
    """部署路径中的美元符号保持字面值，不能被systemd当环境变量展开。"""
    target = deployment.root / "部署${RDP_TEST_SENTINEL}"
    result = deployment.run("install.sh", "--deploy-dir", str(target))
    assert result.returncode == 0, result.stderr
    unit = (deployment.home / ".config/systemd/user/rdp-web.service").read_text()
    assert f"WorkingDirectory={target}\n" in unit
    assert '/部署$${RDP_TEST_SENTINEL}/.venv/bin/rdp" web --no-stderr' in unit


def test_install_partial_start_cleanup(deployment: DeploymentCase) -> None:
    """安装enable部分成功时也回收本项目服务，保留部署和单元供排查。"""
    result = deployment.run("install.sh", overrides={"FAKE_FAIL": "enable"})
    assert result.returncode != 0
    assert "安装完成" not in result.stdout
    assert (deployment.root / "rdp-worker.service").read_text() == "inactive"
    assert (deployment.root / "rdp-web.service").read_text() == "inactive"
    assert deployment.deploy.is_dir()
    assert (deployment.home / ".config/systemd/user/rdp-web.service").exists()


@pytest.mark.parametrize("directory", ("plain", "部署 空格", "部署%目录"))
@pytest.mark.parametrize("operation", ("install", "upgrade"))
def test_rendered_units_pass_systemd_verify(
    deployment: DeploymentCase, directory: str, operation: str
) -> None:
    """真实systemd解析安装/升级渲染的两单元；普通、中文空格、百分号路径均合法，绝不连接总线或启动服务。"""
    import os
    import shutil

    analyzer = shutil.which("systemd-analyze")
    assert analyzer is not None, "必须提供systemd-analyze用于离线单元校验，不能跳过"
    target = deployment.root / directory
    config = deployment.home / '配置 %"$字面\\斜.toml'
    config.write_text("")
    result = deployment.run(
        "install.sh", "--deploy-dir", str(target), overrides={"RDP_CONFIG": str(config)}
    )
    assert result.returncode == 0, result.stderr
    if operation == "upgrade":
        result = deployment.run(
            "upgrade.sh",
            "--deploy-dir",
            str(target),
            "--yes",
            overrides={"RDP_CONFIG": str(config)},
        )
        assert result.returncode == 0, result.stderr
    # 安装替身提供临时可执行入口；verify会检查它存在，但不会执行。
    assert (target / ".venv/bin/rdp").is_file()
    assert os.access(target / ".venv/bin/rdp", os.X_OK)
    units = deployment.home / ".config/systemd/user"
    runtime = deployment.root / "runtime"
    runtime.mkdir(mode=0o700)
    environment = {
        "HOME": str(deployment.home),
        "PATH": str(deployment.bin),
        "XDG_RUNTIME_DIR": str(runtime),
        "XDG_CONFIG_HOME": str(deployment.home / ".config"),
        "XDG_DATA_HOME": str(deployment.home / ".local/share"),
        "SYSTEMD_UNIT_PATH": str(units) + ":",
    }
    checked = subprocess.run(  # noqa: S603  # 理由：真实解析器仅verify临时单元，入口为临时替身，不连接总线。
        [
            analyzer,
            "--user",
            "verify",
            "--man=no",
            "--generators=no",
            str(units / "rdp-web.service"),
            str(units / "rdp-worker.service"),
        ],
        env=environment,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert checked.returncode == 0, checked.stdout + checked.stderr
