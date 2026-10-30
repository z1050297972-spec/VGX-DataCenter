"""存储根的只读打开（领域层，M1-02真实扫描回归），不处理业务路径与挂载身份。

2026-10-29真实扫描发现rw,relatime会因读取更新atime并产生扇区写入；
因此文件和目录都请求O_NOATIME。无属主权限时允许EPERM回退，挂载层的ro/noatime仍由运维控制。
"""

import errno
import os
from collections.abc import Generator, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import BinaryIO


def open_fd(
    path: Path, *, directory: bool = False, dir_fd: int | None = None, nonblocking: bool = False
) -> int:
    """只读且不跟随末级软链接；查看器可用dir_fd逐分量打开，并用nonblocking避免FIFO阻塞。"""
    flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW
    if nonblocking:
        flags |= os.O_NONBLOCK
    if directory:
        flags |= os.O_DIRECTORY
    try:
        return os.open(path, flags | os.O_NOATIME, dir_fd=dir_fd)
    except OSError as error:
        if error.errno != errno.EPERM:
            raise
        return os.open(path, flags, dir_fd=dir_fd)


@contextmanager
def open_file(path: Path) -> Generator[BinaryIO]:
    """将已打开描述符交给标准库文件对象，退出时关闭，不改数据内容。"""
    with os.fdopen(open_fd(path), "rb") as stream:
        yield stream


@contextmanager
def scan_directory(path: Path) -> Generator[Iterator[os.DirEntry[str]]]:
    """用带O_NOATIME的目录描述符枚举，条目路径需由调用方用父路径和name组合。"""
    descriptor = open_fd(path, directory=True)
    try:
        with os.scandir(descriptor) as stream:
            yield stream
    finally:
        os.close(descriptor)
