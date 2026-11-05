"""链接目标大小遍历（领域层，M1-02），只读元数据，不打开普通数据文件。

标准库lstat/scandir即可统计表观字节；目录复用O_NOATIME打开，避免真实扫描发现的atime写入。
内部软链接不跟随；LeRobot 仅计普通数据文件，其他格式计软链接自身长度。
数据块边界用标准库字典精确查找，递归携带当前块，不逐文件扫描全部前缀。
隐藏目录和块外文件仍巡检下载残留，但不计入 LeRobot 或已登记块的大小。
"""

import os
import sqlite3
import stat
from collections.abc import Callable, Iterator
from contextlib import closing
from pathlib import Path

from rdp.infra.diagnostics import DIAGNOSTIC_SAMPLE_LIMIT
from rdp.jobs.datasets._readonly import scan_directory
from rdp.jobs.datasets._sizing_types import SizeSource, SizeValue

# 限制同时打开的目录描述符及Python调用深度，不限制目录内文件数量。
MAX_DIRECTORY_DEPTH = 256
# 临时inode表的页缓存上限，单位KiB；大规模硬链接去重不占用无界Python集合。
INODE_CACHE_KIB = 2048


def walk(path: Path, checkpoint: Callable[[], None], sources: tuple[SizeSource, ...]) -> SizeValue:
    """流式累计各块的有效字节和全量下载残留；没有数据块才回退为统计整个目标。"""
    size_bytes = aria2 = incomplete = 0
    samples: list[Path] = []
    formats = {path / source.relative_path: source.format for source in sources}
    # None 表示尚未进入任何块；(path, None) 表示已覆盖但格式未知，两者不能混同。
    scope = None if sources else (path, None)
    # 硬链接去重与du一致；SQLite临时数据库自动删除，2MiB页缓存避免百万inode驻留内存。
    with closing(sqlite3.connect("")) as seen:
        seen.execute(f"PRAGMA cache_size=-{INODE_CACHE_KIB}")
        seen.execute(
            "CREATE TABLE inodes (device TEXT, inode TEXT, PRIMARY KEY(device, inode)) WITHOUT ROWID"
        )
        for current, info, counted in _entries(path, checkpoint, 0, formats, scope):
            duplicate = False
            if counted and info.st_nlink > 1:
                duplicate = (
                    seen.execute(
                        "INSERT OR IGNORE INTO inodes VALUES (?, ?)",
                        (str(info.st_dev), str(info.st_ino)),
                    ).rowcount
                    == 0
                )
            # M1-02评审第1轮：目录只负责遍历，排除其st_size以对齐真实数据核对口径。
            if counted and not duplicate:
                size_bytes += info.st_size
            if stat.S_ISREG(info.st_mode):
                aria2 += current.name.endswith(".aria2")
                incomplete += current.name.endswith(".incomplete")
                if (
                    current.name.endswith((".aria2", ".incomplete"))
                    and len(samples) < DIAGNOSTIC_SAMPLE_LIMIT
                ):
                    samples.append(current)
    return SizeValue(size_bytes, aria2, incomplete, tuple(samples))


def _entries(
    path: Path,
    checkpoint: Callable[[], None],
    depth: int,
    formats: dict[Path, str | None],
    scope: tuple[Path, str | None] | None,
) -> Iterator[tuple[Path, os.stat_result, bool]]:
    """进入块时覆盖继承状态，以最深块为准；返回父目录后不影响兄弟块。"""
    checkpoint()
    info = path.lstat()
    checkpoint()
    # 单文件数据块也可能是边界；每个路径只做一次字典查找，不做全量前缀匹配。
    if path in formats:
        scope = (path, formats[path])
    counted = scope is not None and _counted(path.relative_to(scope[0]), info, scope[1])
    yield path, info, counted
    if not stat.S_ISDIR(info.st_mode):
        return
    if depth >= MAX_DIRECTORY_DEPTH:
        raise OSError("目录深度超过统计上限")
    with scan_directory(path) as entries:
        checkpoint()
        for entry in entries:
            yield from _entries(path / entry.name, checkpoint, depth + 1, formats, scope)


def _counted(relative: Path, info: os.stat_result, data_format: str | None) -> bool:
    """仅对有效文件去重，防止被排除的硬链接先出现时吞掉有效副本。"""
    if data_format != "lerobot":
        return stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode)
    directories = relative.parts[:-1]
    if not stat.S_ISREG(info.st_mode) or any(part.startswith(".") for part in directories):
        return False
    return (
        "meta" in directories
        or "data" in directories
        and relative.suffix == ".parquet"
        or "videos" in directories
        and relative.suffix == ".mp4"
    )
