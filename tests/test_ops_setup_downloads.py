"""部署工具真实发行格式与下载失败契约；只使用临时HOME和本地响应替身。"""

from pathlib import Path

import pytest
from setup_support import pin_release_digest, release_downloads, release_url, setup_case


@pytest.fixture(autouse=True)
def isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """测试进程和所有子进程都使用临时用户目录。"""
    monkeypatch.setenv("HOME", str(tmp_path))


def test_missing_noninteractive_config_stops_before_tools(tmp_path: Path) -> None:
    """无终端且配置缺失时直接返回2；不探测、下载、安装工具或创建部署暂存。"""
    case = setup_case(tmp_path)
    result = case.run("--yes", "--no-systemd", overrides={"FAKE_VERSION_NODE": "missing"})
    assert result.returncode == 2, result.stderr
    assert "配置缺失" in result.stderr
    assert not any(case.calls(name) for name in ("node", "uv", "pnpm", "curl", "install.sh"))
    assert list(case.home.iterdir()) == []
    assert list((case.root / "tmp").iterdir()) == []


@pytest.mark.parametrize("installed", (True, False))
def test_uv_real_version_output_is_accepted(tmp_path: Path, installed: bool) -> None:
    """已有uv和新归档中的uv均接受真实平台后缀，不能重复下载安装或误拒绝正确版本。"""
    case = setup_case(tmp_path)
    case.config()
    if not installed:
        release_downloads(case, "uv")
    result = case.run(
        "--yes", "--skip-admin", overrides={} if installed else {"FAKE_VERSION_UV": "missing"}
    )
    assert result.returncode == 0, result.stderr
    downloads = [call for call in case.calls("curl") if call["args"][-1].startswith("https://")]
    assert len(downloads) == (0 if installed else 1)
    assert (case.home / ".local/bin/uv").exists() is (not installed)


@pytest.mark.parametrize("layout", ("root", "pnpm-linux-x64"))
def test_pnpm_official_archive_layouts(tmp_path: Path, layout: str) -> None:
    """按官方glibc tar.gz资产名校验并解包；根目录和一层目录中的pnpm均能自检后发布。"""
    case = setup_case(tmp_path)
    case.config()
    release_downloads(case, "pnpm", package_layout=layout)
    result = case.run("--yes", "--skip-admin", overrides={"FAKE_VERSION_PNPM": "missing"})
    assert result.returncode == 0, result.stderr
    executable = case.home / ".local/bin/pnpm"
    assert executable.is_symlink() and executable.resolve().is_file()
    assert executable.resolve().is_relative_to(case.home / ".local/opt/rdp-tools/pnpm")
    calls = [call for call in case.calls("curl") if call["args"][-1].startswith("https://")]
    assert len(calls) == 1
    assert calls[0]["args"][-1] == release_url("pnpm")
    help_text = case.run("--help").stdout
    assert "pnpm-linux-<架构>.tar.gz" in help_text and "官方 tar.gz" in help_text


def test_tls_failure_retries_then_verifies_download(tmp_path: Path) -> None:
    """首次TLS错误35后重试成功，仍校验固定SHA256并完成安装，不回显底层连接诊断。"""
    import json

    case = setup_case(tmp_path)
    case.config()
    release_downloads(case, "uv")
    url = release_url("uv")
    (case.root / "responses.json").write_text(json.dumps({url: [{"exit": 35}, {"code": "200"}]}))
    result = case.run("--yes", "--skip-admin", overrides={"FAKE_VERSION_UV": "missing"})
    assert result.returncode == 0, result.stderr
    assert len([call for call in case.calls("curl") if call["args"][-1] == url]) == 2
    assert (case.home / ".local/bin/uv").is_symlink()
    assert "模拟TLS连接错误" not in result.stderr


@pytest.mark.parametrize("status", ("403", "429"))
def test_download_denied_or_throttled_is_explicit(tmp_path: Path, status: str) -> None:
    """下载地址拒绝或限流时给通用HTTP诊断和手动办法，不请求API、不重试4xx、不回显响应体。"""
    import json

    case = setup_case(tmp_path)
    case.config()
    release_downloads(case, "uv")
    url = release_url("uv")
    response = {"code": status, "body": "opaque server error private-egress-address"}
    (case.root / "responses.json").write_text(json.dumps({url: [response]}))
    result = case.run("--yes", "--skip-admin", overrides={"FAKE_VERSION_UV": "missing"})
    assert result.returncode == 1
    assert "被拒绝或限流" in result.stderr and "HTTP " + status in result.stderr
    assert "手动安装" in result.stderr and "SHA256" in result.stderr
    assert "API" not in result.stderr and "private-egress-address" not in result.stderr
    assert len(case.calls("curl")) == 1
    assert not (case.home / ".local/bin/uv").exists()
    assert list((case.root / "tmp").iterdir()) == []


