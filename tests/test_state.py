"""工单 03 契约测试清单，骨架阶段逐项跳过；所有文件样例限于 tmp_path。"""

import os
import stat
from dataclasses import FrozenInstanceError
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

import pytest

from rdp.infra.config import PlatformConfig
from rdp.infra.state import initialize_state, state_paths


def test_complete_layout(tmp_path: Path) -> None:
    """验证契约：state_paths 返回：数据库 rdp.sqlite3、logs、中文作业目录、worker.lock 均位于注入状态根，顺序与输入一致。"""
    paths = state_paths(PlatformConfig(state_dir=tmp_path), ["下载", "转换"])
    assert paths.root == tmp_path
    assert paths.database == tmp_path / "rdp.sqlite3"
    assert paths.logs == tmp_path / "logs"
    assert paths.worker_lock == tmp_path / "worker.lock"
    assert paths.job_logs == (("下载", tmp_path / "logs/下载"), ("转换", tmp_path / "logs/转换"))


def test_empty_job_types(tmp_path: Path) -> None:
    """验证契约：state_paths 返回：空作业清单得到空元组，但仍提供数据库、logs、worker 锁路径。"""
    paths = state_paths(PlatformConfig(state_dir=tmp_path), [])
    assert paths.job_logs == ()
    assert paths.database == tmp_path / "rdp.sqlite3"
    assert paths.logs == tmp_path / "logs"
    assert paths.worker_lock == tmp_path / "worker.lock"


def test_immutable_layout(tmp_path: Path) -> None:
    """验证契约：StatePaths 冻结且嵌套 job_logs 为元组；不暴露可变字典，不受原清单修改影响。"""
    names = ["下载"]
    paths = state_paths(PlatformConfig(state_dir=tmp_path), names)
    names.append("转换")
    assert paths.job_logs == (("下载", tmp_path / "logs/下载"),)
    with pytest.raises(FrozenInstanceError):
        cast(Any, paths).logs = tmp_path / "other"


def test_invalid_job_names(tmp_path: Path) -> None:
    """验证契约：state_paths Raises：空名、点、双点、路径分隔符或控制字符抛 ValueError，消息含实际和期望。"""
    for name in ("", ".", "..", "a/b", "a\\b", "a\n", "a\x00", "a\x7f"):
        with pytest.raises(ValueError) as caught:
            state_paths(PlatformConfig(state_dir=tmp_path), [name])
        assert "实际" in str(caught.value) and "期望" in str(caught.value)


def test_duplicate_job_names(tmp_path: Path) -> None:
    """验证契约：state_paths Raises：重复作业名拒绝且不返回部分布局；工单 08 负责提供合法类型清单。"""
    with pytest.raises(ValueError, match="下载"):
        state_paths(PlatformConfig(state_dir=tmp_path), ["下载", "转换", "下载"])
    assert not list(tmp_path.iterdir())


def test_layout_has_no_io(tmp_path: Path) -> None:
    """验证契约：state_paths 副作用：不读取时钟/cwd/文件系统、不创建对象、不修改 config 或 job_types。"""
    config = PlatformConfig(state_dir=tmp_path)
    names = ["下载"]
    with (
        patch.object(Path, "stat", side_effect=AssertionError("不得读状态")),
        patch.object(Path, "cwd", side_effect=AssertionError("不得读 cwd")),
    ):
        paths = state_paths(config, names)
    assert paths.root == tmp_path and names == ["下载"]
    assert not list(tmp_path.iterdir())


def test_initialize_all_directories(tmp_path: Path) -> None:
    """验证契约及 P4：首次创建所有目录为 0700，返回空的宽权限清单，不创建文件。"""
    paths = state_paths(PlatformConfig(state_dir=tmp_path / "parent/state"), ["下载", "转换"])
    assert initialize_state(paths) == ()
    for relative in (
        "parent",
        "parent/state",
        "parent/state/logs",
        "parent/state/logs/下载",
        "parent/state/logs/转换",
    ):
        assert stat.S_IMODE((tmp_path / relative).stat().st_mode) == 0o700
    assert not paths.database.exists() and not paths.worker_lock.exists()


