"""第 11 张 web_lifecycle 契约清单；只用临时目录和可注入依赖，不触碰真实部署或服务。"""

import logging
from pathlib import Path
from threading import Event, Thread
from typing import Unpack, cast
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx import Client
from ops_support import runtime_inputs
from sqlalchemy import event

from rdp.api.production import UvicornOptions, WebRuntime, start_web
from rdp.api.shutdown import TrackedReport, drain_error_reports
from rdp.infra.diagnostics import DefectError
from rdp.ops.runtime import prepare_service


def _runtime(root: Path) -> WebRuntime:
    """生产资源仍经公共装配，运行器在进程内调用应用，不绑定端口。"""
    inputs = runtime_inputs(root)
    runtime = prepare_service("web", no_stderr=True, inputs=inputs)
    return WebRuntime(
        inputs.layout.web_dist,
        runtime.loaded.config.web,
        runtime.engine,
        runtime.paths,
        runtime.registry,
        runtime.scheduling,
        runtime.inspector,
        inputs.clock.now,
        runtime.version,
    )


def test_engine_passed(tmp_path: Path) -> None:
    """验证契约：第5张B1：create_app 接收同一真实 engine、绝对 dist 和注入时钟，不使用 database=None。"""
    runtime = _runtime(tmp_path)
    applications: list[FastAPI] = []

    def runner(app: FastAPI, **_options: Unpack[UvicornOptions]) -> None:
        applications.append(app)
        with TestClient(app) as client:
            assert cast(Client, client).get("/api/health").json() == {"status": "ok"}
        assert app.state.database_engine is runtime.engine

    assert start_web(runtime, runner=runner) == 0
    assert len(applications) == 1


def test_configure_jobs_storage_version(tmp_path: Path) -> None:
    """验证契约：configure_jobs 的 scheduling、configure_storage 的 inspector 和版本快照全部装配后才运行 uvicorn。"""
    runtime = _runtime(tmp_path)

    def runner(app: FastAPI, **_options: Unpack[UvicornOptions]) -> None:
        assert app.state.job_paths is runtime.paths
        assert app.state.storage_inspector is runtime.inspector
        assert app.state.platform_version == runtime.version
        assert app.state.scheduling_service is not None
        assert app.state.job_service is not None

    assert start_web(runtime, runner=runner) == 0


