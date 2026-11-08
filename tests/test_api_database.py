"""工单 05 契约测试；只在 tmp_path 的假状态目录验证。"""

import asyncio
import json
import logging
import shutil
import sqlite3
import threading
import time
import traceback
from collections.abc import Generator, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, cast

import httpx
import pytest
from auth_support import authenticated_client
from db_support import sqlite_connection
from fastapi import Depends, FastAPI, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from rdp.api import create_app
from rdp.api.database import configure_database, get_read_session, get_session
from rdp.api.error_details import (
    InvalidErrorIdentifierError,
    get_error_details,
)
from rdp.api.errors import build_problem, format_exception_report, report_error_with_database
from rdp.infra.config import PlatformConfig
from rdp.infra.db.connection import create_database_engine, session_scope
from rdp.infra.db.migration import migrate, migration_config
from rdp.infra.db.records import ErrorRecord, find_error, write_error
from rdp.infra.diagnostics import ConflictError, DefectError, Diagnostic, ExternalError, InputError
from rdp.infra.logging import log_context
from rdp.infra.state import initialize_state, state_paths


@pytest.fixture
def engine(tmp_path: Path) -> Generator[Engine, None, None]:
    """只在临时状态目录迁移数据库，所有调用结束后回收本测试引擎。"""
    paths = state_paths(PlatformConfig(state_dir=tmp_path), ())
    initialize_state(paths)
    migrate(paths, now=datetime(2026, 10, 24, tzinfo=UTC))
    value = create_database_engine(paths.database)
    try:
        yield value
    finally:
        value.dispose()


def _record(
    identifier: str = "123456789abc4def8abc123456789abc", kind: str = "request"
) -> ErrorRecord:
    """固定发生时间及安全报告，所有预期值独立于格式化实现。"""
    return ErrorRecord.model_validate(
        dict(
            error_id=identifier,
            source_kind=kind,
            occurred_at=datetime(2026, 10, 1, 2, 0, 0, 123456, tzinfo=UTC),
            category="defect",
            summary="平台内部错误",
            report="TypeError: 示例\n",
        )
    )


def _route(app: FastAPI, endpoint: Any, *, response_model: Any = None) -> None:
    """测试路由排在 API 兜底之前；不改变生产路由和配置。"""
    app.add_api_route("/api/probe", endpoint, methods=["GET"], response_model=response_model)
    app.router.routes.insert(0, app.router.routes.pop())


def _api_fault(engine: Engine, code: int, status: int, *, root: Path) -> None:
    """驱动执行边界注入故障，验证真实依赖、仓储和 HTTP 错误映射，不 mock 领域函数。"""
    app = create_app(None, database=engine)

    def fail(*args: Any, **kwargs: Any) -> None:
        if "error_reports" in args[2]:
            error = sqlite3.OperationalError("驱动故障")
            error.sqlite_errorcode = code
            raise error

    event.listen(engine, "before_cursor_execute", fail)
    try:
        with _client(app, root=root) as client:
            response = client.get("/api/errors/1")
        assert response.status_code == status
        assert response.headers["content-type"] == "application/problem+json"
    finally:
        event.remove(engine, "before_cursor_execute", fail)


def _request(app: FastAPI) -> Request:
    """构造不带查询、凭据或请求体的内存 HTTP scope。"""
    return Request(
        {"type": "http", "method": "GET", "path": "/api/probe", "headers": [], "app": app}
    )


def test_database_argument_required() -> None:
    """验证 B1：省略 database 必须在签名层面抛 TypeError，不能默认为无数据库。"""
    with pytest.raises(TypeError, match="database"):
        cast(Any, create_app)(None)


def test_configure_success(engine: Engine) -> None:
    """验证契约：configure_database 校验版本后绑定 app.state，引擎由调用者 dispose，不自动迁移。"""
    app = FastAPI()
    assert configure_database(app, engine) is None
    assert app.state.database_engine is engine
    with session_scope(engine, read_only=True) as session:
        assert session.execute(text("SELECT count(*) FROM error_reports")).scalar_one() == 0