def test_restrictive_umask(tmp_path: Path) -> None:
    """验证契约：initialize_state：用文件系统边界替身模拟严格 umask，只纠正本次创建目录权限，不调用进程 umask。"""
    paths = state_paths(PlatformConfig(state_dir=tmp_path / "state"), [])
    original = Path.mkdir

    def restricted(
        path: Path, mode: int = 0o777, parents: bool = False, exist_ok: bool = False
    ) -> None:
        """在文件系统边界模拟 umask 收紧结果，不修改进程全局值。"""
        original(path, mode=mode, parents=parents, exist_ok=exist_ok)
        path.chmod(0o500)

    with (
        patch.object(Path, "mkdir", restricted),
        patch("os.umask", side_effect=AssertionError("不得改 umask")),
    ):
        initialize_state(paths)
    assert stat.S_IMODE(paths.root.stat().st_mode) == 0o700
    assert stat.S_IMODE(paths.logs.stat().st_mode) == 0o700


def test_existing_permissions_unchanged(tmp_path: Path) -> None:
    """验证验收 2/P4：宽权限目录被列出，权限和时间戳不变，第二次仍只读且清单不可变。"""
    paths = state_paths(PlatformConfig(state_dir=tmp_path / "state"), ["下载"])
    initialize_state(paths)
    paths.root.chmod(0o755)
    paths.logs.chmod(0o750)
    content = paths.logs / "keep.txt"
    content.write_text("已有内容", encoding="utf-8")
    before = {p: p.stat() for p in (paths.root, paths.logs, content)}
    warnings = initialize_state(paths)
    assert [(w.path, w.mode) for w in warnings] == [(paths.root, 0o755), (paths.logs, 0o750)]
    assert {p: p.stat() for p in before} == before
    assert initialize_state(paths) == warnings
    assert content.read_text(encoding="utf-8") == "已有内容"
    with pytest.raises(FrozenInstanceError):
        cast(Any, warnings[0]).mode = 0o700


def test_partial_existing_layout(tmp_path: Path) -> None:
    """验证契约：initialize_state：布局部分存在时仅补缺失目录，保留既有内容，不创建数据库、锁文件或日志文件。"""
    paths = state_paths(PlatformConfig(state_dir=tmp_path / "state"), ["下载"])
    paths.root.mkdir(mode=0o700)
    content = paths.root / "keep"
    content.write_text("不改变", encoding="utf-8")
    assert initialize_state(paths) == ()
    assert paths.job_logs[0][1].is_dir()
    assert content.read_text(encoding="utf-8") == "不改变"
    assert not paths.database.exists() and not paths.worker_lock.exists()


def test_file_blocks_directory(tmp_path: Path) -> None:
    """验证契约：验收 2/NotADirectoryError：root、logs、作业目录或祖先被文件占用时报错并指出冲突路径。"""
    for target in ("state", "state/logs", "state/logs/下载", "ancestor"):
        base = tmp_path / str(len(list(tmp_path.iterdir())))
        base.mkdir()
        root = base / ("ancestor/state" if target == "ancestor" else "state")
        occupied = base / target
        occupied.parent.mkdir(parents=True, exist_ok=True)
        occupied.write_text("保留", encoding="utf-8")
        paths = state_paths(PlatformConfig(state_dir=root), ["下载"])
        with pytest.raises(NotADirectoryError) as caught:
            initialize_state(paths)
        assert str(occupied) in str(caught.value)
        assert occupied.read_text(encoding="utf-8") == "保留"


def test_symlink_directory_rejected(tmp_path: Path) -> None:
    """验证契约：initialize_state Raises：root/logs/作业目录为软链接（含悬空）抛 ValueError，不跟随、不改目标。"""
    for name in ("state", "state/logs", "state/logs/下载"):
        for dangling in (False, True):
            base = tmp_path / str(len(list(tmp_path.iterdir())))
            base.mkdir()
            target = base / "target"
            if not dangling:
                target.mkdir(mode=0o700)
            link = base / name
            link.parent.mkdir(parents=True, exist_ok=True)
            link.symlink_to(target, target_is_directory=True)
            paths = state_paths(PlatformConfig(state_dir=base / "state"), ["下载"])
            with pytest.raises(ValueError, match="软链接"):
                initialize_state(paths)
            assert link.is_symlink()
            assert target.exists() is not dangling


