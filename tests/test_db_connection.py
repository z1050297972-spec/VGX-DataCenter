"""工单 05 契约测试；只在 tmp_path 的假状态目录验证。"""

import multiprocessing
import sqlite3
import time
from pathlib import Path
from queue import Empty
from typing import Any, cast

import pytest
from db_support import reap_processes as _reap
from db_support import sqlite_connection
from sqlalchemy import event, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError, StatementError
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from rdp.infra.db.connection import (
    create_database_engine,
    session_scope,
    session_scope_with_lock_timeout,
    translate_database_error,
)
from rdp.infra.diagnostics import ConflictError, DefectError, ExternalError, InputError


def _sqlite_error(code: int) -> sqlite3.OperationalError:
    """用公开的驱动错误对象模拟 SQLite 系统边界，不 mock 平台内部函数。"""
    error = sqlite3.OperationalError("数据库故障")
    error.sqlite_errorcode = code
    return error


def _hold_writer(path: str, ready: Any, release: Any, result: Any = None) -> None:
    """子进程在临时库持锁，等待有硬上限，退出必关闭引擎。"""
    engine = create_database_engine(Path(path))
    try:
        with session_scope(engine) as session:
            if result is not None:
                session.execute(text("INSERT INTO items VALUES (7)"))
            ready.set()
            if not release.wait(15):
                raise TimeoutError("测试释放信号超时")
        if result is not None:
            result.put("ok")
    finally:
        engine.dispose()


def _write_child(path: str, result: Any, waiting: Any = None) -> None:
    """子进程通过公共工作单元写入，并把耗时和安全诊断送回父进程。"""
    engine = create_database_engine(Path(path))
    if waiting is not None:

        def notify(*args: Any, **kwargs: Any) -> None:
            if args[2] == "BEGIN IMMEDIATE":
                waiting.set()

        event.listen(engine, "before_cursor_execute", notify)
    started = time.monotonic()
    try:
        with session_scope(engine) as session:
            session.execute(text("INSERT INTO items VALUES (7)"))
        result.put(("ok", time.monotonic() - started, ""))
    except ConflictError as error:
        result.put(("conflict", time.monotonic() - started, error.diagnostics[0].model_dump()))
    finally:
        engine.dispose()


def test_engine_lazy(tmp_path: Path) -> None:
    """验证契约：create_database_engine 返回独立惰性 NullPool 引擎，构造时不建库、不建表，调用方 dispose。"""
    path = tmp_path / "db.sqlite3"
    engine = create_database_engine(path)
    try:
        assert isinstance(engine.pool, NullPool)
        assert engine.hide_parameters is True
        assert not path.exists()
    finally:
        engine.dispose()


def test_engine_path(tmp_path: Path) -> None:
    """验证契约：create_database_engine 对相对路径、NUL、..、内存路径给 InputError 诊断且不建库。"""
    for path, actual in (
        (Path("relative"), "相对路径"),
        (Path(":memory:"), "相对路径"),
        (tmp_path / ".." / "db", "包含 .. 分量"),
        (tmp_path / "bad\0db", "包含 NUL"),
    ):
        with pytest.raises(InputError) as caught:
            create_database_engine(path)
        diagnostic = caught.value.diagnostics[0]
        assert diagnostic.objects[0].value == str(path)
        assert diagnostic.rule == "数据库路径必须为不含 NUL 或 .. 分量的绝对文件路径"
        assert actual in diagnostic.actual
        assert "错误码=0" not in diagnostic.actual
        assert diagnostic.expected is not None
        assert "绝对" in diagnostic.expected
        assert "拒绝建立" in diagnostic.consequence
        assert "修正路径" in diagnostic.next_step
    assert not list(tmp_path.iterdir())


def test_engine_file_failure(tmp_path: Path) -> None:
    """验证契约：create_database_engine 对目录、软链接、父目录不可用给 ExternalError，不跟随或创建目录。"""
    link = tmp_path / "link"
    link.symlink_to(tmp_path / "absent")
    for path in (tmp_path, link, tmp_path / "absent" / "db"):
        with pytest.raises(ExternalError):
            create_database_engine(path)


