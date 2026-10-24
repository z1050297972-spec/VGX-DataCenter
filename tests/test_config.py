"""工单 03 契约测试清单，骨架阶段逐项跳过；所有文件样例限于 tmp_path。"""

import tomllib
from dataclasses import FrozenInstanceError
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from rdp.infra.config import LogConfig, PlatformConfig, WebConfig, load_config


def test_missing_default_file(tmp_path: Path) -> None:
    """验证契约：验收 1/C1：注入空环境和 tmp_path home，缺省文件不存在时返回全部默认值及 used_defaults=True。"""
    loaded = load_config(environ={}, home=tmp_path)
    assert loaded.used_defaults is True
    assert loaded.source == tmp_path / ".config/rdp/config.toml"
    assert loaded.config.state_dir == tmp_path / ".local/share/rdp"
    assert loaded.config.web.host == "0.0.0.0"  # noqa: S104  # 理由：核对获批的缺省监听地址。
    assert loaded.config.web.port == 8600
    assert loaded.config.log.level == "INFO"
    assert loaded.config.log.retention_days == 30
    assert not (tmp_path / ".local").exists()


def test_explicit_config(tmp_path: Path) -> None:
    """验证契约：验收 1：RDP_CONFIG 指向 tmp_path 内 TOML，五个字段全部生效且 source 为指定绝对路径。"""
    source = tmp_path / "chosen.toml"
    source.write_text(
        f'state_dir = "{tmp_path}/state"\n[web]\nhost = "127.0.0.1"\nport = 9001\n[log]\nlevel = "DEBUG"\nretention_days = 7\n',
        encoding="utf-8",
    )
    loaded = load_config(environ={"RDP_CONFIG": str(source)}, home=tmp_path)
    assert loaded.source == source
    assert not loaded.used_defaults
    assert loaded.config.state_dir == tmp_path / "state"
    assert loaded.config.web.host == "127.0.0.1"
    assert loaded.config.web.port == 9001
    assert loaded.config.log.level == "DEBUG"
    assert loaded.config.log.retention_days == 7


def test_empty_environment_value(tmp_path: Path) -> None:
    """验证契约：C1/C2：RDP_CONFIG 空串使用缺省位置；不读真实环境或真实 home。"""
    loaded = load_config(environ={"RDP_CONFIG": ""}, home=tmp_path)
    assert loaded.used_defaults
    assert loaded.source == tmp_path / ".config/rdp/config.toml"


def test_only_one_environment_variable(tmp_path: Path) -> None:
    """验证契约：C2：环境中的端口、日志、HOME、XDG 配置变量都不覆盖文件或注入 home。"""
    source = tmp_path / "config.toml"
    source.write_text("[web]\nport = 9321\n", encoding="utf-8")
    environ = {
        "RDP_CONFIG": str(source),
        "RDP_WEB_PORT": "7777",
        "RDP_LOG_LEVEL": "ERROR",
        "HOME": "/not-the-home",
        "XDG_CONFIG_HOME": "/not-config",
    }
    loaded = load_config(environ=environ, home=tmp_path)
    assert loaded.config.web.port == 9321
    assert loaded.config.log.level == "INFO"
    assert loaded.config.state_dir == tmp_path / ".local/share/rdp"


def test_missing_explicit_file(tmp_path: Path) -> None:
    """验证契约：load_config Raises：非空 RDP_CONFIG 文件缺失抛含文件名的 FileNotFoundError，不回退。"""
    source = tmp_path / "missing.toml"
    with pytest.raises(FileNotFoundError) as caught:
        load_config(environ={"RDP_CONFIG": str(source)}, home=tmp_path)
    assert caught.value.filename == str(source)


def test_empty_and_partial_file(tmp_path: Path) -> None:
    """验证契约：load_config 返回：空 TOML、空 web/log 表及部分字段文件补默认值，used_defaults 均为 False。"""
    source = tmp_path / ".config/rdp/config.toml"
    source.parent.mkdir(parents=True)
    for contents in ("", "[web]\n[log]\n", "[web]\nport = 8600\n"):
        source.write_text(contents, encoding="utf-8")
        loaded = load_config(environ={}, home=tmp_path)
        assert not loaded.used_defaults
        assert loaded.config.web.port == 8600
        assert loaded.config.log.retention_days == 30


