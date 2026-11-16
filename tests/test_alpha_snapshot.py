"""Alpha 快照边界：仅元信息、选定任务、有限遍历，不依赖观测目录 mtime。"""

import os
from pathlib import Path

import pytest

from rdp.jobs.cleaning._alpha_snapshot import SnapshotBudget, episode_snapshot, task_snapshot


def test_snapshot_does_not_scan_unrelated_tasks(tmp_path: Path) -> None:
    """其他任务即使含不允许的链接也不能阻止所选任务；结果包含实际文件和缺失候选。"""
    task = tmp_path / "observations/42"
    episode = task / "1"
    episode.mkdir(parents=True)
    video = episode / "head.mp4"
    video.write_bytes(b"temporary video identity only")
    (tmp_path / "observations/43").symlink_to(tmp_path / "outside")
    result = task_snapshot(task, lambda: None)
    assert set(result) == {str(episode)}
    snapshot = {item.path: item for item in result[str(episode)]}
    assert snapshot[str(video)].size_bytes == video.stat().st_size
    assert snapshot[str(tmp_path / "task_info/task_42.json")].size_bytes is None
    assert str(tmp_path / "proprio_stats/42/1/proprio_stats.h5") in snapshot


def test_snapshot_enforces_entry_budget(tmp_path: Path) -> None:
    """预算耗尽时明确失败，不接受截断的文件集合以供未来转换复用。"""
    episode = tmp_path / "observations/42/1"
    episode.mkdir(parents=True)
    (episode / "depth.png").touch()
    budget = SnapshotBudget(lambda: None)
    budget.remaining = 0
    with pytest.raises(ValueError, match="超出"):
        episode_snapshot(episode, budget)


def test_snapshot_rejects_linked_proprioception_parent(tmp_path: Path) -> None:
    """共用观测外的 h5 路径也逐层拒绝链接，不通过本体感知目录访问越界文件。"""
    episode = tmp_path / "observations/42/1"
    episode.mkdir(parents=True)
    (tmp_path / "outside").mkdir()
    (tmp_path / "proprio_stats").symlink_to(tmp_path / "outside", target_is_directory=True)
    with pytest.raises(OSError):
        episode_snapshot(episode, SnapshotBudget(lambda: None))


@pytest.mark.parametrize("denied", [False, True])
def test_enumeration_requires_noatime_without_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, denied: bool
) -> None:
    """任务、集、嵌套深度及共用 tar 目录枚举都须 NOATIME；权限不足不得退回普通枚举。"""
    task = tmp_path / "observations/42"
    episode = task / "1"
    depth = episode / "depth"
    shared = tmp_path / "proprio_stats"
    depth.mkdir(parents=True)
    shared.mkdir()
    (depth / "0001.png").touch()
    (shared / "shared.tar").touch()
    opened_flags: dict[int, int] = {}
    enumerated: set[int] = set()
    original_open, original_scandir = os.open, os.scandir

    def tracked_open(
        path: str | os.PathLike[str], flags: int, mode: int = 0o777, *, dir_fd: int | None = None
    ) -> int:
        if denied and flags & os.O_NOATIME:
            raise PermissionError("模拟 NOATIME 权限不足")
        descriptor = original_open(path, flags, mode, dir_fd=dir_fd)
        opened_flags[descriptor] = flags
        return descriptor

    def checked_scandir(descriptor: int):
        assert opened_flags[descriptor] & os.O_NOATIME, "枚举目录没有 O_NOATIME"
        enumerated.add(os.fstat(descriptor).st_ino)
        return original_scandir(descriptor)

    with monkeypatch.context() as patch:
        patch.setattr(os, "open", tracked_open)
        patch.setattr(os, "scandir", checked_scandir)
        if denied:
            with pytest.raises(PermissionError, match="NOATIME"):
                task_snapshot(task, lambda: None)
            assert not enumerated
        else:
            task_snapshot(task, lambda: None)
            assert enumerated == {path.stat().st_ino for path in (task, episode, depth, shared)}
