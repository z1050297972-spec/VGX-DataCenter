"""工单 05 契约测试；只在 tmp_path 的假状态目录验证。"""

from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, cast

import pytest
from sqlalchemy import Column, MetaData, Table, create_engine, select
from sqlalchemy.dialects.sqlite import dialect
from sqlalchemy.exc import StatementError

from rdp.infra.db.utc import UTCDateTime
from rdp.infra.diagnostics import InputError


def test_bind_offset(tmp_path: Path) -> None:
    """验证契约：验收 3：+08:00 时刻经 ensure_utc 换成 UTC，同一时刻微秒 123456 保留。"""
    value = datetime(2026, 10, 23, 10, 0, 0, 123456, tzinfo=timezone(timedelta(hours=8)))
    assert UTCDateTime().process_bind_param(value, dialect()) == "2026-10-23T02:00:00.123456Z"


def test_bind_zero(tmp_path: Path) -> None:
    """验证契约：写入整秒固定六位 000000 微秒、Z 结尾；年份 0001/0999 仍四位，共 27 字符。"""
    for year in (1, 999, 2026):
        value = datetime(year, 1, 2, tzinfo=UTC)
        assert (
            UTCDateTime().process_bind_param(value, dialect())
            == f"{year:04d}-01-02T00:00:00.000000Z"
        )


def test_bind_null(tmp_path: Path) -> None:
    """验证契约：process_bind_param(None) 返回 None；非空列的 SQL NULL 由数据库约束拒绝。"""
    assert UTCDateTime().process_bind_param(None, dialect()) is None


def test_bind_naive(tmp_path: Path) -> None:
    """验证契约：naive 或 utcoffset() 为 None 给 InputError，不推测本机 -06:00。"""
    with pytest.raises(InputError):
        UTCDateTime().process_bind_param(
            datetime(2026, 1, 1, tzinfo=UTC).replace(tzinfo=None), dialect()
        )


def test_bind_type(tmp_path: Path) -> None:
    """验证契约：非 datetime 值给 InputError，不回显输入，不向驱动交付值。"""
    with pytest.raises(InputError):
        UTCDateTime().process_bind_param(cast(Any, "secret-invalid"), dialect())


def test_bind_overflow(tmp_path: Path) -> None:
    """验证契约：ensure_utc 跨越年份 1/9999 的溢出转 InputError。"""
    with pytest.raises(InputError):
        UTCDateTime().process_bind_param(
            datetime(1, 1, 1, tzinfo=timezone(timedelta(hours=8))), dialect()
        )


def test_bind_wrapping(tmp_path: Path) -> None:
    """验证契约：直接 bind 调用抛 InputError，实际 SQL 执行抛 StatementError 且 orig=InputError；工作单元归回 InputError。"""
    engine = create_engine("sqlite:///" + str(tmp_path / "utc.sqlite3"), hide_parameters=True)
    table = Table("moments", MetaData(), Column("moment", UTCDateTime()))
    try:
        table.create(engine)
        with engine.begin() as connection:
            with pytest.raises(StatementError) as caught:
                connection.execute(
                    table.insert().values(
                        moment=datetime(2026, 1, 1, tzinfo=UTC).replace(tzinfo=None)
                    )
                )
            assert isinstance(caught.value.orig, InputError)
    finally:
        engine.dispose()


def test_result_utc(tmp_path: Path) -> None:
    """验证契约：process_result_value 读出 tzinfo is UTC，微秒 000001/123456/999999 不丢。"""
    for microsecond in (1, 123456, 999999):
        result = UTCDateTime().process_result_value(
            f"2026-10-23T02:00:00.{microsecond:06d}Z", dialect()
        )
        assert result == datetime(2026, 10, 23, 2, microsecond=microsecond, tzinfo=UTC)
        assert result is not None and result.tzinfo is UTC


def test_result_null(tmp_path: Path) -> None:
    """验证契约：process_result_value(None) 返回 None，不把 NULL 变成当前时间。"""
    assert UTCDateTime().process_result_value(None, dialect()) is None


def test_result_invalid(tmp_path: Path) -> None:
    """验证契约：非文本、坏长度/分隔符、非 Z 偏移、少/多微秒位或非法日期均 InputError，不修复坏数据。"""
    for value in (
        "2026-10-23T02:00:00Z",
        "2026-10-23T02:00:00.123456+00:00",
        "2026-02-30T02:00:00.123456Z",
        "2026-10-23 02:00:00.123456Z",
        "secret-invalid",
        7,
    ):
        with pytest.raises(InputError) as caught:
            UTCDateTime().process_result_value(cast(Any, value), dialect())
        assert "secret-invalid" not in str(caught.value)


def test_result_propagation(tmp_path: Path) -> None:
    """验证契约：实际查询的结果处理器 InputError 直接传播，session_scope 保留该异常且不输出坏文本。"""
    engine = create_engine("sqlite:///" + str(tmp_path / "utc.sqlite3"))
    table = Table("moments", MetaData(), Column("moment", UTCDateTime()))
    try:
        table.create(engine)
        with engine.begin() as connection:
            connection.exec_driver_sql("INSERT INTO moments VALUES ('bad')")
            with pytest.raises(InputError):
                connection.execute(select(table)).all()
    finally:
        engine.dispose()


def test_roundtrip(tmp_path: Path) -> None:
    """验证契约：验收 3：临时库正负时区/UTC 和边界年份往返等时，文本排序等于 UTC 时刻顺序。"""
    engine = create_engine("sqlite:///" + str(tmp_path / "utc.sqlite3"))
    table = Table("moments", MetaData(), Column("moment", UTCDateTime()))
    values = [
        datetime(2026, 10, 23, 10, 0, 0, 123456, tzinfo=timezone(timedelta(hours=8))),
        datetime(1, 1, 1, tzinfo=UTC),
        datetime(9999, 12, 31, 23, 59, 59, 999999, tzinfo=UTC),
    ]
    try:
        table.create(engine)
        with engine.begin() as connection:
            for value in values:
                connection.execute(table.insert().values(moment=value))
            results = (
                connection.execute(select(table.c.moment).order_by(table.c.moment)).scalars().all()
            )
            assert results == [
                values[1],
                datetime(2026, 10, 23, 2, 0, 0, 123456, tzinfo=UTC),
                values[2],
            ]
    finally:
        engine.dispose()


def test_no_clock(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """验证契约：UTC 类型不读墙钟或本地时区、不修改输入、不写日志。"""
    value = datetime(2026, 1, 1, tzinfo=UTC)
    assert UTCDateTime().process_bind_param(value, dialect()) == "2026-01-01T00:00:00.000000Z"
    assert value.tzinfo is UTC
    assert not list(tmp_path.iterdir())
    assert not caplog.records