def test_unwritable_directory(tmp_path: Path) -> None:
    """验证契约：initialize_state Raises：目录不可写或不可搜索抛含路径的 PermissionError；用边界替身，不靠执行账号权限。"""
    paths = state_paths(PlatformConfig(state_dir=tmp_path / "state"), [])
    initialize_state(paths)
    original_access = os.access

    def denied(path: str | Path, mode: int) -> bool:
        """仅模拟目标目录权限失败，不依赖执行账号。"""
        return False if Path(path) == paths.logs else original_access(path, mode)

    with patch("os.access", denied), pytest.raises(PermissionError) as caught:
        initialize_state(paths)
    assert str(paths.logs) in str(caught.value)


def test_create_permission_failure(tmp_path: Path) -> None:
    """验证契约：initialize_state Raises：mkdir 或新目录 chmod 权限失败保留 PermissionError 和路径。"""
    for operation in ("mkdir", "chmod"):
        paths = state_paths(PlatformConfig(state_dir=tmp_path / operation), [])
        error = PermissionError(13, "权限失败", str(paths.root))
        with (
            patch.object(Path, operation, side_effect=error),
            pytest.raises(PermissionError) as caught,
        ):
            initialize_state(paths)
        assert caught.value is error


def test_other_filesystem_failure(tmp_path: Path) -> None:
    """验证契约：initialize_state Raises：状态检查失败或磁盘满等 OSError 保留原因，已有对象不变。"""
    paths = state_paths(PlatformConfig(state_dir=tmp_path / "state"), [])
    for operation in ("stat", "mkdir"):
        error = OSError(28, "磁盘满", str(paths.root))
        with patch.object(Path, operation, side_effect=error), pytest.raises(OSError) as caught:
            initialize_state(paths)
        assert caught.value is error
    assert not paths.root.exists()


def test_failure_retains_created_directories(tmp_path: Path) -> None:
    """验证契约：initialize_state 失败副作用：中途失败保留新建空目录，不删除既有对象；修正原因后重试成功。"""
    paths = state_paths(PlatformConfig(state_dir=tmp_path / "state"), ["下载"])
    original = Path.mkdir

    def fail_logs(
        path: Path, mode: int = 0o777, parents: bool = False, exist_ok: bool = False
    ) -> None:
        """在已建 root 后模拟磁盘满，验证保留现场。"""
        if path == paths.logs:
            raise OSError(28, "磁盘满", str(path))
        original(path, mode=mode, parents=parents, exist_ok=exist_ok)

    with patch.object(Path, "mkdir", fail_logs), pytest.raises(OSError):
        initialize_state(paths)
    assert paths.root.is_dir() and not paths.logs.exists()
    assert initialize_state(paths) == ()
    assert paths.job_logs[0][1].is_dir()


def test_existing_layout_checked_without_writes(tmp_path: Path) -> None:
    """验证契约：initialize_state：全部已存在时只检查，不试写探测权限、不 chmod；检查失败也不写入。"""
    paths = state_paths(PlatformConfig(state_dir=tmp_path / "state"), ["下载"])
    initialize_state(paths)
    with (
        patch.object(Path, "mkdir", side_effect=AssertionError("不得创建")),
        patch.object(Path, "chmod", side_effect=AssertionError("不得改权限")),
        patch.object(Path, "open", side_effect=AssertionError("不得试写")),
    ):
        assert initialize_state(paths) == ()


def test_permission_warning_scope_and_order(tmp_path: Path) -> None:
    """验证 P4：只列出已有 root/logs/作业目录，排除祖先和新建目录，按布局顺序。"""
    paths = state_paths(PlatformConfig(state_dir=tmp_path / "state"), ["下载", "转换"])
    initialize_state(paths)
    paths.root.chmod(0o755)
    paths.logs.chmod(0o710)
    paths.job_logs[0][1].chmod(0o701)
    paths.job_logs[1][1].rmdir()
    warnings = initialize_state(paths)
    assert [(w.path, w.mode) for w in warnings] == [
        (paths.root, 0o755),
        (paths.logs, 0o710),
        (paths.job_logs[0][1], 0o701),
    ]
    assert stat.S_IMODE(paths.job_logs[1][1].stat().st_mode) == 0o700
    assert tmp_path not in [w.path for w in warnings]
