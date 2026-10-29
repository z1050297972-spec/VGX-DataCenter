"""部署工具真实发行格式与下载失败契约；只使用临时HOME和本地响应替身。"""

from pathlib import Path

import pytest
from setup_support import release_downloads, setup_case


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
    assert len(downloads) == (0 if installed else 2)
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
    assert len(calls) == 2
    assert calls[0]["args"][-1].endswith("/pnpm/pnpm/releases/tags/v11.22.0")
    assert calls[1]["args"][-1].endswith("/pnpm/pnpm/releases/assets/123")
    help_text = case.run("--help").stdout
    assert "pnpm-linux-<架构>.tar.gz" in help_text and "官方 tar.gz" in help_text


def test_tls_failure_retries_then_verifies_download(tmp_path: Path) -> None:
    """首次TLS错误35后重试成功，仍校验官方digest并完成安装，不回显底层连接诊断。"""
    import json

    case = setup_case(tmp_path)
    case.config()
    release_downloads(case, "uv")
    url = "https://api.github.com/repos/astral-sh/uv/releases/tags/0.13.5"
    (case.root / "responses.json").write_text(json.dumps({url: [{"exit": 35}, {"code": "200"}]}))
    result = case.run("--yes", "--skip-admin", overrides={"FAKE_VERSION_UV": "missing"})
    assert result.returncode == 0, result.stderr
    assert len([call for call in case.calls("curl") if call["args"][-1] == url]) == 2
    assert (case.home / ".local/bin/uv").is_symlink()
    assert "模拟TLS连接错误" not in result.stderr


@pytest.mark.parametrize("status", ("403", "429"))
def test_github_rate_limit_reports_reset_without_retry(tmp_path: Path, status: str) -> None:
    """GitHub限流响应明确报告UTC重试时间和手动办法，只请求一次，不泄漏响应体或绕过校验。"""
    import json

    case = setup_case(tmp_path)
    case.config()
    release_downloads(case, "uv")
    url = "https://api.github.com/repos/astral-sh/uv/releases/tags/0.13.5"
    response = {
        "code": status,
        "headers": "x-ratelimit-reset: 1700000000\r\n",
        "body": '{"message":"API rate limit exceeded for private-egress-address"}',
    }
    (case.root / "responses.json").write_text(json.dumps({url: [response]}))
    result = case.run("--yes", "--skip-admin", overrides={"FAKE_VERSION_UV": "missing"})
    assert result.returncode == 1
    assert "GitHub限流" in result.stderr
    assert "2023-11-14T22:13:20.000Z" in result.stderr
    assert "手动安装" in result.stderr and "SHA256" in result.stderr
    assert "private-egress-address" not in result.stderr
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
    url = "https://api.github.com/repos/astral-sh/uv/releases/tags/0.13.5"
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
    url = "https://api.github.com/repos/astral-sh/uv/releases/tags/0.13.5"
    (case.root / "responses.json").write_text(json.dumps({url: [{"delay_s": 5, "exit": 35}]}))
    started = time.monotonic()
    result = case.run("--yes", "--skip-admin", overrides={"FAKE_VERSION_UV": "missing"})
    assert time.monotonic() - started < 4
    assert result.returncode == 1 and len(case.calls("curl")) == 1
    assert not (case.home / ".local/bin/uv").exists()


@pytest.mark.parametrize("header", ("", "X-RateLimit-Reset: invalid\n"))
def test_rate_limit_without_valid_reset_is_explicit(tmp_path: Path, header: str) -> None:
    """缺失或非法reset头不编造时间，仍明确报告限流和手动办法且不重试。"""
    import json

    case = setup_case(tmp_path)
    case.config()
    release_downloads(case, "uv")
    url = "https://api.github.com/repos/astral-sh/uv/releases/tags/0.13.5"
    (case.root / "responses.json").write_text(
        json.dumps(
            {url: [{"code": "429", "headers": header, "body": '{"message":"rate limit exceeded"}'}]}
        )
    )
    result = case.run("--yes", "--skip-admin", overrides={"FAKE_VERSION_UV": "missing"})
    assert result.returncode == 1 and "GitHub限流" in result.stderr
    assert "未提供有效重试时间" in result.stderr and "手动安装" in result.stderr
    assert len(case.calls("curl")) == 1


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


@pytest.mark.parametrize("layout", ("outer/inner", "duplicate", "link-escape", "musl-only"))
def test_pnpm_rejects_unexpected_or_unsafe_archive(tmp_path: Path, layout: str) -> None:
    """不猜测深层或歧义入口，不选musl，不允许链接逃逸；失败时不发布pnpm。"""
    import hashlib
    import io
    import json
    import tarfile

    case = setup_case(tmp_path)
    case.config()
    release_downloads(
        case, "pnpm", package_layout="outer/inner" if layout == "outer/inner" else "root"
    )
    archive = case.root / "pnpm-linux-x64.tar.gz"
    metadata = case.root / "pnpm.json"
    data = json.loads(metadata.read_text())
    if layout == "musl-only":
        data["assets"][0]["name"] = "pnpm-linux-x64-musl.tar.gz"
    elif layout in ("duplicate", "link-escape"):
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
        data["assets"][0]["digest"] = "sha256:" + hashlib.sha256(archive.read_bytes()).hexdigest()
    metadata.write_text(json.dumps(data))
    result = case.run("--yes", "--skip-admin", overrides={"FAKE_VERSION_PNPM": "missing"})
    assert result.returncode == 1, result.stderr
    if layout in ("outer/inner", "duplicate"):
        assert "pnpm归档结构不符合预期" in result.stderr
    assert not (case.home / ".local/bin/pnpm").exists()
    assert not list(case.home.glob(".local/opt/rdp-tools/pnpm/.incoming.*"))
    assert not case.calls("install.sh")


@pytest.mark.parametrize("tool", ("uv", "pnpm"))
def test_verified_archive_still_requires_matching_version(tmp_path: Path, tool: str) -> None:
    """即使digest正确，新工具自身报告的版本不匹配也不能发布，避免放宽版本解析后跳过自检。"""
    import hashlib
    import io
    import json
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
    metadata = case.root / (tool + ".json")
    data = json.loads(metadata.read_text())
    data["assets"][0]["digest"] = "sha256:" + hashlib.sha256(archive.read_bytes()).hexdigest()
    metadata.write_text(json.dumps(data))
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
    url = "https://api.github.com/repos/astral-sh/uv/releases/tags/0.13.5"
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
    url = "https://api.github.com/repos/astral-sh/uv/releases/tags/0.13.5"
    (case.root / "responses.json").write_text(json.dumps({url: [{"delay_s": 0.8, "exit": 35}]}))
    started = time.monotonic()
    result = case.run("--yes", "--skip-admin", overrides={"FAKE_VERSION_UV": "missing"})
    assert result.returncode == 1 and "预算" in result.stderr
    assert time.monotonic() - started < 3
    assert 1 <= len(case.calls("curl")) <= 2
    assert not (case.home / ".local/bin/uv").exists()
