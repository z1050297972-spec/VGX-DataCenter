"""基础层 SQLite 连接和工作单元契约，不拥有引擎生命周期或应用日志。

依据工单 05 验收 1/2/4；事务方案核对本地 SQLAlchemy 2.1.6
dialects/sqlite/base.py 的 sqlite_transactions：isolation_level=None，begin 事件显式开始。
不用 autocommit=False，避免连接时已在事务内，无法设置 journal_mode 和 foreign_keys。
写事务先拿锁再读，避免 WAL 的延迟读事务升级写锁立刻 SQLITE_BUSY_SNAPSHOT。
"""

import sqlite3
import stat
from collections.abc import Generator
from contextlib import AbstractContextManager, contextmanager
from pathlib import Path
from typing import cast

from sqlalchemy import URL, Connection, Engine, create_engine, event
from sqlalchemy.exc import SQLAlchemyError, StatementError
from sqlalchemy.orm import Session
from sqlalchemy.pool import ConnectionPoolEntry, NullPool

from rdp.infra.db._constants import BUSY_TIMEOUT_MS as BUSY_TIMEOUT_MS
from rdp.infra.db._errors import database_path_error, database_problem, readonly_write_error
from rdp.infra.diagnostics import (
    ConflictError,
    DefectError,
    ExternalError,
    InputError,
)


def create_database_engine(database: Path) -> Engine:
    """为单个状态数据库建立同步引擎及逐连接初始化规则。

    Args:
        database: StatePaths.database 的绝对文件 Path，无单位；不含 NUL、..，
            不接受内存库、URI 或目录，父目录须由 initialize_state 创建且可信。

    Returns:
        独立 SQLite Engine；NullPool 避免额外池等待，check_same_thread=False 允许
        FastAPI 顺序跨线程使用，绝不允许同一 Session 并发使用；hide_parameters=True。
        延迟连接，不 create_all、不迁移。每个新 DBAPI 连接先设 isolation_level=None，
        再在无事务状态设 busy_timeout=BUSY_TIMEOUT_MS、journal_mode=WAL、foreign_keys=ON，
        验证实际值；然后 begin 事件默认发 BEGIN IMMEDIATE。
        仅 session_scope(read_only=True) 使用 rdp_read_only 执行选项切为 BEGIN，
        并在事务前设置 query_only=ON；连接关闭后不复用该设置。

    Raises:
        InputError: 路径形式非法，诊断只含数据库路径、路径规则、实际、期望、拒绝建立、修正路径。
        ExternalError: 检查父目录/目标失败或目标是目录、软链接；不跟随数据库文件软链接。
        DefectError: 无法构造引擎或事件配置错误。

    Side Effects:
        构造时只检查本地路径状态；首次连接可能创建数据库及 WAL/SHM 文件，不创建表。
        连接初始化失败关闭该连接，可能留下空数据库或 SQLite 管理的辅助文件，不删除已有库。
        连接阶段数据库异常由 session_scope 按 translate_database_error 转换，不打日志。
        引擎由调用者最终 dispose；调用者不得绕过工作单元直接执行业务 SQL。

    Time Semantics:
        不读墙钟；连接 PRAGMA 和 BEGIN 的单次锁等待最多约 BUSY_TIMEOUT_MS（5000 毫秒），无额外重试。
        普通工作单元的写锁等待发生在任何 SELECT 之前；本地磁盘 I/O 不承诺硬实时上限。
    """
    path_error = database_path_error(database)
    if path_error is not None:
        raise path_error
    try:
        _check_database_file(database)
    except OSError as error:
        problem = translate_database_error(error, database=database, operation="校验路径")
        raise problem from error
    engine: Engine | None = None
    try:
        engine = create_engine(
            URL.create("sqlite", database=str(database)),
            poolclass=NullPool,
            connect_args={"check_same_thread": False},
            hide_parameters=True,
            execution_options={"rdp_managed": True},
        )
        event.listen(engine, "connect", _initialize_connection)
        event.listen(engine, "begin", _begin_transaction)
        return engine
    except Exception as error:
        if engine is not None:
            engine.dispose()
        problem = database_problem(DefectError, database, "构造引擎", 0)
        raise problem from error


