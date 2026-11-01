"""第 11 张 worker_entry 契约清单；只用临时目录和可注入依赖，不触碰真实部署或服务。"""

import fcntl
import signal
from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from threading import Event
from unittest.mock import Mock

import pytest
from ops_support import runtime_inputs
from sqlalchemy import event

from rdp.infra.diagnostics import DefectError, ExternalError, InputError
from rdp.ops import lifecycle
from rdp.ops.lifecycle import start_worker, stop_signals
from rdp.ops.runtime import prepare_service
from rdp.ops.status import check_worker_stopped
from rdp.ops.worker import WorkerExit


@contextmanager
def _stopped(stop: Event) -> Generator[None]:
    """模拟入口已收到停止，不安装测试进程的真实信号处理器。"""
    stop.set()
    yield


@pytest.fixture(autouse=True)
def offline_mirror(monkeypatch: pytest.MonkeyPatch) -> None:
    """真实 worker 测试只使用假镜像响应，不访问网络。"""
    from rdp.jobs.downloads.plan import HttpResponse

    def request(*args: object, **kwargs: object) -> HttpResponse:
        return HttpResponse(200, {}, b"")

    monkeypatch.setattr("rdp.jobs.downloads.plan.UrllibTransport.request", request)


def test_exit_codes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """验证契约：第8张：正常0、失败1、实例冲突2及停止超预算原样经 start_worker/run_cli/main 返回给 sys.exit。"""
    for code in (0, 1, 2, 7):
        inputs = runtime_inputs(tmp_path / str(code))
        runtime = prepare_service("worker", no_stderr=True, inputs=inputs)
        runner = Mock(return_value=WorkerExit(code, "测试结果", False))
        monkeypatch.setattr(lifecycle, "run_worker", runner, raising=False)
        assert start_worker(runtime, inputs=inputs, signals=_stopped) == code
        assert runner.call_count == 1


def test_signals_stop(monkeypatch: pytest.MonkeyPatch) -> None:
    """验证契约：验收：注入信号安装器把SIGTERM和SIGINT都映射到同一个stop Event；不直接杀工具或写数据库。"""
    handlers: dict[int, object] = {}
    monkeypatch.setattr(signal, "getsignal", Mock(return_value=signal.SIG_DFL))

    def install(number: int, handler: object) -> object:
        handlers[number] = handler
        return signal.SIG_DFL

    monkeypatch.setattr(signal, "signal", install)
    stop = Event()
    with stop_signals(stop):
        for number in (signal.SIGTERM, signal.SIGINT):
            handler = handlers[number]
            assert callable(handler)
            handler(number, None)
            handler(number, None)
            assert stop.is_set()


def test_signal_restore(monkeypatch: pytest.MonkeyPatch) -> None:
    """验证契约：stop_signals 在受控子进程测试正常/异常退出均恢复原处理器；部分安装失败也回滚，不修改 pytest 的真实处理器。"""
    install = Mock(return_value=signal.SIG_IGN)
    monkeypatch.setattr(signal, "signal", install)
    monkeypatch.setattr(signal, "getsignal", Mock(return_value=signal.SIG_IGN))
    with pytest.raises(RuntimeError), stop_signals(Event()):
        raise RuntimeError("业务异常")
    assert install.call_args_list[-2].args == (signal.SIGINT, signal.SIG_IGN)
    assert install.call_args_list[-1].args == (signal.SIGTERM, signal.SIG_IGN)
    install.reset_mock(side_effect=True)
    install.side_effect = [signal.SIG_IGN, OSError("安装失败"), signal.SIG_IGN]
    with pytest.raises(DefectError), stop_signals(Event()):
        pytest.fail("部分安装失败不得进入运行")
    assert install.call_args_list[-1].args == (signal.SIGTERM, signal.SIG_IGN)


def test_signal_invalid_thread(monkeypatch: pytest.MonkeyPatch) -> None:
    """验证契约：非主线程安装信号拒绝为 DefectError，不留下半安装状态；测试线程 finally 回收。"""
    install = Mock(side_effect=AssertionError("不应安装"))
    monkeypatch.setattr(signal, "signal", install)

    def enter() -> None:
        with stop_signals(Event()):
            pytest.fail("不应进入")

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(enter)
        with pytest.raises(DefectError):
            future.result(timeout=2)
    install.assert_not_called()


