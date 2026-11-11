"""M5-04/10 安装验收：小 tar 包和临时状态目录，不读取真实发布包或访问网络。"""

import hashlib
import io
import tarfile
from contextlib import nullcontext
from pathlib import Path

import pytest
from account_api_support import add_actor, api_case
from ops_support import runtime_inputs
from pydantic import SecretStr

from rdp.api.lichtblick import configure_lichtblick
from rdp.infra import lichtblick
from rdp.ops.cli import Console, run_cli


def _archive(path: Path, *, unsafe: bool = False, matches: int = 2) -> str:
    """只造可区分安装行为的小包；固定内容不依赖发布包或系统文件。"""
    with tarfile.open(path, "w:gz") as archive:
        for name, data in (
            (
                "index.html",
                (
                    "<html>Lichtblick test<script>\nwindow.viewerReady = true;\n</script>"
                    '<script>window.decoderMode = "本机 &amp; 数据";</script>'
                    '<script src="./bundle.js">忽略外链脚本内容</script></html>'
                ).encode(),
            ),
            ("decoder.wasm", b"\x00asm"),
            ("bundle.js.map", b"{}"),
            ("../escape" if unsafe else "bundle.js", b"test"),
            *(
                (
                    f"chunks/{index}.js",
                    (
                        f"// 中文\r\nconst {variable}=10;"
                        f'let wait=codec.startsWith("hvc1")===!0?2e3:{variable};'
                        f"other({variable});\r\n"
                    ).encode(),
                )
                for index, variable in enumerate(("$X_2", "Ke", "A")[:matches])
            ),
        ):
            member = tarfile.TarInfo(name)
            member.size = len(data)
            archive.addfile(member, io.BytesIO(data))
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_install_patches_only_h264_wait(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """M5-10 验收 1：两处 H.264 等待改成 100 毫秒，其余字节（含 H.265）不变。"""
    inputs = runtime_inputs(tmp_path, migrated=False)
    package = tmp_path / "lichtblick-web.tar.gz"
    monkeypatch.setattr(lichtblick, "LICHTBLICK_SHA256", _archive(package))
    assert (
        run_cli(
            ["install-lichtblick", str(package)],
            inputs=inputs,
            console=Console(io.StringIO(), io.StringIO(), lambda _: ""),
            web=lambda _: 0,
            signals=lambda _: nullcontext(),
        )
        == 0
    )
    directory = lichtblick.lichtblick_directory(inputs.home / "state")
    expected_chunks = {
        "chunks/0.js": (
            b"// \xe4\xb8\xad\xe6\x96\x87\r\nconst $X_2=10;"
            b'let wait=codec.startsWith("hvc1")===!0?2e3:100;other($X_2);\r\n'
        ),
        "chunks/1.js": (
            b"// \xe4\xb8\xad\xe6\x96\x87\r\nconst Ke=10;"
            b'let wait=codec.startsWith("hvc1")===!0?2e3:100;other(Ke);\r\n'
        ),
    }
    with tarfile.open(package, "r:gz") as archive:
        for member in archive.getmembers():
            if member.name.endswith(".map"):
                continue
            original = archive.extractfile(member)
            assert original is not None
            expected = expected_chunks.get(member.name, original.read())
            assert (directory / member.name).read_bytes() == expected


@pytest.mark.parametrize("failure", ["checksum", "traversal"])
def test_install_rejects_package_without_writing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    """验收 1：摘要不符或包含 ../ 条目时命令失败，不创建状态目录或越界文件。"""
    inputs = runtime_inputs(tmp_path, migrated=False)
    package = tmp_path / "lichtblick-web.tar.gz"
    digest = _archive(package, unsafe=failure == "traversal")
    monkeypatch.setattr(
        lichtblick, "LICHTBLICK_SHA256", "0" * 64 if failure == "checksum" else digest
    )
    stderr = io.StringIO()
    code = run_cli(
        ["install-lichtblick", str(package)],
        inputs=inputs,
        console=Console(io.StringIO(), stderr, lambda _: ""),
        web=lambda _: 0,
        signals=lambda _: nullcontext(),
    )
    assert code == 1
    assert "lichtblick." in stderr.getvalue()
    assert not (inputs.home / "state").exists()
    assert not (tmp_path / "escape").exists()


@pytest.mark.parametrize("matches", [1, 3])
def test_install_rejects_unexpected_patch_count(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, matches: int
) -> None:
    """M5-10 验收 2：匹配不是两处时给出诊断，不发布目录或留下临时产物。"""
    inputs = runtime_inputs(tmp_path, migrated=False)
    package = tmp_path / "lichtblick-web.tar.gz"
    monkeypatch.setattr(lichtblick, "LICHTBLICK_SHA256", _archive(package, matches=matches))
    stderr = io.StringIO()
    assert (
        run_cli(
            ["install-lichtblick", str(package)],
            inputs=inputs,
            console=Console(io.StringIO(), stderr, lambda _: ""),
            web=lambda _: 0,
            signals=lambda _: nullcontext(),
        )
        == 1
    )
    diagnostic = stderr.getvalue()
    for part in (
        "1.30.0",
        "lichtblick.h264_wait",
        "Lichtblick 包内容和预期不同，H.264 等待补丁没法打",
        f"{matches} 处",
        "2 处",
        "未发布",
        "rdp install-lichtblick",
    ):
        assert part in diagnostic
    assert list((inputs.home / "state" / "lichtblick").iterdir()) == []


def test_installed_viewer_is_authenticated_and_served_with_csp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """M5-04/10：升级仅托管新目录且响应需重验证缓存，保留认证、CSP 和 WASM 类型。"""
    inputs = runtime_inputs(tmp_path / "deploy", migrated=False)
    state = inputs.home / "state"
    old_directory = state / "lichtblick" / "1.30.0"
    old_directory.mkdir(parents=True)
    (old_directory / "index.html").write_bytes(b"old viewer")
    package = tmp_path / "lichtblick-web.tar.gz"
    monkeypatch.setattr(lichtblick, "LICHTBLICK_SHA256", _archive(package))
    for _ in range(2):
        assert (
            run_cli(
                ["install-lichtblick", str(package)],
                inputs=inputs,
                console=Console(io.StringIO(), io.StringIO(), lambda _: ""),
                web=lambda _: 0,
                signals=lambda _: nullcontext(),
            )
            == 0
        )
    assert (state / "lichtblick" / "1.30.0-rdp1" / "index.html").is_file()
    assert (old_directory / "index.html").read_bytes() == b"old viewer"
    assert not list(state.rglob("*.map"))
    with api_case(tmp_path / "api") as case:
        configure_lichtblick(case.app, state_dir=state)
        response = case.client.get("/lichtblick/index.html")
        assert response.status_code == 401
        assert response.headers["cache-control"] == "no-cache"
        add_actor(case)
        case.login("member", SecretStr("member-updated-value"))
        response = case.client.get("/lichtblick/index.html")
        assert response.status_code == 200
        assert "Lichtblick test" in response.text
        assert response.headers["cache-control"] == "no-cache"
        assert "x-frame-options" not in response.headers
        directives = {
            parts[0]: set(parts[1:])
            for directive in response.headers["content-security-policy"].split(";")
            if (parts := directive.split())
        }
        # 用 openssl 对夹具中的两段原文独立求摘要；空白、中文和 &amp; 都属于脚本文本。
        assert directives["script-src"] == {
            "'self'",
            "'wasm-unsafe-eval'",
            "'unsafe-eval'",
            "'sha256-edqOxiurEVM1IK8WaOF/8YOPlG/2W/u8XrDH2x9kXHI='",
            "'sha256-qJ7sSXGixwl15sf35NjZ9TTK/9BDAGMFLcX4q/FCkto='",
        }
        assert directives["connect-src"] == {"'self'", "ws:", "blob:", "data:"}
        response = case.client.get("/lichtblick/decoder.wasm")
        assert response.status_code == 200
        assert response.headers["content-type"] == "application/wasm"
        assert response.headers["cache-control"] == "no-cache"
        response = case.client.get("/lichtblick/chunks/0.js")
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-cache"
        response = case.client.get(
            "/lichtblick/chunks/0.js", headers={"If-None-Match": response.headers["etag"]}
        )
        assert response.status_code == 304
        assert response.headers["cache-control"] == "no-cache"
        response = case.client.get("/lichtblick/missing.js")
        assert response.status_code == 404
        assert response.headers["cache-control"] == "no-cache"


def test_old_viewer_alone_is_not_served(tmp_path: Path) -> None:
    """M5-10 验收 3：只有旧目录视为未安装，根路径返回 404、安装命令和 no-cache。"""
    state = tmp_path / "viewer"
    directory = state / "lichtblick" / "1.30.0"
    directory.mkdir(parents=True)
    (directory / "index.html").write_bytes(b"old viewer")
    with api_case(tmp_path / "api") as case:
        configure_lichtblick(case.app, state_dir=state)
        add_actor(case)
        case.login("member", SecretStr("member-updated-value"))
        response = case.client.get("/lichtblick/")
        assert response.status_code == 404
        assert "rdp install-lichtblick" in response.text
        assert response.headers["cache-control"] == "no-cache"