def _initialize_connection(connection: sqlite3.Connection, _record: ConnectionPoolEntry) -> None:
    """事务外设置每个连接；初始化失败关闭句柄，避免把半配置的连接交给业务。"""
    try:
        connection.isolation_level = None
        cursor = connection.cursor()
        try:
            cursor.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
            cursor.execute("PRAGMA journal_mode=WAL")
            if cursor.fetchone() != ("wal",):
                raise sqlite3.OperationalError("无法启用 WAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA foreign_keys")
            if cursor.fetchone() != (1,):
                raise sqlite3.OperationalError("无法启用外键")
        finally:
            cursor.close()
    except BaseException:
        connection.close()
        raise


def _begin_transaction(connection: Connection) -> None:
    """写者先拿写锁再读，避免 WAL 快照升级跳过 busy_timeout。

    session_scope_with_lock_timeout 的连接带 rdp_lock_timeout_ms 执行选项，
    必须在 BEGIN 之前将该连接的 PRAGMA busy_timeout 设为指定整数毫秒；不改父引擎或其他连接。
    无此选项时保留现有 BUSY_TIMEOUT_MS，非法选项拒绝为 DefectError。
    """
    options = connection.get_execution_options()
    if "rdp_lock_timeout_ms" in options:
        timeout = _checked_lock_timeout(options["rdp_lock_timeout_ms"])
        # 必须在 BEGIN 之前设置，入场失败才能遵守短等待预算。
        connection.exec_driver_sql(f"PRAGMA busy_timeout={timeout}")
    read_only = bool(options.get("rdp_read_only", False))
    if read_only:
        connection.exec_driver_sql("PRAGMA query_only=ON")
    connection.exec_driver_sql("BEGIN" if read_only else "BEGIN IMMEDIATE")


def session_scope(engine: Engine, *, read_only: bool = False) -> AbstractContextManager[Session]:
    """把一次工作单元的连接、提交或回滚和关闭收在同一边界。

    Args:
        engine: create_database_engine 返回的引擎，无单位；未 dispose，不跨进程继承。
        read_only: 默认 False，进入时立即 BEGIN IMMEDIATE；True 为 BEGIN 加 query_only，
            只能读，不能先读再升级为写；禁止在作用域内手工 commit/rollback 或共享 Session。

    Returns:
        上下文管理器，每次进入产生一个新 Session（expire_on_commit=False）；
        正常退出提交，异常退出回滚，所有路径关闭 Session 和连接。只读会话也正常结束事务。

    Raises:
        ConflictError: BEGIN 或 SQL/提交触发 SQLITE_BUSY（含扩展码）、SQLITE_LOCKED，
            或唯一/外键/CHECK 约束冲突；用 translate_database_error 补诊断并 raise ... from。
        InputError: SQLite 报 NOTADB/CORRUPT，数据损坏；不把空库当损坏。
        ExternalError: 打开、读写、提交、清理遇到磁盘满、权限或 I/O 故障。
        DefectError: 编程错误、非法 SQL、只读会话尝试写或其余数据库异常。
        BaseException: 业务异常（包括已有四类异常和取消）原对象传播；仅数据库异常转换。
            回滚/关闭再失败时保留原异常，以固定安全 note 标明清理失败，不以清理错误覆盖根因。

    Side Effects:
        成功提交整个工作单元；业务或 flush/commit 失败回滚，不留半条记录，不自动重试。
        清理失败使连接失效并关闭；SQLite 回滚无法完成时结果未知，note 提示检查数据库，
        不声称已经回滚。没有主异常的清理故障按四类转换。无日志、无迁移。

    Time Semantics:
        一次工作单元一个会话，事务范围不包含外部长任务；首次读前获取写锁，
        单次锁等待 BUSY_TIMEOUT_MS 毫秒；会话不限制调用方业务耗时，不读墙钟。
    """
    return _work_unit(engine, read_only)


