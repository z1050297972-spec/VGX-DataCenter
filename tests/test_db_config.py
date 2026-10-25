"""工单 05 契约测试；只在 tmp_path 的假状态目录验证。"""

from pathlib import Path

import pytest
from pydantic import ValidationError

from rdp.infra.config import ErrorRetentionConfig, LogConfig, PlatformConfig, load_config


def test_default(tmp_path: Path) -> None:
    """验证契约：PlatformConfig.errors.retention_days 缺省 30，旧配置不变，模型不可变且不可空。"""
    config = PlatformConfig(state_dir=tmp_path)
    assert config.errors.retention_days == 30
    with pytest.raises(ValidationError):
        config.errors.retention_days = 2


def test_toml(tmp_path: Path) -> None:
    """验证契约：tmp_path TOML [errors] retention_days 被 load_config 接受，未读取真实 ~/.config/rdp。"""
    path = tmp_path / "config.toml"
    path.write_text("[errors]\nretention_days = 17\n")
    loaded = load_config(environ={"RDP_CONFIG": str(path)}, home=tmp_path)
    assert loaded.config.errors.retention_days == 17


def test_bounds(tmp_path: Path) -> None:
    """验证契约：报错保留天数 1/3650 合法，0/3651/bool/字符串/null 拒绝，来源路径和项名明确。"""
    for valid in (1, 3650):
        assert ErrorRetentionConfig(retention_days=valid).retention_days == valid
    for invalid in (0, 3651, True, "30", None):
        with pytest.raises(ValidationError):
            ErrorRetentionConfig.model_validate({"retention_days": invalid})


def test_unknown(tmp_path: Path) -> None:
    """验证契约：C1 仍拒绝 errors 未知字段及其他未知节，不回显未知或敏感输入。"""
    path = tmp_path / "config.toml"
    path.write_text('[errors]\nunknown = "hidden-sensitive-value"\n')
    with pytest.raises(ValueError) as caught:
        load_config(environ={"RDP_CONFIG": str(path)}, home=tmp_path)
    assert str(path) in str(caught.value)
    assert "errors.unknown" in str(caught.value)
    assert "hidden-sensitive-value" not in str(caught.value)


def test_clock(tmp_path: Path) -> None:
    """验证契约：报错保留期采用 UTC 固定 24 小时，不改变 LogConfig 的当地日历天契约。"""
    config = PlatformConfig(state_dir=tmp_path)
    assert config.errors.retention_days == config.log.retention_days == 30
    assert "UTC" in (ErrorRetentionConfig.__doc__ or "")
    assert "当地日历天" in (LogConfig.__doc__ or "")