def test_strict_types(tmp_path: Path) -> None:
    """验证契约：验收 1：端口字符串、bool、浮点及各叶子字段错类型逐项报 ValueError，含文件、项名、实际和期望。"""
    source = tmp_path / "bad.toml"
    for content, item, actual in (
        ("[web]\nport = '8600'", "web.port", "8600"),
        ("[web]\nport = true", "web.port", "True"),
        ("[web]\nport = 1.5", "web.port", "1.5"),
        ("[web]\nhost = 42", "web.host", "42"),
        ("[log]\nlevel = 3", "log.level", "3"),
        ("[log]\nretention_days = false", "log.retention_days", "False"),
        ("state_dir = 5", "state_dir", "5"),
    ):
        source.write_text(content, encoding="utf-8")
        with pytest.raises(ValueError) as caught:
            load_config(environ={"RDP_CONFIG": str(source)}, home=tmp_path)
        message = str(caught.value)
        assert str(source) in message
        assert item in message and actual in message
        assert "实际" in message and "期望" in message


def test_unknown_fields(tmp_path: Path) -> None:
    """验证契约：验收 1：顶层、web、log 的未知字段均拒绝，指出完整点分项名，实际值显示已隐藏。"""
    source = tmp_path / "unknown.toml"
    for text, item in (
        ("unknown = 'hidden-value'", "unknown"),
        ("[web]\nunknown = 7", "web.unknown"),
        ("[log]\nunknown = true", "log.unknown"),
    ):
        source.write_text(text, encoding="utf-8")
        with pytest.raises(ValueError) as caught:
            load_config(environ={"RDP_CONFIG": str(source)}, home=tmp_path)
        assert str(source) in str(caught.value)
        assert item in str(caught.value) and "实际 <已隐藏>" in str(caught.value)
        assert "hidden-value" not in str(caught.value)


def test_port_boundaries(tmp_path: Path) -> None:
    """验证契约：WebConfig：端口 1/65535 合法，0/65536 非法；load_config 转 ValueError，直接模型报 ValidationError。"""
    source = tmp_path / "port.toml"
    for port in (1, 65535):
        assert WebConfig(port=port).port == port
    for port in (0, 65536):
        with pytest.raises(ValidationError):
            WebConfig(port=port)
        source.write_text(f"[web]\nport = {port}\n", encoding="utf-8")
        with pytest.raises(ValueError, match="web.port") as caught:
            load_config(environ={"RDP_CONFIG": str(source)}, home=tmp_path)
        assert type(caught.value) is ValueError


def test_host_constraints(tmp_path: Path) -> None:
    """验证契约：WebConfig：IPv4、IPv6、localhost 合法；空串、空白、斜杠、反斜杠、NUL、254 字符非法，253 字符合法。"""
    for host in ("127.0.0.1", "::1", "localhost", "a" * 253):
        assert WebConfig(host=host).host == host
    for host in ("", "a b", "a/b", "a\\b", "a\x00b", "a" * 254):
        with pytest.raises(ValidationError):
            WebConfig(host=host)


def test_log_level_options(tmp_path: Path) -> None:
    """验证契约：LogConfig：四个大写级别合法，小写或其他级别非法；默认 INFO。"""
    for level in ("DEBUG", "INFO", "WARNING", "ERROR"):
        assert LogConfig.model_validate({"level": level}).level == level
    for level in ("debug", "CRITICAL", "", 20):
        with pytest.raises(ValidationError):
            LogConfig.model_validate({"level": level})
    assert LogConfig().level == "INFO"


def test_retention_boundaries(tmp_path: Path) -> None:
    """验证契约：C3/LogConfig：1/3650 天合法，0/3651/bool 非法；默认 30，模型不可经赋值修改。"""
    for days in (1, 3650):
        assert LogConfig(retention_days=days).retention_days == days
    for days in (0, 3651, True):
        with pytest.raises(ValidationError):
            LogConfig(retention_days=days)
    assert LogConfig().retention_days == 30
    with pytest.raises(ValidationError):
        cast(Any, LogConfig()).retention_days = 7


def test_immutable_nested_models(tmp_path: Path) -> None:
    """验证契约：配置及 web/log 冻结，LoadedConfig 冻结；修改返回对象不能改变已生效设置。"""
    loaded = load_config(environ={}, home=tmp_path)
    for obj, key, value in (
        (loaded.config, "state_dir", tmp_path / "other"),
        (loaded.config.web, "port", 80),
        (loaded.config.log, "level", "DEBUG"),
    ):
        with pytest.raises(ValidationError):
            setattr(obj, key, value)
    with pytest.raises(FrozenInstanceError):
        cast(Any, loaded).used_defaults = False
    assert loaded.config.web.port == 8600