@pytest.mark.parametrize(
    ("response", "expected_calls"),
    (
        ({"exit": 35}, 3),
        ({"exit": 7}, 3),
        ({"exit": 60}, 1),
        ({"code": "503", "body": "unavailable"}, 3),
        ({"code": "404", "body": "not found"}, 1),
        ({"code": "403", "body": "forbidden"}, 1),
        ({"code": "429", "body": "busy"}, 1),
    ),
)
def test_retry_classification_is_bounded(
    tmp_path: Path, response: dict[str, object], expected_calls: int
) -> None:
    """传输故障至多重试两次；证书错误和所有4xx不重试，也不发布任何未验证工具。"""
    import json

    case = setup_case(tmp_path)
    case.config()
    release_downloads(case, "uv")
    url = release_url("uv")
    (case.root / "responses.json").write_text(json.dumps({url: [response]}))
    result = case.run("--yes", "--skip-admin", overrides={"FAKE_VERSION_UV": "missing"})
    assert result.returncode == 1
    assert len(case.calls("curl")) == expected_calls
    for call in case.calls("curl"):
        assert call["args"][call["args"].index("--retry") + 1] == "0"
    assert not (case.home / ".local/bin/uv").exists()


def test_download_total_budget_covers_blocked_request(tmp_path: Path) -> None:
    """缩小测试副本总预算后，阻塞请求被外层timeout终止，不重新获得一份完整重试预算。"""
    import json
    import time

    case = setup_case(tmp_path)
    case.config()
    release_downloads(case, "uv")
    script = case.source / "scripts/setup.sh"
    script.write_text(
        script.read_text().replace("SETUP_DOWNLOAD_TIMEOUT_S=300", "SETUP_DOWNLOAD_TIMEOUT_S=1")
    )
    url = release_url("uv")
    (case.root / "responses.json").write_text(json.dumps({url: [{"delay_s": 5, "exit": 35}]}))
    started = time.monotonic()
    result = case.run("--yes", "--skip-admin", overrides={"FAKE_VERSION_UV": "missing"})
    assert time.monotonic() - started < 4
    assert result.returncode == 1 and len(case.calls("curl")) == 1
    assert not (case.home / ".local/bin/uv").exists()


@pytest.mark.parametrize(
    ("tool", "output"),
    (
        ("node", "v22.23.20"),
        ("node", "v22.23.2-rc1"),
        ("uv", "uv 0.13.50 (x86_64-unknown-linux-gnu)"),
        ("uv", "uv 0.13.5-dev"),
        ("pnpm", "11.22.00"),
        ("pnpm", "11.22.0-dev"),
    ),
)
def test_version_comparison_requires_token_boundary(tmp_path: Path, tool: str, output: str) -> None:
    """相近补丁号和预发行后缀不能冒充固定版本，仍须询问且拒绝后不下载。"""
    case = setup_case(tmp_path)
    case.config()
    result = case.interactive("--no-systemd", overrides={"FAKE_VERSION_" + tool.upper(): output})
    assert result.returncode == 130, result.stdout
    assert "安装" + tool in result.stdout
    assert not case.calls("curl")


@pytest.mark.parametrize("layout", ("outer/inner", "duplicate", "link-escape"))
def test_pnpm_rejects_unexpected_or_unsafe_archive(tmp_path: Path, layout: str) -> None:
    """不猜测深层或歧义入口，不允许链接逃逸；失败时不发布pnpm。"""
    import io
    import tarfile

    case = setup_case(tmp_path)
    case.config()
    release_downloads(
        case, "pnpm", package_layout="outer/inner" if layout == "outer/inner" else "root"
    )
    archive = case.root / "pnpm-linux-x64.tar.gz"
    if layout in ("duplicate", "link-escape"):
        with tarfile.open(archive) as stream:
            original = stream.getmembers()[0]
            reader = stream.extractfile(original)
            assert reader is not None
            payload = reader.read()
        with tarfile.open(archive, "w:gz") as stream:
            stream.addfile(original, io.BytesIO(payload))
            extra = tarfile.TarInfo("other/pnpm" if layout == "duplicate" else "outside")
            if layout == "duplicate":
                extra.size, extra.mode = len(payload), 0o755
                stream.addfile(extra, io.BytesIO(payload))
            else:
                extra.type, extra.linkname = tarfile.SYMTYPE, "../escape"
                stream.addfile(extra)
        pin_release_digest(case, "pnpm")
    result = case.run("--yes", "--skip-admin", overrides={"FAKE_VERSION_PNPM": "missing"})
    assert result.returncode == 1, result.stderr
    if layout in ("outer/inner", "duplicate"):
        assert "pnpm归档结构不符合预期" in result.stderr
    assert not (case.home / ".local/bin/pnpm").exists()
    assert not list(case.home.glob(".local/opt/rdp-tools/pnpm/.incoming.*"))
    assert not case.calls("install.sh")


