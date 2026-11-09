"""M5-04 安装验收：小 tar 包和临时状态目录，不读取真实发布包或访问网络。"""

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


def _archive(path: Path, *, unsafe: bool = False) -> str:
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
        ):
            member = tarfile.TarInfo(name)
            member.size = len(data)
            archive.addfile(member, io.BytesIO(data))
    return hashlib.sha256(path.read_bytes()).hexdigest()


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


def test_installed_viewer_is_authenticated_and_served_with_csp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """验收 1/CSP 修复：安装可重入；授权内嵌脚本及解码所需能力，仍拦外网，无 X-Frame-Options。"""
    inputs = runtime_inputs(tmp_path / "deploy", migrated=False)
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
    state = inputs.home / "state"
    assert not list(state.rglob("*.map"))
    with api_case(tmp_path / "api") as case:
        configure_lichtblick(case.app, state_dir=state)
        assert case.client.get("/lichtblick/index.html").status_code == 401
        add_actor(case)
        case.login("member", SecretStr("member-updated-value"))
        response = case.client.get("/lichtblick/index.html")
        assert response.status_code == 200
        assert "Lichtblick test" in response.text
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