def test_expand_home_paths(tmp_path: Path) -> None:
    """验证契约：load_config 返回：配置位置与 state_dir 的 ~、~/ 仅展开注入 home，返回绝对 Path，不解析软链接。"""
    source = tmp_path / "config.toml"
    source.write_text('state_dir = "~/state"', encoding="utf-8")
    loaded = load_config(environ={"RDP_CONFIG": "~/config.toml"}, home=tmp_path)
    assert loaded.source == source
    assert loaded.config.state_dir == tmp_path / "state"
    source.write_text('state_dir = "~"', encoding="utf-8")
    assert (
        load_config(environ={"RDP_CONFIG": str(source)}, home=tmp_path).config.state_dir == tmp_path
    )
    link = tmp_path / "link"
    link.symlink_to(tmp_path / "missing", target_is_directory=True)
    source.write_text(f'state_dir = "{link}"', encoding="utf-8")
    assert load_config(environ={"RDP_CONFIG": str(source)}, home=tmp_path).config.state_dir == link


def test_reject_invalid_paths(tmp_path: Path) -> None:
    """验证契约：load_config Raises：相对路径、~其他用户、NUL、.. 分量拒绝；home 错误来源标为 <arguments>。"""
    for home in (Path("relative"), tmp_path / "..", tmp_path / "bad\x00"):
        with pytest.raises(ValueError, match="<arguments>"):
            load_config(environ={}, home=home)
    for value in ("relative", "~someone/config.toml", str(tmp_path / ".." / "x"), "bad\x00"):
        with pytest.raises(ValueError, match="RDP_CONFIG"):
            load_config(environ={"RDP_CONFIG": value}, home=tmp_path)
    source = tmp_path / "paths.toml"
    for value in ("relative", "~someone/state", str(tmp_path / ".." / "x")):
        source.write_text(f'state_dir = "{value}"', encoding="utf-8")
        with pytest.raises(ValueError) as caught:
            load_config(environ={"RDP_CONFIG": str(source)}, home=tmp_path)
        assert str(source) in str(caught.value) and "state_dir" in str(caught.value)


def test_state_dir_validator_valid(tmp_path: Path) -> None:
    """验证契约：validate_state_dir 返回：绝对 Path 原值返回，不访问文件系统，不要求路径已存在。"""
    value = tmp_path / "not-created"
    assert PlatformConfig.validate_state_dir(value) == value
    assert not value.exists()


def test_state_dir_validator_invalid(tmp_path: Path) -> None:
    """验证契约：validate_state_dir Raises：相对路径、NUL、.. 报 ValueError；模型边界包装成 ValidationError。"""
    for value in (Path("relative"), tmp_path / "bad\x00name", tmp_path / ".." / "outside"):
        with pytest.raises(ValueError):
            PlatformConfig.validate_state_dir(value)
        with pytest.raises(ValidationError):
            PlatformConfig(state_dir=value)


def test_toml_syntax_error(tmp_path: Path) -> None:
    """验证契约：load_config Raises：坏 TOML 报 ValueError，含文件、<document>、行列和期望，不回显整份文档。"""
    source = tmp_path / "syntax.toml"
    source.write_text("[web\nport = 8", encoding="utf-8")
    with pytest.raises(ValueError) as caught:
        load_config(environ={"RDP_CONFIG": str(source)}, home=tmp_path)
    message = str(caught.value)
    assert str(source) in message and "<document>" in message
    assert "实际" in message and "期望" in message
    assert "[web" not in message
    assert caught.value.__cause__ is not None


def test_invalid_utf8(tmp_path: Path) -> None:
    """验证契约：load_config Raises：非法 UTF-8 报 ValueError，含文件、编码位置和期望，保留原因链。"""
    source = tmp_path / "encoding.toml"
    source.write_bytes(b"host = '\xff'\n")
    with pytest.raises(ValueError) as caught:
        load_config(environ={"RDP_CONFIG": str(source)}, home=tmp_path)
    assert str(source) in str(caught.value) and "<document>" in str(caught.value)
    assert "期望" in str(caught.value) and "UTF-8" in str(caught.value)
    assert isinstance(caught.value.__cause__, UnicodeDecodeError)


