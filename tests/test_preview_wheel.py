"""M5-09 离线 wheel 命令验收；使用小文件，不读取真实离线包。"""

import hashlib
import io
from contextlib import nullcontext
from pathlib import Path

import pytest
from ops_support import runtime_inputs

from rdp.infra import viz_relay
from rdp.ops.cli import Console, run_cli


def test_wheel_command_rejects_checksum_without_writing(tmp_path: Path) -> None:
    """验收 6：摘要不符时运维命令失败，状态目录没有新增产物。"""
    inputs = runtime_inputs(tmp_path, migrated=False)
    package = tmp_path / viz_relay.WHEEL_FILENAME
    package.write_bytes(b"not the approved wheel")
    stderr = io.StringIO()
    console = Console(io.StringIO(), stderr, lambda _: "")
    assert (
        run_cli(
            ["install-viz-relay-wheel", str(package)],
            inputs=inputs,
            console=console,
            web=lambda _: 0,
            signals=lambda _: nullcontext(),
        )
        == 1
    )
    assert not (inputs.home / "state").exists()
    assert "sha256" in stderr.getvalue()


def test_wheel_command_installs_verified_local_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """验收 6：合法小包原子发布，重复安装成功且内容不变。"""
    inputs = runtime_inputs(tmp_path, migrated=False)
    package = tmp_path / viz_relay.WHEEL_FILENAME
    package.write_bytes(b"test-wheel")
    monkeypatch.setattr(viz_relay, "WHEEL_SHA256", hashlib.sha256(b"test-wheel").hexdigest())
    stderr = io.StringIO()
    console = Console(io.StringIO(), stderr, lambda _: "")
    for _ in range(2):
        assert (
            run_cli(
                ["install-viz-relay-wheel", str(package)],
                inputs=inputs,
                console=console,
                web=lambda _: 0,
                signals=lambda _: nullcontext(),
            )
            == 0
        )
    assert (inputs.home / "state/viz_relay/wheels" / package.name).read_bytes() == b"test-wheel"
