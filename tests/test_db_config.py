"""工单 05 契约测试清单；骨架阶段逐条跳过，实施阶段只在 tmp_path 的假状态目录验证。"""

from pathlib import Path

import pytest


def test_default(tmp_path: Path) -> None:
    """验证契约：PlatformConfig.errors.retention_days 缺省 30，旧配置不变，模型不可变且不可空。"""
    pytest.skip("工单 05 契约骨架，待批准后逐函数 TDD")


def test_toml(tmp_path: Path) -> None:
    """验证契约：tmp_path TOML [errors] retention_days 被 load_config 接受，未读取真实 ~/.config/rdp。"""
    pytest.skip("工单 05 契约骨架，待批准后逐函数 TDD")


def test_bounds(tmp_path: Path) -> None:
    """验证契约：报错保留天数 1/3650 合法，0/3651/bool/字符串/null 拒绝，来源路径和项名明确。"""
    pytest.skip("工单 05 契约骨架，待批准后逐函数 TDD")


def test_unknown(tmp_path: Path) -> None:
    """验证契约：C1 仍拒绝 errors 未知字段及其他未知节，不回显未知或敏感输入。"""
    pytest.skip("工单 05 契约骨架，待批准后逐函数 TDD")


def test_clock(tmp_path: Path) -> None:
    """验证契约：报错保留期采用 UTC 固定 24 小时，不改变 LogConfig 的当地日历天契约。"""
    pytest.skip("工单 05 契约骨架，待批准后逐函数 TDD")
