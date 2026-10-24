"""基础层 SQLite 连接和工作单元契约，不拥有引擎生命周期或应用日志。

依据工单 05 验收 1/2/4；事务方案核对本地 SQLAlchemy 2.1.6
dialects/sqlite/base.py 的 sqlite_transactions：isolation_level=None，begin 事件显式开始。
不用 autocommit=False，避免连接时已在事务内，无法设置 journal_mode 和 foreign_keys。
写事务先拿锁再读，避免 WAL 的延迟读事务升级写锁立刻 SQLITE_BUSY_SNAPSHOT。
"""

import sqlite3
from contextlib import AbstractContextManager
from pathlib import Path

from sqlalchemy import Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from rdp.infra.diagnostics import ConflictError, DefectError, ExternalError, InputError

# 工单 05 连接要求：SQLite 等待写锁的上限，单位毫秒；不额外自动重试。
BUSY_TIMEOUT_MS = 5000


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
        不读墙钟；连接 PRAGMA 和 BEGIN 的单次锁等待最多约 5000 毫秒，无额外重试。
        普通工作单元的写锁等待发生在任何 SELECT 之前；本地磁盘 I/O 不承诺硬实时上限。
    """
    raise NotImplementedError


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
    raise NotImplementedError


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
        SQLite 码及“等待 5000 毫秒未获锁”，期望为“5000 毫秒内取得锁”，后果为
        “本次事务未提交”，下一步为“等待当前写入结束后重试，检查长事务”；
        非锁故障同样给出规则、实际码、期望、后果和修复建议，不复制 SQL/参数/异常消息。

    Raises:
        无；未知数据库故障保守归为程序缺陷，不伪装成可重试冲突。

    Side Effects:
        无；不抛返回值、不修改原异常、不记日志。调用者 raise 返回值 from error；
        只允许 hide_parameters=True 的 SQLAlchemy 错误链进入报告，不附请求或完整行数据。

    Time Semantics:
        同步分类，不等待或重试；5000 毫秒描述 SQLite 的锁等待预算，不伪造实测耗时。
    """
    raise NotImplementedError