def session_scope_with_lock_timeout(
    engine: Engine, *, busy_timeout_ms: int
) -> AbstractContextManager[Session]:
    """为短时写入提供独立连接上的有限获锁等待。

    Args:
        engine: create_database_engine 的受管 SQLite 引擎，不可空、无单位；不接管其生命周期。
        busy_timeout_ms: 单次 SQLite 忙等待上限，整数毫秒，0 至 BUSY_TIMEOUT_MS（5000）；拒绝 bool。
            账号活动刷新传 SESSION_TOUCH_LOCK_TIMEOUT_MS（100），其他工作单元不受影响。

    Returns:
        返回写工作单元上下文管理器，进入后产生新 Session；先设置独立连接的 busy_timeout，
        再 BEGIN IMMEDIATE，随后才允许调用者读写。提交、回滚、关闭和清理失败语义复用 session_scope。

    Raises:
        DefectError: 引擎或超时参数非法、执行选项不能安全应用，或 SQL/映射错误。
        ConflictError: BEGIN 在指定忙等待内未取得锁，或后续 SQL/提交的锁与约束冲突；
            保留原始 SQLite 码和失败阶段，调用者只能把获锁阶段的 BUSY/LOCKED 视为可跳过。
        InputError: SQLite 数据损坏。
        ExternalError: 本地数据库 I/O、提交或清理失败。
        BaseException: 工作单元内的业务异常原对象传播并回滚；不掩盖取消或原始失败。

    Side Effects:
        实现时用 engine.execution_options(rdp_lock_timeout_ms=busy_timeout_ms) 的局部派生引擎，
        在 _begin_transaction 中于 BEGIN 前设置本连接 PRAGMA；复用 _work_unit 的资源管理。
        不修改父引擎、默认 BUSY_TIMEOUT_MS 或全局事件监听器；不 dispose 派生引擎以免影响共享池。
        NullPool 使本连接关闭后丢弃，后续普通 session_scope 仍为 5000 毫秒；失败不遗留短超时配置。
        连接初始化和 WAL/外键校验仍复用现有受管引擎；不新增表或记录日志。

    Time Semantics:
        指定值约束 BEGIN 的 SQLite 忙等待，配置在发出 BEGIN 前完成，不能在 Session 已开启后再改。
        不是整个连接初始化、文件 I/O 或业务 SQL 的硬实时期限；没有自动重试，也不读取业务墙钟。
    """
    if (
        not isinstance(cast(object, engine), Engine)
        or engine.dialect.name != "sqlite"
        or not engine.get_execution_options().get("rdp_managed")
    ):
        raise DefectError()
    timeout = _checked_lock_timeout(busy_timeout_ms)
    return _work_unit(engine.execution_options(rdp_lock_timeout_ms=timeout), False)


@contextmanager
def _work_unit(engine: Engine, read_only: bool) -> Generator[Session, None, None]:
    """成对管理会话退出，业务异常不在此处记日志。"""
    session = Session(engine, expire_on_commit=False)
    session.info["rdp_read_only"] = read_only
    primary: BaseException | None = None
    try:
        session.connection(execution_options={"rdp_read_only": read_only})
        yield session
        session.commit()
    except BaseException as error:
        primary = error
        try:
            session.rollback()
        except Exception:
            error.add_note("数据库回滚失败，结果未知；请检查数据库与备份。")
            _invalidate_safely(session, error)
        if isinstance(error, (SQLAlchemyError, sqlite3.Error, OSError)):
            primary = readonly_write_error(session, error) or translate_database_error(
                error, database=Path(engine.url.database or "未知数据库"), operation="工作单元"
            )
            raise primary from error
        raise
    finally:
        try:
            session.close()
        except Exception as cleanup:
            _invalidate_safely(session, primary or cleanup)
            if primary is not None:
                primary.add_note("数据库关闭失败，结果未知；请检查数据库与备份。")
            elif isinstance(cleanup, (SQLAlchemyError, sqlite3.Error, OSError)):
                problem = translate_database_error(
                    cleanup,
                    database=Path(engine.url.database or "未知数据库"),
                    operation="关闭会话",
                )
                raise problem from cleanup
            else:
                problem = database_problem(
                    DefectError, Path(engine.url.database or "未知数据库"), "关闭会话", 0
                )
                raise problem from cleanup


