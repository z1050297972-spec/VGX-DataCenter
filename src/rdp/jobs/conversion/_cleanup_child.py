"""转换暂存删除子进程；父进程限制执行时间，标准库fd相对删除防止跟随软链接。"""

import os
import shutil
import sys
from contextlib import ExitStack
from pathlib import Path

# 每一层必须是目录且不能是软链接，防止暂存清理触及存储根外的内容。
_DIRECTORY_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC


def _remove(root: Path, identifiers: list[str]) -> None:
    """只沿固定暂存/转换层级打开目录，作业编号不能携带路径分量。"""
    if not root.is_absolute() or not shutil.rmtree.avoids_symlink_attacks:
        raise ValueError("删除边界无效")
    with ExitStack() as stack:
        descriptor = os.open(root, _DIRECTORY_FLAGS)
        stack.callback(os.close, descriptor)
        for part in ("暂存", "转换"):
            try:
                descriptor = os.open(part, _DIRECTORY_FLAGS, dir_fd=descriptor)
            except FileNotFoundError:
                return
            stack.callback(os.close, descriptor)
        for identifier in identifiers:
            if not identifier.isascii() or not identifier.isdecimal() or int(identifier) <= 0:
                raise ValueError("作业编号不是正整数")
            try:
                shutil.rmtree(identifier, dir_fd=descriptor)
            except FileNotFoundError:
                # 已清理或未曾创建目录的失败作业不需要恢复文件。
                continue


if __name__ == "__main__":
    _remove(Path(sys.argv[1]), sys.argv[2:])