def test_engine_defect(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """验证契约：create_database_engine 的配置程序错误为 DefectError。"""

    def fail(*args: Any, **kwargs: Any) -> Any:
        raise SQLAlchemyError("事件配置失败")

    monkeypatch.setattr(event, "listen", fail)
    with pytest.raises(DefectError):
        create_database_engine(tmp_path / "db")


def test_pragmas(tmp_path: Path) -> None:
    """验证契约：验收 1：两个新连接各自 journal_mode=wal、foreign_keys=1、busy_timeout=5000。"""
    engine = create_database_engine(tmp_path / "db")
    try:
        for _ in range(2):
            with engine.connect() as connection:
                assert connection.exec_driver_sql("PRAGMA journal_mode").scalar() == "wal"
                assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1
                assert connection.exec_driver_sql("PRAGMA busy_timeout").scalar() == 5000
    finally:
        engine.dispose()


def test_pragma_order(tmp_path: Path) -> None:
    """验证契约：连接先 isolation_level=None，再于事务外设置 busy_timeout/WAL/外键，最后才 BEGIN。"""
    engine = create_database_engine(tmp_path / "db")
    statements: list[str] = []

    def trace(connection: sqlite3.Connection, record: Any) -> None:
        connection.set_trace_callback(statements.append)

    event.listen(engine, "connect", trace, insert=True)
    try:
        with session_scope(engine) as session:
            session.execute(text("SELECT 1"))
        assert statements.index("PRAGMA journal_mode=WAL") < statements.index("BEGIN IMMEDIATE")
        assert statements.index("PRAGMA foreign_keys=ON") < statements.index("BEGIN IMMEDIATE")
    finally:
        engine.dispose()


def test_failed_connection(tmp_path: Path) -> None:
    """验证契约：连接初始化失败关闭连接，不删已有数据库；允许留下 SQLite 空库/WAL/SHM。"""
    path = tmp_path / "db"
    path.write_bytes(b"damaged" * 100)
    engine = create_database_engine(path)
    try:
        for _ in range(2):
            with pytest.raises(InputError), session_scope(engine):
                pass
        assert path.read_bytes() == b"damaged" * 100
    finally:
        engine.dispose()


def test_write_begin(tmp_path: Path) -> None:
    """验证契约：写会话在第一次 SELECT 之前 BEGIN IMMEDIATE，避免 WAL 读后写升级立即 BUSY。"""
    engine = create_database_engine(tmp_path / "db")
    try:
        with (
            session_scope(engine),
            sqlite_connection(tmp_path / "db", timeout=0) as other,
            pytest.raises(sqlite3.OperationalError, match="locked"),
        ):
            other.execute("BEGIN IMMEDIATE")
    finally:
        engine.dispose()


def test_read_begin(tmp_path: Path) -> None:
    """验证契约：只读会话 BEGIN 加 query_only，读已提交快照可与 WAL 写者并发，不污染新连接。"""
    engine = create_database_engine(tmp_path / "db")
    try:
        with session_scope(engine, read_only=True) as session:
            assert session.execute(text("PRAGMA query_only")).scalar_one() == 1
            with sqlite_connection(tmp_path / "db", timeout=0) as other:
                other.execute("BEGIN IMMEDIATE")
        with session_scope(engine) as session:
            assert session.execute(text("PRAGMA query_only")).scalar_one() == 0
    finally:
        engine.dispose()


def test_session_commit(tmp_path: Path) -> None:
    """验证契约：正常退出提交完整工作单元并关闭 Session/连接，expire_on_commit=False。"""
    engine = create_database_engine(tmp_path / "db")
    try:
        with session_scope(engine) as session:
            assert session.expire_on_commit is False
            session.execute(text("CREATE TABLE items (value INTEGER)"))
            session.execute(text("INSERT INTO items VALUES (7)"))
        with session_scope(engine) as session:
            assert session.execute(text("SELECT value FROM items")).scalar_one() == 7
    finally:
        engine.dispose()


def test_session_read_commit(tmp_path: Path) -> None:
    """验证契约：只读会话正常退出结束读事务并关闭连接，不更改数据。"""
    engine = create_database_engine(tmp_path / "db")
    try:
        with session_scope(engine, read_only=True) as session:
            assert session.execute(text("SELECT 7")).scalar_one() == 7
        with session_scope(engine) as session:
            session.execute(text("CREATE TABLE after_read (value INTEGER)"))
    finally:
        engine.dispose()


def test_session_rollback(tmp_path: Path) -> None:
    """验证契约：验收 4：业务异常对象原样传播并回滚，退出后没有半条记录。"""
    engine = create_database_engine(tmp_path / "db")
    error = ValueError("业务失败")
    try:
        with session_scope(engine) as session:
            session.execute(text("CREATE TABLE items (value INTEGER)"))
        with pytest.raises(ValueError) as caught, session_scope(engine) as session:
            session.execute(text("INSERT INTO items VALUES (7)"))
            raise error
        assert caught.value is error
        with session_scope(engine) as session:
            assert session.execute(text("SELECT count(*) FROM items")).scalar_one() == 0
    finally:
        engine.dispose()


def test_session_cancel(tmp_path: Path) -> None:
    """验证契约：BaseException 和取消不被转成程序缺陷，回滚并关闭会话。"""
    engine = create_database_engine(tmp_path / "db")
    original = KeyboardInterrupt()
    try:
        with pytest.raises(KeyboardInterrupt) as caught, session_scope(engine):
            raise original
        assert caught.value is original
        with session_scope(engine):
            pass
    finally:
        engine.dispose()


def test_session_commit_failure(tmp_path: Path) -> None:
    """验证契约：flush/commit 数据库故障转换四类异常并回滚，保留 cause，不重试。"""
    engine = create_database_engine(tmp_path / "db")
    try:
        with session_scope(engine) as session:
            session.execute(text("CREATE TABLE items (value INTEGER)"))

        def fail(connection: Any) -> None:
            raise OSError("提交失败")

        event.listen(engine, "commit", fail)
        with pytest.raises(ExternalError) as caught, session_scope(engine) as session:
            session.execute(text("INSERT INTO items VALUES (7)"))
        assert isinstance(caught.value.__cause__, OSError)
        event.remove(engine, "commit", fail)
        with session_scope(engine, read_only=True) as session:
            assert session.execute(text("SELECT count(*) FROM items")).scalar_one() == 0
    finally:
        engine.dispose()


def test_session_cleanup_primary(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """验证契约：回滚或关闭失败保留原业务异常，用安全 note 标明结果未知并使连接失效。"""
    engine = create_database_engine(tmp_path / "db")
    original = ValueError("业务故障")

    def fail_rollback(self: Session) -> None:
        raise OSError("回滚失败")

    def fail_invalidate(self: Session) -> None:
        raise OSError("连接失效失败")

    try:
        with monkeypatch.context() as patch:
            patch.setattr(Session, "rollback", fail_rollback)
            patch.setattr(Session, "invalidate", fail_invalidate)
            with pytest.raises(ValueError) as caught, session_scope(engine):
                raise original
        assert caught.value is original
        assert any("结果未知" in note for note in getattr(original, "__notes__", []))
    finally:
        engine.dispose()


def test_session_cleanup_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """验证契约：没有主异常时清理 I/O 失败给 ExternalError，其他清理故障分类正确。"""
    engine = create_database_engine(tmp_path / "db")
    close = Session.close

    def fail_close(self: Session) -> None:
        close(self)
        raise OSError("关闭失败")

    try:
        monkeypatch.setattr(Session, "close", fail_close)
        with pytest.raises(ExternalError), session_scope(engine):
            pass
    finally:
        engine.dispose()


def test_session_corrupt(tmp_path: Path) -> None:
    """验证契约：会话 NOTADB/CORRUPT 给 InputError，不误把空数据库当损坏。"""
    path = tmp_path / "db"
    path.write_bytes(b"not a sqlite database" * 20)
    engine = create_database_engine(path)
    try:
        with pytest.raises(InputError), session_scope(engine):
            pass
        assert path.read_bytes().startswith(b"not a sqlite")
    finally:
        engine.dispose()


def test_session_external(tmp_path: Path) -> None:
    """验证契约：会话打开/写入遇到磁盘满、权限或 I/O 故障给 ExternalError，失败无提交。"""
    engine = create_database_engine(tmp_path / "db")

    def fail(connection: Any, record: Any) -> None:
        raise _sqlite_error(sqlite3.SQLITE_FULL)

    event.listen(engine, "connect", fail)
    try:
        with pytest.raises(ExternalError), session_scope(engine):
            pass
    finally:
        engine.dispose()


def test_session_defect(tmp_path: Path) -> None:
    """验证契约：只读会话写入、非法 SQL 或驱动编程错误给 DefectError。"""
    engine = create_database_engine(tmp_path / "db")
    try:
        with pytest.raises(DefectError), session_scope(engine) as session:
            session.execute(text("INVALID SQL"))
        with pytest.raises(DefectError), session_scope(engine, read_only=True) as session:
            session.execute(text("CREATE TABLE forbidden (value INTEGER)"))
    finally:
        engine.dispose()


def test_session_busy(tmp_path: Path) -> None:
    """验证契约：会话 BEGIN/SQL/提交遇到 BUSY 扩展码或 LOCKED 给 ConflictError 和完整五段诊断。"""
    engine = create_database_engine(tmp_path / "db")

    def fail(connection: Any) -> None:
        raise _sqlite_error(sqlite3.SQLITE_BUSY_SNAPSHOT)

    event.listen(engine, "begin", fail)
    try:
        with pytest.raises(ConflictError) as caught, session_scope(engine):
            pass
        assert caught.value.diagnostics[0].consequence == "本次事务未提交"
    finally:
        engine.dispose()


def test_session_constraint(tmp_path: Path) -> None:
    """验证契约：会话唯一/外键/CHECK 失败给 ConflictError，原事务回滚。"""
    engine = create_database_engine(tmp_path / "db")
    try:
        with session_scope(engine) as session:
            session.execute(text("CREATE TABLE items (value INTEGER UNIQUE)"))
            session.execute(text("INSERT INTO items VALUES (7)"))
        with pytest.raises(ConflictError), session_scope(engine) as session:
            session.execute(text("INSERT INTO items VALUES (8), (7)"))
        with session_scope(engine, read_only=True) as session:
            assert session.execute(text("SELECT value FROM items")).scalars().all() == [7]
    finally:
        engine.dispose()


def test_process_success(tmp_path: Path) -> None:
    """验证契约：验收 2：multiprocessing.get_context('spawn') 两个进程写 tmp_path 库都成功；事件协调先后，连接不跨进程继承。"""
    path = tmp_path / "db"
    engine = create_database_engine(path)
    context = multiprocessing.get_context("spawn")
    ready, waiting, release = context.Event(), context.Event(), context.Event()
    first_result, second_result = context.Queue(), context.Queue()
    holder = context.Process(target=_hold_writer, args=(str(path), ready, release, first_result))
    writer = context.Process(target=_write_child, args=(str(path), second_result, waiting))
    started: list[Any] = []
    try:
        with session_scope(engine) as session:
            session.execute(text("CREATE TABLE items (value INTEGER)"))
        holder.start()
        started.append(holder)
        assert ready.wait(5)
        writer.start()
        started.append(writer)
        assert waiting.wait(3)
        # 第二个进程已开始 BEGIN，首个事务仍持锁；释放前不允许第二个写入完成。
        with pytest.raises(Empty):
            second_result.get(timeout=0.5)
        release.set()
        assert first_result.get(timeout=3) == "ok"
        status, elapsed, _ = second_result.get(timeout=3)
        assert status == "ok" and 0.4 <= elapsed < 5
        for process in started:
            process.join(3)
            assert process.exitcode == 0
        with session_scope(engine, read_only=True) as session:
            assert session.execute(text("SELECT count(*) FROM items")).scalar_one() == 2
    finally:
        release.set()
        _reap(started)
        for result in (first_result, second_result):
            result.close()
            result.join_thread()
        engine.dispose()


def test_process_timeout(tmp_path: Path) -> None:
    """验证契约：验收 2：spawn 持锁进程用 Event 保持 BEGIN IMMEDIATE；第二进程 monotonic 测等待为 4-10 秒并收到 ConflictError，诊断对象/实际/后果齐全。"""
    path = tmp_path / "db"
    engine = create_database_engine(path)
    context = multiprocessing.get_context("spawn")
    ready, release, result = context.Event(), context.Event(), context.Queue()
    holder = context.Process(target=_hold_writer, args=(str(path), ready, release))
    writer = context.Process(target=_write_child, args=(str(path), result))
    started: list[Any] = []
    try:
        with session_scope(engine) as session:
            session.execute(text("CREATE TABLE items (value INTEGER)"))
        holder.start()
        started.append(holder)
        assert ready.wait(5)
        writer.start()
        started.append(writer)
        status, elapsed, diagnostic = result.get(timeout=12)
        assert status == "conflict" and 4 <= elapsed <= 10
        assert diagnostic["objects"][0]["value"] == str(path)
        assert "5000" in diagnostic["actual"]
        assert diagnostic["consequence"] == "本次事务未提交"
    finally:
        release.set()
        _reap(started)
        result.close()
        result.join_thread()
        engine.dispose()


def test_process_cleanup(tmp_path: Path) -> None:
    """验证契约：两进程测试 Event/Queue 等待和 join 均限时，finally terminate/kill/join 回收全部子进程，故障路径 pytest 不挂住。"""
    context = multiprocessing.get_context("spawn")
    ready, release = context.Event(), context.Event()
    process = context.Process(target=_hold_writer, args=(str(tmp_path / "db"), ready, release))
    process.start()
    try:
        assert ready.wait(5)
    finally:
        _reap([process])
    assert process.exitcode is not None


def test_translate_busy(tmp_path: Path) -> None:
    """验证契约：translate_database_error 对 BUSY/BUSY_SNAPSHOT/LOCKED 返回 ConflictError，区分锁规则和约束规则。"""
    for code in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_BUSY_SNAPSHOT, sqlite3.SQLITE_LOCKED):
        original = _sqlite_error(code)
        error = translate_database_error(original, database=tmp_path / "db", operation="开始事务")
        assert isinstance(error, ConflictError)
        assert "5000" in error.diagnostics[0].actual
        assert error.diagnostics[0].objects[0].value == str(tmp_path / "db")


def test_translate_constraint(tmp_path: Path) -> None:
    """验证契约：translate_database_error 对唯一/外键/CHECK 返回 ConflictError，不输出 SQL 或参数。"""
    for code in (
        sqlite3.SQLITE_CONSTRAINT_UNIQUE,
        sqlite3.SQLITE_CONSTRAINT_FOREIGNKEY,
        sqlite3.SQLITE_CONSTRAINT_CHECK,
    ):
        error = translate_database_error(
            IntegrityError(
                "INSERT", {"secret": "hidden"}, _sqlite_error(code), hide_parameters=True
            ),
            database=tmp_path / "db",
            operation="写入",
        )
        assert isinstance(error, ConflictError)
        assert "hidden" not in str(error.diagnostics)


def test_translate_corrupt(tmp_path: Path) -> None:
    """验证契约：translate_database_error 对 NOTADB/CORRUPT 返回 InputError。"""
    for code in (sqlite3.SQLITE_NOTADB, sqlite3.SQLITE_CORRUPT):
        assert isinstance(
            translate_database_error(
                _sqlite_error(code), database=tmp_path / "db", operation="读取"
            ),
            InputError,
        )


def test_translate_external(tmp_path: Path) -> None:
    """验证契约：translate_database_error 对 CANTOPEN/FULL/IOERR/PERM/READONLY/OSError 返回 ExternalError。"""
    errors = [
        _sqlite_error(code)
        for code in (
            sqlite3.SQLITE_CANTOPEN,
            sqlite3.SQLITE_FULL,
            sqlite3.SQLITE_IOERR,
            sqlite3.SQLITE_PERM,
            sqlite3.SQLITE_READONLY,
        )
    ]
    for error in [*errors, PermissionError("安全消息")]:
        assert isinstance(
            translate_database_error(error, database=tmp_path / "db", operation="读取"),
            ExternalError,
        )


def test_translate_unknown(tmp_path: Path) -> None:
    """验证契约：translate_database_error 对未知 SQLAlchemy/sqlite 错误返回 DefectError，不自动重试。"""
    for error in (SQLAlchemyError("内部故障"), sqlite3.ProgrammingError("内部故障")):
        assert isinstance(
            translate_database_error(error, database=tmp_path / "db", operation="读取"), DefectError
        )


def test_translate_wrapped(tmp_path: Path) -> None:
    """验证契约：translate_database_error 对 StatementError.orig 的 UTC InputError/DefectError 保留原四类异常。"""
    original = DefectError()
    wrapped = StatementError("故障", None, None, original, hide_parameters=True)
    assert translate_database_error(wrapped, database=tmp_path / "db", operation="读取") is original


def test_translate_diagnostic(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """验证契约：每类数据库诊断含 database/operation、规则、实际安全码、期望、后果、下一步；不改变原异常且不打日志。"""
    for code in (5, 19, 26, 13, 1):
        original = _sqlite_error(code)
        error = translate_database_error(original, database=tmp_path / "db", operation="读取")
        diagnostic = error.diagnostics[0]
        assert [o.key for o in diagnostic.objects] == ["database", "operation"]
        assert all(
            (
                diagnostic.rule,
                diagnostic.actual,
                diagnostic.expected,
                diagnostic.consequence,
                diagnostic.next_step,
            )
        )
        assert original.__cause__ is None
    assert not caplog.records


def test_parameters_hidden(tmp_path: Path) -> None:
    """验证契约：引擎 hide_parameters=True，异常链和日志不泄漏绑定参数中的密码、令牌、cookie、私钥。"""
    engine = create_database_engine(tmp_path / "db")
    try:
        with session_scope(engine) as session:
            session.execute(text("CREATE TABLE items (value TEXT UNIQUE)"))
            session.execute(
                text("INSERT INTO items VALUES (:value)"), {"value": "credential-test-value"}
            )
        with pytest.raises(ConflictError) as caught, session_scope(engine) as session:
            session.execute(
                text("INSERT INTO items VALUES (:value)"), {"value": "credential-test-value"}
            )
        assert "credential-test-value" not in str(caught.value.__cause__)
        assert "credential-test-value" not in str(caught.value.diagnostics)
    finally:
        engine.dispose()


def test_short_write_timeout_before_begin(tmp_path: Path) -> None:
    """验证契约：session_scope_with_lock_timeout在独立连接BEGIN之前设PRAGMA busy_timeout为100毫秒，事务内读到100，不能先BEGIN再设置。"""
    engine = create_database_engine(tmp_path / "short.sqlite3")
    statements: list[str] = []

    def trace(conn: Any, cursor: Any, statement: str, *args: Any) -> None:
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", trace)
    try:
        with session_scope_with_lock_timeout(engine, busy_timeout_ms=100) as session:
            assert session.scalar(text("PRAGMA busy_timeout")) == 100
        assert statements.index("PRAGMA busy_timeout=100") < statements.index("BEGIN IMMEDIATE")
    finally:
        event.remove(engine, "before_cursor_execute", trace)
        engine.dispose()


def test_short_write_timeout_contention(tmp_path: Path) -> None:
    """验证契约：另一连接持有写锁时短写入场按100毫秒预算冲突，保留SQLite BUSY/LOCKED原因与获锁阶段，不重试至5秒。"""
    engine = create_database_engine(tmp_path / "short.sqlite3")
    try:
        with session_scope(engine):
            started = time.monotonic()
            with (
                pytest.raises(ConflictError) as caught,
                session_scope_with_lock_timeout(engine, busy_timeout_ms=100),
            ):
                pytest.fail("不应获得被占用的写锁")
            assert time.monotonic() - started < 1.5
            assert caught.value.__cause__ is not None
    finally:
        engine.dispose()


def test_short_write_timeout_isolation(tmp_path: Path) -> None:
    """验证契约：短会话结束/入场失败后丢弃NullPool连接，不改父引擎或其他并行连接，普通session_scope仍为5000毫秒。"""
    engine = create_database_engine(tmp_path / "short.sqlite3")
    try:
        with session_scope_with_lock_timeout(engine, busy_timeout_ms=100) as short:
            assert short.scalar(text("PRAGMA busy_timeout")) == 100
        with session_scope(engine) as normal:
            assert normal.scalar(text("PRAGMA busy_timeout")) == 5000
        assert "rdp_lock_timeout_ms" not in engine.get_execution_options()
    finally:
        engine.dispose()


def test_short_write_invalid_options(tmp_path: Path) -> None:
    """验证契约：超时bool/负值/大于5000或非受管引擎归DefectError，不打开工作单元；0和5000合法。"""
    engine = create_database_engine(tmp_path / "short.sqlite3")
    try:
        for invalid in (True, -1, 5001, "100", None):
            with pytest.raises(DefectError):
                session_scope_with_lock_timeout(engine, busy_timeout_ms=cast(Any, invalid))
        for valid in (0, 5000):
            with session_scope_with_lock_timeout(engine, busy_timeout_ms=valid) as session:
                assert session.scalar(text("PRAGMA busy_timeout")) == valid
    finally:
        engine.dispose()


def test_short_write_transaction_lifecycle(tmp_path: Path) -> None:
    """验证契约：短写正常提交、业务异常回滚，清理失败沿用session_scope保留主异常，不吞取消、不dispose调用者引擎。"""
    engine = create_database_engine(tmp_path / "short.sqlite3")
    try:
        with session_scope(engine) as session:
            session.execute(text("CREATE TABLE counter(value INTEGER)"))
        with (
            pytest.raises(KeyboardInterrupt),
            session_scope_with_lock_timeout(engine, busy_timeout_ms=100) as session,
        ):
            session.execute(text("INSERT INTO counter VALUES (1)"))
            raise KeyboardInterrupt()
        with session_scope(engine, read_only=True) as session:
            assert session.scalar(text("SELECT count(*) FROM counter")) == 0
        with session_scope_with_lock_timeout(engine, busy_timeout_ms=100) as session:
            session.execute(text("INSERT INTO counter VALUES (2)"))
        with session_scope(engine, read_only=True) as session:
            assert session.scalar(text("SELECT value FROM counter")) == 2
    finally:
        engine.dispose()


def test_short_write_error_categories(tmp_path: Path) -> None:
    """验证契约：数据损坏InputError、I/O ExternalError、SQL DefectError、非获锁阶段锁或约束ConflictError，不能被认证刷新误吞。"""
    engine = create_database_engine(tmp_path / "short.sqlite3")
    try:
        for code, expected in (
            (sqlite3.SQLITE_CORRUPT, InputError),
            (sqlite3.SQLITE_IOERR, ExternalError),
            (sqlite3.SQLITE_BUSY, ConflictError),
        ):
            with (
                pytest.raises(expected),
                session_scope_with_lock_timeout(engine, busy_timeout_ms=100),
            ):
                raise _sqlite_error(code)
        with (
            pytest.raises(DefectError),
            session_scope_with_lock_timeout(engine, busy_timeout_ms=100) as session,
        ):
            session.execute(text("SELECT missing FROM absent"))
    finally:
        engine.dispose()