def _invalidate_safely(session: Session, primary: BaseException) -> None:
    """清理再失败只补安全 note，不能覆盖首先发生的业务或提交异常。"""
    try:
        session.invalidate()
    except Exception:
        primary.add_note("数据库连接失效处理也失败，结果未知；请检查数据库与备份。")


def translate_database_error(
    error: SQLAlchemyError | sqlite3.Error | OSError, *, database: Path, operation: str
) -> InputError | ConflictError | ExternalError | DefectError:
    """把底层数据库故障转换成带对象身份的四类异常值，交调用者串接原因。

    Args:
        error: 当前 SQLAlchemy、sqlite3 或文件系统异常；无单位，不接受业务异常。
        database: 相关数据库的绝对 Path，无单位；不得传 SQL 参数或存储根路径。
        operation: 固定操作名，无单位，非空白且不含请求值，例如“开始事务”“提交”。

    Returns:
        BUSY/LOCKED（sqlite_errorcode 低 8 位，含 BUSY_SNAPSHOT）或约束冲突为 ConflictError；
        NOTADB/CORRUPT 为 InputError；CANTOPEN/FULL/IOERR/PERM/READONLY 和 OSError 为
        ExternalError，但只读会话违规由 session_scope 显式归 DefectError；其余为 DefectError。
        StatementError.orig 为本包 UTC 类型抛出的 InputError/DefectError 时保留该四类异常。
        诊断对象含 database/operation；锁规则为“写事务必须取得数据库写锁”，实际为
        SQLite 码及等待 BUSY_TIMEOUT_MS（5000 毫秒）未获锁的说明，期望在该预算内取得锁，后果为
        “本次事务未提交”，下一步为“等待当前写入结束后重试，检查长事务”；
        非锁故障同样给出规则、实际码、期望、后果和修复建议，不复制 SQL/参数/异常消息。

    Raises:
        无；未知数据库故障保守归为程序缺陷，不伪装成可重试冲突。

    Side Effects:
        无；不抛返回值、不修改原异常、不记日志。调用者 raise 返回值 from error；
        只允许 hide_parameters=True 的 SQLAlchemy 错误链进入报告，不附请求或完整行数据。

    Time Semantics:
        同步分类，不等待或重试；BUSY_TIMEOUT_MS（5000 毫秒）描述 SQLite 的锁等待预算，不伪造实测耗时。
    """
    original = error.orig if isinstance(error, StatementError) else error
    if isinstance(original, (InputError, DefectError)):
        return original
    code = getattr(original, "sqlite_errorcode", 0)
    code = code & 0xFF if isinstance(code, int) else 0
    kind: type[InputError] | type[ConflictError] | type[ExternalError] | type[DefectError] = (
        DefectError
    )
    if code in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED, sqlite3.SQLITE_CONSTRAINT):
        kind = ConflictError
    elif code in (sqlite3.SQLITE_NOTADB, sqlite3.SQLITE_CORRUPT):
        kind = InputError
    elif isinstance(original, OSError) or code in (
        sqlite3.SQLITE_CANTOPEN,
        sqlite3.SQLITE_FULL,
        sqlite3.SQLITE_IOERR,
        sqlite3.SQLITE_PERM,
        sqlite3.SQLITE_READONLY,
    ):
        kind = ExternalError
    return database_problem(kind, database, operation, code)


def _check_database_file(database: Path) -> None:
    """只读检查父目录与文件种类，底层路径错误交工厂统一转换。"""
    if not stat.S_ISDIR(database.parent.stat().st_mode):
        raise NotADirectoryError(str(database.parent))
    if database.is_symlink() or (database.exists() and not database.is_file()):
        raise OSError("数据库路径必须为普通文件且不能是软链接")


def _checked_lock_timeout(value: object) -> int:
    """执行选项只允许受限整数，不能把未校验内容拼入 PRAGMA。"""
    if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= BUSY_TIMEOUT_MS:
        raise DefectError()
    return value
