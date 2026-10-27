"""作业领域的受管事务边界；复用数据库异常转换和统一诊断，不创建事务或记录运行日志。"""

import json
import sqlite3
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import cast

from sqlalchemy import Engine
from sqlalchemy.exc import SQLAlchemyError, StatementError
from sqlalchemy.orm import Session

from rdp.infra.db.connection import translate_database_error
from rdp.infra.db.validation import invalid_field
from rdp.infra.diagnostics import (
    DefectError,
    Diagnostic,
    DiagnosticCategory,
    DiagnosticLevel,
    DiagnosticObject,
)
from rdp.infra.ids import MAX_SQLITE_INTEGER, is_request_id
from rdp.infra.timeutil import ensure_utc
from rdp.jobs.errors import JobInputError
from rdp.jobs.types import WorkerHeartbeat


def identifier(value: object, *, internal: bool = False) -> int:
    """严格区分正整数编号和bool；调用者内部错误不能伪装用户输入错误。"""
    if type(value) is not int or not 1 <= value <= MAX_SQLITE_INTEGER:
        if internal:
            raise DefectError()
        raise JobInputError(invalid_field("job_id", "1至2^63-1的整数编号").diagnostics)
    return value


def diagnostic(job_id: int, actual: str, category: DiagnosticCategory) -> Diagnostic:
    """只把已确认的编号和固定说明放入诊断，不回显参数或完整数据库行。"""
    return Diagnostic(
        level=DiagnosticLevel.ERROR,
        category=category,
        stage="作业记录",
        source="平台",
        objects=(DiagnosticObject(key="job_id", value=str(job_id)),),
        rule="作业记录必须存在且满足状态约束",
        actual=actual,
        expected="存在符合约束的作业记录",
        consequence="本次操作未修改作业",
        next_step="刷新作业列表，必要时检查运行日志",
    )


@contextmanager
def operation(session: object, *, write: bool = False) -> Generator[None]:
    """受管Session才能读写；业务异常保持原类，驱动故障按已有四类转换，不泄漏SQL参数。"""
    if not isinstance(session, Session):
        raise DefectError()
    try:
        engine = session.get_bind().engine
    except SQLAlchemyError:
        raise DefectError() from None
    if (
        not isinstance(cast(object, engine), Engine)
        or not engine.get_execution_options().get("rdp_managed")
        or "rdp_read_only" not in session.info
        or not session.in_transaction()
        or (write and session.info["rdp_read_only"])
    ):
        raise DefectError()
    try:
        yield
    except json.JSONDecodeError:
        # JSON解码器消息可能包含历史参数原文，只保留固定的字段诊断。
        raise invalid_field("job_record", "可解码的作业JSON快照") from None
    except (SQLAlchemyError, sqlite3.Error, OSError) as error:
        failure = translate_database_error(
            error, database=Path(engine.url.database or "未知数据库"), operation="作业存取"
        )
        raise failure from None


def moment(value: datetime) -> datetime:
    """内部时钟非法归程序缺陷；规范化仍由ensure_utc提供，不推测本地时区。"""
    try:
        return ensure_utc(value)
    except (AttributeError, TypeError, ValueError, OverflowError):
        raise DefectError() from None


def heartbeat(value: WorkerHeartbeat) -> WorkerHeartbeat:
    """心跳读写共用身份及时刻校验，未来/回拨时刻仍合法，不把pid当在线依据。"""
    if (
        not isinstance(cast(object, value), WorkerHeartbeat)
        or type(value.pid) is not int
        or value.pid <= 0
        or not is_request_id(value.instance_id)
    ):
        raise DefectError()
    return replace(
        value, started_at=moment(value.started_at), last_seen_at=moment(value.last_seen_at)
    )


def entry_busy(error: BaseException) -> bool:
    """只认可异常链中的SQLite BUSY/LOCKED，不把其他入场冲突静默跳过。"""
    current: BaseException | None = error
    for _ in range(8):
        if current is None:
            break
        source = current.orig if isinstance(current, StatementError) else current
        code = getattr(source, "sqlite_errorcode", None)
        if type(code) is int and code & 0xFF in {sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED}:
            return True
        current = current.__cause__
    return False