def test_configuration_read_errors(tmp_path: Path) -> None:
    """验证契约：load_config Raises：目录代替文件、无读取权限及其他 OSError 保留路径和原因；使用文件边界替身。"""
    with pytest.raises(IsADirectoryError):
        load_config(environ={"RDP_CONFIG": str(tmp_path)}, home=tmp_path)
    source = tmp_path / "cannot-read.toml"
    for error in (PermissionError(13, "不可读", str(source)), OSError(5, "读取失败", str(source))):
        with patch.object(Path, "open", side_effect=error), pytest.raises(OSError) as caught:
            load_config(environ={"RDP_CONFIG": str(source)}, home=tmp_path)
        assert caught.value is error


def test_validation_error_translation(tmp_path: Path) -> None:
    """验证契约：load_config：pydantic 多项错误逐项转换为一个 ValueError，保留 __cause__，不直接输出原 ValidationError。"""
    source = tmp_path / "many.toml"
    source.write_text("[web]\nport = -1\nhost = ''\n[log]\nlevel = 'bad'", encoding="utf-8")
    with pytest.raises(ValueError) as caught:
        load_config(environ={"RDP_CONFIG": str(source)}, home=tmp_path)
    assert type(caught.value) is ValueError
    assert isinstance(caught.value.__cause__, ValidationError)
    for item in ("web.port", "web.host", "log.level"):
        assert item in str(caught.value)
    assert str(caught.value).count("配置文件") == 3


def test_sensitive_error_values(tmp_path: Path) -> None:
    """验证契约：规范 6.10：未知令牌字段和已知字段的容器载荷均不回显；异常链隐藏模型输入，不泄露嵌套口令。"""
    source = tmp_path / "secret.toml"
    source.write_text(
        "token = 'private-marker'\n[web]\nhost = {password = 'nested-marker'}", encoding="utf-8"
    )
    with pytest.raises(ValueError) as caught:
        load_config(environ={"RDP_CONFIG": str(source)}, home=tmp_path)
    for error in (caught.value, caught.value.__cause__):
        assert "private-marker" not in str(error)
        assert "nested-marker" not in str(error)
    assert "<已隐藏>" in str(caught.value)


def test_load_read_only(tmp_path: Path) -> None:
    """验证契约：load_config 副作用：成功或失败均不建目录、不改环境、不写文件、不打日志，不读取第二份配置。"""
    source = tmp_path / "config.toml"
    source.write_text("[web]\nport = 9456", encoding="utf-8")
    environ = {"RDP_CONFIG": str(source)}
    before = source.read_bytes()
    with patch("pathlib.Path.home", side_effect=AssertionError("禁止真实 home")):
        loaded = load_config(environ=environ, home=tmp_path)
    assert loaded.config.web.port == 9456
    assert source.read_bytes() == before
    assert environ == {"RDP_CONFIG": str(source)}
    assert list(tmp_path.iterdir()) == [source]


def test_snapshot_requires_reload(tmp_path: Path) -> None:
    """验证契约：load_config 时间语义：返回后修改 tmp_path TOML 不影响旧对象，再调用才读取新值。"""
    source = tmp_path / "config.toml"
    source.write_text("[web]\nport = 9100", encoding="utf-8")
    first = load_config(environ={"RDP_CONFIG": str(source)}, home=tmp_path)
    source.write_text("[web]\nport = 9200", encoding="utf-8")
    second = load_config(environ={"RDP_CONFIG": str(source)}, home=tmp_path)
    assert first.config.web.port == 9100
    assert second.config.web.port == 9200


def test_toml_error_without_position_has_safe_fallback(tmp_path: Path) -> None:
    """验证评审 3：解析器文案没有位置时仍报告文件、文档项和期望，不回显未知文案。"""
    source = tmp_path / "changed-message.toml"
    source.write_text("", encoding="utf-8")
    parser_error = tomllib.TOMLDecodeError("文案已改变：不应回显的文档片段")
    with patch("tomllib.load", side_effect=parser_error), pytest.raises(ValueError) as caught:
        load_config(environ={"RDP_CONFIG": str(source)}, home=tmp_path)
    message = str(caught.value)
    assert str(source) in message and "<document>" in message
    assert "实际 位置未知" in message
    assert "期望合法 UTF-8 TOML" in message and "拒绝启动" in message
    assert "不应回显的文档片段" not in message
    assert caught.value.__cause__ is parser_error