def test_retained_lock(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """验证契约：WorkerExit.lock_retained=True 时不 dispose、不解锁、不在同进程重启，最终退出保留失败码。"""
    inputs = runtime_inputs(tmp_path)
    runtime = prepare_service("worker", no_stderr=True, inputs=inputs)
    disposed = Mock()
    event.listen(runtime.engine, "engine_disposed", disposed)
    monkeypatch.setattr(lifecycle, "run_worker", Mock(return_value=WorkerExit(1, "仍有线程", True)))
    try:
        assert start_worker(runtime, inputs=inputs, signals=_stopped) == 1
        disposed.assert_not_called()
    finally:
        event.remove(runtime.engine, "engine_disposed", disposed)
        runtime.engine.dispose()


def test_normal_cleanup(tmp_path: Path) -> None:
    """验证契约：无遗留线程时释放引擎一次，信号上下文异常或 GPU 定位失败也安全清理。"""
    inputs = runtime_inputs(tmp_path)
    runtime = prepare_service("worker", no_stderr=True, inputs=inputs)
    disposed = Mock()
    event.listen(runtime.engine, "engine_disposed", disposed)
    try:
        assert start_worker(runtime, inputs=inputs, signals=_stopped) == 0
        disposed.assert_called_once_with(runtime.engine)
    finally:
        event.remove(runtime.engine, "engine_disposed", disposed)


def test_scheduling_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """验证契约：WorkerScheduling 含同一 catalog、GPU绝对路径与 config.errors.retention_days，不遗漏定时维护。"""
    inputs = runtime_inputs(tmp_path)
    runtime = prepare_service("worker", no_stderr=True, inputs=inputs)
    runner = Mock(return_value=WorkerExit(0, "停止", False))
    monkeypatch.setattr(lifecycle, "run_worker", runner)
    assert start_worker(runtime, inputs=inputs, signals=_stopped) == 0
    scheduling = runner.call_args.kwargs["scheduling"]
    assert scheduling.catalog is runtime.scheduling
    assert scheduling.nvidia_smi is None
    assert scheduling.error_retention_days == runtime.loaded.config.errors.retention_days
    assert runner.call_args.kwargs["log_time"] is inputs.log_time


def test_logging_clock(tmp_path: Path) -> None:
    """验证契约：run_worker 接收与入口相同的 LogTime，二次日志配置不会丢注入时钟或 --no-stderr。"""
    inputs = runtime_inputs(tmp_path)
    runtime = prepare_service("worker", no_stderr=True, inputs=inputs)
    with runtime.paths.worker_lock.open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert start_worker(runtime, inputs=inputs, signals=_stopped) == 2
    lines = (runtime.paths.logs / "worker.log").read_text().splitlines()
    conflict = next(line for line in lines if "另一个 worker" in line)
    assert conflict.startswith("2026-10-28 12:00:00.000+00:00 WARNING ")


def test_held_lock_refused(tmp_path: Path) -> None:
    """验证契约：验收3：独立文件描述符持有worker.lock时检查返回拒绝，诊断含锁路径、实际状态、后果与下一步。"""
    path = tmp_path / "worker.lock"
    with path.open("w") as stream:
        stream.write("陈旧PID")
        stream.flush()
        fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        availability = check_worker_stopped(path)
        assert not availability.allowed
        assert len(availability.diagnostics) == 1
        assert str(path) in str(availability.diagnostics[0].objects)
    assert path.read_text() == "陈旧PID"


def test_free_and_missing_lock(tmp_path: Path) -> None:
    """验证契约：锁缺失或陈旧文件未持锁时允许；不创建缺失文件，不依赖文件内容中的PID或过期心跳。"""
    path = tmp_path / "missing/worker.lock"
    assert check_worker_stopped(path).allowed
    assert not path.parent.exists()
    path = tmp_path / "worker.lock"
    path.write_text("99999")
    assert check_worker_stopped(path).allowed
    assert path.read_text() == "99999"


def test_probe_releases_lock(tmp_path: Path) -> None:
    """验证契约：探测成功后立刻释放并关闭fd，真正worker随后可取得同一inode锁；不删除替换锁文件。"""
    path = tmp_path / "worker.lock"
    path.touch()
    for _ in range(3):
        assert check_worker_stopped(path).allowed
        with path.open("rb") as stream:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            assert not check_worker_stopped(path).allowed


def test_probe_errors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """验证契约：相对路径、目录、软链接拒绝；权限、打开和加/解锁失败不能误报已停止，所有fd回收。"""
    path = tmp_path / "worker.lock"
    path.touch()
    link = tmp_path / "link"
    link.symlink_to(path)
    for invalid in (Path("relative"), tmp_path, link):
        with pytest.raises(InputError):
            check_worker_stopped(invalid)
    with monkeypatch.context() as patch:
        patch.setattr(fcntl, "flock", Mock(side_effect=PermissionError("拒绝加锁")))
        with pytest.raises(ExternalError):
            check_worker_stopped(path)
    assert check_worker_stopped(path).allowed


@pytest.mark.parametrize(
    ("scenario", "code", "meaning"),
    (
        ("normal", 0, "worker已停止"),
        ("locked", 2, "另一个 worker 正在运行"),
        ("failure", 1, "worker资源副本初始化失败"),
    ),
)
def test_worker_lifecycle_logs(
    tmp_path: Path, scenario: str, code: int, meaning: str, capsys: pytest.CaptureFixture[str]
) -> None:
    """入口开始记录版本/PID/实例号，结束记录真实退出码和含义，非零结束为ERROR且不写stderr。"""
    import os
    import re

    inputs = runtime_inputs(tmp_path)
    runtime = prepare_service("worker", no_stderr=True, inputs=inputs)
    with runtime.paths.worker_lock.open("w") as lock:
        if scenario == "locked":
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        elif scenario == "failure":
            with runtime.engine.begin() as connection:
                connection.exec_driver_sql("DROP TABLE jobs")
        assert start_worker(runtime, inputs=inputs, signals=_stopped) == code
    lines = (runtime.paths.logs / "worker.log").read_text().splitlines()
    starts = [line for line in lines if "worker开始运行" in line]
    ends = [line for line in lines if "worker结束运行" in line]
    assert len(starts) == len(ends) == 1
    assert " INFO rdp.ops.worker " in starts[0]
    assert 'platform_version="0.1.0 (aaaaaaa)"' in starts[0]
    assert f"pid={os.getpid()}" in starts[0]
    identifiers = re.findall(r"instance_id=([0-9a-f]{32})", starts[0])
    assert len(identifiers) == 1 and f"instance_id={identifiers[0]}" in ends[0]
    level = "INFO" if code == 0 else "ERROR"
    assert f" {level} rdp.ops.worker " in ends[0]
    assert f"exit_code={code}" in ends[0] and meaning in ends[0]
    assert capsys.readouterr().err == ""


def test_worker_loop_exit_log(tmp_path: Path) -> None:
    """真实主循环产生心跳后协作停止，返回分支仍只写一条INFO结束记录，不安装真实信号。"""
    from threading import Timer

    inputs = runtime_inputs(tmp_path)
    runtime = prepare_service("worker", no_stderr=True, inputs=inputs)
    heartbeat_seen = Event()

    @contextmanager
    def stop_after_heartbeat(stop: Event) -> Generator[None]:
        def observe(*args: object) -> None:
            statement = args[2]
            if isinstance(statement, str) and statement.startswith("INSERT INTO worker_heartbeat"):
                heartbeat_seen.set()
                stop.set()

        # 事件只用于决定停止时刻；兜底定时器使SQL变化也不能让测试无限运行。
        deadline = Timer(2, stop.set)
        event.listen(runtime.engine, "after_cursor_execute", observe)
        deadline.start()
        try:
            yield
        finally:
            deadline.cancel()
            deadline.join(timeout=2)
            event.remove(runtime.engine, "after_cursor_execute", observe)
            assert not deadline.is_alive()

    assert start_worker(runtime, inputs=inputs, signals=stop_after_heartbeat) == 0
    assert heartbeat_seen.is_set()
    text = (runtime.paths.logs / "worker.log").read_text()
    assert text.count("INFO rdp.ops.worker worker结束运行：worker已停止 exit_code=0") == 1
