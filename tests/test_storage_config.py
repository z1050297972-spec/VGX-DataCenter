"""存储配置契约清单（10、验收4），只用临时配置和注入home。"""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from rdp.infra.config import (
    DEFAULT_NAV_ROOT,
    PlatformConfig,
    StorageConfig,
    StorageRootConfig,
    load_config,
)

UUID = "12345678-1234-1234-1234-123456789abc"


def _root(path: Path, **changes: object) -> StorageRootConfig:
    """通过公开模型构造登记，允许测试注入不可信字段。"""
    return StorageRootConfig.model_validate({"name": "disk", "path": path, "uuid": UUID, **changes})


def _load(tmp_path: Path, text: str) -> PlatformConfig:
    """配置始终写临时文件，home同样显式注入。"""
    source = tmp_path / "config.toml"
    source.write_text(text, encoding="utf-8")
    return load_config(environ={"RDP_CONFIG": str(source)}, home=tmp_path).config


def _entry(path: str, name: str = "disk") -> str:
    """用JSON兼容的TOML基本字符串保留特殊路径字符。"""
    return f'[[storage_roots]]\nname={json.dumps(name)}\npath={json.dumps(path)}\nuuid="{UUID}"\n'


def test_defaults(tmp_path: Path) -> None:
    """验证默认导航位置来自 DEFAULT_NAV_ROOT、根列表为空、只读默认和十秒预算，无本机盘默认值。"""
    config = _load(tmp_path, "")
    assert config.nav_root == DEFAULT_NAV_ROOT
    assert DEFAULT_NAV_ROOT.parts == ("/", "mnt", "datasets")
    assert config.storage_roots == ()
    assert config.storage.access_timeout_s == 10.0
    assert _root(tmp_path / "disk").writable is False


def test_duplicate_names(tmp_path: Path) -> None:
    """验收4：两个不同路径使用同名根时拒绝启动，单条错误含来源、storage_roots 项名、实际和期望。"""
    with pytest.raises(ValueError) as caught:
        _load(tmp_path, _entry(str(tmp_path / "a")) + _entry(str(tmp_path / "b")))
    message = str(caught.value)
    assert message.count("配置文件") == 1
    assert str(tmp_path / "config.toml") in message
    assert "storage_roots" in message and "名字" in message and "重复" in message
    assert "实际" in message and "期望" in message and "拒绝启动" in message


def test_relative_path(tmp_path: Path) -> None:
    """验收4：根路径为相对路径时单条配置错误拒绝启动，诊断含来源和数组位置。"""
    with pytest.raises(ValueError) as caught:
        _load(tmp_path, _entry("relative/disk"))
    message = str(caught.value)
    assert message.count("配置文件") == 1
    assert str(tmp_path / "config.toml") in message
    assert "storage_roots.0" in message and "绝对路径" in message


def test_overlapping_paths(tmp_path: Path) -> None:
    """验收4：根路径相等、父子互换各拒绝；相同字符串前缀但不同路径分量的兄弟目录合法。"""
    root = tmp_path / "disk"
    for left, right in ((root, root), (root, root / "child"), (root / "child", root)):
        with pytest.raises(ValueError, match="路径.*包含|路径.*相等") as caught:
            _load(tmp_path, _entry(str(left), "a") + _entry(str(right), "b"))
        assert str(caught.value).count("配置文件") == 1
    config = _load(tmp_path, _entry(str(root), "a") + _entry(str(tmp_path / "disk2"), "b"))
    assert [item.name for item in config.storage_roots] == ["a", "b"]


