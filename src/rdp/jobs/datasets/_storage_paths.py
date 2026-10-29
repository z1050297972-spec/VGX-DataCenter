"""存储路径有限解析（领域层，12 L1）：在已核对的根内解析，不跟随越界目标。

pathlib.resolve不能在跨根前停下，故用标准库lstat/readlink逐分量观察；
实际I/O全部由调用方放进M0访问预算。只读观察不能防御平台外并发改链。
"""

import stat
from dataclasses import dataclass
from pathlib import Path

# Linux路径解析的软链接次数上限；循环链按不存在处理，不无限迭代。
MAX_SYMLINKS = 40


@dataclass(frozen=True)
class PathObservation:
    """一次受限路径观察。

    Attributes:
        resolved: 已消去已见软链接的绝对路径，越界时只保留目标文本。
        exists: 存在为True，缺失或循环为False，越过当前根尚未检查为None。
    """

    resolved: Path
    exists: bool | None


def inspect_path(path: Path, root: Path) -> PathObservation:
    """逐分量检查；跨出当前根即停，不stat外部目标。"""
    target = path
    followed = 0
    while target.is_relative_to(root):
        current = root
        parts = target.relative_to(root).parts
        redirected = False
        for index, part in enumerate(parts):
            if part == "..":
                current = current.parent
                if not current.is_relative_to(root):
                    return PathObservation(current / Path(*parts[index + 1 :]), None)
                continue
            current /= part
            try:
                mode = current.lstat().st_mode
            except (FileNotFoundError, NotADirectoryError):
                return PathObservation(target, False)
            if stat.S_ISLNK(mode):
                target = current.parent / current.readlink() / Path(*parts[index + 1 :])
                followed += 1
                if followed > MAX_SYMLINKS:
                    return PathObservation(target, False)
                redirected = True
                break
        if not redirected:
            return PathObservation(current, True)
    return PathObservation(target, None)


def locate_path(path: Path, roots: tuple[Path, ...]) -> Path:
    """只归一进入登记根之前的父目录；根内的..必须留待软链接展开后处理。"""
    current = Path(path.anchor)
    for index, part in enumerate(path.parts[1:], start=1):
        current = current.parent if part == ".." else current / part
        if current in roots:
            return current / Path(*path.parts[index + 1 :])
    return current
