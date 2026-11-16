"""Alpha 输入元信息快照（领域层，08 票）；只 stat 选定任务，不读数据内容。

标准库目录描述符提供 NOFOLLOW 边界；平台自行记录路径集合，是因为目录 mtime
不能表示子文件内容变化。G2 单归档的 size/mtime 身份不使用此模块。
"""

import os
import stat
import time
from collections.abc import Callable, Generator
from contextlib import contextmanager
from pathlib import Path

from rdp.jobs.cleaning.models import InputFileSnapshot

# 单次任务快照至多 25 万项、30 秒；深度图按文件计数，超限明确要求缩小输入。
MAX_SNAPSHOT_ENTRIES = 250_000
SNAPSHOT_TIMEOUT_S = 30.0
_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
# 宿主侧 scandir 也会触发 relatime；所有被枚举的目录必须独立以 NOATIME 打开。
_ENUMERATE_FLAGS = _FLAGS | os.O_NOATIME


class SnapshotBudget:
    """一次预览前/后快照共用的遍历预算，不读取其他任务的观测或本体感知。"""

    def __init__(self, checkpoint: Callable[[], None]) -> None:
        """记录单调时间截止点与取消入口。"""
        self.deadline = time.monotonic() + SNAPSHOT_TIMEOUT_S
        self.remaining = MAX_SNAPSHOT_ENTRIES
        self.checkpoint = checkpoint

    def tick(self) -> None:
        """每个目录项都计费，不能靠大量无关文件绕过上界。"""
        self.checkpoint()
        self.remaining -= 1
        if self.remaining < 0 or time.monotonic() >= self.deadline:
            raise ValueError("Alpha 输入元信息快照超出 25 万项或 30 秒预算")


@contextmanager
def _directory(path: Path, *, enumerate_entries: bool = False) -> Generator[int]:
    """逐层拒绝链接；祖先只遍历，实际枚举目录用 NOATIME 重新打开且禁止权限降级。"""
    if not path.is_absolute() or ".." in path.parts:
        raise ValueError("快照路径必须为不含 .. 的绝对路径")
    descriptor = os.open("/", _FLAGS)
    try:
        for part in path.parts[1:]:
            child = os.open(part, _FLAGS, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        if enumerate_entries:
            child = _open_enumeration(".", descriptor)
            os.close(descriptor)
            descriptor = child
        yield descriptor
    finally:
        os.close(descriptor)


def _open_enumeration(name: str, parent: int) -> int:
    """枚举需要文件所有权或 CAP_FOWNER；失败明确报告，不静默更新数据目录 atime。"""
    try:
        return os.open(name, _ENUMERATE_FLAGS, dir_fd=parent)
    except PermissionError as error:
        raise PermissionError("Alpha 目录枚举需要 O_NOATIME 权限，禁止降级为普通读取") from error


def _file(path: Path, budget: SnapshotBudget) -> InputFileSnapshot:
    """缺失候选也保留身份，后续新增解压 h5 或标注不能绕过旧快照。"""
    budget.tick()
    try:
        with _directory(path.parent) as parent:
            info = os.stat(path.name, dir_fd=parent, follow_symlinks=False)
    except FileNotFoundError:
        return InputFileSnapshot(path=str(path), size_bytes=None, mtime_ns=None)
    if not stat.S_ISREG(info.st_mode):
        raise ValueError(f"输入不是普通文件，不能建立快照：{path}")
    return InputFileSnapshot(path=str(path), size_bytes=info.st_size, mtime_ns=info.st_mtime_ns)


def _walk(
    parent: int, path: Path, budget: SnapshotBudget, depth: int = 0
) -> list[InputFileSnapshot]:
    """仅遍历所选集；对目录和文件均拒绝链接，深度上限防止递归耗尽。"""
    if depth > 16:
        raise ValueError("Alpha 集目录层数超过 16")
    result: list[InputFileSnapshot] = []
    with os.scandir(parent) as entries:
        for entry in entries:
            budget.tick()
            info = entry.stat(follow_symlinks=False)
            child_path = path / entry.name
            if stat.S_ISDIR(info.st_mode):
                child = _open_enumeration(entry.name, parent)
                try:
                    result.extend(_walk(child, child_path, budget, depth + 1))
                finally:
                    os.close(child)
            elif stat.S_ISREG(info.st_mode):
                result.append(
                    InputFileSnapshot(
                        path=str(child_path), size_bytes=info.st_size, mtime_ns=info.st_mtime_ns
                    )
                )
            else:
                raise ValueError(f"Alpha 输入不能包含链接或特殊文件：{child_path}")
    return result


def episode_snapshot(path: Path, budget: SnapshotBudget) -> tuple[InputFileSnapshot, ...]:
    """记录标注、该集 h5 或共用 tar，以及该集实际视频和深度路径集合。"""
    task = path.parent
    if task.parent.name != "observations" or not task.name.isascii() or not task.name.isdecimal():
        raise ValueError("Alpha 输入不是任务观测目录下的集")
    root = task.parent.parent
    with _directory(path, enumerate_entries=True) as directory:
        result = _walk(directory, path, budget)
    result.append(_file(root / f"task_info/task_{task.name}.json", budget))
    h5 = _file(root / "proprio_stats" / task.name / path.name / "proprio_stats.h5", budget)
    result.append(h5)
    if h5.size_bytes is None:
        # 工具可在共用 tar 中按偏移读取该集；只列举顶层 tar，不下钻其他任务。
        shared = root / "proprio_stats"
        try:
            with (
                _directory(shared, enumerate_entries=True) as directory,
                os.scandir(directory) as entries,
            ):
                for entry in entries:
                    budget.tick()
                    if entry.name.endswith(".tar"):
                        result.append(_file(shared / entry.name, budget))
        except FileNotFoundError:
            pass
    return tuple(sorted(result, key=lambda item: item.path))


def task_snapshot(
    task: Path, checkpoint: Callable[[], None]
) -> dict[str, tuple[InputFileSnapshot, ...]]:
    """预览前后分别记录所选任务全部数字集；结果报告必须逐集对应这个集合。"""
    budget = SnapshotBudget(checkpoint)
    result: dict[str, tuple[InputFileSnapshot, ...]] = {}
    with _directory(task, enumerate_entries=True) as directory, os.scandir(directory) as entries:
        for entry in entries:
            budget.tick()
            if entry.name.isascii() and entry.name.isdecimal():
                path = task / entry.name
                result[str(path)] = episode_snapshot(path, budget)
    return result
