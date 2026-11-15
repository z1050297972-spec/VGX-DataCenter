"""M4.6-02 工具缓存的文件系统边界测试；所有目录和链接仅在 tmp_path 内。"""

import stat
from pathlib import Path

import pytest

from rdp.infra.config import ToolsConfig, load_config
from rdp.infra.diagnostics import DefectError, ExternalError
from rdp.jobs.tool_cache import result_file, tool_cache_dir


def test_creates_private_cache_directories(tmp_path: Path) -> None:
    """验收3：缓存根及缺失的祖先逐层以 0700 创建，重复调用返回同一路径。"""
    root = tmp_path / "state/tool-cache"
    settings = ToolsConfig(cache_root=root)
    cache = tool_cache_dir(settings, "agibot2lerobot")
    assert cache == root / "agibot2lerobot"
    for path in (tmp_path / "state", root, cache):
        assert stat.S_IMODE(path.stat().st_mode) == 0o700
    assert tool_cache_dir(settings, "agibot2lerobot") == cache


@pytest.mark.parametrize("level", ["state", "state/tool-cache", "state/tool-cache/agibot2lerobot"])
def test_cache_rejects_symlink_at_any_level(tmp_path: Path, level: str) -> None:
    """验收3：缓存路径的任何一层是符号链接都报五段外部诊断，不写链接目标。"""
    target = tmp_path / "outside"
    target.mkdir()
    link = tmp_path / level
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(target, target_is_directory=True)
    with pytest.raises(ExternalError) as caught:
        tool_cache_dir(ToolsConfig(cache_root=tmp_path / "state/tool-cache"), "agibot2lerobot")
    diagnostic = caught.value.diagnostics[0]
    assert diagnostic.objects and diagnostic.rule and diagnostic.actual and diagnostic.expected
    assert diagnostic.consequence and diagnostic.next_step
    assert list(target.iterdir()) == []


@pytest.mark.parametrize("tool_name", ["../agibot2lerobot", "/agibot2lerobot", "bad_name"])
def test_cache_rejects_invalid_tool_name(tmp_path: Path, tool_name: str) -> None:
    """安全底线：不符合清单命名的工具名在目录写入之前作为程序缺陷拒绝。"""
    root = tmp_path / "cache"
    with pytest.raises(DefectError):
        tool_cache_dir(ToolsConfig(cache_root=root), tool_name)
    assert not root.exists()


def test_result_file_removes_previous_regular_file(tmp_path: Path) -> None:
    """验收3：返回固定作业结果路径，删除上次中断的普通文件，不新建结果文件。"""
    expected = tmp_path / "preview-327.json"
    expected.write_text("old result")
    assert result_file(tmp_path, 327) == expected
    assert not expected.exists()
    assert result_file(tmp_path, 327) == expected


@pytest.mark.parametrize("kind", ["symlink", "directory"])
def test_result_file_rejects_non_regular_entry(tmp_path: Path, kind: str) -> None:
    """验收3：结果路径是符号链接或目录时拒绝，不删除目标或目录。"""
    target = tmp_path / "keep.json"
    target.write_text("keep")
    path = tmp_path / "preview-327.json"
    if kind == "symlink":
        path.symlink_to(target)
    else:
        path.mkdir()
    with pytest.raises(ExternalError):
        result_file(tmp_path, 327)
    assert path.is_symlink() if kind == "symlink" else path.is_dir()
    assert target.read_text() == "keep"


@pytest.mark.parametrize(
    "configuration",
    [None, "", "state_dir = '~/custom-state'\n", "[tools]\ncache_root = '{root}/explicit'\n"],
)
def test_loaded_cache_root_uses_effective_state_directory(
    tmp_path: Path, configuration: str | None
) -> None:
    """配置契约：缺省配置、空配置、改 state_dir 都推导缓存根，显式缓存根优先。"""
    environ: dict[str, str] = {}
    if configuration is not None:
        source = tmp_path / "config.toml"
        source.write_text(configuration.format(root=tmp_path))
        environ["RDP_CONFIG"] = str(source)
    config = load_config(environ=environ, home=tmp_path).config
    expected = (
        tmp_path / "explicit"
        if configuration and "cache_root" in configuration
        else config.state_dir / "tool-cache"
    )
    assert config.tools.cache_root == expected
    assert not expected.exists()


@pytest.mark.parametrize("path", [Path("relative"), Path("/cache/../elsewhere")])
def test_cache_root_rejects_unsafe_path_form(path: Path) -> None:
    """安全底线：缓存根必须是无父级跳转的绝对路径；此测试不访问路径。"""
    with pytest.raises(ValueError):
        ToolsConfig(cache_root=path)
