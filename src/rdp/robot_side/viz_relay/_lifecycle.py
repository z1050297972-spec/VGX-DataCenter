"""机器人进程的信号边界（M5-03），只管有界退出，不启动 ROS 或网络。

标准库 Timer 仅作退出期限保护；正常路径取消并回收它，不增加消息处理线程。
SDK 的 stop 没有超时参数，若底层清理卡住，期限到达让操作系统回收进程资源，
避免第 09 张一直等不到退出；不能把阻塞的 SDK 清理留成存活的后台线程。
"""

import os
import signal
from collections.abc import Generator
from contextlib import contextmanager
from threading import Event, Timer
from types import FrameType

# 工单要求信号后 3 秒退出，预留 0.5 秒给调度与解释器结束。
SHUTDOWN_TIMEOUT_S = 2.5
# 正常退出取消保护定时器后，它只需退出 Event.wait，不等待业务任务。
TIMER_JOIN_TIMEOUT_S = 0.1


def _expired() -> None:
    """底层清理超时后退出整个进程，OS 回收线程和监听端口。"""
    # 不在最后期限再写日志：stdout 本身可能是卡住的管道。
    os._exit(0)


@contextmanager
def shutdown_signals() -> Generator[Event, None, None]:
    """在主线程安装停止信号，调用方退出上下文前完成业务资源回收。"""
    stopped = Event()
    watchdog = Timer(SHUTDOWN_TIMEOUT_S, _expired)
    watchdog.daemon = True
    watchdog.name = "viz-relay-shutdown"

    def request_stop(_signum: int, _frame: FrameType | None) -> None:
        if not stopped.is_set():
            stopped.set()
            watchdog.start()

    previous = {sig: signal.getsignal(sig) for sig in (signal.SIGTERM, signal.SIGINT)}
    try:
        for sig in previous:
            signal.signal(sig, request_stop)
        yield stopped
    finally:
        watchdog.cancel()
        if watchdog.ident is not None:
            watchdog.join(TIMER_JOIN_TIMEOUT_S)
        for sig, handler in previous.items():
            signal.signal(sig, handler)
