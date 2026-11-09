"""敏感命令的有界子进程边界，仅供连接检查使用。

复用标准库 Popen/selector；现有作业进程边界会原样落日志，不能用于可能携带
认证信息的 SSH 输出。这里仅在内存保留有界输出供分类，日志只由调用方写安全结论。
无需读线程，取消、期限、后代持管道都由同一循环管理。
"""

import os
import selectors
import signal
import subprocess
from contextlib import suppress
from dataclasses import dataclass

from rdp.jobs.execution import ExecutionContext
from rdp.jobs.policy import (
    PROCESS_POLL_INTERVAL_S,
    PROCESS_REAP_TIMEOUT_S,
    PROCESS_STDERR_TAIL_MAX_BYTES,
)


@dataclass(frozen=True)
class Result:
    """子进程的瞬时结果，原始输出不得持久化。

    Attributes:
        returncode: 操作系统退出码，负值为信号。
        stderr: 最后至多 PROCESS_STDERR_TAIL_MAX_BYTES 字节；仅用于识别已知错误。
    """

    returncode: int
    stderr: bytes


def run(argv: tuple[str, ...], timeout_s: float, context: ExecutionContext) -> Result:
    """运行可信参数并有界回收进程组；输出不进入日志或异常文本。"""
    context.reporter.check_cancelled()
    deadline = context.clock.monotonic() + timeout_s
    # 绝对可执行路径由 worker 装配；参数独立传递，永不经过 shell。
    process = subprocess.Popen(  # noqa: S603  # 理由：可信程序与参数元组，禁止 shell。
        argv,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
        close_fds=True,
        env=dict(os.environ, LC_ALL="C"),
    )
    tail = b""
    try:
        with selectors.DefaultSelector() as selector:
            for stream in (process.stdout, process.stderr):
                if stream is not None:
                    os.set_blocking(stream.fileno(), False)
                    selector.register(stream, selectors.EVENT_READ)
            while selector.get_map() or process.poll() is None:
                context.reporter.check_cancelled()
                context.reporter.flush_due()
                remaining = deadline - context.clock.monotonic()
                if remaining <= 0:
                    raise TimeoutError("连接检查子进程超过期限")
                for key, _ in selector.select(min(remaining, PROCESS_POLL_INTERVAL_S)):
                    data = os.read(key.fd, PROCESS_STDERR_TAIL_MAX_BYTES)
                    if not data:
                        selector.unregister(key.fileobj)
                    elif key.fileobj is process.stderr:
                        tail = (tail + data)[-PROCESS_STDERR_TAIL_MAX_BYTES:]
            return Result(process.wait(timeout=PROCESS_REAP_TIMEOUT_S), tail)
    finally:
        # 即使直接子进程已退出，也清理仍持有管道的后代；检查没有需要保留的远程工作。
        try:
            with suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=PROCESS_REAP_TIMEOUT_S)
        finally:
            for stream in (process.stdout, process.stderr):
                if stream is not None:
                    stream.close()
