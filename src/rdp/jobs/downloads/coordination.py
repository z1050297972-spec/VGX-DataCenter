"""下载与暂存清理共用本地进程锁；锁留在执行进程内直到文件系统操作结束。

使用标准库 flock；即使删除子进程因内核 I/O 卡住，文件锁仍阻止下载并发进入。
"""

import fcntl
import os
import time
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

from rdp.infra.diagnostics import Diagnostic, DiagnosticCategory, DiagnosticLevel, ExternalError
from rdp.jobs._inherited_fds import INHERITED_FDS
from rdp.jobs.execution import ExecutionContext

# 锁存于状态目录，不访问存储根；等待 30 秒足以响应用户取消并避免无界等待。
LOCK_NAME = "download-staging.lock"
LOCK_WAIT_SECONDS = 30.0


def open_lock(state_root: Path) -> int:
    """打开状态目录内固定的锁文件。

    Args:
        state_root: 可信平台状态目录绝对路径。

    Returns:
        带 CLOEXEC 的锁文件描述符，调用方负责关闭。

    Raises:
        OSError: 状态目录或锁文件不可用，包括软链接。

    Side Effects:
        首次创建权限 0600 的锁文件，不访问存储根。

    Time Semantics:
        同步本地状态文件操作，不等待文件锁。
    """
    return os.open(
        state_root / LOCK_NAME, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600
    )


@contextmanager
def download_guard(state_root: Path, context: ExecutionContext) -> Generator[None]:
    """为下载取得与删除互斥的本地锁。

    Args:
        state_root: 可信平台状态目录。
        context: 含取消检查和有界等待的下载上下文。

    Returns:
        无。

    Yields:
        持锁期间交出控制权，不返回数据。

    Raises:
        ExternalError: 锁等待超时。
        OSError: 锁文件不可访问。
        JobCancelledError: 用户取消。
        WorkerStoppingError: worker 停止。

    Side Effects:
        读取或创建状态目录内锁文件，退出释放描述符；不访问存储根。

    Time Semantics:
        非阻塞重试，等待不超过 30 秒；每 0.1 秒响应取消或停止。
    """
    fd = open_lock(state_root)
    deadline = time.monotonic() + LOCK_WAIT_SECONDS
    try:
        while True:
            context.reporter.check_cancelled()
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise ExternalError(
                        (
                            Diagnostic(
                                level=DiagnosticLevel.ERROR,
                                category=DiagnosticCategory.EXTERNAL,
                                stage="下载互斥",
                                source="平台",
                                objects=(),
                                rule="download.staging_lock",
                                actual="等待暂存清理锁超时",
                                expected="暂存目录未被清理",
                                consequence="下载未开始",
                                next_step="检查清理作业后重新提交",
                            ),
                        )
                    ) from None
                context.reporter.wait(0.1)
        # 子进程持有同一打开文件描述符；worker 意外退出后，未回收工具仍阻止删除。
        token = INHERITED_FDS.set((fd,))
        try:
            yield
        finally:
            INHERITED_FDS.reset(token)
    finally:
        os.close(fd)
