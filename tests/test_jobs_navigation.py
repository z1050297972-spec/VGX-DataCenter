"""导航写锁、协作取消与状态文件的行为测试；数据库和文件均位于临时目录。"""

import time
from pathlib import Path

import pytest
from jobs_progress_support import reporter_context
from jobs_storage_support import NOW

from rdp.jobs.navigation import NavigationWriter
from rdp.jobs.types import JobClock


def test_serialize(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """验收4：两个写锁示例并发运行但verify/write保护段不重叠；执行线程之外无模块全局锁。"""
    import os
    from threading import Event

    from jobs_navigation_support import (
        navigation_jobs,
        navigation_thread,
        navigation_work,
        wait_for_navigation,
    )

    entered, release = Event(), Event()
    original = os.fsync

    def blocked_fsync(descriptor: int) -> None:
        if not entered.is_set():
            entered.set()
            assert release.wait(2)
        original(descriptor)

    monkeypatch.setattr(os, "fsync", blocked_fsync)
    with navigation_jobs(tmp_path) as dependencies:
        first, first_signals = navigation_work(dependencies, 71, "")
        second, second_signals = navigation_work(dependencies, 72, "71")
        with navigation_thread(dependencies, first, first_signals) as (
            _first_thread,
            first_results,
        ):
            try:
                assert entered.wait(1)
                with navigation_thread(dependencies, second, second_signals) as (
                    second_thread,
                    second_results,
                ):
                    try:
                        wait_for_navigation(dependencies, 72)
                        assert second_thread.is_alive() and first_results == second_results == []
                        assert (
                            len(
                                dependencies.paths.navigation_example.read_text(
                                    encoding="utf-8"
                                ).splitlines()
                            )
                            == 1
                        )
                        with reporter_context(tmp_path / "independent", dependencies.clock) as (
                            reporter,
                            _engine,
                            _signals,
                            _path,
                        ):
                            assert (
                                NavigationWriter().run(reporter, lambda: None, lambda: "独立实例")
                                == "独立实例"
                            )
                    finally:
                        release.set()
            finally:
                release.set()
        results = first_results + second_results
        assert len(results) == 2
        assert all(
            result is not None
            and result.summary is not None
            and result.summary.outcome == "succeeded"
            for result in results
        )
        assert (
            len(dependencies.paths.navigation_example.read_text(encoding="utf-8").splitlines()) == 2
        )


def test_conflict(tmp_path: Path) -> None:
    """验收4/场景二：同一预览空值的A先写，B核对冲突，诊断带A编号、实际/期望/后果，文件无B行且结果失败。"""
    import json

    from jobs_navigation_support import navigation_jobs, navigation_work

    from rdp.jobs.execution import execute_job

    with navigation_jobs(tmp_path) as dependencies:
        first, first_signals = navigation_work(dependencies, 71, "")
        second, second_signals = navigation_work(dependencies, 72, "")
        result = execute_job(first, dependencies, first_signals)
        assert (
            result is not None
            and result.summary is not None
            and result.summary.outcome == "succeeded"
        )
        result = execute_job(second, dependencies, second_signals)
        assert (
            result is not None and result.summary is not None and result.summary.outcome == "failed"
        )
        assert result.summary.total_items == 0
        diagnostic = result.diagnostics[0].samples[0]
        assert diagnostic.category == "conflict" and "#71" in diagnostic.actual
        assert {item.key: item.value for item in diagnostic.objects} == {
            "job_id": "72",
            "previous_job_id": "71",
        }
        assert diagnostic.expected == "预览值：" and "没有追加" in diagnostic.consequence
        assert "重新预览" in diagnostic.next_step
        assert [
            json.loads(line)
            for line in dependencies.paths.navigation_example.read_text(
                encoding="utf-8"
            ).splitlines()
        ] == [{"job_id": 71, "value": "71"}]


def test_matching_value(tmp_path: Path) -> None:
    """契约：预览值匹配最后value时追加当前编号新值，旧行保留，摘要完成条目为1。"""
    import json
    import stat

    from jobs_navigation_support import navigation_jobs, navigation_work

    from rdp.jobs.execution import execute_job
    from rdp.jobs.resource_examples import read_example_value

    with navigation_jobs(tmp_path) as dependencies:
        path = dependencies.paths.navigation_example
        old = '{"job_id":12,"value":"预览值"}\n'
        path.write_text(old, encoding="utf-8")
        work, signals = navigation_work(dependencies, 71, "预览值")
        result = execute_job(work, dependencies, signals)
        assert (
            result is not None
            and result.summary is not None
            and result.summary.outcome == "succeeded"
        )
        assert result.summary is not None and result.summary.total_items == 1
        lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
        assert lines[0] == old and len(lines) == 2
        assert json.loads(lines[1]) == {"job_id": 71, "value": "71"}
        last = read_example_value(path)
        assert last.job_id == 71 and last.value == "71"
        path.unlink()
        work, signals = navigation_work(dependencies, 72, "")
        assert execute_job(work, dependencies, signals) is not None
        assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_missing_file(tmp_path: Path) -> None:
    """契约：示例文件不存在时只接受空期望值，非空期望冲突且不创建文件。"""
    from jobs_navigation_support import navigation_jobs, navigation_work

    from rdp.jobs.execution import execute_job
    from rdp.jobs.resource_examples import read_example_value

    with navigation_jobs(tmp_path) as dependencies:
        path = dependencies.paths.navigation_example
        assert read_example_value(path).job_id is None and read_example_value(path).value == ""
        work, signals = navigation_work(dependencies, 71, "非空预览")
        result = execute_job(work, dependencies, signals)
        assert (
            result is not None and result.summary is not None and result.summary.outcome == "failed"
        )
        assert not path.exists()
        assert result.diagnostics[0].samples[0].category == "conflict"
        assert "尚无值" in result.diagnostics[0].samples[0].actual
        work, signals = navigation_work(dependencies, 72, "")
        result = execute_job(work, dependencies, signals)
        assert (
            result is not None
            and result.summary is not None
            and result.summary.outcome == "succeeded"
        )
        assert read_example_value(path).value == "72"


def test_cancel_wait(tmp_path: Path) -> None:
    """契约：等待写锁可以取消，至多一个分段等待加短锁预算内响应，核对/写入均不调用。"""
    from threading import Event, Thread

    from jobs_navigation_support import held_writer
    from jobs_progress_support import saved_record

    from rdp.jobs.errors import JobCancelledError
    from rdp.jobs.types import WaitReason

    calls: list[str] = []
    errors: list[BaseException] = []
    done = Event()
    with (
        held_writer(tmp_path / "holder") as (writer, _release, holder),
        reporter_context(tmp_path / "waiter", JobClock(lambda: NOW, time.monotonic)) as (
            reporter,
            engine,
            signals,
            _path,
        ),
    ):

        def run() -> None:
            try:
                writer.run(reporter, lambda: calls.append("verify"), lambda: calls.append("write"))
            except BaseException as error:
                errors.append(error)
            finally:
                done.set()

        waiter = Thread(target=run, daemon=True)
        try:
            waiter.start()
            deadline = time.monotonic() + 0.5
            while saved_record(engine).wait_reason is not WaitReason.NAVIGATION_LOCK:
                assert time.monotonic() < deadline
                done.wait(0.005)
            signals.cancelled.set()
            assert done.wait(0.3)
            assert holder.is_alive() and calls == []
            assert len(errors) == 1 and isinstance(errors[0], JobCancelledError)
        finally:
            signals.cancelled.set()
            waiter.join(timeout=1)
            assert not waiter.is_alive()


def test_cancel_after_acquire(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """契约：拿锁后进入屏蔽段前的取消仍生效，释放锁且不执行回调。"""
    from _thread import LockType
    from threading import Lock

    from rdp.jobs import navigation
    from rdp.jobs.errors import JobCancelledError

    locks: list[LockType] = []

    def observed_lock() -> LockType:
        lock = Lock()
        locks.append(lock)
        return lock

    # 在标准库互斥边界精确注入拿到写锁后的取消，不替换上报或业务回调。
    monkeypatch.setattr(navigation, "Lock", observed_lock)
    writer = NavigationWriter()
    with reporter_context(tmp_path, JobClock(lambda: NOW, time.monotonic)) as (
        reporter,
        _engine,
        signals,
        _path,
    ):
        original = signals.cancelled.is_set

        def cancelled_on_lock() -> bool:
            if locks[0].locked():
                signals.cancelled.set()
            return original()

        calls: list[str] = []
        with monkeypatch.context() as patch:
            patch.setattr(signals.cancelled, "is_set", cancelled_on_lock)
            with pytest.raises(JobCancelledError):
                writer.run(reporter, lambda: calls.append("verify"), lambda: calls.append("write"))
        assert calls == [] and not locks[0].locked() and original()
        signals.cancelled.clear()
        assert writer.run(reporter, lambda: None, lambda: 3) == 3


def test_cancel_during_write(tmp_path: Path) -> None:
    """验收5：写入期间请求取消，reporter.check_cancelled/wait不抛，写完放锁后下一检查点变已取消。"""
    from jobs_execution_support import execution_case

    from rdp.infra.db.connection import session_scope
    from rdp.jobs.execution import ExecutionContext, execute_job
    from rdp.jobs.records import StateChange, transition_job
    from rdp.jobs.types import JobState

    artifact = tmp_path / "finished"

    def execute(context: ExecutionContext) -> None:
        def write() -> None:
            with session_scope(dependencies.engine) as session:
                transition_job(
                    session, context.job_id, StateChange(JobState.RUNNING, JobState.CANCELLING, NOW)
                )
            signals.cancelled.set()
            context.reporter.check_cancelled()
            context.reporter.wait(0)
            artifact.write_text("写完", encoding="utf-8")

        context.write_navigation(lambda: None, write)
        context.reporter.check_cancelled()

    with execution_case(tmp_path, {"steps": 1, "interval_ms": 0}, execute) as (
        work,
        dependencies,
        signals,
    ):
        result = execute_job(work, dependencies, signals)
        assert artifact.exists() and artifact.read_text(encoding="utf-8") == "写完"
        assert result is not None and result.state is JobState.CANCELLED
        assert not result.holds_navigation_lock and result.wait_reason is None
        assert signals.cancelled.is_set()


def test_stop_during_write(tmp_path: Path) -> None:
    """契约：持锁期间worker停止同样延后，写完必放锁，保存进度后留给下实例恢复，不冒充用户取消。"""
    from jobs_execution_support import execution_case
    from jobs_progress_support import saved_record

    from rdp.jobs.execution import ExecutionContext, execute_job
    from rdp.jobs.types import JobState

    artifact = tmp_path / "finished"

    def execute(context: ExecutionContext) -> None:
        def write() -> None:
            signals.stopping.set()
            context.reporter.check_cancelled()
            context.reporter.wait(0.01)
            artifact.write_text("停止前写完", encoding="utf-8")

        context.write_navigation(lambda: None, write)
        context.reporter.check_cancelled()

    with execution_case(tmp_path, {"steps": 1, "interval_ms": 0}, execute) as (
        work,
        dependencies,
        signals,
    ):
        assert execute_job(work, dependencies, signals) is None
        record = saved_record(dependencies.engine)
        assert artifact.read_text(encoding="utf-8") == "停止前写完"
        assert record.state is JobState.RUNNING and record.summary is None
        assert not record.holds_navigation_lock and record.wait_reason is None
        assert signals.stopping.is_set() and not signals.cancelled.is_set()
        assert dependencies.resources is not None
        with reporter_context(tmp_path / "next", dependencies.clock) as (
            reporter,
            _engine,
            _signals,
            _path,
        ):
            assert dependencies.resources.navigation.run(reporter, lambda: None, lambda: 1) == 1


def test_stop_wait(tmp_path: Path) -> None:
    """契约：等锁时停止不等满300秒，write不调用，等待副本清空或由恢复清空。"""
    from threading import Event, Thread

    from jobs_navigation_support import held_writer
    from jobs_progress_support import saved_record

    from rdp.jobs.errors import WorkerStoppingError
    from rdp.jobs.types import WaitReason

    calls: list[str] = []
    errors: list[BaseException] = []
    done = Event()
    with (
        held_writer(tmp_path / "holder") as (writer, _release, holder),
        reporter_context(tmp_path / "waiter", JobClock(lambda: NOW, time.monotonic)) as (
            reporter,
            engine,
            signals,
            _path,
        ),
    ):

        def run() -> None:
            try:
                writer.run(reporter, lambda: calls.append("verify"), lambda: calls.append("write"))
            except BaseException as error:
                errors.append(error)
            finally:
                done.set()

        waiter = Thread(target=run, daemon=True)
        try:
            waiter.start()
            deadline = time.monotonic() + 0.5
            while saved_record(engine).wait_reason is not WaitReason.NAVIGATION_LOCK:
                assert time.monotonic() < deadline
                done.wait(0.005)
            signals.stopping.set()
            assert done.wait(0.3)
            assert holder.is_alive() and calls == []
            assert len(errors) == 1 and isinstance(errors[0], WorkerStoppingError)
        finally:
            signals.stopping.set()
            waiter.join(timeout=1)
            assert not waiter.is_alive()


def test_verify_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """契约：verify抛ConflictError后write未调用，锁在finally释放，原诊断和异常链保留。"""
    from jobs_progress_support import diagnostic, saved_record

    from rdp.infra.diagnostics import ConflictError, DiagnosticCategory, DiagnosticLevel
    from rdp.jobs import progress as progress_module

    monkeypatch.setattr(progress_module, "PROGRESS_INTERVAL_S", 0)
    writer = NavigationWriter()
    error = ConflictError(
        (
            diagnostic(1).model_copy(
                update={"level": DiagnosticLevel.ERROR, "category": DiagnosticCategory.CONFLICT}
            ),
        )
    )
    cause = ValueError("预览已经过期")
    calls: list[str] = []

    def verify() -> None:
        raise error from cause

    with reporter_context(tmp_path, JobClock(lambda: NOW, time.monotonic)) as (
        reporter,
        engine,
        _signals,
        _path,
    ):
        with pytest.raises(ConflictError) as caught:
            writer.run(reporter, verify, lambda: calls.append("错误的写入"))
        assert caught.value is error and caught.value.__cause__ is cause
        assert caught.value.diagnostics == error.diagnostics and calls == []
        reporter.flush_due()
        assert not saved_record(engine).holds_navigation_lock
        assert saved_record(engine).wait_reason is None
        assert writer.run(reporter, lambda: None, lambda: "再次获锁") == "再次获锁"


def test_write_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """契约：write抛外部错误后锁仍释放，清副本失败不掩盖原异常，部分产物按类型契约保留。"""
    from jobs_progress_support import diagnostic
    from sqlalchemy import event

    from rdp.infra.diagnostics import DiagnosticCategory, DiagnosticLevel, ExternalError
    from rdp.jobs import progress as progress_module

    monkeypatch.setattr(progress_module, "PROGRESS_INTERVAL_S", 0)
    writer = NavigationWriter()
    artifact = tmp_path / "partial"
    error = ExternalError(
        (
            diagnostic(2).model_copy(
                update={"level": DiagnosticLevel.ERROR, "category": DiagnosticCategory.EXTERNAL}
            ),
        )
    )

    def fail(*args: object) -> None:
        if isinstance(args[2], str) and args[2].startswith("UPDATE jobs"):
            raise OSError("清空展示失败")

    with reporter_context(tmp_path, JobClock(lambda: NOW, time.monotonic)) as (
        reporter,
        engine,
        _signals,
        _path,
    ):

        def write() -> None:
            artifact.write_text("部分产物", encoding="utf-8")
            event.listen(engine, "after_cursor_execute", fail)
            raise error

        try:
            with pytest.raises(ExternalError) as caught:
                writer.run(reporter, lambda: None, write)
            assert caught.value is error
            assert "清空失败" in "".join(caught.value.__notes__)
            assert artifact.read_text(encoding="utf-8") == "部分产物"
        finally:
            event.remove(engine, "after_cursor_execute", fail)
        assert writer.run(reporter, lambda: None, lambda: 9) == 9


def test_wait_timeout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """契约：总等锁达到300秒ConflictError，诊断含实际等待秒数、当前作业和内存锁持有者编号；write未调用，分段等待用monotonic。"""
    from jobs_navigation_support import held_writer

    from rdp.infra.diagnostics import ConflictError
    from rdp.jobs import policy

    monkeypatch.setattr(policy, "NAVIGATION_LOCK_TIMEOUT_S", 0.04)
    monkeypatch.setattr(policy, "NAVIGATION_LOCK_POLL_S", 0.005)
    calls: list[str] = []
    with (
        held_writer(tmp_path / "holder") as (writer, _release, holder),
        reporter_context(tmp_path / "waiter", JobClock(lambda: NOW, time.monotonic)) as (
            reporter,
            _engine,
            _signals,
            _path,
        ),
    ):
        started = time.monotonic()
        with pytest.raises(ConflictError) as caught:
            writer.run(reporter, lambda: calls.append("verify"), lambda: calls.append("write"))
        elapsed = time.monotonic() - started
        assert 0.04 <= elapsed < 0.3 and holder.is_alive() and calls == []
        diagnostic = caught.value.diagnostics[0]
        assert {item.key: item.value for item in diagnostic.objects} == {
            "job_id": "71",
            "holder_job_id": "72",
        }
        assert (
            "#72" in diagnostic.actual
            and diagnostic.expected is not None
            and "0.04" in diagnostic.expected
        )
        assert 0.04 <= float(diagnostic.actual.split("秒")[0].removeprefix("已等待")) <= elapsed
        assert "未调用" in diagnostic.consequence and diagnostic.next_step


def test_nested_guard(tmp_path: Path) -> None:
    """契约：重复/跨线程取消屏蔽和递归写锁均DefectError，不能死锁或永久屏蔽取消。"""
    from threading import Thread

    from rdp.infra.diagnostics import DefectError
    from rdp.jobs.errors import JobCancelledError

    with reporter_context(tmp_path, JobClock(lambda: NOW, time.monotonic)) as (
        reporter,
        _engine,
        signals,
        _path,
    ):
        manager = reporter.defer_cancellation()
        errors: list[BaseException] = []

        def foreign() -> None:
            for call in (manager.__enter__, lambda: manager.__exit__(None, None, None)):
                try:
                    call()
                except BaseException as error:
                    errors.append(error)

        thread = Thread(target=foreign, daemon=True)
        with manager:
            with pytest.raises(DefectError), reporter.defer_cancellation():
                pytest.fail("不得进入嵌套屏蔽")
            try:
                thread.start()
                thread.join(timeout=1)
                assert not thread.is_alive()
            finally:
                thread.join(timeout=1)
            assert len(errors) == 2 and all(isinstance(error, DefectError) for error in errors)
        with pytest.raises(DefectError), manager:
            pytest.fail("不得重复进入")
        writer = NavigationWriter()
        with pytest.raises(DefectError):
            writer.run(
                reporter, lambda: None, lambda: writer.run(reporter, lambda: None, lambda: None)
            )
        assert writer.run(reporter, lambda: None, lambda: 5) == 5
        signals.cancelled.set()
        with pytest.raises(JobCancelledError):
            reporter.check_cancelled()


def test_callback_result(tmp_path: Path) -> None:
    """契约：框架原样返回write结果，核对和写入各调用一次且顺序固定。"""
    calls: list[str] = []
    result = object()

    def verify() -> None:
        calls.append("verify")

    def write() -> object:
        calls.append("write")
        return result

    with reporter_context(tmp_path, JobClock(lambda: NOW, time.monotonic)) as (
        reporter,
        _engine,
        _signals,
        _path,
    ):
        assert NavigationWriter().run(reporter, verify, write) is result
        assert calls == ["verify", "write"]


def test_pause_bounds() -> None:
    """契约：示例暂停接受0和10秒，拒绝11、bool及字符串；期望值允许空、拒绝超过256码点。"""
    from pydantic import ValidationError

    from rdp.jobs.resource_examples import NavigationExampleParameters

    assert NavigationExampleParameters(expected_value="").pause_s == 0
    assert NavigationExampleParameters(expected_value="值" * 256, pause_s=10).pause_s == 10
    for pause in (-1, 11, True, "1", 1.0):
        with pytest.raises(ValidationError):
            NavigationExampleParameters.model_validate({"expected_value": "", "pause_s": pause})
    for expected in ("值" * 257, None, 1):
        with pytest.raises(ValidationError):
            NavigationExampleParameters.model_validate({"expected_value": expected})


def test_file_corrupt(tmp_path: Path) -> None:
    """契约：坏JSON、超长行、缺换行尾部和非法编号均InputError，不静默覆盖或截断旧行。"""
    from rdp.infra.diagnostics import InputError
    from rdp.jobs.resource_examples import read_example_value

    path = tmp_path / "navigation-example.jsonl"
    bad_tails = (
        b"{broken}\n",
        b"x" * 4097 + b"\n",
        b'{"job_id":1,"value":"1"}',
        b'{"job_id":0,"value":"0"}\n',
        b'{"job_id":true,"value":"1"}\n',
        b'{"job_id":9223372036854775808,"value":"1"}\n',
        b'{"job_id":1,"value":null}\n',
        b"[]\n",
        b'{"job_id":1}\n',
        b'{"job_id":1,"value":"' + b"x" * 257 + b'"}\n',
        b"\xff\n",
    )
    for tail in bad_tails:
        content = b'{"job_id":12,"value":"12"}\n' + tail
        path.write_bytes(content)
        with pytest.raises(InputError):
            read_example_value(path)
        assert path.read_bytes() == content
    path.write_bytes(b"")
    assert read_example_value(path).job_id is None
    path.write_bytes(b'{"job_id":12,"value":"12"}\n' * 1000 + b'{"job_id":71,"value":"71"}\n\n')
    assert read_example_value(path).job_id == 71


def test_file_io(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """契约：打开/追加/flush/fsync失败为ExternalError，可能留下的半行可识别，后次读取拒绝继续追加。"""
    import os
    from typing import TextIO, cast

    from jobs_navigation_support import FailingAppend, navigation_jobs, navigation_work

    from rdp.infra.diagnostics import ExternalError, InputError
    from rdp.jobs.execution import execute_job
    from rdp.jobs.resource_examples import read_example_value

    path = tmp_path / "read.jsonl"
    path.write_text('{"job_id":1,"value":"1"}\n', encoding="utf-8")

    def denied(*args: object, **kwargs: object) -> None:
        raise PermissionError("模拟权限失败")

    with monkeypatch.context() as patch:
        patch.setattr(Path, "open", denied)
        with pytest.raises(ExternalError) as caught:
            read_example_value(path)
        assert isinstance(caught.value.__cause__, OSError)
    original, original_open = os.fdopen, os.open
    for phase in ("open", "append", "flush", "fsync", "close"):
        with navigation_jobs(tmp_path / phase) as dependencies:
            work, signals = navigation_work(dependencies, 71, "")

            def wrapped(
                descriptor: int, mode: str, *, encoding: str, failure_phase: str = phase
            ) -> FailingAppend:
                return FailingAppend(
                    cast(TextIO, original(descriptor, mode, encoding=encoding)), failure_phase
                )

            with monkeypatch.context() as patch:
                if phase == "open":

                    def deny_example(file: str | Path, flags: int, mode: int = 0o777) -> int:
                        if str(file).endswith("navigation-example.jsonl"):
                            raise PermissionError("模拟权限失败")
                        return original_open(file, flags, mode)

                    patch.setattr(os, "open", deny_example)
                elif phase == "fsync":
                    patch.setattr(os, "fsync", denied)
                else:
                    patch.setattr(os, "fdopen", wrapped)
                result = execute_job(work, dependencies, signals)
            assert (
                result is not None
                and result.summary is not None
                and result.summary.outcome == "failed"
            )
            assert result.diagnostics[0].samples[0].category == "external"
            assert result.summary.total_items == 0
            if phase == "append":
                content = dependencies.paths.navigation_example.read_bytes()
                assert content and not content.endswith(b"\n")
                with pytest.raises(InputError):
                    read_example_value(dependencies.paths.navigation_example)
                assert dependencies.paths.navigation_example.read_bytes() == content


def test_path_boundary(tmp_path: Path) -> None:
    """契约：示例拒绝软链接、非普通文件及不可信路径；所有文件只在tmp_path状态目录。"""
    import os

    from rdp.infra.diagnostics import DefectError
    from rdp.jobs.resource_examples import read_example_value

    target = tmp_path / "real.jsonl"
    original = b'{"job_id":1,"value":"1"}\n'
    target.write_bytes(original)
    link = tmp_path / "linked.jsonl"
    link.symlink_to(target)
    directory = tmp_path / "directory"
    directory.mkdir()
    parent_link = tmp_path / "parent-link"
    parent_link.symlink_to(directory, target_is_directory=True)
    fifo = tmp_path / "fifo"
    os.mkfifo(fifo)
    for path in (
        Path("relative.jsonl"),
        link,
        directory,
        fifo,
        parent_link / "missing.jsonl",
        tmp_path / ".." / tmp_path.name / "real.jsonl",
    ):
        with pytest.raises(DefectError):
            read_example_value(path)
    assert target.read_bytes() == original


def test_deferred_wait_is_bounded_without_spin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """验收5：持锁收到取消后reporter.wait仍经过登记暂停时长，采用分段计时等待而非已置位Event忙等，普通I/O错误仍传播。"""
    from threading import Event

    from jobs_progress_support import progress
    from sqlalchemy import event

    from rdp.infra.diagnostics import ExternalError
    from rdp.jobs import progress as progress_module
    from rdp.jobs.errors import JobCancelledError

    waits: list[tuple[bool, float | None]] = []
    original = Event.wait

    def observed_wait(signal: Event, timeout: float | None = None) -> bool:
        waits.append((signal.is_set(), timeout))
        return original(signal, timeout)

    def fail(*args: object) -> None:
        if isinstance(args[2], str) and args[2].startswith("UPDATE jobs"):
            raise OSError("模拟保护段补写失败")

    monkeypatch.setattr(Event, "wait", observed_wait)
    monkeypatch.setattr(progress_module, "PROGRESS_LOCK_TIMEOUT_MS", 10)
    monkeypatch.setattr(progress_module, "PROGRESS_INTERVAL_S", 0)
    with reporter_context(tmp_path, JobClock(lambda: NOW, time.monotonic)) as (
        reporter,
        engine,
        signals,
        _path,
    ):
        signals.cancelled.set()
        with reporter.defer_cancellation():
            started = time.monotonic()
            reporter.wait(0.04)
            assert time.monotonic() - started >= 0.04
        assert 0 < len(waits) < 20 and all(not ready for ready, _ in waits)
        assert all(timeout is not None and 0 < timeout <= 0.05 for _, timeout in waits)
        with engine.begin():
            reporter.report(progress(1))
        event.listen(engine, "after_cursor_execute", fail)
        try:
            with reporter.defer_cancellation(), pytest.raises(ExternalError):
                reporter.check_cancelled()
        finally:
            event.remove(engine, "after_cursor_execute", fail)
        with pytest.raises(JobCancelledError):
            reporter.check_cancelled()


def test_timeout_holder_release_race(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """契约：等锁超时恰逢持有者释放时，诊断明确观察到无人持有，不从滞后数据库编造持锁作业编号。"""
    from jobs_navigation_support import held_writer
    from jobs_progress_support import saved_record

    from rdp.infra.diagnostics import ConflictError
    from rdp.jobs import policy
    from rdp.jobs.types import WaitReason

    monkeypatch.setattr(policy, "NAVIGATION_LOCK_TIMEOUT_S", 0.04)
    seconds = [0.0]
    calls: list[str] = []
    with held_writer(tmp_path / "holder") as (writer, release, holder):

        def monotonic() -> float:
            # 到期读数返回前确定持有人已经退出，重现超时与释放的交界。
            if (
                seconds[0] == 0
                and ready
                and saved_record(engine).wait_reason is WaitReason.NAVIGATION_LOCK
            ):
                release.set()
                holder.join(timeout=1)
                assert not holder.is_alive()
                seconds[0] = 0.04
            return seconds[0]

        ready = False
        with reporter_context(tmp_path / "waiter", JobClock(lambda: NOW, monotonic)) as (
            reporter,
            engine,
            _signals,
            _path,
        ):
            ready = True
            with pytest.raises(ConflictError) as caught:
                writer.run(reporter, lambda: calls.append("verify"), lambda: calls.append("write"))
            assert calls == []
            diagnostic = caught.value.diagnostics[0]
            assert {item.key: item.value for item in diagnostic.objects}[
                "holder_job_id"
            ] == "无人持有"
            assert "无人持有" in diagnostic.actual and "#72" not in diagnostic.actual


def test_execution_context_exposes_only_needed_capabilities(tmp_path: Path) -> None:
    """契约：类型上下文只有write_navigation入口和最小清除回调，无资源池、发布者、引擎或整份配置；缺必填关键字直接TypeError。"""
    import inspect

    from jobs_execution_support import execution_case

    from rdp.jobs.execution import ExecutionContext, execute_job

    observed: list[int] = []

    def execute(context: ExecutionContext) -> None:
        assert not any(
            hasattr(context, name)
            for name in ("resources", "pool", "publisher", "engine", "configuration")
        )
        observed.append(context.write_navigation(lambda: None, lambda: 7))

    with execution_case(tmp_path, {"steps": 1, "interval_ms": 0}, execute) as (
        work,
        dependencies,
        signals,
    ):
        result = execute_job(work, dependencies, signals)
        assert (
            result is not None
            and result.summary is not None
            and result.summary.outcome == "succeeded"
        )
        assert observed == [7]
    for name in (
        "_navigation",
        "gpu_index",
        "maintenance",
        "gpu_example_command",
        "navigation_example_path",
    ):
        parameter = inspect.signature(ExecutionContext).parameters[name]
        assert (
            parameter.kind is inspect.Parameter.KEYWORD_ONLY
            and parameter.default is inspect.Parameter.empty
        )


def test_release_metadata_failure_keeps_primary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """持有人信息锁发生故障仍放开实际写锁，清理故障不得掩盖回调原异常或造成二次释放。"""
    from threading import Event, Lock

    from jobs_progress_support import diagnostic

    from rdp.infra.diagnostics import DiagnosticCategory, DiagnosticLevel, ExternalError
    from rdp.jobs import navigation

    failed = Event()
    actual = Lock()

    class MetadataLock:
        """在标准库锁边界模拟释放时的有界取锁失败。"""

        def acquire(self, *, timeout: float) -> bool:
            """失败由写回调触发，之前的检查与登记可以正常完成。"""
            return not failed.is_set()

        def release(self) -> None:
            """此替身不持资源，无需实际释放。"""

    locks = iter((actual, MetadataLock()))
    monkeypatch.setattr(navigation, "Lock", lambda: next(locks))
    writer = NavigationWriter()
    error = ExternalError(
        (
            diagnostic(3).model_copy(
                update={"level": DiagnosticLevel.ERROR, "category": DiagnosticCategory.EXTERNAL}
            ),
        )
    )

    def write() -> None:
        failed.set()
        raise error

    with reporter_context(tmp_path, JobClock(lambda: NOW, time.monotonic)) as (
        reporter,
        _engine,
        _signals,
        _path,
    ):
        with pytest.raises(ExternalError) as caught:
            writer.run(reporter, lambda: None, write)
        assert caught.value is error and not actual.locked()
        assert "持有人" in "".join(error.__notes__)


def test_full_limit_tail_after_previous_line(tmp_path: Path) -> None:
    """最后一行恰好4096字节且前面有旧记录时仍是合法有界JSON，不能把整行当作截断前缀丢弃。"""
    from rdp.jobs.resource_examples import read_example_value

    value = b'{"job_id":71,"value":"71"}'
    tail = value + b" " * (4095 - len(value)) + b"\n"
    path = tmp_path / "navigation-example.jsonl"
    path.write_bytes(b'{"job_id":12,"value":"12"}\n' + tail)
    result = read_example_value(path)
    assert result.job_id == 71 and result.value == "71"


@pytest.mark.parametrize("phase", ["metadata", "display"])
def test_successful_write_cleanup_in_outer_except_propagates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, phase: str
) -> None:
    """调用方except里的无关异常不能成为写锁调用的主异常；写入成功后的持有人或展示清理失败必须传播。"""
    from threading import Event, Lock

    from sqlalchemy import event

    from rdp.infra.diagnostics import DefectError, ExternalError
    from rdp.jobs import navigation
    from rdp.jobs import progress as progress_module

    failed = Event()
    actual = Lock()
    cleanup_failure = DefectError()

    class MetadataLock:
        """在标准库锁边界只让本次写入完成后的持有人清理失败。"""

        def acquire(self, *, timeout: float) -> bool:
            """之前的检查和登记正常，写完后按指定场景失败。"""
            if phase == "metadata" and failed.is_set():
                raise cleanup_failure
            return True

        def release(self) -> None:
            """此替身不持资源，实际写锁由真实Lock管理。"""

    locks = iter((actual, MetadataLock()))
    monkeypatch.setattr(navigation, "Lock", lambda: next(locks))
    monkeypatch.setattr(progress_module, "PROGRESS_INTERVAL_S", 0)
    writer = NavigationWriter()

    def fail_display(*args: object) -> None:
        if (
            phase == "display"
            and failed.is_set()
            and isinstance(args[2], str)
            and args[2].startswith("UPDATE jobs")
        ):
            raise OSError("模拟写完后的展示清理失败")

    def write() -> int:
        failed.set()
        return 42

    outer = KeyError("调用方正在处理的异常")
    with reporter_context(tmp_path, JobClock(lambda: NOW, time.monotonic)) as (
        reporter,
        engine,
        _signals,
        _path,
    ):
        event.listen(engine, "before_cursor_execute", fail_display)
        try:
            try:
                raise outer
            except KeyError:
                with pytest.raises(DefectError if phase == "metadata" else ExternalError) as caught:
                    writer.run(reporter, lambda: None, write)
                if phase == "metadata":
                    assert caught.value is cleanup_failure
            assert not hasattr(outer, "__notes__")
            assert not actual.locked()
        finally:
            event.remove(engine, "before_cursor_execute", fail_display)