@pytest.mark.parametrize("tool", ("uv", "pnpm"))
def test_verified_archive_still_requires_matching_version(tmp_path: Path, tool: str) -> None:
    """即使固定摘要正确，新工具自身报告的版本不匹配也不能发布，避免放宽版本解析后跳过自检。"""
    import io
    import tarfile

    case = setup_case(tmp_path)
    case.config()
    release_downloads(case, tool)
    archive = case.root / (
        "uv-x86_64-unknown-linux-gnu.tar.gz" if tool == "uv" else "pnpm-linux-x64.tar.gz"
    )
    with tarfile.open(archive) as stream:
        entry = stream.getmembers()[0]
        reader = stream.extractfile(entry)
        assert reader is not None
        original = reader.read()
    payload = (
        original.replace(b"0.13.5", b"0.13.50")
        if tool == "uv"
        else original.replace(b"11.22.0", b"11.22.1")
    )
    with tarfile.open(archive, "w:gz") as stream:
        entry.size = len(payload)
        stream.addfile(entry, io.BytesIO(payload))
    pin_release_digest(case, tool)
    result = case.run(
        "--yes", "--skip-admin", overrides={"FAKE_VERSION_" + tool.upper(): "missing"}
    )
    assert result.returncode == 1 and "版本自检失败" in result.stderr
    assert not (case.home / ".local/bin" / tool).exists()
    assert not case.calls("install.sh")


def test_http_client_error_is_not_retried_after_body_timeout(tmp_path: Path) -> None:
    """已经收到403时，即使读取错误体随后超时，也不能把该4xx重新分类为可重试请求。"""
    import json

    case = setup_case(tmp_path)
    case.config()
    release_downloads(case, "uv")
    url = release_url("uv")
    (case.root / "responses.json").write_text(json.dumps({url: [{"code": "403", "exit": 28}]}))
    result = case.run("--yes", "--skip-admin", overrides={"FAKE_VERSION_UV": "missing"})
    assert result.returncode == 1
    assert len(case.calls("curl")) == 1


def test_total_budget_is_shared_by_tls_retries(tmp_path: Path) -> None:
    """短于单次预算的TLS失败累积消耗同一总预算，不能每次重试都重新计时。"""
    import json
    import time

    case = setup_case(tmp_path)
    case.config()
    release_downloads(case, "uv")
    script = case.source / "scripts/setup.sh"
    script.write_text(
        script.read_text().replace("SETUP_DOWNLOAD_TIMEOUT_S=300", "SETUP_DOWNLOAD_TIMEOUT_S=1")
    )
    url = release_url("uv")
    (case.root / "responses.json").write_text(json.dumps({url: [{"delay_s": 0.8, "exit": 35}]}))
    started = time.monotonic()
    result = case.run("--yes", "--skip-admin", overrides={"FAKE_VERSION_UV": "missing"})
    assert result.returncode == 1 and "预算" in result.stderr
    assert time.monotonic() - started < 3
    assert 1 <= len(case.calls("curl")) <= 2
    assert not (case.home / ".local/bin/uv").exists()


@pytest.mark.parametrize("tool", ("uv", "pnpm"))
def test_release_downloads_do_not_use_api(tmp_path: Path, tool: str) -> None:
    """工具下载直接使用releases/download，不请求GitHub API，也不跳过SHA256和版本自检。"""
    case = setup_case(tmp_path)
    case.config()
    release_downloads(case, tool)
    result = case.run(
        "--yes", "--skip-admin", overrides={"FAKE_VERSION_" + tool.upper(): "missing"}
    )
    assert result.returncode == 0, result.stderr
    urls = [
        call["args"][-1] for call in case.calls("curl") if call["args"][-1].startswith("https://")
    ]
    assert all("api.github.com" not in url for url in urls)
    expected = (
        "https://github.com/astral-sh/uv/releases/download/0.13.5/uv-x86_64-unknown-linux-gnu.tar.gz"
        if tool == "uv"
        else "https://github.com/pnpm/pnpm/releases/download/v11.22.0/pnpm-linux-x64.tar.gz"
    )
    assert urls == [expected]
    assert (case.home / ".local/bin" / tool).is_symlink()


