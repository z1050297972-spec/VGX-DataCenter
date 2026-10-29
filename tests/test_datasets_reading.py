"""读取契约与记录值；使用既有fake_nav在tmp_path展开后逐项变更，不读取真实数据。"""

import pytest


def test_missing_schema() -> None:
    """验收5：删除schema_version后有效版本为1，原payload仍保留省略状态。"""
    pytest.skip("M1-01：该契约尚未实现")


def test_omitted_version() -> None:
    """验收5：省略version和显式null投影等价，未知字段不被补写或丢弃。"""
    pytest.skip("M1-01：该契约尚未实现")


def test_unknown_fields() -> None:
    """验收5：顶层和嵌套未知字段在读取、索引保存及读取后完整保留。"""
    pytest.skip("M1-01：该契约尚未实现")


def test_invalid_json() -> None:
    """验收5：改坏一份JSON后该文件不可用并有JSON_INVALID五段诊断，其余文件和数据集仍列出。"""
    pytest.skip("M1-01：该契约尚未实现")


def test_missing_required_field() -> None:
    """验收5：删除依赖字段使整份文件不可用，诊断指明入口、文件、字段、后果和下一步。"""
    pytest.skip("M1-01：该契约尚未实现")


def test_invalid_required_type() -> None:
    """读取契约：依赖字段类型错误、布尔schema_version、非法UTF-8、非对象或非有限JSON数值均不生成假投影。"""
    pytest.skip("M1-01：该契约尚未实现")


def test_unreadable_file() -> None:
    """验收5：注入打开文件失败得到JSON_UNREADABLE，数据集和入口不从列表消失。"""
    pytest.skip("M1-01：该契约尚未实现")


def test_all_documents_unavailable() -> None:
    """验收5：三个文件全不可用仍按位置列出入口，dataset_id为空且不编造永久编号。"""
    pytest.skip("M1-01：该契约尚未实现")


def test_derived_fields() -> None:
    """读取契约：入口视图格式版本和links/sources.entry_path以位置推导，文件原值保留供核对。"""
    pytest.skip("M1-01：该契约尚未实现")


def test_source_path_boundary() -> None:
    """读取契约：最长完整路径前缀决定source.entry_path，相似前缀不匹配，无链接覆盖保留direct_path。"""
    pytest.skip("M1-01：该契约尚未实现")


def test_no_target_access() -> None:
    """验收2：将假存储根访问设为抛错，读取导航仍成功；JSON软链接、父目录软链接均不跟随。"""
    pytest.skip("M1-01：该契约尚未实现")


def test_recorded_sizes() -> None:
    """验收6：fake_nav的五个样本均取得第4项已知字节数，期望值从原样本独立写定。"""
    pytest.skip("M1-01：该契约尚未实现")


def test_missing_recorded_size() -> None:
    """验收6：把第4项改为不含全角（N B；的文字时值为None，并出现RECORDED_SIZE_MISSING提示。"""
    pytest.skip("M1-01：该契约尚未实现")


def test_recorded_size_first_match() -> None:
    """验收6：仅提取第4项第一个匹配，零字节合法，重复项、溢出为None，其余13项保持原文。"""
    pytest.skip("M1-01：该契约尚未实现")


def test_read_budgets() -> None:
    """读取契约：单文件超32MiB记该文件不可用，整次超128MiB或入口/目录项超限时拒绝发布部分全量。"""
    pytest.skip("M1-01：该契约尚未实现")


def test_empty_version_directories() -> None:
    """验收2：空lerobot/2.0和2.1不当作数据集；archives映射保留原目录名和中文标点。"""
    pytest.skip("M1-01：该契约尚未实现")