def test_configure_version(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """验证契约：验收 7：create_app(database=engine) 在返回前拒绝缺失/无版本/落后/领先/未知库，提示先运行 migrate。"""
    source = migration_config().get_main_option("script_location")
    assert source is not None
    package = tmp_path / "newer_code"
    shutil.copytree(source, package / "migrations")
    (package / "migrations" / "versions" / "v0021_test.py").write_text(
        "revision = '0021_test'\ndown_revision = '0020_dataset_collection'\n"
    )
    for case in ("missing", "unversioned", "behind", "future_or_unknown"):
        paths = state_paths(PlatformConfig(state_dir=tmp_path / case), ())
        initialize_state(paths)
        if case == "unversioned":
            with sqlite_connection(paths.database):
                pass
        elif case in ("behind", "future_or_unknown"):
            migrate(paths, now=datetime(2026, 10, 24, tzinfo=UTC))
            if case == "future_or_unknown":
                with sqlite_connection(paths.database) as connection:
                    connection.execute("UPDATE alembic_version SET version_num='9999_future'")
        engine = create_database_engine(paths.database)
        try:
            with monkeypatch.context() as patch:
                if case == "behind":
                    patch.setattr("rdp.infra.db.migration.__file__", str(package / "migration.py"))
                with pytest.raises(InputError) as caught:
                    create_app(None, database=engine)
            assert any("先运行 migrate" in item.next_step for item in caught.value.diagnostics), (
                case
            )
            if case == "missing":
                assert not paths.database.exists()
        finally:
            engine.dispose()


def test_configure_busy(engine: Engine, monkeypatch: pytest.MonkeyPatch) -> None:
    """验证契约：configure_database 版本读取冲突传 ConflictError，失败不绑定。"""

    def fail(*args: Any, **kwargs: Any) -> Any:
        error = sqlite3.OperationalError("锁故障")
        error.sqlite_errorcode = sqlite3.SQLITE_BUSY
        raise error

    monkeypatch.setattr(sqlite3, "connect", fail)
    app = FastAPI()
    with pytest.raises(ConflictError):
        configure_database(app, engine)
    assert not hasattr(app.state, "database_engine")


def test_configure_io(engine: Engine, monkeypatch: pytest.MonkeyPatch) -> None:
    """验证契约：configure_database 读取权限/I/O 传 ExternalError，失败不关闭调用者引擎。"""

    def fail(*args: Any, **kwargs: Any) -> Any:
        raise PermissionError("权限故障")

    monkeypatch.setattr(sqlite3, "connect", fail)
    app = FastAPI()
    with pytest.raises(ExternalError):
        configure_database(app, engine)
    assert not hasattr(app.state, "database_engine")


def test_configure_defect(engine: Engine) -> None:
    """验证契约：已启动/已绑定 app、错误引擎或坏迁移图给 DefectError，不替换引擎。"""
    app = FastAPI()
    configure_database(app, engine)
    with pytest.raises(DefectError):
        configure_database(app, engine)
    unmanaged = create_engine("sqlite://")
    try:
        with pytest.raises(DefectError):
            configure_database(FastAPI(), unmanaged)
    finally:
        unmanaged.dispose()
    started = FastAPI()
    started.middleware_stack = started.build_middleware_stack()
    with pytest.raises(DefectError):
        configure_database(started, engine)


def test_factory_compat(tmp_path: Path) -> None:
    """验证契约：无数据库工厂仍可健康查询及离线 OpenAPI，在线文档关闭；无引擎详情为诊断502，不碰真实home。"""
    app = create_app(None, database=None)
    assert "/api/health" in app.openapi()["paths"]
    with _client(app, root=tmp_path) as client:
        assert client.get("/api/health").status_code == 200
        for path in ("/docs", "/redoc", "/openapi.json"):
            assert client.get(path).status_code == 404
        response = client.get("/api/errors/1")
    assert response.status_code == 502
    assert response.json()["diagnostics"][0]["actual"] == "数据库未启用"
    assert not list(tmp_path.iterdir())


def test_factory_schema(tmp_path: Path) -> None:
    """验证契约：GET /api/errors/{error_id} 和 ErrorRecord schema 出现在 OpenAPI，生成类型由 make api-types 产出。"""
    schema = create_app(None, database=None).openapi()
    assert "ErrorRecord" in schema["components"]["schemas"]
    assert (
        schema["paths"]["/api/errors/{error_id}"]["get"]["responses"]["200"]["content"][
            "application/json"
        ]["schema"]["$ref"]
        == "#/components/schemas/ErrorRecord"
    )


def test_factory_lifecycle(tmp_path: Path, engine: Engine) -> None:
    """验证契约：工厂不 dispose 外部引擎、不配置 logger；调用者完成请求和在途报告后 dispose。"""
    before = tuple(logging.getLogger().handlers)
    with _client(create_app(None, database=engine), root=tmp_path) as client:
        assert client.get("/api/health").status_code == 200
    with session_scope(engine) as session:
        assert session.execute(text("SELECT 1")).scalar_one() == 1
    assert tuple(logging.getLogger().handlers) == before


def test_session_cached(tmp_path: Path, engine: Engine) -> None:
    """验证契约：同请求 Depends(get_session,scope='function') 缓存同一 Session，不同请求不同会话。"""
    app = create_app(None, database=engine)
    sessions: list[Session] = []

    def probe(
        first: Annotated[Session, Depends(get_session, scope="function")],
        second: Annotated[Session, Depends(get_session, scope="function")],
    ) -> dict[str, bool]:
        sessions.append(first)
        return {"same": first is second}

    _route(app, probe)
    with _client(app, root=tmp_path) as client:
        assert client.get("/api/probe").json() == {"same": True}
        assert client.get("/api/probe").json() == {"same": True}
    assert sessions[0] is not sessions[1]


def test_session_commit_before_send(tmp_path: Path, engine: Engine) -> None:
    """验证契约：FastAPI 同步 yield 的 function scope 在 http.response.start 之前提交，提交失败可返回统一错误。"""
    app = create_app(None, database=engine)

    def probe(
        session: Annotated[Session, Depends(get_session, scope="function")],
    ) -> StreamingResponse:
        write_error(session, _record("7", "job"))

        def chunks() -> Generator[bytes, None, None]:
            with session_scope(engine, read_only=True) as reader:
                assert find_error(reader, "7") is not None
            yield b"committed"

        return StreamingResponse(chunks())

    _route(app, probe)
    with _client(app, root=tmp_path) as client:
        assert client.get("/api/probe").text == "committed"


def test_session_route_exception(tmp_path: Path, engine: Engine) -> None:
    """验证契约：路由异常传回 yield，回滚后无业务记录，原四类异常身份保持。"""
    app = create_app(None, database=engine)

    def probe(session: Annotated[Session, Depends(get_session, scope="function")]) -> None:
        write_error(session, _record("7", "job"))
        get_error_details("8", session)

    _route(app, probe)
    with _client(app, root=tmp_path) as client:
        assert client.get("/api/probe").status_code == 404
    with session_scope(engine, read_only=True) as reader:
        assert find_error(reader, "7") is None


def test_session_serialization_exception(tmp_path: Path, engine: Engine) -> None:
    """验证契约：响应序列化失败同样回滚，错误边界可另开事务记报错。"""
    app = create_app(None, database=engine)

    def probe(
        session: Annotated[Session, Depends(get_session, scope="function")],
    ) -> dict[str, str]:
        write_error(session, _record("7", "job"))
        return {"wrong": "response"}

    _route(app, probe, response_model=int)
    with _client(app, root=tmp_path) as client:
        assert client.get("/api/probe").status_code == 500
    with session_scope(engine, read_only=True) as reader:
        assert find_error(reader, "7") is None


def test_session_no_database(tmp_path: Path) -> None:
    """验证契约：两种会话依赖在无引擎时 ExternalError，带数据库未启用诊断。"""
    for dependency in (get_session, get_read_session):
        request = _request(create_app(None, database=None))
        with pytest.raises(ExternalError):
            next(dependency(request))


def test_session_database_errors(tmp_path: Path, engine: Engine) -> None:
    """验证契约：依赖对 InputError/ConflictError/ExternalError/DefectError 原分类传播，不重复报告。"""
    for code, status in ((26, 400), (5, 409), (13, 502), (1, 500)):
        _api_fault(engine, code, status, root=tmp_path)


def test_session_cleanup(engine: Engine) -> None:
    """验证契约：依赖清理失败保留主异常，关闭失败连接；取消不吞，已运行同步 SQL 不承诺立即中止。"""
    request = _request(create_app(None, database=engine))
    dependency = get_session(request)
    next(dependency)
    error = KeyboardInterrupt()
    with pytest.raises(KeyboardInterrupt) as caught:
        dependency.throw(error)
    assert caught.value is error
    with session_scope(engine):
        pass


def test_session_thread(tmp_path: Path, engine: Engine) -> None:
    """验证契约：同步会话进入/查询/退出顺序跨线程不并发，SQL 不在事件循环执行。"""
    app = create_app(None, database=engine)
    thread_ids: list[int] = []

    def probe(
        session: Annotated[Session, Depends(get_session, scope="function")],
    ) -> dict[str, bool]:
        thread_ids.append(threading.get_ident())
        session.execute(text("SELECT 1"))
        return {"ok": True}

    _route(app, probe)
    with _client(app, root=tmp_path) as client:
        assert client.get("/api/probe").status_code == 200
    assert thread_ids and thread_ids[0] != threading.get_ident()


def test_read_session(tmp_path: Path, engine: Engine) -> None:
    """验证契约：get_read_session 使用只读 BEGIN/query_only，查询与 WAL 写入并发，响应发出前释放。"""
    app = create_app(None, database=engine)

    def probe(
        session: Annotated[Session, Depends(get_read_session, scope="function")],
    ) -> dict[str, int]:
        return {"readonly": session.execute(text("PRAGMA query_only")).scalar_one()}

    _route(app, probe)
    with _client(app, root=tmp_path) as client:
        assert client.get("/api/probe").json() == {"readonly": 1}


def test_read_exception(engine: Engine) -> None:
    """验证契约：只读依赖路由异常回滚关闭且原样传播，尝试写入给 DefectError。"""
    request = _request(create_app(None, database=engine))
    dependency = get_read_session(request)
    session = next(dependency)
    try:
        with pytest.raises(SQLAlchemyError) as write_failure:
            session.execute(text("CREATE TABLE forbidden (value INTEGER)"))
        with pytest.raises(DefectError) as caught:
            dependency.throw(write_failure.value)
        assert caught.value.diagnostics
    finally:
        dependency.close()
    with session_scope(engine, read_only=True) as reader:
        assert (
            reader.execute(
                text("SELECT count(*) FROM sqlite_master WHERE name='forbidden'")
            ).scalar_one()
            == 0
        )


def test_details_request(tmp_path: Path, engine: Engine) -> None:
    """验证契约：get_error_details 返回请求编号对应完整时间/类别/摘要/报告/来源，UTC 微秒不丢。"""
    with session_scope(engine) as session:
        write_error(session, _record())
    with _client(create_app(None, database=engine), root=tmp_path) as client:
        response = client.get("/api/errors/" + _record().error_id)
    assert response.status_code == 200
    assert response.json() == _record().model_dump(mode="json")


def test_details_job(tmp_path: Path, engine: Engine) -> None:
    """验证契约：get_error_details 支持规范作业编号，不放宽 ProblemResponse.error_id。"""
    with session_scope(engine) as session:
        write_error(session, _record("7", "job"))
    with _client(create_app(None, database=engine), root=tmp_path) as client:
        response = client.get("/api/errors/7")
    assert response.status_code == 200 and response.json()["source_kind"] == "job"


def test_details_not_found(tmp_path: Path, engine: Engine) -> None:
    """验证契约：详情查不到或过期为 InputError 的 404 子类，诊断含编号、规则、实际、期望、后果、下一步。"""
    with _client(create_app(None, database=engine), root=tmp_path) as client:
        response = client.get("/api/errors/7")
    assert response.status_code == 404
    diagnostic = response.json()["diagnostics"][0]
    assert diagnostic["objects"] == [{"key": "error_id", "value": "7"}]
    assert all(
        diagnostic[field] for field in ("rule", "actual", "expected", "consequence", "next_step")
    )


def test_details_invalid(tmp_path: Path, engine: Engine) -> None:
    """验证契约：HTTP 编号形状非法为统一 422 且不回显原值，作业超 2^63-1/直接调用非法值为 InvalidErrorIdentifierError。"""
    with _client(create_app(None, database=engine), root=tmp_path) as client:
        for value in ("secret-invalid", "01", "9223372036854775808"):
            response = client.get("/api/errors/" + value)
            assert response.status_code == 422
            # 服务端随机 uuid 可能碰巧含短串 01；只检查承载原值的响应内容，避免误报。
            payload = response.json()
            payload.pop("error_id")
            assert value not in json.dumps(payload)
    with (
        session_scope(engine, read_only=True) as session,
        pytest.raises(InvalidErrorIdentifierError),
    ):
        get_error_details("bad", session)


def test_details_corrupt(tmp_path: Path, engine: Engine) -> None:
    """验证契约：详情读损坏 UTC/数据库为 InputError，不返回半份详情。"""
    with session_scope(engine) as session:
        write_error(session, _record("7", "job"))
        session.execute(text("UPDATE error_reports SET occurred_at='bad'"))
    with _client(create_app(None, database=engine), root=tmp_path) as client:
        assert client.get("/api/errors/7").status_code == 400


def test_details_busy(tmp_path: Path, engine: Engine) -> None:
    """验证契约：详情读取锁冲突为 ConflictError 409。"""
    _api_fault(engine, 5, 409, root=tmp_path)


def test_details_external(tmp_path: Path, engine: Engine) -> None:
    """验证契约：详情权限/I/O 故障为 ExternalError 502。"""
    _api_fault(engine, 13, 502, root=tmp_path)


def test_details_defect(tmp_path: Path, engine: Engine) -> None:
    """验证契约：详情 SQL/映射错误为 DefectError 500。"""
    _api_fault(engine, 1, 500, root=tmp_path)


def test_details_auth(tmp_path: Path, engine: Engine) -> None:
    """验证契约：本票查询无登录依赖；第 06 张须允许所有登录账号，OpenAPI/函数文档明确临时边界。"""
    with session_scope(engine) as session:
        write_error(session, _record("7", "job"))
    with _client(create_app(None, database=engine), root=tmp_path) as client:
        assert client.get("/api/errors/7").status_code == 200
    assert "第 06 张" in (get_error_details.__doc__ or "")


def test_report_unknown(tmp_path: Path, engine: Engine) -> None:
    """验证契约：验收 8：未知接口异常返回 500 后待请求处理完成，用 X-Request-ID 可查询唯一完整报错。"""
    app = create_app(None, database=engine)

    def probe() -> None:
        raise RuntimeError("安全演示异常")

    _route(app, probe)
    with _client(app, root=tmp_path) as client:
        response = client.get("/api/probe")
        assert response.status_code == 500
        details = client.get("/api/errors/" + response.headers["X-Request-ID"])
    assert details.status_code == 200
    assert "RuntimeError: 安全演示异常" in details.json()["report"]


def test_report_explicit(tmp_path: Path, engine: Engine, caplog: pytest.LogCaptureFixture) -> None:
    """验证契约：DefectError 由 handle_error 报告一次；未知异常由 ErrorBoundary 报告一次，无 uvicorn 重复 traceback。"""
    app = create_app(None, database=engine)

    def probe() -> None:
        raise DefectError()

    _route(app, probe)
    with _client(app, root=tmp_path) as client:
        response = client.get("/api/probe")
        assert client.get("/api/errors/" + response.headers["X-Request-ID"]).status_code == 200
    records = [record for record in caplog.records if record.name == "rdp.api.errors"]
    assert len(records) == 1 and records[0].levelno == logging.ERROR


def test_report_same_text(tmp_path: Path, engine: Engine, caplog: pytest.LogCaptureFixture) -> None:
    """验证契约：报告只格式化一次，日志 traceback 段与表字段逐字一致，不额外附请求或 SQL 数据。"""
    app = create_app(None, database=engine)

    def probe() -> None:
        raise RuntimeError("安全异常链")

    _route(app, probe)
    with _client(app, root=tmp_path) as client:
        response = client.get("/api/probe")
    with session_scope(engine, read_only=True) as session:
        record = find_error(session, response.headers["X-Request-ID"])
    assert record is not None
    messages = [item.getMessage() for item in caplog.records if item.name == "rdp.api.errors"]
    assert len(messages) == 1 and messages[0].endswith(record.report)
    assert record.report.count("RuntimeError: 安全异常链") == 1


def test_report_nondefect(tmp_path: Path, engine: Engine, caplog: pytest.LogCaptureFixture) -> None:
    """验证契约：输入/冲突/外部/参数校验及无引擎仅写运行日志，不写报错表。"""
    error_types = {"input": InputError, "conflict": ConflictError, "external": ExternalError}

    def probe(kind: str) -> None:
        if kind == "defect":
            raise DefectError()
        diagnostic = Diagnostic.model_validate(
            dict(
                level="error",
                category=kind,
                stage="测试边界",
                source="平台",
                objects=[],
                rule="测试规则",
                actual="条件不满足",
                expected="条件满足",
                consequence="请求未完成",
                next_step="修正条件后重试",
            )
        )
        raise error_types[kind]((diagnostic,))

    for database in (engine, None):
        app = create_app(None, database=database)
        _route(app, probe)
        with _client(app, root=tmp_path) as client:
            for kind, status in (("input", 400), ("conflict", 409), ("external", 502)):
                response = client.get("/api/probe", params={"kind": kind})
                assert response.status_code == status
            assert client.get("/api/probe").status_code == 422
            if database is not None:
                assert client.get("/api/errors/7").status_code == 404
            else:
                assert client.get("/api/probe", params={"kind": "defect"}).status_code == 500
        with session_scope(engine, read_only=True) as session:
            assert session.execute(text("SELECT count(*) FROM error_reports")).scalar_one() == 0
    assert not any("完整报错持久化失败" in item.getMessage() for item in caplog.records)


def test_report_reentry(engine: Engine, caplog: pytest.LogCaptureFixture) -> None:
    """验证契约：同请求重复进入报告函数只记一次日志和一条记录，不同请求编号独立。"""
    request = _request(create_app(None, database=engine))
    error = RuntimeError("示例")
    with log_context(request_id=_record().error_id):
        problem = build_problem(request, error)

        async def report_twice() -> None:
            for _ in range(2):
                await report_error_with_database(
                    request, error, problem, occurred_at=datetime(2026, 10, 1, tzinfo=UTC)
                )

        asyncio.run(report_twice())
    assert len([item for item in caplog.records if item.name == "rdp.api.errors"]) == 1
    with session_scope(engine, read_only=True) as session:
        assert session.execute(text("SELECT count(*) FROM error_reports")).scalar_one() == 1


def test_report_independent(tmp_path: Path, engine: Engine) -> None:
    """验证契约：业务 Session 回滚不删除独立报错事务，先释放业务锁再存表。"""
    app = create_app(None, database=engine)

    def probe(session: Annotated[Session, Depends(get_session, scope="function")]) -> None:
        write_error(session, _record("7", "job"))
        raise RuntimeError("事务失败")

    _route(app, probe)
    with _client(app, root=tmp_path) as client:
        response = client.get("/api/probe")
    with session_scope(engine, read_only=True) as session:
        assert find_error(session, "7") is None
        assert find_error(session, response.headers["X-Request-ID"]) is not None


def test_report_failure(tmp_path: Path, engine: Engine, caplog: pytest.LogCaptureFixture) -> None:
    """验证契约：持久化锁超时/磁盘满/调度失败不覆盖原 500；仅额外一条 ERROR，无第二个 traceback、不递归入库。"""
    app = create_app(None, database=engine)

    def probe() -> None:
        raise RuntimeError("原始故障")

    def fail(*args: Any, **kwargs: Any) -> None:
        if args[2].startswith("INSERT"):
            error = sqlite3.OperationalError("磁盘满")
            error.sqlite_errorcode = sqlite3.SQLITE_FULL
            raise error

    _route(app, probe)
    event.listen(engine, "before_cursor_execute", fail)
    try:
        with _client(app, root=tmp_path) as client:
            response = client.get("/api/probe")
        assert response.status_code == 500
        logs = [item.getMessage() for item in caplog.records if item.name == "rdp.api.errors"]
        assert len(logs) == 2
        assert "RuntimeError: 原始故障" in logs[0]
        assert logs[1] == "完整报错持久化失败"
    finally:
        event.remove(engine, "before_cursor_execute", fail)


def test_report_async(engine: Engine) -> None:
    """验证契约：报错 SQL 在 asyncio.to_thread 的独立会话内执行，事件循环仍能处理其他请求。"""
    request = _request(create_app(None, database=engine))
    entered, release = threading.Event(), threading.Event()
    thread_ids: list[int] = []

    def pause(*args: Any, **kwargs: Any) -> None:
        if args[2].startswith("INSERT"):
            thread_ids.append(threading.get_ident())
            entered.set()
            if not release.wait(3):
                raise TimeoutError("测试释放超时")

    event.listen(engine, "before_cursor_execute", pause)

    async def exercise() -> None:
        event_thread = threading.get_ident()
        with log_context(request_id=_record().error_id):
            problem = build_problem(request, RuntimeError("异步故障"))
            task = asyncio.create_task(
                report_error_with_database(
                    request,
                    RuntimeError("异步故障"),
                    problem,
                    occurred_at=datetime(2026, 1, 1, tzinfo=UTC),
                )
            )
            try:
                for _ in range(100):
                    if entered.is_set():
                        break
                    await asyncio.sleep(0.01)
                assert entered.is_set() and not task.done()
                assert thread_ids[0] != event_thread
            finally:
                release.set()
                await asyncio.wait_for(task, timeout=3)
                await asyncio.wait_for(
                    asyncio.get_running_loop().shutdown_default_executor(), timeout=3
                )

    try:
        asyncio.run(exercise())
    finally:
        release.set()
        event.remove(engine, "before_cursor_execute", pause)


def test_report_timeout(engine: Engine, caplog: pytest.LogCaptureFixture) -> None:
    """验证契约：asyncio.wait_for 用 6 秒上限返回，迟到线程可留一条记录但不重复日志，失败回滚，关闭引擎前等待线程。"""
    request = _request(create_app(None, database=engine))
    release = threading.Event()

    def pause(*args: Any, **kwargs: Any) -> None:
        if args[2].startswith("INSERT") and not release.wait(9):
            raise TimeoutError("测试释放超时")

    event.listen(engine, "before_cursor_execute", pause)

    async def exercise() -> None:
        with log_context(request_id=_record().error_id):
            problem = build_problem(request, RuntimeError("超时故障"))
            started = time.monotonic()
            try:
                await report_error_with_database(
                    request,
                    RuntimeError("超时故障"),
                    problem,
                    occurred_at=datetime(2026, 1, 1, tzinfo=UTC),
                )
                assert 5.5 <= time.monotonic() - started <= 8
            finally:
                release.set()
                await asyncio.wait_for(
                    asyncio.get_running_loop().shutdown_default_executor(), timeout=3
                )

    try:
        asyncio.run(exercise())
        assert len([item for item in caplog.records if item.name == "rdp.api.errors"]) == 2
        with session_scope(engine, read_only=True) as session:
            assert find_error(session, _record().error_id) is not None
    finally:
        release.set()
        event.remove(engine, "before_cursor_execute", pause)


def test_report_input(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """验证契约：无时区或 UTC 溢出的 occurred_at 抛 InputError，报告前失败不留半份。"""
    request = _request(create_app(None, database=None))
    with log_context(request_id=_record().error_id):
        problem = build_problem(request, RuntimeError("故障"))
        with pytest.raises(InputError):
            asyncio.run(
                report_error_with_database(
                    request,
                    RuntimeError("故障"),
                    problem,
                    occurred_at=datetime(2026, 1, 1, tzinfo=UTC).replace(tzinfo=None),
                )
            )
    assert not caplog.records


def test_report_identity(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """验证契约：problem 编号不符抛 DefectError，不生成伪造关联号。"""
    request = _request(create_app(None, database=None))
    with log_context(request_id=_record().error_id):
        problem = build_problem(request, RuntimeError("故障"))
    current_id = "abcdef1234564abc9abc123456789abc"
    with log_context(request_id=current_id), pytest.raises(DefectError) as caught:
        asyncio.run(
            report_error_with_database(
                request,
                RuntimeError("故障"),
                problem,
                occurred_at=datetime(2026, 1, 1, tzinfo=UTC),
            )
        )
    assert caught.value.diagnostics
    diagnostic = caught.value.diagnostics[0]
    assert {item.key: item.value for item in diagnostic.objects} == {
        "request_id": current_id,
        "error_id": problem.error_id,
    }
    assert diagnostic.rule == "错误编号必须等于当前请求编号"
    assert current_id in diagnostic.actual and problem.error_id in diagnostic.actual
    assert diagnostic.expected is not None
    assert "相同" in diagnostic.expected
    assert "拒绝报告" in diagnostic.consequence
    assert "请求上下文" in diagnostic.next_step
    assert not caplog.records


def test_report_empty_format(engine: Engine, monkeypatch: pytest.MonkeyPatch) -> None:
    """验证格式化器返回空报告时抛带诊断的 DefectError，且不保存空报错记录。"""
    request = _request(create_app(None, database=engine))

    def empty_format(self: traceback.TracebackException, **kwargs: object) -> Iterator[str]:
        """在标准库格式化边界模拟空输出，不替换平台内部报告函数。"""
        return iter(())

    monkeypatch.setattr(traceback.TracebackException, "format", empty_format)
    with log_context(request_id=_record().error_id):
        error = RuntimeError("安全示例")
        problem = build_problem(request, error)
        with pytest.raises(DefectError) as caught:
            asyncio.run(
                report_error_with_database(
                    request, error, problem, occurred_at=datetime(2026, 1, 1, tzinfo=UTC)
                )
            )
    diagnostic = caught.value.diagnostics[0]
    assert diagnostic.objects[0].value == problem.error_id
    assert diagnostic.rule == "程序缺陷报告必须非空"
    assert diagnostic.actual == "异常格式化结果为空"
    assert diagnostic.expected is not None
    assert "非空" in diagnostic.expected
    assert "未写入报错表" in diagnostic.consequence
    assert "格式化" in diagnostic.next_step
    with session_scope(engine, read_only=True) as session:
        assert find_error(session, problem.error_id) is None


def test_report_boundary_failure(tmp_path: Path) -> None:
    """验证契约：格式化或日志 handler 失败按第 04 张传播 Exception，取消 BaseException 原样传播。"""
    request = _request(create_app(None, database=None))

    class FailingHandler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            raise RuntimeError("日志边界失败")

    logger = logging.getLogger("rdp.api.errors")
    handler = FailingHandler()
    logger.addHandler(handler)
    try:
        with log_context(request_id=_record().error_id):
            problem = build_problem(request, RuntimeError("故障"))
            with pytest.raises(RuntimeError, match="日志边界失败"):
                asyncio.run(
                    report_error_with_database(
                        request,
                        RuntimeError("故障"),
                        problem,
                        occurred_at=datetime(2026, 1, 1, tzinfo=UTC),
                    )
                )
    finally:
        logger.removeHandler(handler)
        handler.close()


def test_report_stream(tmp_path: Path, engine: Engine) -> None:
    """验证契约：响应开始/结束后的缺陷保留已发内容且只存一条；早查可能 404，不自动轮询。"""
    app = create_app(None, database=engine)

    def probe() -> StreamingResponse:
        def chunks() -> Generator[bytes, None, None]:
            yield b"prefix"
            raise RuntimeError("流式故障")

        return StreamingResponse(chunks())

    _route(app, probe)
    with _client(app, root=tmp_path) as client:
        response = client.get("/api/probe")
    assert response.status_code == 200
    with session_scope(engine, read_only=True) as session:
        assert find_error(session, response.headers["X-Request-ID"]) is not None


def test_report_bound(tmp_path: Path) -> None:
    """验证契约：format_exception_report N-1/N 保留原文，N+1 总长度不超过 N 且尾部有截断标记，异常链/源码/无 locals 规则保持。"""
    limit = 262144
    marker = "\n[报告超出字符上限，后续内容已截断]\n"
    assert format_exception_report(ValueError("正常")) == "ValueError: 正常\n"
    for size in (limit - 1, limit, limit + 1):
        message = "x" * (size - len("ValueError: ") - 1)
        original = "ValueError: " + message + "\n"
        assert len(original) == size
        report = format_exception_report(ValueError(message))
        if size <= limit:
            assert report == original and len(report) == size
        else:
            assert report == original[: limit - len(marker)] + marker
            assert len(report) == limit and report.endswith(marker)


def test_report_truncated_same_text(
    tmp_path: Path, engine: Engine, caplog: pytest.LogCaptureFixture
) -> None:
    """验证 B2：超长缺陷经真实 HTTP 边界后，日志和报错表保存同一份有界截断报告。"""
    app = create_app(None, database=engine)
    message = "x" * 262145

    def probe() -> None:
        raise RuntimeError(message)

    _route(app, probe)
    with _client(app, root=tmp_path) as client:
        response = client.get("/api/probe")
    assert response.status_code == 500
    with session_scope(engine, read_only=True) as session:
        record = find_error(session, response.headers["X-Request-ID"])
    assert record is not None
    messages = [item.getMessage() for item in caplog.records if item.name == "rdp.api.errors"]
    assert len(messages) == 1
    prefix = response.json()["detail"] + "\n"
    assert messages[0].startswith(prefix)
    log_report = messages[0][len(prefix) :]
    assert log_report == record.report
    for report in (log_report, record.report):
        assert len(report) <= 262144
        assert report.endswith("\n[报告超出字符上限，后续内容已截断]\n")


def test_report_sensitive(tmp_path: Path, engine: Engine, caplog: pytest.LogCaptureFixture) -> None:
    """验证契约：参数校验原值、请求体/query/headers/cookie 和 SQL 绑定凭据不进入日志、报错表或接口响应。"""
    app = create_app(None, database=engine)

    def probe(value: int) -> int:
        return value

    _route(app, probe)
    with _client(app, root=tmp_path) as client:
        response = client.get(
            "/api/probe?value=credential-marker&token=credential-marker",
            headers={
                "Cookie": client.headers["Cookie"] + "; session=credential-marker",
                "Authorization": "credential-marker",
            },
        )
    assert response.status_code == 422
    assert "credential-marker" not in response.text
    assert "credential-marker" not in caplog.text
    with session_scope(engine, read_only=True) as session:
        assert session.execute(text("SELECT count(*) FROM error_reports")).scalar_one() == 0


@contextmanager
def _client(app: FastAPI, *, root: Path) -> Generator[httpx.Client, None, None]:
    """桥接 Starlette 的 httpx 回退类型，真实 TestClient 生命周期和传输不变。"""
    with authenticated_client(app, root) as client:
        yield client