def test_pinned_release_digests_match_approved_values() -> None:
    """生产摘要表逐项等于执行线核对的四个值，并且每个值只维护一份。"""
    script = (Path(__file__).parents[1] / "scripts/setup.sh").read_text()
    approved = {
        "uv:x86_64": "f68d291c75783122dad58ab77def0e13f3233f358731db5d6d7e8715603b928f",
        "uv:aarch64": "4bb69cf95ed13f23713bb7bc09f241896ea0c75b7c557e615a20604b82f9c403",
        "pnpm:x86_64": "4c592fa410eb23b69691a9efb9bf21c87c15b3e9d88c6ec8acdd354a0eb8de71",
        "pnpm:aarch64": "f1426231f365bdfd46c15fa3d1211c3936ee2c4e557afd304f6c66dbf1b2a8bf",
    }
    for key, value in approved.items():
        assert f"[{key}]='{value}'" in script
        assert script.count(value) == 1
    assert "升级版本时必须同时更新版本表和SHA256表" in script


@pytest.mark.parametrize("tool", ("uv", "pnpm"))
def test_fixed_digest_mismatch_never_publishes(tmp_path: Path, tool: str) -> None:
    """固定表摘要与归档不符时必须停下；不执行工具、不发布入口、不进入安装。"""
    case = setup_case(tmp_path)
    case.config()
    release_downloads(case, tool, digest="0" * 64)
    result = case.run(
        "--yes", "--skip-admin", overrides={"FAKE_VERSION_" + tool.upper(): "missing"}
    )
    assert result.returncode == 1 and "SHA256校验失败" in result.stderr
    assert len(case.calls("curl")) == 1
    assert not (case.home / ".local/bin" / tool).exists()
    assert not (case.home / ".local/opt/rdp-tools" / tool).exists()
    assert not case.calls("install.sh")


@pytest.mark.parametrize("machine", ("x86_64", "aarch64"))
@pytest.mark.parametrize("tool", ("uv", "pnpm"))
def test_architecture_selects_pinned_glibc_archive(tmp_path: Path, machine: str, tool: str) -> None:
    """两架构均选择对应glibc归档和摘要，不回退到其他架构或musl包。"""
    case = setup_case(tmp_path)
    case.config()
    release_downloads(case, tool, machine=machine)
    result = case.run(
        "--yes",
        "--skip-admin",
        overrides={
            "FAKE_ARCH": machine,
            "FAKE_VERSION_" + tool.upper(): "missing",
        },
    )
    assert result.returncode == 0, result.stderr
    urls = [
        call["args"][-1] for call in case.calls("curl") if call["args"][-1].startswith("https://")
    ]
    assert urls == [release_url(tool, machine)]
    assert "musl" not in urls[0]
    executable = (case.home / ".local/bin" / tool).resolve()
    assert executable.is_file() and machine in str(executable)


@pytest.mark.parametrize(
    "host", ("release-assets.githubusercontent.com", "objects.githubusercontent.com")
)
def test_official_asset_redirect_preserves_digest_check(tmp_path: Path, host: str) -> None:
    """releases地址可重定向到两个官方资产主机，最终字节仍须通过固定摘要后才能发布。"""
    import json

    case = setup_case(tmp_path)
    case.config()
    release_downloads(case, "uv")
    original = release_url("uv")
    redirect = f"https://{host}/fixture-asset"
    mappings = case.root / "downloads.json"
    data = json.loads(mappings.read_text())
    data[redirect] = data[original]
    mappings.write_text(json.dumps(data))
    (case.root / "responses.json").write_text(
        json.dumps({original: [{"code": "302", "body": "", "redirect": redirect}]})
    )
    result = case.run("--yes", "--skip-admin", overrides={"FAKE_VERSION_UV": "missing"})
    assert result.returncode == 0, result.stderr
    urls = [
        call["args"][-1] for call in case.calls("curl") if call["args"][-1].startswith("https://")
    ]
    assert urls == [original, redirect]
    assert (case.home / ".local/bin/uv").is_symlink()
