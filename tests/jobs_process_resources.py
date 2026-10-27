"""Linux真实工具后代的测试资源归属；临时成为subreaper，使孤儿能由夹具waitpid回收。"""

import ctypes
import os
import signal
import time
from collections.abc import Generator
from contextlib import contextmanager, suppress
from threading import Event

# Linux prctl的固定操作码；测试结束恢复调用前状态，不改变生产worker进程配置。
_PR_SET_CHILD_SUBREAPER = 36
_PR_GET_CHILD_SUBREAPER = 37


@contextmanager
def adopt_orphans() -> Generator[None]:
    """仅测试期间接管本测试工具的孤儿，所有已知PID须在退出本上下文前回收。"""
    libc = ctypes.CDLL(None, use_errno=True)
    previous = ctypes.c_int()
    assert libc.prctl(_PR_GET_CHILD_SUBREAPER, ctypes.byref(previous), 0, 0, 0) == 0
    assert libc.prctl(_PR_SET_CHILD_SUBREAPER, 1, 0, 0, 0) == 0
    try:
        yield
    finally:
        assert libc.prctl(_PR_SET_CHILD_SUBREAPER, previous.value, 0, 0, 0) == 0


def reap_known(pid: int, *, kill: bool = False) -> None:
    """只处理本夹具登记的PID，最多两秒；已经由Popen或其他本夹具路径回收时幂等。"""
    if kill:
        with suppress(ProcessLookupError):
            os.kill(pid, signal.SIGKILL)
    deadline = time.monotonic() + 2
    while True:
        try:
            found, _ = os.waitpid(pid, os.WNOHANG)
        except ChildProcessError:
            return
        if found == pid:
            return
        assert time.monotonic() < deadline, "测试后代进程未回收"
        Event().wait(0.005)


class BlockedTool:
    """Popen外部边界的不可回收替身；真实管道让输出线程阻塞，只有测试finally释放写端。"""

    def __init__(self, blocked_wait: bool) -> None:
        """建立两条真实管道和可选择的wait故障，不启动操作系统子进程。"""
        import subprocess
        from typing import BinaryIO, cast

        self.timeout_error = subprocess.TimeoutExpired
        self.blocked_wait = blocked_wait
        self.pid = 123456789
        self.returncode: int | None = None if blocked_wait else 0
        self.sent: list[int] = []
        self.writers: list[int] = []
        self.reads: list[BinaryIO] = []
        for _ in range(2):
            read, write = os.pipe()
            self.reads.append(cast(BinaryIO, os.fdopen(read, "rb", buffering=0)))
            self.writers.append(write)
        self.stdout, self.stderr = self.reads

    def launch(self, *_args: object, **options: object) -> "BlockedTool":
        """核对生产启动选项，再提供受控外部进程对象。"""
        assert options["close_fds"] is True and options["start_new_session"] is True
        return self

    def send(self, _pid: int, number: int) -> None:
        """只记录发给测试进程组的信号，不操作系统中任何实际PID。"""
        self.sent.append(number)

    def poll(self) -> int | None:
        """区分仍运行与真实零退出，不将未知值伪造成零。"""
        return self.returncode

    def wait(self, timeout: float) -> int:
        """按场景模拟回收超时或已经结束，不执行阻塞等待。"""
        if self.blocked_wait:
            raise self.timeout_error("测试工具", timeout)
        return 0

    def release(self) -> None:
        """关闭写端使阻塞读取到达EOF，重复调用幂等。"""
        while self.writers:
            os.close(self.writers.pop())

    def close(self) -> None:
        """最终关闭本夹具所有描述符，调用方先回收读线程。"""
        self.release()
        for stream in self.reads:
            stream.close()
