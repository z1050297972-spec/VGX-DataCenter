"""第 11 张 version 契约清单；只用临时目录和可注入依赖，不触碰真实部署或服务。"""

from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import replace
from importlib.metadata import PackageNotFoundError
from pathlib import Path
from threading import Event, Thread
from typing import cast

import pytest
from account_api_support import ApiCase, add_actor, api_case, request_for
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx import Client
from jobs_api_support import job_api_case
from jobs_scheduling_execution_support import scheduling_case
from jobs_storage_support import NOW
from pydantic import SecretStr
from sqlalchemy import Engine, event

from rdp.api import create_app
from rdp.api.version import configure_version, get_version
from rdp.infra.config import PlatformConfig
from rdp.infra.db.connection import session_scope
from rdp.infra.diagnostics import ConflictError, DefectError, ExternalError, InputError
from rdp.infra.state import state_paths
from rdp.infra.version import DeploymentLayout, deployment_layout, read_platform_version
from rdp.jobs.errors import JobNotFoundError
from rdp.jobs.execution import recover_job
from rdp.jobs.records import StateChange, claim_job, transition_job
from rdp.jobs.scheduling import Scheduler
from rdp.jobs.types import JobState, WorkerHeartbeat
from rdp.jobs.versioning import record_execution_version
from rdp.jobs.worker import run_loop


def test_layout_independent_of_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """验证契约：部署布局来自src/rdp包位置，切换cwd不改变dist/build_info；支持中文空格路径。"""
    root = tmp_path / "部署 中文"
    package = root / "src/rdp/__init__.py"
    monkeypatch.chdir(tmp_path)
    layout = deployment_layout(package)
    assert layout.root == root
    assert layout.web_dist == root / "src/web/dist"
    assert layout.build_info == root / "rdp-build.json"
    monkeypatch.chdir(tmp_path.parent)
    assert deployment_layout(package) == layout


def test_invalid_layout(tmp_path: Path) -> None:
    """验证契约：相对路径或wheel/site-packages布局明确拒绝，不扫描父目录猜另一个仓库。"""
    for path in (
        Path("src/rdp/__init__.py"),
        tmp_path / "site-packages/rdp/__init__.py",
        tmp_path / "src/other/__init__.py",
        tmp_path / "src/rdp/wrong.py",
    ):
        with pytest.raises(InputError) as caught:
            deployment_layout(path)
        assert "安装脚本" in caught.value.diagnostics[0].next_step


def test_version_format(tmp_path: Path) -> None:
    """验证契约：包版本0.1.0与完整提交组合为0.1.0 (82907a1)，SHA1和SHA256均取前7位，不运行git。"""
    layout = DeploymentLayout(tmp_path, tmp_path / "dist", tmp_path / "rdp-build.json")
    calls: list[str] = []

    def metadata(name: str) -> str:
        calls.append(name)
        return "0.1.0"

    for length in (40, 64):
        layout.build_info.write_text('{"commit":"82907a1' + "b" * (length - 7) + '"}')
        assert read_platform_version(layout, package_version=metadata) == "0.1.0 (82907a1)"
    assert calls == ["rdp", "rdp"]


def test_missing_build_info(tmp_path: Path) -> None:
    """验证契约：M2：构建信息缺失时输出包版本 (未知)，不把工作目录HEAD当作提交。"""
    layout = DeploymentLayout(tmp_path, tmp_path / "dist", tmp_path / "absent.json")
    assert read_platform_version(layout, package_version=lambda _: "0.1.0") == "0.1.0 (未知)"
    assert not layout.build_info.exists()


def test_metadata_missing(tmp_path: Path) -> None:
    """验证契约：PackageNotFoundError显示未知包版本；其他元数据回调异常/非字符串属于DefectError。"""
    layout = DeploymentLayout(tmp_path, tmp_path / "dist", tmp_path / "absent.json")

    def missing(_: str) -> str:
        raise PackageNotFoundError("rdp")

    assert read_platform_version(layout, package_version=missing) == "未知 (未知)"

    def broken(_: str) -> str:
        raise RuntimeError("metadata fault")

    with pytest.raises(DefectError) as caught:
        read_platform_version(layout, package_version=broken)
    assert isinstance(caught.value.__cause__, RuntimeError)
    with pytest.raises(DefectError):
        read_platform_version(layout, package_version=lambda _: cast(str, 7))


def test_build_info_invalid(tmp_path: Path) -> None:
    """验证契约：坏JSON、未知字段、缺commit、非40/64位小写十六进制、超过4096字节拒绝，读取有界。"""
    layout = DeploymentLayout(tmp_path, tmp_path / "dist", tmp_path / "build.json")
    for content in (
        b"{",
        b"[]",
        b"{}",
        b'{"commit":7}',
        b'{"commit":"a"}',
        b'{"commit":"' + b"A" * 40 + b'"}',
        b'{"commit":"' + b"a" * 40 + b'","extra":1}',
        b" " * 4097,
        b"\xff",
    ):
        layout.build_info.write_bytes(content)
        with pytest.raises(InputError):
            read_platform_version(layout, package_version=lambda _: "0.1.0")


