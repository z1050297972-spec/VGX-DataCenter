"""导航文件描述符边界；逐分量O_NOFOLLOW打开，只读普通文件，不跟随数据链接。"""

import os
import stat
from collections.abc import Callable, Generator
from contextlib import contextmanager
from pathlib import Path

from rdp.jobs.datasets import catalog
from rdp.jobs.datasets._issues import input_error

# 每64KiB调用一次控制检查点，避免大JSON让取消/停止长期得不到检查。
READ_CHUNK_BYTES = 64 * 1024


@contextmanager
def directory(path: Path) -> Generator[int]:
    """从根描述符逐段打开目录，消除路径检查与实际打开之间的链接替换窗口。"""
    if not path.is_absolute() or ".." in path.parts or "\x00" in str(path):
        raise input_error(str(path), "需要无穿越的绝对目录")
    descriptor = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in path.parts[1:]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        yield descriptor
    finally:
        os.close(descriptor)


def names(descriptor: int) -> tuple[str, ...]:
    """有界枚举直接目录项，不对任何子项做跟随链接的检查。"""
    result: list[str] = []
    with os.scandir(descriptor) as entries:
        for entry in entries:
            if len(result) >= catalog.MAX_ENTRY_MEMBERS:
                raise input_error("导航目录", "目录项超过预算")
            result.append(entry.name)
    return tuple(sorted(result))


def read_file(descriptor: int, name: str, checkpoint: Callable[[], None]) -> bytes:
    """只打开单层普通文件；非阻塞打开避免FIFO挂起，再按上限读取原字节。"""
    if "/" in name or name in {".", ".."} or "\x00" in name:
        raise input_error("导航文件", "文件名越界")
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=descriptor)
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode):
            raise OSError("不是普通文件")
        if before.st_size > catalog.MAX_DOCUMENT_BYTES:
            raise input_error(name, "文件字节数超过预算")
        content = bytearray()
        while True:
            checkpoint()
            block = os.read(
                fd, min(READ_CHUNK_BYTES, catalog.MAX_DOCUMENT_BYTES + 1 - len(content))
            )
            if not block:
                break
            content.extend(block)
            if len(content) > catalog.MAX_DOCUMENT_BYTES:
                raise input_error(name, "文件字节数超过预算")
        after = os.fstat(fd)
        if (before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        ):
            raise OSError("读取期间文件发生变化")
        return bytes(content)
    finally:
        os.close(fd)
