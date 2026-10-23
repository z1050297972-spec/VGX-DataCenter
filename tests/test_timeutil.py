"""UTC 规范化的契约测试清单；A2 只收集并跳过，派工 B 逐条用 TDD 实现。"""

import pytest


def test_positive_offset() -> None:
    """验证契约：2026-10-22 08:30:00+08:00 换算为当天 00:30:00 UTC。"""
    pytest.skip("A2 契约骨架，派工 B 用 TDD 实现")


def test_negative_offset() -> None:
    """验证契约：2026-10-22 23:30:00-02:00 换算为次日 01:30:00 UTC。"""
    pytest.skip("A2 契约骨架，派工 B 用 TDD 实现")


def test_already_utc() -> None:
    """验证契约：UTC 输入保持时刻和值不变，返回 tzinfo 为 datetime.UTC。"""
    pytest.skip("A2 契约骨架，派工 B 用 TDD 实现")


def test_microseconds() -> None:
    """验证契约：偏移时区输入的 123456 微秒不截断、不舍入。"""
    pytest.skip("A2 契约骨架，派工 B 用 TDD 实现")


def test_naive_rejected() -> None:
    """验证契约：tzinfo 为 None 时抛 ValueError，不默认采用本地时区。"""
    pytest.skip("A2 契约骨架，派工 B 用 TDD 实现")


def test_missing_offset_rejected() -> None:
    """验证契约：tzinfo 非空但 utcoffset() 为 None 时仍抛 ValueError。"""
    pytest.skip("A2 契约骨架，派工 B 用 TDD 实现")


def test_lower_overflow() -> None:
    """验证契约：0001-01-01 00:00:00+00:01 换算低于下界时抛 OverflowError。"""
    pytest.skip("A2 契约骨架，派工 B 用 TDD 实现")


def test_upper_overflow() -> None:
    """验证契约：9999-12-31 23:59:59.999999-00:01 超过上界时抛 OverflowError。"""
    pytest.skip("A2 契约骨架，派工 B 用 TDD 实现")


def test_representable_limits() -> None:
    """验证契约：datetime.min、datetime.max 附上 UTC 后均可原值返回。"""
    pytest.skip("A2 契约骨架，派工 B 用 TDD 实现")


def test_input_unchanged() -> None:
    """验证契约：换算前后的输入字段及 tzinfo 不变，不依赖系统时钟或本地时区。"""
    pytest.skip("A2 契约骨架，派工 B 用 TDD 实现")
