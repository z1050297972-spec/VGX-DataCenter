"""基础层数据库诊断构造与只读会话规则；不连接数据库、不记录日志。"""

import sqlite3
from pathlib import Path

from sqlalchemy.exc import SQLAlchemyError, StatementError
from sqlalchemy.orm import Session

from rdp.infra.db._constants import BUSY_TIMEOUT_MS
from rdp.infra.diagnostics import (
    ConflictError,
    DefectError,
    Diagnostic,
    DiagnosticLevel,
    DiagnosticObject,
    ExternalError,
    InputError,
)


def database_problem[Problem: InputError | ConflictError | ExternalError | DefectError](
    kind: type[Problem],
    database: Path,
    operation: str,
    code: int,
) -> Problem:
    """只用路径、固定操作和数字码补诊断，不拼 SQL、绑定值或底层异常正文。"""
    if kind is DefectError and code == sqlite3.SQLITE_READONLY:
        rule = "只读会话不得写入"
        actual = f"只读会话尝试写入，SQLite SQLITE_READONLY 错误码={code}"
        expected = "只读会话只执行读取操作"
        next_step = "检查调用方，将写操作放入可写工作单元"
    elif code in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED):
        rule = "写事务必须取得数据库写锁"
        actual = f"SQLite code={code}；等待 {BUSY_TIMEOUT_MS} 毫秒未获锁"
        expected = f"{BUSY_TIMEOUT_MS} 毫秒内取得锁"
        next_step = "等待当前写入结束后重试，检查长事务"
    else:
        rule = "数据库操作必须满足存储及结构约束"
        actual = f"数据库操作失败，安全错误码={code}"
        expected = "数据库可用且符合声明的结构及约束"
        next_step = "检查权限、空间、数据约束及数据库备份，联系维护者"
    return kind(
        (
            Diagnostic(
                level=DiagnosticLevel.ERROR,
                category=kind.category,
                stage="数据库",
                source="平台",
                objects=(
                    DiagnosticObject(key="database", value=str(database)),
                    DiagnosticObject(key="operation", value=operation),
                ),
                rule=rule,
                actual=actual,
                expected=expected,
                consequence="本次事务未提交",
                next_step=next_step,
            ),
        )
    )


def database_path_error(database: Path) -> InputError | None:
    """把实际路径违规写成路径诊断；校验尚未访问 SQLite，不虚构驱动错误码。"""
    violations: list[str] = []
    if not database.is_absolute():
        violations.append("实际为相对路径")
    if "\x00" in str(database):
        violations.append("路径包含 NUL")
    if ".." in database.parts:
        violations.append("路径包含 .. 分量")
    if not violations:
        return None
    return InputError(
        (
            Diagnostic(
                level=DiagnosticLevel.ERROR,
                category=InputError.category,
                stage="数据库路径校验",
                source="平台",
                objects=(DiagnosticObject(key="database", value=str(database)),),
                rule="数据库路径必须为不含 NUL 或 .. 分量的绝对文件路径",
                actual="；".join(violations),
                expected="StatePaths.database 提供的绝对文件路径，不含 NUL 或 .. 分量",
                consequence="拒绝建立数据库引擎，未创建文件",
                next_step="修正路径后重新建立数据库引擎",
            ),
        )
    )


def readonly_write_error(
    session: Session, error: SQLAlchemyError | sqlite3.Error | OSError
) -> DefectError | None:
    """只在 query_only 会话尝试写入时产生带诊断的程序缺陷，其他故障交通用转换器。"""
    original = error.orig if isinstance(error, StatementError) else error
    if (
        not session.info.get("rdp_read_only")
        or getattr(original, "sqlite_errorcode", 0) != sqlite3.SQLITE_READONLY
    ):
        return None
    database = Path(session.get_bind().engine.url.database or "未知数据库")
    return database_problem(DefectError, database, "只读会话写入", sqlite3.SQLITE_READONLY)
