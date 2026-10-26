"""日志领域的SQLAlchemy存取边界，只转换数据库异常，不提交或打印运行日志。"""

import sqlite3
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from typing import cast

from sqlalchemy import Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from rdp.infra.db.connection import translate_database_error
from rdp.infra.diagnostics import DefectError


@contextmanager
def operation(session: object, *, write: bool = False) -> Generator[None]:
    """拒绝非受管工作单元；驱动故障采用既有四类映射，不能带出SQL参数。"""
    if not isinstance(session, Session):
        raise DefectError()
    try:
        engine = session.get_bind().engine
    except SQLAlchemyError:
        # 未绑定引擎不是业务数据错误；在取得数据库身份之前也必须保持四类异常边界。
        raise DefectError() from None
    if (
        not isinstance(cast(object, engine), Engine)
        or not engine.get_execution_options().get("rdp_managed")
        or "rdp_read_only" not in session.info
        or not session.in_transaction()
    ):
        raise DefectError()
    if write and session.info["rdp_read_only"]:
        raise DefectError()
    try:
        yield
    except (SQLAlchemyError, sqlite3.Error, OSError) as error:
        failure = translate_database_error(
            error, database=Path(engine.url.database or "未知数据库"), operation="日志存取"
        )
        # 存量JSON可能已损坏，底层异常正文及SQL参数不能进入报告；保留安全类别和字段诊断。
        raise failure from None
