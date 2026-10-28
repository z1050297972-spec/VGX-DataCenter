"""存储配置契约清单（10、验收4），只用临时配置和注入home。"""

import pytest


def test_defaults() -> None:
    """验证默认导航位置来自 DEFAULT_NAV_ROOT、根列表为空、只读默认和十秒预算，无本机盘默认值。"""
    pytest.skip("工单10：等待契约实现")


def test_duplicate_names() -> None:
    """验收4：两个不同路径使用同名根时拒绝启动，单条错误含来源、storage_roots 项名、实际和期望。"""
    pytest.skip("工单10：等待契约实现")


def test_relative_path() -> None:
    """验收4：根路径为相对路径时单条配置错误拒绝启动，诊断含来源和数组位置。"""
    pytest.skip("工单10：等待契约实现")


def test_overlapping_paths() -> None:
    """验收4：根路径相等、父子互换各拒绝；相同字符串前缀但不同路径分量的兄弟目录合法。"""
    pytest.skip("工单10：等待契约实现")


def test_nav_home_expansion() -> None:
    """验证 nav_root 绝对路径、~、~/ 使用注入 home 展开，不读进程home、不解析软链接或要求目录存在。"""
    pytest.skip("工单10：等待契约实现")


def test_invalid_nav_path() -> None:
    """验证 nav_root 相对路径、~其他用户、NUL、.. 被拒绝，错误沿用配置来源格式。"""
    pytest.skip("工单10：等待契约实现")


def test_root_path_rejects_home_and_parent() -> None:
    """验证根 path 不展开 ~，拒绝 NUL 与 ..；从 TOML 字符串转绝对 Path，不探测真实目录。"""
    pytest.skip("工单10：等待契约实现")


def test_mount_source_exclusive() -> None:
    """验证 uuid 与 nfs_export 同填或都缺失各拒绝；恰好填一个合法来源才接受。"""
    pytest.skip("工单10：等待契约实现")


def test_uuid_shape() -> None:
    """验证标准小写连字符 UUID 合法，错误长度、非法字符、路径穿越与非标准大小写拒绝。"""
    pytest.skip("工单10：等待契约实现")


def test_nfs_export_shape() -> None:
    """验证主机:/绝对目录及带方括号 IPv6 合法，空主机、相对导出、空白、NUL 拒绝，不做DNS归一化。"""
    pytest.skip("工单10：等待契约实现")


def test_name_pattern() -> None:
    """验证 name 复用 JOB_TYPE_KEY_PATTERN，首字母、长度1与64合法，长度65、斜杠、空白和非字符串拒绝。"""
    pytest.skip("工单10：等待契约实现")


def test_timeout_bounds() -> None:
    """验证超时0.1和60秒含端点，整数秒允许；越界、bool、字符串、NaN和无穷值拒绝。"""
    pytest.skip("工单10：等待契约实现")


def test_strict_immutable_models() -> None:
    """验证 storage_roots 为不可变元组，各层字段冻结且未知项拒绝，writable 不把整数或字符串转bool。"""
    pytest.skip("工单10：等待契约实现")


def test_configuration_diagnostics_hide_containers() -> None:
    """验证新字段错误包含文件路径、点分项名及期望，整个根列表和未知字段值不回显。"""
    pytest.skip("工单10：等待契约实现")