def test_nav_home_expansion(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """验证 nav_root 绝对路径、~、~/ 使用注入 home 展开，不读进程home、不解析软链接或要求目录存在。"""
    monkeypatch.setenv("HOME", str(tmp_path / "wrong"))
    for raw, expected in (
        ("~", tmp_path),
        ("~/nav", tmp_path / "nav"),
        (str(tmp_path / "abs"), tmp_path / "abs"),
    ):
        assert _load(tmp_path, f"nav_root={json.dumps(raw)}").nav_root == expected
    link = tmp_path / "link"
    link.symlink_to(tmp_path / "missing", target_is_directory=True)
    assert _load(tmp_path, f"nav_root={json.dumps(str(link))}").nav_root == link
    assert not (tmp_path / "nav").exists()


def test_invalid_nav_path(tmp_path: Path) -> None:
    """验证 nav_root 相对路径、~其他用户、NUL、.. 被拒绝，错误沿用配置来源格式。"""
    for raw in (
        "relative",
        "~someone/nav",
        str(tmp_path / ".." / "nav"),
        str(tmp_path) + "/bad\x00name",
    ):
        with pytest.raises(ValueError) as caught:
            _load(tmp_path, f"nav_root={json.dumps(raw)}")
        message = str(caught.value)
        assert "nav_root" in message and str(tmp_path / "config.toml") in message
        assert "实际" in message and "期望" in message and "拒绝启动" in message


def test_root_path_rejects_home_and_parent(tmp_path: Path) -> None:
    """验证根 path 不展开 ~，拒绝 NUL 与 ..；从 TOML 字符串转绝对 Path，不探测真实目录。"""
    for raw in ("~/root", str(tmp_path / ".." / "root"), str(tmp_path) + "/x\x00"):
        with pytest.raises(ValueError, match="storage_roots.0"):
            _load(tmp_path, _entry(raw))
    absent = tmp_path / "not-created"
    assert _load(tmp_path, _entry(str(absent))).storage_roots[0].path == absent
    assert not absent.exists()


def test_mount_source_exclusive(tmp_path: Path) -> None:
    """验证 uuid 与 nfs_export 同填或都缺失各拒绝；恰好填一个合法来源才接受。"""
    for changes in ({"uuid": None}, {"nfs_export": "server:/share"}):
        with pytest.raises(ValidationError, match="恰好"):
            _root(tmp_path, **changes)
    assert _root(tmp_path).uuid == UUID
    assert _root(tmp_path, uuid=None, nfs_export="server:/share").nfs_export == "server:/share"


def test_uuid_shape(tmp_path: Path) -> None:
    """验证标准小写连字符 UUID 合法，错误长度、非法字符、路径穿越与非标准大小写拒绝。"""
    assert _root(tmp_path).uuid == UUID
    for value in (
        "",
        UUID[:-1],
        UUID.replace("a", "g"),
        UUID.upper(),
        "../" + UUID,
        UUID.replace("-", ""),
    ):
        with pytest.raises(ValidationError):
            _root(tmp_path, uuid=value)


def test_nfs_export_shape(tmp_path: Path) -> None:
    """验证主机:/绝对目录及带方括号 IPv6 合法，空主机、相对导出、空白、NUL 拒绝，不做DNS归一化。"""
    for value in ("server:/share", "[2001:db8::1]:/share", "nas.example:/"):
        assert _root(tmp_path, uuid=None, nfs_export=value).nfs_export == value
    for value in (
        "",
        ":/share",
        "server:relative",
        "server:/a b",
        "server:/a\x00",
        "2001:db8::1:/share",
        "[broken:/share",
    ):
        with pytest.raises(ValidationError, match="NFS"):
            _root(tmp_path, uuid=None, nfs_export=value)


def test_name_pattern(tmp_path: Path) -> None:
    """验证 name 复用 JOB_TYPE_KEY_PATTERN，首字母、长度1与64合法，长度65、斜杠、空白和非字符串拒绝。"""
    for value in ("a", "a" * 64, "a_2"):
        assert _root(tmp_path, name=value).name == value
    for value in ("", "a" * 65, "2disk", "a/b", "a b", "A", "盘", 1):
        with pytest.raises(ValidationError):
            _root(tmp_path, name=value)


def test_timeout_bounds() -> None:
    """验证超时0.1和60秒含端点，整数秒允许；越界、bool、字符串、NaN和无穷值拒绝。"""
    for value in (0.1, 60.0, 1):
        assert StorageConfig.model_validate({"access_timeout_s": value}).access_timeout_s == value
    for value in (0.099, 60.001, True, "10", float("nan"), float("inf"), -float("inf")):
        with pytest.raises(ValidationError):
            StorageConfig.model_validate({"access_timeout_s": value})


def test_strict_immutable_models(tmp_path: Path) -> None:
    """验证 storage_roots 为不可变元组，各层字段冻结且未知项拒绝，writable 不把整数或字符串转bool。"""
    config = _load(tmp_path, _entry(str(tmp_path / "root")))
    assert isinstance(config.storage_roots, tuple)
    for model, field, replacement in (
        (config, "nav_root", tmp_path),
        (config.storage, "access_timeout_s", 2),
        (config.storage_roots[0], "writable", True),
    ):
        with pytest.raises(ValidationError, match="frozen"):
            setattr(model, field, replacement)
    for value in (1, "false"):
        with pytest.raises(ValidationError):
            _root(tmp_path, writable=value)
    for text in ("surprise=1", "[storage]\nsurprise=1", _entry(str(tmp_path)) + "surprise=1"):
        with pytest.raises(ValueError, match="extra_forbidden"):
            _load(tmp_path, text)


def test_configuration_diagnostics_hide_containers(tmp_path: Path) -> None:
    """验证新字段错误包含文件路径、点分项名及期望，整个根列表和未知字段值不回显。"""
    for text, field in (
        ("[storage]\naccess_timeout_s=99", "storage.access_timeout_s"),
        (_entry(str(tmp_path)) + 'secret="do-not-echo"', "storage_roots.0.secret"),
        ("storage_roots=123", "storage_roots"),
    ):
        with pytest.raises(ValueError) as caught:
            _load(tmp_path, text)
        message = str(caught.value)
        assert str(tmp_path / "config.toml") in message and field in message
        assert "实际 <已隐藏>" in message and "期望" in message
        assert "do-not-echo" not in message and UUID not in message
