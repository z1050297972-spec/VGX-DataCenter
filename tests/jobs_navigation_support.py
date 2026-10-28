"""导航写锁测试的真实上报和有界线程夹具；持锁与竞争线程使用不同作业身份。"""

import time
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from threading import Event, Thread
from typing import Self, TextIO

from jobs_progress_support import reporter_context
from jobs_storage_support import NOW

from rdp.jobs.execution import ExecutionWork, ExecutorDependencies
from rdp.jobs.navigation import NavigationWriter
from rdp.jobs.progress import ExecutionSignals
from rdp.jobs.types import JobClock, JobRecord


@contextmanager
def held_writer(root: Path) -> Generator[tuple[NavigationWriter, Event, Thread]]:
    """让作业72在另一线程持锁，退出时无条件放行并在两秒内回收。"""
    entered, release = Event(), Event()
    errors: list[BaseException] = []
    writer = NavigationWriter()
    with reporter_context(root, JobClock(lambda: NOW, time.monotonic), job_id=72) as (
        reporter,
        _engine,
        _signals,
        _path,
    ):

        def write() -> None:
            entered.set()
            assert release.wait(2), "测试持锁超过两秒"

        def run() -> None:
            try:
                writer.run(reporter, lambda: None, write)
            except BaseException as error:
                errors.append(error)

        thread = Thread(target=run, daemon=True)
        try:
            thread.start()
            assert entered.wait(1)
            yield writer, release, thread
        finally:
            release.set()
            thread.join(timeout=2)
            assert not thread.is_alive()
        assert errors == []


@contextmanager
def navigation_jobs(root: Path) -> Generator[ExecutorDependencies]:
    """提供两个并发名额的真实写锁示例类型，所有作业共享同一临时库及NavigationWriter。"""
    from dataclasses import replace

    from jobs_scheduling_support import resources_fixture
    from jobs_storage_support import job_database

    from rdp.jobs.registry import JobRegistry, production_registry

    definition = production_registry().lookup("example_navigation")
    assert definition is not None
    registry = JobRegistry()
    registry.register(replace(definition, concurrency=2))
    with job_database(root) as (engine, paths):
        dependencies = ExecutorDependencies(
            engine,
            registry,
            paths,
            JobClock(lambda: NOW, time.monotonic),
            resources=resources_fixture(registry),
            storage=None,
        )
        try:
            yield dependencies
        finally:
            assert dependencies.resources is not None
            for claim in dependencies.resources.pool.claims():
                dependencies.resources.pool.release(claim)


def navigation_work(
    dependencies: ExecutorDependencies, number: int, expected: str
) -> tuple[ExecutionWork, ExecutionSignals]:
    """创建排队行并经真实领取取得日志路径及资源凭据，预览值由测试独立给定。"""
    from threading import Lock

    from jobs_scheduling_support import claim_fixture
    from jobs_storage_support import job_row

    from rdp.infra.db.connection import session_scope
    from rdp.jobs.progress import ExecutionMonitor
    from rdp.jobs.records import claim_job
    from rdp.jobs.types import ExecutionMode, JobState

    with session_scope(dependencies.engine) as session:
        row = job_row(JobState.QUEUED, job_id=number)
        row.type_name = "example_navigation"
        row.display_name = "示例：写锁"
        row.parameters = {"expected_value": expected, "pause_s": 0}
        session.add(row)
    with session_scope(dependencies.engine) as session:
        record = claim_job(session, number, now=NOW, paths=dependencies.paths, gpu_index=None)
    return (
        ExecutionWork(record, ExecutionMode.FRESH, None, claim=claim_fixture(record, dependencies)),
        ExecutionSignals(Event(), Event(), ExecutionMonitor([], None, Lock())),
    )


class FailingAppend:
    """只在标准库文件流边界注入写入/flush/关闭失败，实际文件始终在退出时关闭。"""

    def __init__(self, stream: TextIO, phase: str) -> None:
        """保存真实文本流和这次故障位置。"""
        self.stream, self.phase = stream, phase

    def __enter__(self) -> Self:
        """返回当前包装对象，真实描述符仍由退出方法负责。"""
        return self

    def __exit__(self, *args: object) -> None:
        """先关闭真实流，再模拟close错误，不泄漏描述符。"""
        self.stream.close()
        if self.phase == "close":
            raise OSError("模拟关闭失败")

    def write(self, value: str) -> int:
        """追加故障留下半行，以便断言下一次读取拒绝接着写。"""
        if self.phase == "append":
            self.stream.write(value[: len(value) // 2])
            raise OSError("模拟部分追加失败")
        return self.stream.write(value)

    def flush(self) -> None:
        """flush失败前不修改既有文件，退出仍会关闭真实流。"""
        if self.phase == "flush":
            raise OSError("模拟flush失败")
        self.stream.flush()

    def fileno(self) -> int:
        """让真实fsync仍作用于同一临时文件描述符。"""
        return self.stream.fileno()


def wait_for_navigation(dependencies: ExecutorDependencies, job_id: int) -> None:
    """至多半秒观察数据库等锁副本，不通过线程存活状态猜是否进入等待。"""
    from rdp.infra.db.connection import session_scope
    from rdp.jobs.records import find_job
    from rdp.jobs.types import WaitReason

    deadline = time.monotonic() + 0.5
    tick = Event()
    while True:
        with session_scope(dependencies.engine, read_only=True) as session:
            waiting = find_job(session, job_id).wait_reason
        if waiting is WaitReason.NAVIGATION_LOCK:
            return
        assert time.monotonic() < deadline
        tick.wait(0.005)


@contextmanager
def navigation_thread(
    dependencies: ExecutorDependencies, work: ExecutionWork, signals: ExecutionSignals
) -> Generator[tuple[Thread, list[JobRecord | None]]]:
    """启动真实执行线程；无论断言结果如何都在两秒内回收并传出线程异常。"""
    from rdp.jobs.execution import execute_job

    results: list[JobRecord | None] = []
    errors: list[BaseException] = []

    def run() -> None:
        try:
            results.append(execute_job(work, dependencies, signals))
        except BaseException as error:
            errors.append(error)

    thread = Thread(target=run, daemon=True)
    try:
        thread.start()
        yield thread, results
    finally:
        thread.join(timeout=2)
        if thread.is_alive():
            signals.stopping.set()
            thread.join(timeout=1)
        assert not thread.is_alive()
    assert errors == []
