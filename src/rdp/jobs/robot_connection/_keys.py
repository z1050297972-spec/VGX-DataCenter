"""worker 专用密钥初始化；系统 ssh-keygen 生成，标准库临时目录和硬链接避免覆盖。

并发由连接作业类型的单并发与 worker 单实例保证；发布仍用不覆盖的 link，
即使意外竞争也不会替换已有私钥。临时文件在失败和成功时都回收。
"""

import os
import socket
from pathlib import Path
from tempfile import TemporaryDirectory

from rdp.infra.state import STATE_DIRECTORY_MODE, StatePaths
from rdp.jobs.execution import ExecutionContext
from rdp.jobs.robot_connection._process import run
from rdp.jobs.robot_connection.keys import checked_ssh_path

# M5 D9 要求私钥仅属主可读写；生成器本地运行最多十秒，避免异常程序挂住 worker。
_PRIVATE_KEY_MODE = 0o600
_KEYGEN_TIMEOUT_S = 10.0


def ensure_key(paths: StatePaths, keygen: Path, context: ExecutionContext) -> Path:
    """首次需要时生成密钥；已有私钥只收紧权限并复用，永不覆盖。"""
    private = checked_ssh_path(paths, "id_ed25519")
    public = checked_ssh_path(paths, "id_ed25519.pub")
    checked_ssh_path(paths, "known_hosts")
    directory = private.parent
    directory.mkdir(mode=STATE_DIRECTORY_MODE, exist_ok=True)
    directory.chmod(STATE_DIRECTORY_MODE)
    if private.exists():
        private.chmod(_PRIVATE_KEY_MODE)
        return private
    with TemporaryDirectory(prefix=".keygen-", dir=directory) as temp:
        candidate = Path(temp) / "id_ed25519"
        result = run(
            (
                str(keygen),
                "-q",
                "-t",
                "ed25519",
                "-N",
                "",
                "-C",
                f"rdp@{socket.gethostname()}",
                "-f",
                str(candidate),
            ),
            _KEYGEN_TIMEOUT_S,
            context,
        )
        if result.returncode != 0:
            raise OSError("平台密钥生成失败")
        candidate.chmod(_PRIVATE_KEY_MODE)
        os.link(candidate, private)
        os.link(candidate.with_suffix(".pub"), public)
    return private
