"""状态库私有文件权限；只处理数据库、SQLite旁文件和平台完整备份，不跟随软链接。"""

import os
import re
import stat
from pathlib import Path

from rdp.infra.db._constants import BACKUP_FILENAME_PATTERN, BACKUPS_DIRECTORY_NAME

# 工单13要求账号哈希、会话和报错库只允许进程所属用户读写。
_DATABASE_FILE_MODE = 0o600


def secure_file(path: Path, *, create: bool = False) -> None:
    """不跟随软链接地创建或收紧普通文件，避免额外关闭已有数据库inode的描述符。"""
    if create:
        try:
            descriptor = os.open(
                path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, _DATABASE_FILE_MODE
            )
        except FileExistsError:
            pass
        else:
            os.close(descriptor)
    try:
        info = path.stat(follow_symlinks=False)
    except FileNotFoundError:
        if create:
            raise
        return
    if not stat.S_ISREG(info.st_mode):
        raise OSError("数据库关联文件必须是普通文件")
    # SQLite的POSIX锁属于进程；额外open/close同inode会释放本进程其他连接的锁。
    # 已有文件只做不跟随链接的chmod，且权限已经正确时不重复改元数据。
    if stat.S_IMODE(info.st_mode) != _DATABASE_FILE_MODE:
        path.chmod(_DATABASE_FILE_MODE, follow_symlinks=False)


def secure_database_files(database: Path) -> None:
    """启动和迁移前收紧已有文件；仅匹配平台生成的完整备份文件名。"""
    for suffix in ("", "-wal", "-shm"):
        secure_file(database.with_name(database.name + suffix))
    directory = database.parent / BACKUPS_DIRECTORY_NAME
    if directory.is_symlink():
        raise OSError("备份目录不能是软链接")
    if directory.is_dir():
        with os.scandir(directory) as entries:
            for entry in entries:
                if entry.is_file(follow_symlinks=False) and re.fullmatch(
                    BACKUP_FILENAME_PATTERN, entry.name
                ):
                    secure_file(directory / entry.name)