def test_build_info_permission(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """验证契约：文件存在但无权限/其他I/O报ExternalError，不静默变成未知。"""
    layout = DeploymentLayout(tmp_path, tmp_path / "dist", tmp_path / "build.json")
    for fault in (PermissionError("denied"), OSError("disk failed")):

        def fail(*_args: object, failure: OSError = fault, **_kwargs: object) -> None:
            raise failure

        with monkeypatch.context() as patch:
            patch.setattr(Path, "open", fail)
            with pytest.raises(ExternalError) as caught:
                read_platform_version(layout, package_version=lambda _: "0.1.0")
        assert caught.value.__cause__ is fault


def test_version_text_bounds(tmp_path: Path) -> None:
    """验证契约：版本文字控制字符或最终超过128码点拒绝，合法最大边界保留，不截断包版本。"""
    layout = DeploymentLayout(tmp_path, tmp_path / "dist", tmp_path / "build.json")
    assert (
        read_platform_version(layout, package_version=lambda _: "版" * 123)
        == "版" * 123 + " (未知)"
    )
    for version in ("版" * 124, "x\n", "x\x00", "x\x7f", "x\x85", "x\u2028", "x\u2029"):
        with pytest.raises(InputError):
            read_platform_version(layout, package_version=lambda _, value=version: value)


def test_api_version(tmp_path: Path) -> None:
    """验证契约：真实应用GET /api/version只读返回注入版本，路径排在API兜底前；健康响应保持原状。"""
    with _version_case(tmp_path) as case:
        assert case.login().status_code == 200
        response = case.client.get("/api/version")
        assert response.status_code == 200
        assert response.json() == {"version": "0.1.0 (82907a1)"}
        assert case.client.get("/api/health").json() == {"status": "ok"}


def test_api_authentication(tmp_path: Path) -> None:
    """验证契约：版本接口沿用认证边界：未登录401、未完成改密403、完成改密成员/管理员200，不增加公开白名单。"""
    with _version_case(tmp_path) as case:
        assert case.client.get("/api/version").status_code == 401
        add_actor(case, ready=False)
        assert case.login("member").status_code == 200
        assert case.client.get("/api/version").status_code == 403
        case.client.cookies.clear()
        assert case.login().status_code == 200
        assert case.client.get("/api/version").status_code == 200
        add_actor(case, name="ready", ready=True)
        case.client.cookies.clear()
        assert case.login("ready", SecretStr("member-updated-value")).status_code == 200
        assert case.client.get("/api/version").status_code == 200


def test_api_bad_configuration() -> None:
    """验证契约：重复装配、已启动app、无版本快照或非法版本归DefectError；请求不读取磁盘。"""
    app = FastAPI()
    configure_version(app, version="v1")
    with pytest.raises(DefectError):
        configure_version(app, version="v2")
    running = FastAPI()
    with TestClient(running), pytest.raises(DefectError):
        configure_version(running, version="v1")
    for value in ("", "x" * 129, "v\n", "v\x85"):
        with pytest.raises(DefectError):
            create_app(None, database=None, platform_version=value)
    with pytest.raises(DefectError):
        get_version(request_for(FastAPI()))
    app.state.platform_version = 42
    with pytest.raises(DefectError):
        get_version(request_for(app))


def test_openapi_version_schema() -> None:
    """验证契约：版本路径和VersionResponse出现在离线OpenAPI，生成客户端从同一schema读取，不手写响应结构。"""
    schema = create_app(None, database=None).openapi()
    operation = schema["paths"]["/api/version"]["get"]
    assert operation["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/VersionResponse"
    }
    assert operation["security"] == [{"SessionCookie": []}]
    response = schema["components"]["schemas"]["VersionResponse"]
    assert response["required"] == ["version"]
    assert response["properties"]["version"]["maxLength"] == 128


def test_job_claim_version(tmp_path: Path) -> None:
    """验证契约：M2：实际领取事务写入worker启动版本；Web提交不填版本，排队期间升级使用新worker快照。"""
    with scheduling_case(tmp_path) as case:
        case.add(71, "a")
        assert case.get(71).platform_version is None
        dependencies = replace(case.dependencies, platform_version="0.2.0 (abcdef0)")
        scheduler = Scheduler(dependencies, case.resources, recovered=())
        work = scheduler.claim_next()
        assert work is not None
        assert work.record.platform_version == "0.2.0 (abcdef0)"
        assert case.get(71).platform_version == "0.2.0 (abcdef0)"
        assert case.get(71).state is JobState.RUNNING


def test_job_recovery_version(tmp_path: Path) -> None:
    """验证契约：恢复准备不改版本，恢复后实际领取更新到新版本；终态、取消和查询不改写。"""
    with scheduling_case(tmp_path) as case:
        case.add(71, "a", JobState.RUNNING)
        with session_scope(case.dependencies.engine) as session:
            record_execution_version(session, 71, version="old (1111111)")
        dependencies = replace(case.dependencies, platform_version="new (2222222)")
        recovered = recover_job(71, dependencies)
        assert recovered is not None and recovered.record.platform_version == "old (1111111)"
        scheduler = Scheduler(dependencies, case.resources, recovered=(recovered,))
        work = scheduler.claim_next()
        assert work is not None and work.record.platform_version == "new (2222222)"
        with session_scope(case.dependencies.engine) as session:
            transition_job(session, 71, StateChange(JobState.RUNNING, JobState.CANCELLING, NOW))
            transition_job(session, 71, StateChange(JobState.CANCELLING, JobState.CANCELLED, NOW))
        assert case.get(71).platform_version == "new (2222222)"


def test_job_claim_rollback(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """验证契约：领取失败回滚状态/资源/版本，未启动领取退回恢复原版本，不记录未运行版本。"""

    def fail_write(*args: object) -> None:
        statement = args[2]
        if isinstance(statement, str) and "UPDATE jobs SET platform_version" in statement:
            raise RuntimeError("模拟领取写入失败")

    def fail_start(_thread: Thread) -> None:
        raise RuntimeError("模拟线程无法启动")

    for state in (JobState.QUEUED, JobState.RUNNING):
        with scheduling_case(tmp_path / state.value) as case:
            case.add(71, "a", state)
            old = "old (1111111)" if state is JobState.RUNNING else None
            if old is not None:
                with session_scope(case.dependencies.engine) as session:
                    record_execution_version(session, 71, version=old)
            dependencies = replace(case.dependencies, platform_version="new (2222222)")
            if state is JobState.QUEUED:
                event.listen(Engine, "before_cursor_execute", fail_write)
                try:
                    with pytest.raises(RuntimeError):
                        Scheduler(dependencies, case.resources, recovered=()).claim_next()
                finally:
                    event.remove(Engine, "before_cursor_execute", fail_write)
                assert case.get(71).state is JobState.QUEUED
                assert case.get(71).platform_version is None
                assert case.resources.pool.claims() == ()
            with monkeypatch.context() as patch:
                patch.setattr(Thread, "start", fail_start)
                result = run_loop(
                    dependencies,
                    Event(),
                    WorkerHeartbeat("00000000000040008000000000000001", 123, NOW, NOW),
                )
            assert result.code == 1
            assert case.get(71).state is state
            assert case.get(71).platform_version == old
            assert case.resources.pool.claims() == ()


def test_job_version_errors(tmp_path: Path) -> None:
    """验证契约：不存在job报JobNotFoundError，非running报ConflictError，非法编号/版本或只读Session报DefectError，I/O失败整体回滚。"""
    with scheduling_case(tmp_path) as case:
        case.add(71, "a")
        with session_scope(case.dependencies.engine) as session:
            with pytest.raises(JobNotFoundError):
                record_execution_version(session, 999, version="v1")
            with pytest.raises(ConflictError):
                record_execution_version(session, 71, version="v1")
            for number in (0, -1, True):
                with pytest.raises(DefectError):
                    record_execution_version(session, number, version="v1")
        case.add(72, "b", JobState.RUNNING)
        for version in ("", "x" * 129, "x\n", cast(str, 7)):
            with pytest.raises(DefectError), session_scope(case.dependencies.engine) as session:
                record_execution_version(session, 72, version=version)
        with (
            session_scope(case.dependencies.engine, read_only=True) as session,
            pytest.raises(DefectError),
        ):
            record_execution_version(session, 72, version="v1")
        assert case.get(72).platform_version is None


def test_job_resubmit_version(tmp_path: Path) -> None:
    """验证契约：重新提交的新作业不继承原版本；旧作业完成后的版本永久保留。"""
    with job_api_case(tmp_path) as case:
        case.login()
        response = case.client.post("/api/jobs/example", json={"steps": 1, "interval_ms": 0})
        assert response.status_code == 201
        number = int(response.json()["job_id"])
        assert response.json()["platform_version"] is None
        paths = state_paths(PlatformConfig(state_dir=tmp_path), ("示例：数数",))
        with session_scope(case.engine) as session:
            claim_job(session, number, now=NOW, paths=paths, gpu_index=None)
            record_execution_version(session, number, version="old (1111111)")
            transition_job(session, number, StateChange(JobState.RUNNING, JobState.COMPLETED, NOW))
        response = case.client.post(f"/api/jobs/{number}/resubmit")
        assert response.status_code == 201
        assert response.json()["platform_version"] is None
        assert int(response.json()["job_id"]) != number
        assert case.client.get(f"/api/jobs/{number}").json()["platform_version"] == "old (1111111)"


@contextmanager
def _version_case(root: Path) -> Generator[ApiCase]:
    """在真实认证应用注入版本，全部数据库与客户端由测试上下文回收。"""
    with api_case(root) as base:
        app = create_app(
            None, database=base.engine, clock=base.clock, platform_version="0.1.0 (82907a1)"
        )
        app.state.account_service = base.service
        with TestClient(
            app, raise_server_exceptions=False, headers={"Origin": "http://testserver"}
        ) as client:
            yield replace(base, app=app, client=cast(Client, client))
