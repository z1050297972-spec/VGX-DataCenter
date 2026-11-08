"""M4-02 沙箱参数验收；只用临时目录，不依赖本机bwrap或真实存储。"""

from pathlib import Path

import pytest

from rdp.infra.diagnostics import InputError
from rdp.jobs.sandbox import SandboxSpec, sandbox_argv


def test_sandbox_arguments(tmp_path: Path) -> None:
    """验收5：根只读，仅指定暂存可写，隔离网络并随父退出，不经shell。"""
    staging = tmp_path / "staging"
    staging.mkdir()
    assert sandbox_argv(("/bin/tool", "含 空格"), SandboxSpec((staging,)), readonly_roots=()) == (
        "/usr/bin/bwrap",
        "--ro-bind",
        "/",
        "/",
        "--dev-bind",
        "/dev",
        "/dev",
        "--proc",
        "/proc",
        "--tmpfs",
        "/tmp",  # noqa: S108  # 理由：只核对沙箱的tmpfs参数，不访问宿主目录。
        "--bind",
        str(staging),
        str(staging),
        "--unshare-net",
        "--die-with-parent",
        "--",
        "/bin/tool",
        "含 空格",
    )


def test_sandbox_rejects_writing_readonly_roots(tmp_path: Path) -> None:
    """验收5安全底线：根目录、只读根及其子目录/符号链接别名均不能登记为可写。"""
    readonly = tmp_path / "readonly"
    child = readonly / "child"
    child.mkdir(parents=True)
    alias = tmp_path / "alias"
    alias.symlink_to(child, target_is_directory=True)
    for path in (Path("/"), readonly, child, alias):
        with pytest.raises(InputError):
            sandbox_argv(("/bin/tool",), SandboxSpec((path,)), readonly_roots=(readonly,))
