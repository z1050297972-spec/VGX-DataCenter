"""链接目标大小遍历（领域层，M1-02），只读元数据，不打开普通数据文件。

标准库lstat/scandir即可统计表观字节；目录复用O_NOATIME打开，避免真实扫描发现的atime写入。
内部软链接只计算自身长度，不跟随到未登记路径或形成递归环。
"""

import os
import sqlite3
import stat
from collections.abc import Callable, Iterator
from contextlib import closing
from pathlib import Path

from rdp.infra.diagnostics import DIAGNOSTIC_SAMPLE_LIMIT
from rdp.jobs.datasets._readonly import scan_directory
from rdp.jobs.datasets._sizing_types import SizeValue

# 限制同时打开的目录描述符及Python调用深度，不限制目录内文件数量。
MAX_DIRECTORY_DEPTH = 256
# 临时inode表的页缓存上限，单位KiB；大规模硬链接去重不占用无界Python集合。
INODE_CACHE_KIB = 2048


def walk(path: Path, checkpoint: Callable[[], None]) -> SizeValue:
    """流式累计单目标，只计普通文件和软链接自身st_size，目录与特殊设备不计大小。"""
    size_bytes = aria2 = incomplete = 0
    samples: list[Path] = []
    # 硬链接去重与du一致；SQLite临时数据库自动删除，2MiB页缓存避免百万inode驻留内存。
    with closing(sqlite3.connect("")) as seen:
        seen.execute(f"PRAGMA cache_size=-{INODE_CACHE_KIB}")
        seen.execute(
            "CREATE TABLE inodes (device TEXT, inode TEXT, PRIMARY KEY(device, inode)) WITHOUT ROWID"
        )
        for current, info in _entries(path, checkpoint, 0):
            duplicate = False
            if (stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode)) and info.st_nlink > 1:
                duplicate = (
                    seen.execute(
                        "INSERT OR IGNORE INTO inodes VALUES (?, ?)",
                        (str(info.st_dev), str(info.st_ino)),
                    ).rowcount
                    == 0
                )
            # M1-02评审第1轮：目录只负责遍历，排除其st_size以对齐真实数据核对口径。
            if not duplicate and (stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode)):
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
    path: Path, checkpoint: Callable[[], None], depth: int
) -> Iterator[tuple[Path, os.stat_result]]:
    """深度优先只保留祖先目录，随树宽度增长不积累路径列表。"""
    checkpoint()
    info = path.lstat()
    checkpoint()
    yield path, info
    if not stat.S_ISDIR(info.st_mode):
        return
    if depth >= MAX_DIRECTORY_DEPTH:
        raise OSError("目录深度超过统计上限")
    with scan_directory(path) as entries:
        checkpoint()
        for entry in entries:
            yield from _entries(path / entry.name, checkpoint, depth + 1)