def test_uvicorn_logging(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """验证契约：验收2a：运行器收到log_config=None/access_log=False/workers=1及30秒退出宽限；即使WEB_CONCURRENCY非1也单进程，启动行统一且无访问日志。"""
    runtime = _runtime(tmp_path)
    monkeypatch.setenv("WEB_CONCURRENCY", "8")

    def runner(app: FastAPI, **options: Unpack[UvicornOptions]) -> None:
        assert options == {
            "host": runtime.settings.host,
            "port": runtime.settings.port,
            "log_config": None,
            "access_log": False,
            "workers": 1,
            "timeout_graceful_shutdown": 30,
        }
        logging.getLogger("uvicorn.error").info("Started server process")
        with TestClient(app) as client:
            assert cast(Client, client).get("/api/health").status_code == 200
        logging.getLogger("uvicorn.access").info("GET /api/health 200")

    assert start_web(runtime, runner=runner) == 0
    text = (runtime.paths.logs / "web.log").read_text()
    assert "2026-10-28 12:00:00.000+00:00 INFO uvicorn.error Started server process" in text
    assert "GET /api/health" not in text


def test_normal_dispose_order(tmp_path: Path) -> None:
    """验证契约：第5张B3：停止收请求→等待实际报错写入完成→dispose；空任务同样安全关闭。"""
    runtime = _runtime(tmp_path)
    order: list[str] = []
    threads: list[Thread] = []

    def disposed(_engine: object) -> None:
        order.append("dispose")

    event.listen(runtime.engine, "engine_disposed", disposed)

    def runner(app: FastAPI, **_options: Unpack[UvicornOptions]) -> None:
        report = TrackedReport(app, lambda: order.append("write"))
        thread = Thread(target=report.run)
        threads.append(thread)
        thread.start()
        thread.join(timeout=2)
        assert not thread.is_alive()
        order.append("stop")

    try:
        assert start_web(runtime, runner=runner) == 0
        assert order == ["write", "stop", "dispose"]
    finally:
        for thread in threads:
            thread.join(timeout=2)
        event.remove(runtime.engine, "engine_disposed", disposed)


def test_late_report() -> None:
    """验证契约：请求已超时或取消但写入线程仍运行时不得 dispose；线程结束后才允许关闭，不把 asyncio 取消当线程结束。"""
    app = FastAPI()
    started, release, written = Event(), Event(), Event()

    def write() -> None:
        started.set()
        assert release.wait(2)
        written.set()

    report = TrackedReport(app, write)
    thread = Thread(target=report.run)
    thread.start()
    try:
        assert started.wait(1)
        report.cancel_if_pending()
        assert drain_error_reports(app, timeout_s=0) is False
        assert not written.is_set()
        release.set()
        assert drain_error_reports(app, timeout_s=1) is True
        assert written.is_set()
    finally:
        release.set()
        thread.join(timeout=2)
        assert not thread.is_alive()


def test_queued_report_tracked() -> None:
    """验证契约：尚在线程池队列的任务也在提交前登记；关闭不得漏掉尚未开始的写入。"""
    app = FastAPI()
    write = Mock()
    report = TrackedReport(app, write)
    assert drain_error_reports(app, timeout_s=0) is False
    report.run()
    assert drain_error_reports(app, timeout_s=0) is True
    write.assert_called_once_with()
    with pytest.raises(DefectError):
        report.run()
    with pytest.raises(DefectError):
        TrackedReport(app, write)


def test_report_submit_failure() -> None:
    """验证契约：线程提交失败清理登记并走已有持久化失败报告，不留下永远无法完成的任务。"""
    app = FastAPI()
    write = Mock()
    report = TrackedReport(app, write)
    report.cancel_if_pending()
    report.cancel_if_pending()
    report.run()
    write.assert_not_called()
    assert drain_error_reports(app, timeout_s=0) is True


def test_drain_timeout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """验证契约：10秒总预算耗尽返回False，start_web返回1且不dispose；同一应用可再次观察结束状态。"""
    from rdp.api import production

    runtime = _runtime(tmp_path)
    disposed = Mock()
    reports: list[TrackedReport] = []
    applications: list[FastAPI] = []
    event.listen(runtime.engine, "engine_disposed", disposed)
    monkeypatch.setattr(production, "ERROR_REPORT_DRAIN_TIMEOUT_S", 0.0)

    def runner(app: FastAPI, **_options: Unpack[UvicornOptions]) -> None:
        applications.append(app)
        reports.append(TrackedReport(app, lambda: None))

    try:
        assert start_web(runtime, runner=runner) == 1
        assert (
            "ERROR rdp.api.production Web结束运行：失败退出 exit_code=1"
            in (runtime.paths.logs / "web.log").read_text()
        )
        disposed.assert_not_called()
        reports[0].run()
        assert drain_error_reports(applications[0], timeout_s=0) is True
    finally:
        for report in reports:
            report.cancel_if_pending()
        event.remove(runtime.engine, "engine_disposed", disposed)
        runtime.engine.dispose()


def test_drain_invalid_budget() -> None:
    """验证契约：负数、NaN或无穷预算归DefectError；0秒只做即时判断，不延长截止点。"""
    for budget in (-1.0, float("nan"), float("inf"), True):
        with pytest.raises(DefectError):
            drain_error_reports(FastAPI(), timeout_s=budget)
    assert drain_error_reports(FastAPI(), timeout_s=0) is True


def test_report_apps_isolated() -> None:
    """验证契约：两个 app 的报错任务隔离，关闭其中一个不等待另一个、不关闭另一个引擎。"""
    first, second = FastAPI(), FastAPI()
    report = TrackedReport(first, lambda: None)
    try:
        assert drain_error_reports(second, timeout_s=0) is True
        assert drain_error_reports(first, timeout_s=0) is False
    finally:
        report.cancel_if_pending()
    assert drain_error_reports(first, timeout_s=0) is True


def test_runner_failure(tmp_path: Path) -> None:
    """验证契约：运行器异常、SystemExit或构建文件失败返回1，仍按线程完成状态清理；原异常诊断只报一次，另记生命周期退出码。"""
    for index, failure in enumerate((RuntimeError("运行失败"), SystemExit(1), None)):
        runtime = _runtime(tmp_path / str(index))
        disposed = Mock()
        event.listen(runtime.engine, "engine_disposed", disposed)
        runner = Mock(side_effect=failure)
        if failure is None:
            (runtime.dist / "index.html").unlink()
        try:
            assert start_web(runtime, runner=runner) == 1
            disposed.assert_called_once_with(runtime.engine)
            text = (runtime.paths.logs / "web.log").read_text()
            expected = "前端构建产物缺失，请先构建" if failure is None else "Web运行失败，"
            assert text.count("ERROR rdp.api.production " + expected) == 1
            assert text.count("ERROR rdp.api.production Web结束运行：失败退出 exit_code=1") == 1
        finally:
            event.remove(runtime.engine, "engine_disposed", disposed)


def test_defect_report_failure_is_complete() -> None:
    """验证契约：数据库写入失败但线程已结束也算排空，不能永久阻挡引擎关闭或重记原报错。"""
    app = FastAPI()
    report = TrackedReport(app, Mock(side_effect=OSError("写入失败")))
    with pytest.raises(OSError):
        report.run()
    assert drain_error_reports(app, timeout_s=0) is True
    report.cancel_if_pending()


def test_report_integration(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """请求报告必须在提交线程前登记，提交失败后清理并保留原报错行为。"""
    import asyncio

    from account_api_support import request_for
    from ops_support import NOW

    from rdp.api import create_app
    from rdp.api.errors import build_problem, report_error_with_database
    from rdp.infra.logging import log_context

    runtime = _runtime(tmp_path)
    app = create_app(None, database=runtime.engine)
    request = request_for(app)
    observed: list[bool] = []

    async def submit(*_args: object, **_kwargs: object) -> None:
        observed.append(drain_error_reports(app, timeout_s=0))
        raise RuntimeError("模拟线程提交失败")

    monkeypatch.setattr(asyncio, "to_thread", submit)
    try:
        with log_context(request_id="123456789abc4def8123456789abcdef"):
            error = DefectError()
            asyncio.run(
                report_error_with_database(
                    request, error, build_problem(request, error), occurred_at=NOW
                )
            )
        assert observed == [False]
        assert drain_error_reports(app, timeout_s=0) is True
    finally:
        runtime.engine.dispose()


@pytest.mark.parametrize("failed", (False, True))
def test_web_lifecycle_logs(tmp_path: Path, failed: bool) -> None:
    """运行器调用前已有带版本的INFO，正常/失败结束分别记录INFO/ERROR及实际退出码。"""
    runtime = _runtime(tmp_path)
    reached: list[bool] = []

    def runner(app: FastAPI, **_options: Unpack[UvicornOptions]) -> None:
        text = (runtime.paths.logs / "web.log").read_text()
        assert " INFO rdp.api.production Web开始运行" in text
        assert 'platform_version="0.1.0 (aaaaaaa)"' in text
        reached.append(True)
        if failed:
            raise RuntimeError("模拟运行失败")

    assert start_web(runtime, runner=runner) == (1 if failed else 0)
    assert reached == [True]
    lines = (runtime.paths.logs / "web.log").read_text().splitlines()
    starts = [line for line in lines if "Web开始运行" in line]
    ends = [line for line in lines if "Web结束运行" in line]
    assert len(starts) == len(ends) == 1
    level, code = ("ERROR", 1) if failed else ("INFO", 0)
    assert f" {level} rdp.api.production " in ends[0]
    assert f"exit_code={code}" in ends[0]
