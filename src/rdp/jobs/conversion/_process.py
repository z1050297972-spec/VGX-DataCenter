"""转换检查共用的有界子进程；标准库进程组管理保证 ffprobe 后代一同回收。"""

import os
import signal
import subprocess
from contextlib import ExitStack, suppress

from rdp.jobs._inherited_fds import INHERITED_FDS
from rdp.jobs.policy import PROCESS_REAP_TIMEOUT_S

# 四层检查最多300秒，进程回收另外使用框架预算。
CHECK_TIMEOUT_S = 300.0


def run_bounded(command: tuple[str, ...]) -> tuple[bytes, bytes, int]:
    """检查与回收分别限时；不用Popen上下文退出时的无界wait。"""
    process = subprocess.Popen(  # noqa: S603 # 理由：调用方只传固定解释器、模块及已校验参数，不经过shell。
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
        pass_fds=INHERITED_FDS.get(),
    )
    with ExitStack() as streams:
        for stream in (process.stdout, process.stderr):
            if stream is not None:
                streams.enter_context(stream)
        try:
            stdout, stderr = process.communicate(timeout=CHECK_TIMEOUT_S)
        finally:
            # 父检查进程可能还在等待ffprobe；组信号确保超时不会遗留可运行后代。
            with suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=PROCESS_REAP_TIMEOUT_S)
    return stdout, stderr, process.returncode
