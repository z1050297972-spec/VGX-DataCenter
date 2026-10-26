"""主循环测试的有界线程启动与查询；异常显式交测试断言，finally始终停止并join。"""

import time
from collections.abc import Callable, Generator
from contextlib import contextmanager
from threading import Event, Thread

from jobs_storage_support import NOW

from rdp.jobs.execution import ExecutorDependencies
from rdp.jobs.types import WorkerHeartbeat
from rdp.jobs.worker import WorkerLoopResult, run_loop


@contextmanager
def running_loop(
    dependencies: ExecutorDependencies,
) -> Generator[tuple[Event, Thread, list[WorkerLoopResult]]]:
    """测试线程仅承载主循环，后台异常不能变成pytest未处理线程警告。"""
    stop = Event()
    results: list[WorkerLoopResult] = []
    failures: list[BaseException] = []

    def run() -> None:
        try:
            results.append(
                run_loop(
                    dependencies,
                    stop,
                    WorkerHeartbeat("00000000000040008000000000000001", 123, NOW, NOW),
                )
            )
        except BaseException as error:
            failures.append(error)

    thread = Thread(target=run, daemon=True)
    try:
        thread.start()
        yield stop, thread, results
    finally:
        stop.set()
        thread.join(timeout=3)
        assert not thread.is_alive() and not failures, failures


def wait_for(predicate: Callable[[], bool], *, timeout_s: float = 2.0) -> None:
    """等待可观测状态而非猜测固定sleep；每次最多等待5毫秒，总时长有上限。"""
    deadline = time.monotonic() + timeout_s
    while not predicate():
        assert time.monotonic() < deadline, "等待可观测握手超时"
        Event().wait(0.005)
