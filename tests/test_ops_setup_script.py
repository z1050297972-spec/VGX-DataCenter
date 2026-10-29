"""一键部署脚本契约清单；全部外部命令由临时HOME中的替身提供。"""

from pathlib import Path

import pytest
from setup_support import release_downloads, release_url, setup_case, tool_downloads


@pytest.fixture(autouse=True)
def isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """测试进程HOME始终在本次临时目录，阻断依赖的用户配置发现。"""
    monkeypatch.setenv("HOME", str(tmp_path))


def test_help_contract(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """验证契约：帮助列出全部参数、默认值、交互问题、非交互示例、下载来源、失败处理与重复运行行为；帮助不触发探测或写入。"""
    case = setup_case(tmp_path)
    monkeypatch.setenv("HOME", str(case.home))
    result = case.run("--help")
    assert result.returncode == 0
    for text in (
        "--config",
        "--deploy-dir",
        "--commit",
        "--yes",
        "--no-systemd",
        "--skip-admin",
        "RDP_CONFIG",
        "0.0.0.0",  # noqa: S104  # 理由：帮助文本断言，不绑定端口。
        "8600",
        "SHA256",
        "HTTPS_PROXY",
        "不覆盖",
        "重复运行",
        "非交互",
        "明文HTTP",
        "管理员",
        "130",
        "22.23.2",
        "0.13.5",
        "11.22.0",
    ):
        assert text in result.stdout
    assert case.calls() == []
    assert list(case.home.iterdir()) == []


def test_repository_from_script_location(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """验证契约：从BASH_SOURCE定位仓库并把本地引用固定到完整提交，切换cwd不改变来源，不clone/fetch/pull或改开发检出。"""
    case = setup_case(tmp_path)
    monkeypatch.setenv("HOME", str(case.home))
    case.run("--commit", "review-ref", "--no-systemd")
    calls = case.calls("git")
    assert calls[0]["args"] == ["-C", str(case.source), "rev-parse", "--show-toplevel"]
    assert calls[1]["args"] == [
        "-C",
        str(case.source),
        "rev-parse",
        "--verify",
        "--end-of-options",
        "review-ref^{commit}",
    ]
    assert not any(
        word in call["args"] for call in calls for word in ("fetch", "pull", "clone", "checkout")
    )


def test_tool_versions_single_source(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """验证契约：Node/uv/pnpm固定版本只在顶部一处维护，兼容目标pyproject/uv.lock与前端锁定依赖；不下载latest。"""
    case = setup_case(tmp_path)
    monkeypatch.setenv("HOME", str(case.home))
    script = case.source / "scripts/setup.sh"
    original = script.read_text()
    for version in ("22.23.2", "0.13.5", "11.22.0"):
        assert original.count(version) == 1
    script.write_text(original.replace("'22.23.2'", "'22.99.1'"))
    output = case.run("--help").stdout
    assert "22.99.1" in output and "22.23.2" not in output
    assert "latest" not in original


def test_platform_and_base_tools(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """验证契约：不支持的平台或缺git/curl/tar/sha256sum/findmnt/ip/flock只提示手动办法，变更前停止，不自动用sudo装基础工具。"""
    case = setup_case(tmp_path)
    monkeypatch.setenv("HOME", str(case.home))
    result = case.run("--yes", overrides={"FAKE_ARCH": "riscv64"})
    assert result.returncode == 1 and "手动" in result.stderr
    assert not case.calls("curl") and not case.calls("git")
    # PATH只保留测试显式列出的工具，缺git不能回退到机器上的git。
    (case.binary / "git").unlink()
    result = case.run("--yes", overrides={"PATH": str(case.binary)})
    assert result.returncode == 1 and "git" in result.stderr and "手动" in result.stderr
    assert list(case.home.iterdir()) == []


def test_missing_tools_ask_individually(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """验证契约：缺Node、uv、pnpm时按Node优先顺序逐个说明来源版本和目标目录，只有相应确认后才下载该工具。"""
    for index, tool in enumerate(("node", "uv", "pnpm")):
        case = setup_case(tmp_path / tool)
        case.config()
        monkeypatch.setenv("HOME", str(case.home))
        result = case.interactive(
            "--no-systemd", overrides={"FAKE_VERSION_" + tool.upper(): "missing"}
        )
        assert result.returncode == 130, result.stdout
        assert "安装" + tool in result.stdout
        versions = [call["command"] for call in case.calls() if call["args"] == ["--version"]]
        assert versions == ["node", "uv", "pnpm"][: index + 1]
        assert not case.calls("curl")


def test_tool_refusal_stops(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """验证契约：拒绝任一工具安装就停止依赖它的后续步骤，输出该工具的手动下载/校验/用户目录安装办法，不继续部署。"""
    case = setup_case(tmp_path)
    case.config()
    monkeypatch.setenv("HOME", str(case.home))
    result = case.interactive("--no-systemd", overrides={"FAKE_VERSION_NODE": "wrong"})
    assert result.returncode == 130, result.stdout
    assert all(text in result.stdout for text in ("node", "22.23.2", "手动", "SHA256", ".local"))
    assert not case.calls("curl") and not case.calls("uv") and not case.calls("install.sh")
    assert list((tmp_path / "tmp").iterdir()) == []


def test_yes_skips_confirmations(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """验证契约：--yes不读取确认输入，可授权缺工具下载与linger；不能代答配置、存储写许可或口令。"""
    case = setup_case(tmp_path)
    monkeypatch.setenv("HOME", str(case.home))
    case.config()
    tool_downloads(case)
    release_downloads(case, "uv")
    release_downloads(case, "pnpm")
    result = case.run(
        "--yes",
        "--skip-admin",
        overrides={
            "FAKE_VERSION_NODE": "wrong",
            "FAKE_VERSION_UV": "wrong",
            "FAKE_VERSION_PNPM": "wrong",
            "FAKE_LINGER": "no",
        },
    )
    assert result.returncode == 0, result.stderr
    assert "[y/N]" not in result.stdout
    assert ["enable-linger", "operator"] in [call["args"] for call in case.calls("loginctl")]
    assert all((case.home / ".local/bin" / tool).is_symlink() for tool in ("node", "uv", "pnpm"))
    assert len(case.calls("install.sh")) == 1


def test_tools_user_paths_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """验证契约：所有工具位于临时HOME的.local，PATH只改本次进程树；不sudo、不写shell rc、不碰同目录的其他工具。"""
    import os

    case = setup_case(tmp_path)
    case.config()
    monkeypatch.setenv("HOME", str(case.home))
    tool_downloads(case)
    unrelated = case.home / ".local/bin/unrelated"
    unrelated.parent.mkdir(parents=True)
    unrelated.write_text("keep")
    before = os.environ["PATH"]
    case.run("--yes", "--no-systemd", overrides={"FAKE_VERSION_NODE": "wrong"})
    assert (
        (case.home / ".local/bin/node").resolve().is_relative_to(case.home / ".local/opt/rdp-tools")
    )
    assert unrelated.read_text() == "keep"
    assert not (case.home / ".bashrc").exists()
    assert os.environ["PATH"] == before
    assert not any(call["command"] == "sudo" for call in case.calls())


def test_existing_tool_version_policy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """验证契约：PATH已有固定版本直接复用；版本不符先询问再在自管目录并存安装，不覆盖系统工具或用户自有入口。"""
    case = setup_case(tmp_path)
    case.config()
    monkeypatch.setenv("HOME", str(case.home))
    case.run("--no-systemd")
    assert [call["command"] for call in case.calls() if call["args"] == ["--version"]] == [
        "node",
        "uv",
        "pnpm",
    ]
    assert not case.calls("curl")
    result = case.interactive("--no-systemd", overrides={"FAKE_VERSION_PNPM": "10.0.0"})
    assert result.returncode == 130 and "11.22.0" in result.stdout
    assert not case.calls("curl")
    assert (case.binary / "pnpm").is_symlink()


def test_node_checksum_manifest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """验证契约：Node归档先用官方同源SHASUMS256.txt精确匹配唯一文件名及SHA256，再解包执行；错名、重复、截断和非HTTPS来源拒绝。"""
    case = setup_case(tmp_path)
    case.config()
    monkeypatch.setenv("HOME", str(case.home))
    tool_downloads(case)
    result = case.run("--yes", "--no-systemd", overrides={"FAKE_VERSION_NODE": "wrong"})
    node = case.home / ".local/bin/node"
    assert node.is_symlink(), result.stderr
    assert (case.root / "executed-tool").exists()
    calls = case.calls("curl")
    assert calls[0]["args"][-1] == "https://nodejs.org/dist/v22.23.2/SHASUMS256.txt"
    assert calls[1]["args"][-1] == "https://nodejs.org/dist/v22.23.2/node-v22.23.2-linux-x64.tar.gz"
    for variant in ("wrong-name", "duplicate", "truncated"):
        other = setup_case(tmp_path / variant)
        other.config()
        tool_downloads(other)
        manifest = other.root / "SHASUMS256.txt"
        original = manifest.read_text()
        manifest.write_text(
            original.replace("linux-x64", "linux-arm64")
            if variant == "wrong-name"
            else original * 2
            if variant == "duplicate"
            else original[:40]
        )
        result = other.run("--yes", overrides={"FAKE_VERSION_NODE": "wrong"})
        assert result.returncode == 1
        assert not (other.root / "executed-tool").exists()
        assert not (other.home / ".local/bin/node").exists()


def test_release_fixed_digest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """uv/pnpm按固定摘要校验归档；缺失或非法摘要在下载前拒绝，不降级跳过。"""
    for tool in ("uv", "pnpm"):
        case = setup_case(tmp_path / tool)
        case.config()
        monkeypatch.setenv("HOME", str(case.home))
        release_downloads(case, tool)
        result = case.run(
            "--yes", "--no-systemd", overrides={"FAKE_VERSION_" + tool.upper(): "wrong"}
        )
        assert (case.home / ".local/bin" / tool).is_symlink(), result.stderr
        assert case.calls("curl")[-1]["args"][-1] == release_url(tool)
    for bad in (None, "", "sha256:bad", "md5:" + "a" * 64):
        case = setup_case(tmp_path / ("bad" + str(len(list(tmp_path.iterdir())))))
        case.config()
        release_downloads(case, "uv", digest=bad)
        result = case.run("--yes", overrides={"FAKE_VERSION_UV": "wrong"})
        assert result.returncode == 1
        assert not (case.home / ".local/bin/uv").exists()
        assert not case.calls("curl")


def test_checksum_failure_no_partial_tool(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """验证契约：下载或SHA256校验失败时非0退出，正式工具目录与PATH入口不变，无半装可执行文件，临时下载删除。"""
    case = setup_case(tmp_path)
    case.config()
    monkeypatch.setenv("HOME", str(case.home))
    tool_downloads(case, corrupt=True)
    result = case.run("--yes", overrides={"FAKE_VERSION_NODE": "wrong"})
    assert result.returncode == 1 and "SHA256" in result.stderr
    assert not (case.root / "executed-tool").exists()
    assert not (case.home / ".local/bin/node").exists()
    assert not (case.home / ".local/opt/rdp-tools/node").exists()
    assert list((tmp_path / "tmp").iterdir()) == []


def test_archive_path_and_size_limits(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """验证契约：归档绝对路径、父目录穿越、越界链接和大小超限均在发布前拒绝；不执行校验未通过的文件。"""
    import hashlib
    import io
    import tarfile

    for variant in ("parent", "absolute", "link", "archive-size", "extract-size"):
        case = setup_case(tmp_path / variant)
        case.config()
        monkeypatch.setenv("HOME", str(case.home))
        tool_downloads(case, traversal=variant == "parent")
        archive = case.root / "node.tar.gz"
        if variant in ("absolute", "link"):
            with tarfile.open(archive) as stream:
                member = stream.getmembers()[0]
                reader = stream.extractfile(member)
                assert reader is not None
                payload = reader.read()
            with tarfile.open(archive, "w:gz") as stream:
                stream.addfile(member, io.BytesIO(payload))
                entry = tarfile.TarInfo(
                    "/escape" if variant == "absolute" else "node-v22.23.2-linux-x64/bin/out"
                )
                if variant == "link":
                    entry.type, entry.linkname = tarfile.SYMTYPE, "../../escape"
                stream.addfile(entry)
            (case.root / "SHASUMS256.txt").write_text(
                hashlib.sha256(archive.read_bytes()).hexdigest()
                + "  node-v22.23.2-linux-x64.tar.gz\n"
            )
        if variant.endswith("size"):
            # 缩小测试副本预算，以小文件验证边界；生产预算仍由顶部常量维护。
            script = case.source / "scripts/setup.sh"
            token = (
                "SETUP_ARCHIVE_MAX_BYTES=536870912"
                if variant == "archive-size"
                else "SETUP_EXTRACT_MAX_BYTES=1073741824"
            )
            script.write_text(script.read_text().replace(token, token.split("=")[0] + "=32"))
        result = case.run("--yes", overrides={"FAKE_VERSION_NODE": "wrong"})
        assert result.returncode == 1, variant
        assert not (case.root / "executed-tool").exists(), variant
        assert not (case.home / ".local/bin/node").exists()
        assert not list(case.home.glob(".local/opt/rdp-tools/node/.incoming.*"))


def test_tool_publish_atomic(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """验证契约：工具完整校验与版本检查后才原子发布；中途失败保留旧入口，不覆盖非本脚本管理的同名文件。"""
    case = setup_case(tmp_path / "user")
    case.config()
    monkeypatch.setenv("HOME", str(case.home))
    tool_downloads(case)
    entry = case.home / ".local/bin/node"
    entry.parent.mkdir(parents=True)
    entry.write_text("用户自己的工具")
    result = case.run("--yes", overrides={"FAKE_VERSION_NODE": "wrong"})
    assert result.returncode == 1 and "拒绝覆盖" in result.stderr
    assert entry.read_text() == "用户自己的工具"
    case = setup_case(tmp_path / "atomic")
    case.config()
    tool_downloads(case)
    old = case.home / ".local/opt/rdp-tools/node/old"
    (old / "bin").mkdir(parents=True)
    (old / "bin/node").write_text("old")
    (old / ".rdp-setup-tool").write_text("node")
    entry = case.home / ".local/bin/node"
    entry.parent.mkdir(parents=True)
    entry.symlink_to(old / "bin/node")
    failure = case.binary / "mv"
    failure.unlink()
    failure.write_text("#!/bin/sh\nexit 19\n")
    failure.chmod(0o700)
    result = case.run("--yes", overrides={"FAKE_VERSION_NODE": "wrong"})
    assert result.returncode != 0
    assert entry.read_text() == "old"
    assert not list(old.parent.glob(".incoming.*"))
    assert not (old.parent / "22.23.2-x86_64").exists()


def test_download_proxy_and_budgets(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """验证契约：下载保留HTTPS_PROXY等环境，限制连接/总时长/重试/大小，错误不输出代理凭据，不执行下载的安装脚本。"""
    case = setup_case(tmp_path)
    case.config()
    monkeypatch.setenv("HOME", str(case.home))
    tool_downloads(case, corrupt=True)
    proxy = "http://user:secret-value@proxy.invalid:8080"
    result = case.run("--yes", overrides={"FAKE_VERSION_NODE": "wrong", "HTTPS_PROXY": proxy})
    assert "secret-value" not in result.stderr + result.stdout
    for call in case.calls("curl"):
        assert call["proxy"] == proxy
        args = call["args"]
        for flag, value in (
            ("--connect-timeout", "10"),
            ("--max-time", "300"),
            ("--retry", "0"),
            ("--max-redirs", "0"),
            ("--proto", "=https"),
        ):
            assert args[args.index(flag) + 1] == value
        assert "--max-filesize" in args and "-k" not in args
    assert not (case.root / "executed-tool").exists()


def test_systemd_missing_or_bus_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """验证契约：默认模式缺systemctl/loginctl或用户总线不可用只提示并失败，给出--no-systemd办法，不尝试安装系统服务。"""
    case = setup_case(tmp_path)
    case.config()
    monkeypatch.setenv("HOME", str(case.home))
    result = case.run("--yes", overrides={"FAKE_BUS_FAIL": "1"})
    assert result.returncode == 1 and "--no-systemd" in result.stderr
    assert not case.calls("loginctl") and not case.calls("install.sh")


def test_linger_already_enabled(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """验证契约：Linger=yes不询问、不重复enable；检查只针对当前用户，不遍历或修改其他用户。"""
    case = setup_case(tmp_path)
    case.config()
    monkeypatch.setenv("HOME", str(case.home))
    case.run()
    assert [call["args"] for call in case.calls("loginctl")] == [
        ["show-user", "operator", "--property=Linger", "--value"]
    ]
    assert not case.calls("curl")


def test_linger_consent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """验证契约：Linger=no说明退出登录和开机影响，确认后才调用loginctl enable-linger当前用户；拒绝不调用，--yes可授权。"""
    for answer in ("y", "n"):
        case = setup_case(tmp_path / answer)
        monkeypatch.setenv("HOME", str(case.home))
        case.config()
        result = case.interactive(
            "--skip-admin", answers=answer + "\ny\n", overrides={"FAKE_LINGER": "no"}
        )
        calls = [call["args"] for call in case.calls("loginctl")]
        assert "退出登录" in result.stdout and "开机" in result.stdout
        assert (["enable-linger", "operator"] in calls) == (answer == "y")
        if answer == "n":
            assert result.returncode == 130


def test_linger_enable_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """验证契约：启用linger失败退出非0并打印管理员sudo loginctl enable-linger命令，脚本自身没有sudo调用。"""
    case = setup_case(tmp_path)
    case.config()
    monkeypatch.setenv("HOME", str(case.home))
    result = case.run("--yes", overrides={"FAKE_LINGER": "no", "FAKE_LINGER_FAIL": "1"})
    assert result.returncode == 1
    assert "sudo loginctl enable-linger operator" in result.stderr
    assert not any(call["command"] == "sudo" for call in case.calls())
    assert not case.calls("install.sh")


def test_no_systemd_skips_service_manager(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """验证契约：--no-systemd全程无systemctl/loginctl调用，也不复制单元或改linger；缺这些命令不阻止前台模式。"""
    case = setup_case(tmp_path)
    monkeypatch.setenv("HOME", str(case.home))
    case.config()
    result = case.run(
        "--yes",
        "--skip-admin",
        "--no-systemd",
        overrides={"FAKE_BUS_FAIL": "1", "FAKE_LINGER_FAIL": "1"},
    )
    assert result.returncode == 0, result.stderr
    assert not case.calls("systemctl") and not case.calls("loginctl")
    assert not (case.home / ".config/systemd").exists()
    assert "--no-systemd" in case.calls("install.sh")[0]["args"]


def test_config_source_and_no_overwrite(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """验证契约：--config优先于RDP_CONFIG再到默认路径；已有配置只读校验，内容/mtime/权限保持不变，绝不写覆盖。"""
    for selected in ("flag", "environment", "default"):
        case = setup_case(tmp_path / selected)
        monkeypatch.setenv("HOME", str(case.home))
        default = case.config()
        environment = case.config(case.home / "env.toml")
        explicit = case.config(case.home / "chosen.toml")
        expected = {"flag": explicit, "environment": environment, "default": default}[selected]
        before = expected.read_bytes(), expected.stat().st_mtime_ns, expected.stat().st_mode
        case.run(
            "--yes",
            "--skip-admin",
            "--no-systemd",
            *(["--config", str(explicit)] if selected == "flag" else []),
            overrides={"RDP_CONFIG": str(environment) if selected != "default" else ""},
        )
        calls = [call for call in case.calls("python") if "validate-config" in call["args"]]
        assert len(calls) == 1 and calls[0]["args"][-1] == str(expected)
        assert (
            expected.read_bytes(),
            expected.stat().st_mtime_ns,
            expected.stat().st_mode,
        ) == before
        assert not (case.home / "state").exists()


def test_noninteractive_missing_input(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """验证契约：无TTY时缺有效配置、缺确认授权或缺安全管理员输入条件明确报错，stdin永不等待；--yes不能制造答案。"""
    case = setup_case(tmp_path)
    monkeypatch.setenv("HOME", str(case.home))
    result = case.run("--yes", "--no-systemd")
    assert result.returncode == 2 and "配置缺失" in result.stderr
    case.config()
    result = case.run("--no-systemd", overrides={"FAKE_VERSION_NODE": "wrong"})
    assert result.returncode == 2 and "--yes" in result.stderr
    result = case.run("--yes", "--no-systemd")
    assert result.returncode == 2 and "--skip-admin" in result.stderr
    assert not case.calls("install.sh")


def test_validation_environment_matches_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """验证契约：从同一目标提交git archive建临时uv校验环境，依赖锁定且不改源仓库.venv，不调用install.sh提前迁移。"""
    case = setup_case(tmp_path)
    case.config()
    monkeypatch.setenv("HOME", str(case.home))
    case.run("--yes", "--no-systemd", overrides={"VIRTUAL_ENV": "/not-used"})
    archives = [call for call in case.calls("git") if "archive" in call["args"]]
    assert len(archives) == 1 and archives[0]["args"][-1] == "a" * 40
    syncs = [call for call in case.calls("uv") if call["args"][:1] == ["sync"]]
    assert len(syncs) == 1
    assert syncs[0]["args"] == ["sync", "--frozen", "--no-dev"]
    assert syncs[0]["virtual_env"] is None
    assert Path(syncs[0]["venv"]).is_relative_to(tmp_path / "tmp")
    assert Path(syncs[0]["cwd"]).is_relative_to(tmp_path / "tmp")
    assert not (case.source / ".venv").exists() and not case.calls("install.sh")
    result = case.run("--yes", "--no-systemd", overrides={"FAKE_NO_QUERIES": "1"})
    assert result.returncode == 1 and "目标提交" in result.stderr


def test_questionnaire_platform_validation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """验证契约：问答生成的TOML含host/port/nav/state/roots/gpus，特殊字符正确转义，必须经目标平台load_config校验后才发布。"""
    from rdp.ops.setup_queries import validate_setup_configuration

    case = setup_case(tmp_path)
    monkeypatch.setenv("HOME", str(case.home))
    (case.binary / "nvidia-smi").unlink()
    nav = case.home / '导航 "引号"'
    state = case.home / "自定状态"
    answers = f"127.0.0.1\n9124\n{nav}\n{state}\n\ny\n"
    result = case.interactive("--yes", "--skip-admin", answers=answers)
    assert result.returncode == 0, result.stdout
    config = case.home / ".config/rdp/config.toml"
    loaded = validate_setup_configuration(config, home=case.home).config
    assert loaded.nav_root == nav and loaded.state_dir == state
    assert loaded.web.host == "127.0.0.1" and loaded.web.port == 9124
    assert loaded.jobs.gpus == () and loaded.storage_roots == ()
    assert config.stat().st_mode & 0o777 == 0o600
    assert not nav.exists() and not state.exists()
    calls = case.calls()
    validate_index = next(
        index for index, call in enumerate(calls) if "validate-config" in call["args"]
    )
    install_index = next(
        index for index, call in enumerate(calls) if call["command"] == "install.sh"
    )
    assert validate_index < install_index


def test_plain_http_listen_prompt(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """验证契约：默认0.0.0.0/8600，提示局域网明文HTTP并说明127.0.0.1选项；导航层路径没有隐藏的真实机器默认值。"""
    from rdp.ops.setup_queries import validate_setup_configuration

    case = setup_case(tmp_path)
    monkeypatch.setenv("HOME", str(case.home))
    (case.binary / "nvidia-smi").unlink()
    result = case.interactive("--yes", "--skip-admin", answers=f"\n\n{case.home / 'nav'}\n\n\ny\n")
    assert result.returncode == 0, result.stdout
    assert "局域网明文HTTP" in result.stdout and "127.0.0.1" in result.stdout
    assert "导航层绝对目录（必填）" in result.stdout
    loaded = validate_setup_configuration(case.home / ".config/rdp/config.toml", home=case.home)
    assert loaded.config.web == loaded.config.web.model_validate({"host": "0.0.0.0", "port": 8600})  # noqa: S104  # 理由：临时配置由假服务消费。
    assert loaded.config.state_dir == case.home / ".local/share/rdp"


def test_config_validation_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """验证契约：问答配置未通过平台校验时不发布、不调用install.sh，不把用户输入错误当默认配置继续。"""
    case = setup_case(tmp_path)
    monkeypatch.setenv("HOME", str(case.home))
    (case.binary / "nvidia-smi").unlink()
    result = case.interactive(
        "--yes", "--skip-admin", answers=f"127.0.0.1\n65536\n{case.home / 'nav'}\n\n\ny\n"
    )
    assert result.returncode == 1 and "未通过平台校验" in result.stdout
    assert not (case.home / ".config/rdp/config.toml").exists()
    assert not case.calls("install.sh") and not (case.home / "nav").exists()
    assert list((tmp_path / "tmp").iterdir()) == []


def test_config_publish_race(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """验证契约：候选通过后若另一方创建了配置文件或软链接，原子不覆盖发布必须失败并保留对方文件，不跟随链接写入。"""
    for kind in ("file", "symlink"):
        case = setup_case(tmp_path / kind)
        monkeypatch.setenv("HOME", str(case.home))
        (case.binary / "nvidia-smi").unlink()
        result = case.interactive(
            "--yes",
            "--skip-admin",
            answers=f"127.0.0.1\n9123\n{case.home / 'nav'}\n\n\ny\n",
            overrides={"FAKE_CONFIG_RACE": kind},
        )
        assert result.returncode == 1 and "竞争" in result.stdout
        config = case.home / ".config/rdp/config.toml"
        assert config.read_text() == "other owner"
        assert config.is_symlink() == (kind == "symlink")
        assert not case.calls("install.sh")
        assert not list(config.parent.glob(".rdp-config.*"))


def test_mount_uuid_and_read_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """验证契约：假findmnt提供挂载点与UUID/NFS来源、ro/rw，展示并据此选择；不人工编造UUID，不stat/遍历存储根或写标记。"""
    import json

    from rdp.ops.setup_queries import validate_setup_configuration

    case = setup_case(tmp_path)
    monkeypatch.setenv("HOME", str(case.home))
    (case.binary / "nvidia-smi").unlink()
    mounts = {
        "filesystems": [
            {
                "target": str(case.home / "disk"),
                "source": "/dev/example",
                "fstype": "ext4",
                "uuid": "123E4567-E89B-42D3-A456-426614174000",
                "options": "ro",
            },
            {
                "target": str(case.home / "nas"),
                "source": "nas:/platform",
                "fstype": "nfs4",
                "uuid": None,
                "options": "rw",
            },
        ]
    }
    result = case.interactive(
        "--yes",
        "--skip-admin",
        answers=f"127.0.0.1\n9123\n{case.home / 'nav'}\n\n1,2\ndisk\nnas\nn\n",
        overrides={"FAKE_MOUNTS": json.dumps(mounts)},
    )
    assert result.returncode == 0, result.stdout
    config = validate_setup_configuration(
        case.home / ".config/rdp/config.toml", home=case.home
    ).config
    assert config.storage_roots[0].uuid == "123e4567-e89b-42d3-a456-426614174000"
    assert config.storage_roots[1].nfs_export == "nas:/platform"
    assert all(not root.writable for root in config.storage_roots)
    assert "内核只读" in result.stdout and "内核可写" in result.stdout
    assert not (case.home / "disk").exists() and not (case.home / "nas").exists()
    assert case.calls("findmnt")[0]["args"] == [
        "--json",
        "--list",
        "--output",
        "TARGET,SOURCE,FSTYPE,UUID,OPTIONS",
    ]


def test_unsupported_mounts_not_selectable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """验证契约：不支持的文件系统、缺UUID或非法来源显示不可选原因，不能选择或发布配置，不猜来源。"""
    import json

    for filesystem, source, reason in (
        ("tmpfs", "tmpfs", "unsupported_filesystem"),
        ("ext4", "/dev/example", "missing_uuid"),
        ("nfs", "bad source", "invalid_source"),
    ):
        case = setup_case(tmp_path / filesystem)
        monkeypatch.setenv("HOME", str(case.home))
        mount = {
            "target": str(case.home / "disk"),
            "source": source,
            "fstype": filesystem,
            "uuid": None,
            "options": "rw",
        }
        result = case.interactive(
            "--yes",
            "--skip-admin",
            answers=f"127.0.0.1\n9123\n{case.home / 'nav'}\n\n1\n",
            overrides={"FAKE_MOUNTS": json.dumps({"filesystems": [mount]})},
        )
        assert result.returncode == 1 and reason in result.stdout and "不可选" in result.stdout
        assert not case.calls("install.sh")
        assert not (case.home / ".config/rdp/config.toml").exists()


def test_storage_write_permission_explicit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """验证契约：内核rw不自动授予平台写许可，本地盘保持只读；NFS专属平台区且内核可写时才接受用户显式许可，--yes不代答。"""
    import json

    from rdp.ops.setup_queries import validate_setup_configuration

    for label, filesystem, mode, answer, expected in (
        ("grant", "nfs", "rw", "y\n", True),
        ("deny", "nfs", "rw", "\n", False),
        ("readonly", "nfs", "ro", "", False),
        ("local", "ext4", "rw", "", False),
    ):
        case = setup_case(tmp_path / label)
        monkeypatch.setenv("HOME", str(case.home))
        (case.binary / "nvidia-smi").unlink()
        mount = {
            "target": str(case.home / "disk"),
            "source": "nas:/platform" if filesystem == "nfs" else "/dev/example",
            "fstype": filesystem,
            "uuid": "123e4567-e89b-42d3-a456-426614174000" if filesystem == "ext4" else None,
            "options": mode,
        }
        result = case.interactive(
            "--yes",
            "--skip-admin",
            answers=f"127.0.0.1\n9123\n{case.home / 'nav'}\n\n1\nstore\n" + answer,
            overrides={"FAKE_MOUNTS": json.dumps({"filesystems": [mount]})},
        )
        assert result.returncode == 0, result.stdout
        root = validate_setup_configuration(
            case.home / ".config/rdp/config.toml", home=case.home
        ).config.storage_roots[0]
        assert root.writable is expected
        assert ("专属平台区" in result.stdout) == (filesystem == "nfs" and mode == "rw")


def test_gpu_missing_and_existing_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """验证契约：没有nvidia-smi时新问答配置写gpus=[]；已有配置不被修改，原配置要求GPU时报告环境冲突。"""
    from rdp.ops.setup_queries import validate_setup_configuration

    case = setup_case(tmp_path / "new")
    monkeypatch.setenv("HOME", str(case.home))
    (case.binary / "nvidia-smi").unlink()
    result = case.interactive(
        "--yes", "--skip-admin", answers=f"127.0.0.1\n9123\n{case.home / 'nav'}\n\n\ny\n"
    )
    assert result.returncode == 0
    assert (
        validate_setup_configuration(
            case.home / ".config/rdp/config.toml", home=case.home
        ).config.jobs.gpus
        == ()
    )
    other = setup_case(tmp_path / "existing")
    config = other.config(gpus="[2]")
    before = config.read_bytes()
    (other.binary / "nvidia-smi").unlink()
    result = other.run("--yes", "--skip-admin")
    assert result.returncode == 1 and "GPU" in result.stderr
    assert config.read_bytes() == before and not other.calls("install.sh")


def test_gpu_query_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """验证契约：nvidia-smi存在则只作有界编号查询；执行失败或非法编号不伪装为空卡，有TTY须明确选择不用GPU，无TTY报错。"""
    from rdp.ops.setup_queries import validate_setup_configuration

    case = setup_case(tmp_path / "valid")
    monkeypatch.setenv("HOME", str(case.home))
    result = case.interactive(
        "--yes", "--skip-admin", answers=f"127.0.0.1\n9123\n{case.home / 'nav'}\n\n\ny\n2\n"
    )
    assert result.returncode == 0, result.stdout
    assert validate_setup_configuration(
        case.home / ".config/rdp/config.toml", home=case.home
    ).config.jobs.gpus == (2,)
    assert case.calls("nvidia-smi")[0]["args"] == [
        "--query-gpu=index",
        "--format=csv,noheader,nounits",
    ]
    for label, overrides in (
        ("failed", {"FAKE_GPU_FAIL": "1"}),
        ("invalid", {"FAKE_GPUS": "0\n65536"}),
    ):
        other = setup_case(tmp_path / label)
        other.config(gpus="[0]")
        result = other.run("--yes", "--skip-admin", overrides=overrides)
        assert result.returncode == 1 and "GPU" in result.stderr
        assert not other.calls("install.sh")
    other = setup_case(tmp_path / "declared-empty")
    result = other.interactive(
        "--yes",
        "--skip-admin",
        answers=f"127.0.0.1\n9123\n{other.home / 'nav'}\n\n\ny\ny\n",
        overrides={"FAKE_GPU_FAIL": "1"},
    )
    assert result.returncode == 0 and "明确不用GPU" in result.stdout
    assert (
        validate_setup_configuration(
            other.home / ".config/rdp/config.toml", home=other.home
        ).config.jobs.gpus
        == ()
    )


def test_install_argument_forwarding(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """验证契约：以参数数组透传deploy-dir、完整commit和no-systemd，RDP_CONFIG同值用于install、管理员查询及服务；不重复实现迁移和单元安装。"""
    case = setup_case(tmp_path)
    monkeypatch.setenv("HOME", str(case.home))
    config = case.config()
    deploy = case.home / "deploy 中文 空格"
    case.run(
        "--yes", "--no-systemd", "--skip-admin", "--deploy-dir", str(deploy), "--commit", "review"
    )
    calls = case.calls("install.sh")
    assert len(calls) == 1
    assert calls[0]["args"] == ["--deploy-dir", str(deploy), "--commit", "a" * 40, "--no-systemd"]
    assert calls[0]["config"] == str(config) and calls[0]["home"] == str(case.home)
    assert not any("worktree" in call["args"] for call in case.calls("git"))
    assert not any(call["args"] == ["migrate"] for call in case.calls("rdp"))


def test_install_failure_stops_setup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """验证契约：install.sh非零后不建管理员、不宣称健康；保留部署和备份，错误指出失败阶段与人工处理办法。"""
    case = setup_case(tmp_path)
    monkeypatch.setenv("HOME", str(case.home))
    case.config()
    result = case.run("--yes", "--skip-admin", "--no-systemd", overrides={"FAKE_INSTALL_FAIL": "1"})
    assert result.returncode == 1 and "install.sh失败" in result.stderr
    assert (case.home / ".local/opt/rdp/backup").read_text() == "preserve"
    assert not case.calls("rdp") and not case.calls("curl")
    assert len([call for call in case.calls("python") if "administrator" in call["args"]]) == 1
    assert list((tmp_path / "tmp").iterdir()) == []


def test_existing_administrator_skipped(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """验证契约：已有管理员包括disabled时跳过create-admin，不读取口令、不改账号、不新增操作日志。"""
    case = setup_case(tmp_path)
    monkeypatch.setenv("HOME", str(case.home))
    case.config()
    result = case.run("--yes", "--no-systemd", overrides={"FAKE_ADMIN": "present"})
    assert "已有管理员" in result.stdout
    assert len([call for call in case.calls("python") if "administrator" in call["args"]]) == 2
    assert not any(call["args"][:1] == ["create-admin"] for call in case.calls("rdp"))


def test_administrator_interaction_and_audit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """验证契约：仅无管理员且有TTY时询问名字，再用既有rdp create-admin无回显读两次口令；只保留领域原事务的一条审计。"""
    case = setup_case(tmp_path)
    monkeypatch.setenv("HOME", str(case.home))
    case.config()
    result = case.interactive(
        "--yes",
        "--no-systemd",
        answers="chosen\n显示名字\nsecret-value\nsecret-value\n",
        prompts=("登录名 [admin]：", "显示名 [管理员]：", "口令：", "再次口令："),
    )
    calls = [call for call in case.calls("rdp") if call["args"][:1] == ["create-admin"]]
    assert len(calls) == 1 and calls[0]["args"] == ["create-admin", "chosen", "显示名字"]
    assert (case.root / "admin-audit").read_text() == "one operation"
    assert "secret-value" not in result.stdout
    assert "secret-value" not in (case.root / "calls.jsonl").read_text()


def test_skip_admin_and_no_password_transport(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """验证契约：--skip-admin打印后续命令且不调用建号；不存在口令argv/env选项，未skip又无TTY时不能卡住或降级回显。"""
    case = setup_case(tmp_path)
    monkeypatch.setenv("HOME", str(case.home))
    case.config()
    result = case.run("--yes", "--no-systemd", "--skip-admin")
    assert "create-admin" in result.stdout and str(case.home) in result.stdout
    assert not any(call["args"][:1] == ["create-admin"] for call in case.calls("rdp"))
    result = case.run("--password", "never-accepted")
    assert result.returncode == 2
    assert "never-accepted" not in result.stdout + result.stderr


def test_installed_repeat_reports_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """验证契约：完整部署再次运行不重装、不下载工具、不改配置、不启停服务，只打印版本/状态/升级命令；状态读取故障不能报告成功。"""
    case = setup_case(tmp_path)
    monkeypatch.setenv("HOME", str(case.home))
    deploy = case.home / ".local/opt/rdp"
    (deploy / ".venv/bin").mkdir(parents=True)
    (deploy / ".venv/bin/rdp").symlink_to(case.binary / "rdp")
    (deploy / "rdp-build.json").write_text('{"commit":"' + "a" * 40 + '"}')
    result = case.run("--no-systemd")
    assert result.returncode == 0, result.stderr
    assert (
        "0.1.0" in result.stdout
        and "worker 在线" in result.stdout
        and "upgrade.sh" in result.stdout
    )
    assert not any(
        case.calls(name) for name in ("curl", "uv", "systemctl", "loginctl", "install.sh")
    )
    result = case.run("--no-systemd", overrides={"FAKE_STATUS_FAIL": "1"})
    assert result.returncode != 0


def test_partial_install_not_complete(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """验证契约：仅目录存在或缺入口/构建信息不能当完整安装；拒绝覆盖并保留现场，不自动删除重建。"""
    case = setup_case(tmp_path)
    monkeypatch.setenv("HOME", str(case.home))
    deploy = case.home / ".local/opt/rdp"
    deploy.mkdir(parents=True)
    evidence = deploy / "preserve"
    evidence.write_text("现场")
    result = case.run("--yes", "--no-systemd")
    assert result.returncode == 1 and "未完成" in result.stderr
    assert evidence.read_text() == "现场"
    assert not case.calls("curl") and not case.calls("uv") and not case.calls("install.sh")


def test_foreground_supervision(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """验证契约：--no-systemd由setup前台监管两个真实替身子进程，健康后持续等待；信号转发只作用于自己的PID，停止等待有上限，超时回收并失败。"""
    case = setup_case(tmp_path)
    monkeypatch.setenv("HOME", str(case.home))
    case.config()
    result = case.run("--yes", "--skip-admin", "--no-systemd")
    assert result.returncode == 0, result.stderr
    assert "部署健康" in result.stdout
    for service in ("web", "worker"):
        assert (case.root / (service + ".pid")).exists()
        assert (case.root / (service + ".stopped")).read_text() == "0"
    assert not case.calls("systemctl") and not case.calls("loginctl")
    other = setup_case(tmp_path / "timeout")
    other.config()
    script = other.source / "scripts/setup.sh"
    script.write_text(
        script.read_text().replace(
            "SETUP_WORKER_STOP_TIMEOUT_S=45", "SETUP_WORKER_STOP_TIMEOUT_S=1"
        )
    )
    result = other.run(
        "--yes", "--skip-admin", "--no-systemd", overrides={"FAKE_IGNORE_TERM": "worker"}
    )
    assert result.returncode == 1 and "超时" in result.stderr
    assert (other.root / "web.stopped").exists()


def test_service_start_failure_cleanup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """验证契约：任一服务/前台子进程启动失败，停止本次拥有的另一服务并保留日志，不操作无关单元或旧部署进程。"""
    case = setup_case(tmp_path)
    monkeypatch.setenv("HOME", str(case.home))
    case.config()
    result = case.run(
        "--yes", "--skip-admin", overrides={"FAKE_SERVICE_FAIL": "rdp-worker.service"}
    )
    assert result.returncode == 1 and "服务" in result.stderr
    stops = [call["args"] for call in case.calls("systemctl") if "stop" in call["args"]]
    assert stops == [["--user", "stop", "rdp-web.service", "rdp-worker.service"]]
    assert not case.calls("curl")
    assert (case.home / ".local/opt/rdp/rdp-build.json").exists()


def test_health_timeout_and_log_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """验证契约：健康GET只走本机且绕过代理，校验200/status=ok，次数与每次超时有上限；失败非0并指出配置实际状态目录的两个日志路径。"""
    for status, body in (("503", '{"status":"ok"}'), ("200", '{"status":"broken"}')):
        case = setup_case(tmp_path / status)
        monkeypatch.setenv("HOME", str(case.home))
        case.config()
        result = case.run(
            "--yes",
            "--skip-admin",
            overrides={"FAKE_HEALTH_STATUS": status, "FAKE_HEALTH_BODY": body},
        )
        assert result.returncode == 1
        assert str(case.home / "state/logs/web.log") in result.stderr
        assert str(case.home / "state/logs/worker.log") in result.stderr
        calls = case.calls("curl")
        assert len(calls) == 12
        for call in calls:
            args = call["args"]
            assert args[-1] == "http://127.0.0.1:9123/api/health"
            assert args[args.index("--noproxy") + 1] == "*"
            assert args[args.index("--max-time") + 1] == "5"
        assert any("stop" in call["args"] for call in case.calls("systemctl"))


def test_access_addresses_from_interfaces(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """验证契约：假ip JSON经只读查询按绑定范围打印地址，0.0.0.0/::不作为访问URL，IPv6正确加括号及scope，不探测公网或改防火墙。"""
    case = setup_case(tmp_path)
    monkeypatch.setenv("HOME", str(case.home))
    config = case.config()
    config.write_text(config.read_text().replace("127.0.0.1", "0.0.0.0"))  # noqa: S104  # 理由：只测试地址映射，服务为替身。
    result = case.run("--yes", "--skip-admin")
    assert result.returncode == 0, result.stderr
    assert "http://127.0.0.1:9123/" in result.stdout and "http://192.0.2.55:9123/" in result.stdout
    assert "http://0.0.0.0" not in result.stdout
    assert "upgrade.sh" in result.stdout and "PATH" in result.stdout
    assert case.calls("ip")[0]["args"] == ["-j", "address", "show"]
    assert not any("stop" in call["args"] for call in case.calls("systemctl"))
    other = setup_case(tmp_path / "failure")
    other.config()
    result = other.run("--yes", "--skip-admin", overrides={"FAKE_IP_FAIL": "1"})
    assert result.returncode == 1 and "网卡" in result.stderr
    assert any("stop" in call["args"] for call in other.calls("systemctl"))


def test_setup_concurrency_lock(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """验证契约：首次部署持非阻塞用户锁，并行setup拒绝继续，不能同时发布工具/配置或创建部署；重复完整安装的只读报告不被前台监管锁阻塞。"""
    import fcntl

    case = setup_case(tmp_path)
    case.config()
    monkeypatch.setenv("HOME", str(case.home))
    locks = case.home / ".local/state/rdp"
    locks.mkdir(parents=True)
    with (locks / "setup.lock").open("w") as held:
        fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
        result = case.run("--yes", "--no-systemd")
    assert result.returncode == 3 and "占用" in result.stderr
    assert not case.calls("uv") and not case.calls("curl")


def test_cleanup_and_retry_boundaries(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """验证契约：任何失败清理仅本次下载、解包、候选和临时校验环境；已验证工具、已发布配置、部署和备份保留，重试不误用半成品。"""
    case = setup_case(tmp_path)
    monkeypatch.setenv("HOME", str(case.home))
    config = case.config()
    before = config.read_bytes()
    tool_downloads(case)
    result = case.run(
        "--yes",
        "--skip-admin",
        "--no-systemd",
        overrides={"FAKE_VERSION_NODE": "wrong", "FAKE_INSTALL_FAIL": "1"},
    )
    assert result.returncode == 1
    assert config.read_bytes() == before
    assert (case.home / ".local/bin/node").is_symlink()
    assert (case.home / ".local/opt/rdp/backup").exists()
    assert list((tmp_path / "tmp").iterdir()) == []
    assert not list(case.home.rglob(".incoming.*"))
    count = len(case.calls("install.sh"))
    result = case.run("--yes", "--skip-admin", "--no-systemd", overrides={"FAKE_STATUS_FAIL": "1"})
    assert result.returncode != 0 and len(case.calls("install.sh")) == count
    assert config.read_bytes() == before


def test_fake_commands_and_temporary_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """验证契约：测试进程及脚本HOME均为临时目录，git/uv/node/pnpm/curl/systemctl/loginctl/findmnt/ip/nvidia-smi全部用PATH前置替身记录，绝不联网或调用真实管理命令。"""
    case = setup_case(tmp_path)
    monkeypatch.setenv("HOME", str(case.home))
    assert Path.home() == case.home
    result = case.interactive(
        "--yes", "--skip-admin", answers=f"127.0.0.1\n9123\n{case.home / 'nav'}\n\n\ny\n\n"
    )
    assert result.returncode == 0, result.stdout
    commands = {call["command"] for call in case.calls()}
    assert {
        "git",
        "uv",
        "node",
        "pnpm",
        "curl",
        "systemctl",
        "loginctl",
        "findmnt",
        "ip",
        "nvidia-smi",
        "install.sh",
    } <= commands
    assert all(call["home"] == str(case.home) for call in case.calls())
    assert str(case.binary) == case.environment()["PATH"]
    assert not (case.home / ".config/systemd").exists()


def test_retry_reuses_verified_tools(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """验证失败重试复用已验证的用户工具，不重复下载或把完整版本误报为部分安装。"""
    case = setup_case(tmp_path)
    monkeypatch.setenv("HOME", str(case.home))
    case.config()
    tool_downloads(case)
    release_downloads(case, "uv", digest=None)
    first = case.run(
        "--yes",
        "--skip-admin",
        overrides={"FAKE_VERSION_NODE": "wrong", "FAKE_VERSION_UV": "wrong"},
    )
    assert first.returncode == 1
    assert (case.home / ".local/bin/node").is_symlink()
    downloads = len(case.calls("curl"))
    second = case.run("--yes", "--skip-admin", overrides={"FAKE_VERSION_NODE": "wrong"})
    assert second.returncode == 0, second.stderr
    # 只增加一次本机健康探测，没有再次下载Node或其他发行包。
    assert len(case.calls("curl")) == downloads + 1


def test_foreground_child_failure_is_not_healthy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """验证worker提前失败时即使Web健康响应为200，也不能宣称组合服务健康，且回收另一子进程。"""
    case = setup_case(tmp_path)
    monkeypatch.setenv("HOME", str(case.home))
    case.config()
    result = case.run(
        "--yes", "--skip-admin", "--no-systemd", overrides={"FAKE_CHILD_FAIL": "worker"}
    )
    assert result.returncode == 1
    assert "部署健康" not in result.stdout
    assert (case.root / "web.stopped").read_text() == "0"
    assert not case.calls("systemctl")


def test_rejects_untrusted_release_redirects(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """发行包重定向拒绝HTTP、第三方主机和API主机，在发出下一次请求前停止。"""
    for variant, redirect in (
        ("http", "http://github.com/asset"),
        ("foreign", "https://evil.invalid/asset"),
        ("api", "https://api.github.com/asset"),
    ):
        case = setup_case(tmp_path / variant)
        case.config()
        monkeypatch.setenv("HOME", str(case.home))
        release_downloads(case, "uv")
        result = case.run(
            "--yes", overrides={"FAKE_VERSION_UV": "wrong", "FAKE_REDIRECT": redirect}
        )
        assert result.returncode == 1
        assert len(case.calls("curl")) == 1
        assert not (case.home / ".local/bin/uv").exists()


def test_foreground_interrupt_preserves_unrelated_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """验证Ctrl+C同样正常收尾，并且停止范围仅为本次Web/worker，不触碰无关进程。"""
    import signal
    import subprocess
    import sys

    case = setup_case(tmp_path)
    monkeypatch.setenv("HOME", str(case.home))
    case.config()
    unrelated = subprocess.Popen(  # 理由：固定解释器，独立会话，finally回收。
        [sys.executable, "-c", "import time; time.sleep(30)"], start_new_session=True
    )
    try:
        result = case.run("--yes", "--skip-admin", "--no-systemd", stop_signal=signal.SIGINT)
        assert result.returncode == 0, result.stderr
        assert unrelated.poll() is None
        assert (case.root / "web.stopped").read_text() == "0"
        assert (case.root / "worker.stopped").read_text() == "0"
    finally:
        unrelated.kill()
        unrelated.wait(timeout=2)


def test_repeat_arguments_match_real_cli(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """重复报告发给rdp的每组参数必须通过真实解析器，解析阶段不启动服务或读取配置。"""
    from io import StringIO

    from rdp.ops.cli import Console, parse_command

    case = setup_case(tmp_path)
    monkeypatch.setenv("HOME", str(case.home))
    deploy = case.home / ".local/opt/rdp"
    (deploy / ".venv/bin").mkdir(parents=True)
    (deploy / ".venv/bin/rdp").symlink_to(case.binary / "rdp")
    (deploy / "rdp-build.json").write_text('{"commit":"' + "a" * 40 + '"}')
    result = case.run("--no-systemd")
    assert result.returncode == 0, result.stderr
    console = Console(StringIO(), StringIO(), lambda _: pytest.fail("解析参数不能读取口令"))
    calls = case.calls("rdp")
    assert calls
    for call in calls:
        parse_command(call["args"], console=console)
    assert [call["args"] for call in calls] == [
        ["--version"],
        ["status", "--worker-stopped"],
        ["status", "--active-jobs"],
    ]


@pytest.mark.parametrize(
    ("worker", "jobs", "units", "no_systemd"),
    ((0, 0, 0, False), (3, 3, 3, False), (0, 3, 0, True)),
)
def test_repeat_reports_read_only_states(
    tmp_path: Path,
    worker: int,
    jobs: int,
    units: int,
    no_systemd: bool,
) -> None:
    """重复报告将0/3解释为状态；默认模式报告两个单元，前台模式不调用管理器且均无启停。"""
    case = setup_case(tmp_path)
    deploy = case.home / ".local/opt/rdp"
    (deploy / ".venv/bin").mkdir(parents=True)
    (deploy / ".venv/bin/rdp").symlink_to(case.binary / "rdp")
    (deploy / "rdp-build.json").write_text('{"commit":"' + "a" * 40 + '"}')
    result = case.run(
        *(["--no-systemd"] if no_systemd else []),
        overrides={
            "FAKE_WORKER_STATUS": str(worker),
            "FAKE_ACTIVE_STATUS": str(jobs),
            "FAKE_UNITS_STATUS": str(units),
        },
    )
    assert result.returncode == 0, result.stderr
    assert ("worker 已停止" if worker == 0 else "worker 在线") in result.stdout
    assert ("无活跃作业" if jobs == 0 else "存在活跃作业") in result.stdout
    calls = case.calls("systemctl")
    assert [call["args"] for call in calls] == (
        [] if no_systemd else [["--user", "is-active", "rdp-web.service", "rdp-worker.service"]]
    )
    if not no_systemd:
        assert ("active" if units == 0 else "inactive") in result.stdout
    assert not any(case.calls(name) for name in ("install.sh", "uv", "curl", "loginctl"))


def test_fake_entrypoints_enforce_real_argument_contracts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """替身拒绝真实入口不接受的参数；rdp/install/管理员查询均在任何业务动作前返回参数错误。"""
    import subprocess

    case = setup_case(tmp_path)
    monkeypatch.setenv("HOME", str(case.home))
    for program, args in (
        ("rdp", ["status"]),
        ("rdp", ["status", "--active-jobs", "--worker-stopped"]),
        ("install.sh", ["--unexpected"]),
        (
            "python",
            [
                "-m",
                "rdp.ops.setup_queries",
                "administrator",
                "--wrong-database",
                str(case.home / "absent"),
            ],
        ),
    ):
        result = subprocess.run(  # noqa: S603  # 理由：固定临时替身，HOME/PATH隔离，仅参数解析。
            [str(case.binary / program), *args],
            env=case.environment(),
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
        assert result.returncode == 2, (program, result.stderr)
    assert not (case.root / "installed").exists()
    assert not (case.home / "absent").exists()


@pytest.mark.parametrize(
    "failure",
    (
        {"FAKE_WORKER_STATUS": "1"},
        {"FAKE_WORKER_STATUS": "2"},
        {"FAKE_ACTIVE_STATUS": "1"},
        {"FAKE_UNITS_STATUS": "1"},
        {"FAKE_UNITS_STATUS": "4"},
    ),
)
def test_repeat_does_not_hide_status_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: dict[str, str]
) -> None:
    """状态0/3之外的配置、数据库或用户总线错误仍失败，不将查询故障当作正常状态。"""
    case = setup_case(tmp_path)
    monkeypatch.setenv("HOME", str(case.home))
    deploy = case.home / ".local/opt/rdp"
    (deploy / ".venv/bin").mkdir(parents=True)
    (deploy / ".venv/bin/rdp").symlink_to(case.binary / "rdp")
    (deploy / "rdp-build.json").write_text('{"commit":"' + "a" * 40 + '"}')
    result = case.run(overrides=failure)
    assert result.returncode == 1 and "失败" in result.stderr
    assert "已有完整部署" not in result.stdout
    assert not any(case.calls(name) for name in ("install.sh", "uv", "curl", "loginctl"))


def test_printed_upgrade_command_matches_script_parser(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """打印的升级命令替换提交占位符后通过真实脚本参数解析；--help在末尾阻止安装和服务动作。"""
    import shlex
    import shutil
    import subprocess

    case = setup_case(tmp_path)
    monkeypatch.setenv("HOME", str(case.home))
    deploy = case.home / ".local/opt/rdp"
    (deploy / ".venv/bin").mkdir(parents=True)
    (deploy / ".venv/bin/rdp").symlink_to(case.binary / "rdp")
    (deploy / "rdp-build.json").write_text('{"commit":"' + "a" * 40 + '"}')
    result = case.run("--no-systemd")
    assert result.returncode == 0, result.stderr
    line = next(line for line in result.stdout.splitlines() if "升级命令：" in line)
    command = shlex.split(line.partition("升级命令：")[2])
    assert command[:2] == ["bash", str(case.source / "scripts/upgrade.sh")]
    assert command[-1] == "<本地提交>"
    upgrade = case.root / "contracts/upgrade.sh"
    shutil.copyfile(Path(__file__).parents[1] / "scripts/upgrade.sh", upgrade)
    parsed = subprocess.run(  # noqa: S603  # 理由：临时脚本副本只解析参数后显示帮助，所有外部命令隔离。
        ["/bin/bash", str(upgrade), *command[2:-1], "a" * 40, "--help"],
        env=case.environment(),
        capture_output=True,
        text=True,
        timeout=3,
        check=False,
    )
    assert parsed.returncode == 0 and "--deploy-dir" in parsed.stdout, parsed.stderr
    assert not case.calls("install.sh") and not case.calls("systemctl")


def test_questionnaire_continues_with_stacked_mounts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """含叠加挂载的问答保留并解释两层，仍可选择独立ext4根，生成通过平台校验的配置。"""
    import json

    from rdp.ops.setup_queries import validate_setup_configuration

    case = setup_case(tmp_path)
    monkeypatch.setenv("HOME", str(case.home))
    (case.binary / "nvidia-smi").unlink()
    stacked = case.home / "a-stacked"
    disk = case.home / "z-disk"
    mounts = {
        "filesystems": [
            {
                "target": str(stacked),
                "source": "systemd-1",
                "fstype": "autofs",
                "uuid": None,
                "options": "rw",
            },
            {
                "target": str(stacked),
                "source": "binfmt_misc",
                "fstype": "binfmt_misc",
                "uuid": None,
                "options": "rw",
            },
            {
                "target": str(disk),
                "source": "/dev/example",
                "fstype": "ext4",
                "uuid": "123e4567-e89b-42d3-a456-426614174000",
                "options": "ro",
            },
        ]
    }
    result = case.interactive(
        "--yes",
        "--skip-admin",
        answers=f"127.0.0.1\n9123\n{case.home / 'nav'}\n\n3\ndisk\n",
        overrides={"FAKE_MOUNTS": json.dumps(mounts)},
    )
    assert result.returncode == 0, result.stdout
    assert result.stdout.count("叠加挂载，无法确认哪一层可见") == 2
    assert "autofs" in result.stdout and "binfmt_misc" in result.stdout
    config = validate_setup_configuration(
        case.home / ".config/rdp/config.toml", home=case.home
    ).config
    assert len(config.storage_roots) == 1
    root = config.storage_roots[0]
    assert root.name == "disk" and root.path == disk
    assert root.uuid == "123e4567-e89b-42d3-a456-426614174000" and not root.writable
    assert not disk.exists() and not stacked.exists()
    assert len(case.calls("install.sh")) == 1


@pytest.mark.parametrize("selection", ("1", "2"))
def test_questionnaire_cannot_select_either_stacked_layer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, selection: str
) -> None:
    """两个原本来源合法的ext4叠加层都不能选择，不发布配置、不进入安装。"""
    import json

    case = setup_case(tmp_path)
    monkeypatch.setenv("HOME", str(case.home))
    row = {
        "target": str(case.home / "stacked"),
        "source": "/dev/example",
        "fstype": "ext4",
        "uuid": "123e4567-e89b-42d3-a456-426614174000",
        "options": "ro",
    }
    mounts = {"filesystems": [row, row | {"source": "/dev/other", "options": "rw"}]}
    result = case.interactive(
        "--yes",
        "--skip-admin",
        answers=f"127.0.0.1\n9123\n{case.home / 'nav'}\n\n{selection}\n",
        overrides={"FAKE_MOUNTS": json.dumps(mounts)},
    )
    assert result.returncode == 1 and "所选存储根不可选" in result.stdout
    assert result.stdout.count("叠加挂载，无法确认哪一层可见") == 2
    assert not (case.home / ".config/rdp/config.toml").exists()
    assert not case.calls("install.sh") and not case.calls("nvidia-smi")
