"""UTC 规范化的契约测试，使用手算的偏移、微秒及年份边界验证公共接口。"""

import time
from datetime import UTC, datetime, timedelta, timezone, tzinfo

import pytest

from rdp.infra.timeutil import ensure_utc


class _MissingOffset(tzinfo):
    """模拟 tzinfo 存在但无法提供 UTC 偏移的输入。"""

    def utcoffset(self, dt: datetime | None) -> None:
        """返回未知偏移，用于无效时区的契约测试。"""
        return None


def test_positive_offset() -> None:
    """验证契约：2026-10-22 08:30:00+08:00 换算为当天 00:30:00 UTC。"""
    value = datetime(2026, 10, 22, 8, 30, tzinfo=timezone(timedelta(hours=8)))
    result = ensure_utc(value)
    assert result == datetime(2026, 10, 22, 0, 30, tzinfo=UTC)
    assert result.tzinfo is UTC


def test_negative_offset() -> None:
    """验证契约：2026-10-22 23:30:00-02:00 换算为次日 01:30:00 UTC。"""
    value = datetime(2026, 10, 22, 23, 30, tzinfo=timezone(timedelta(hours=-2)))
    result = ensure_utc(value)
    assert result == datetime(2026, 10, 23, 1, 30, tzinfo=UTC)
    assert result.tzinfo is UTC


def test_already_utc() -> None:
    """验证契约：UTC 输入保持时刻和值不变，返回 tzinfo 为 datetime.UTC。"""
    value = datetime(2026, 10, 22, 11, 20, tzinfo=UTC)
    assert ensure_utc(value) == value
    assert ensure_utc(value).tzinfo is UTC


def test_microseconds() -> None:
    """验证契约：偏移时区输入的 123456 微秒不截断、不舍入。"""
    value = datetime(2026, 10, 22, 8, 30, 12, 123456, tzinfo=timezone(timedelta(hours=8)))
    assert ensure_utc(value) == datetime(2026, 10, 22, 0, 30, 12, 123456, tzinfo=UTC)


def test_naive_rejected() -> None:
    """验证契约：tzinfo 为 None 时抛 ValueError，不默认采用本地时区。"""
    # 明确构造非法输入，验证不能默认当作本地时间。
    value = datetime(2026, 10, 22, 8, 30)  # noqa: DTZ001  # 理由：测试无时区输入的拒绝契约。
    with pytest.raises(ValueError):
        ensure_utc(value)


def test_missing_offset_rejected() -> None:
    """验证契约：tzinfo 非空但 utcoffset() 为 None 时仍抛 ValueError。"""
    value = datetime(2026, 10, 22, tzinfo=_MissingOffset())
    with pytest.raises(ValueError):
        ensure_utc(value)


def test_lower_overflow() -> None:
    """验证契约：0001-01-01 00:00:00+00:01 换算低于下界时抛 OverflowError。"""
    value = datetime(1, 1, 1, tzinfo=timezone(timedelta(minutes=1)))
    with pytest.raises(OverflowError):
        ensure_utc(value)


def test_upper_overflow() -> None:
    """验证契约：9999-12-31 23:59:59.999999-00:01 超过上界时抛 OverflowError。"""
    value = datetime(9999, 12, 31, 23, 59, 59, 999999, tzinfo=timezone(timedelta(minutes=-1)))
    with pytest.raises(OverflowError):
        ensure_utc(value)


def test_representable_limits() -> None:
    """验证契约：datetime.min、datetime.max 附上 UTC 后均可原值返回。"""
    for value in (datetime.min.replace(tzinfo=UTC), datetime.max.replace(tzinfo=UTC)):
        assert ensure_utc(value) == value
        assert ensure_utc(value).tzinfo is UTC


def test_input_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    """验证契约：换算前后的输入字段及 tzinfo 不变，不依赖系统时钟或本地时区。"""
    zone = timezone(timedelta(hours=8))
    value = datetime(2026, 10, 22, 8, 30, 12, 123456, tzinfo=zone)
    try:
        with monkeypatch.context() as environment:
            for local_zone in ("Asia/Shanghai", "America/New_York"):
                environment.setenv("TZ", local_zone)
                time.tzset()
                result = ensure_utc(value)
                assert (value.year, value.month, value.day, value.hour, value.minute) == (
                    2026,
                    10,
                    22,
                    8,
                    30,
                )
                assert (value.second, value.microsecond, value.tzinfo) == (12, 123456, zone)
                assert result == datetime(2026, 10, 22, 0, 30, 12, 123456, tzinfo=UTC)
    finally:
        # context 先恢复环境变量，随后同步 C 库的时区状态；断言失败时也不影响后续测试。
        time.tzset()
