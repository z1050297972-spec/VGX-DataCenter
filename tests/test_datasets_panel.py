"""面板①②组；每例在fake_nav上改一处，核对对象、规则、级别及五段后果。"""

import pytest


def test_json_unreadable() -> None:
    """验收7①1：文件打不开报JSON_UNREADABLE，需要处理，包含入口和文件身份。"""
    pytest.skip("M1-01：该契约尚未实现")


def test_json_invalid() -> None:
    """验收7①1：JSON解析失败报JSON_INVALID，需要处理，失败入口只计一次。"""
    pytest.skip("M1-01：该契约尚未实现")


def test_required_field() -> None:
    """验收7①1：缺依赖字段报JSON_REQUIRED_FIELD，需要处理，不为同文件每个缺字段重复计失败条目。"""
    pytest.skip("M1-01：该契约尚未实现")


def test_schema_version() -> None:
    """验收7①1：不认识的schema_version报JSON_SCHEMA_VERSION，需要处理，文件不参与下游比较。"""
    pytest.skip("M1-01：该契约尚未实现")


def test_identity_mismatch() -> None:
    """验收7①2：入口三份dataset_id不同报DATASET_ID_MISMATCH，需要处理，保留各原值。"""
    pytest.skip("M1-01：该契约尚未实现")


def test_name_mismatch() -> None:
    """验收7①2：dataset_name不等于目录名报DATASET_NAME_MISMATCH，需要处理；不把dataset_id文本与目录名直接比较。"""
    pytest.skip("M1-01：该契约尚未实现")


def test_duplicate_task_identity() -> None:
    """验收7①2：两个按任务入口同编号报DUPLICATE_TASK_ID，需要处理，均保留且不任取规范副本。"""
    pytest.skip("M1-01：该契约尚未实现")


def test_canonical_missing() -> None:
    """验收7①3：仅有按格式入口报CANONICAL_MISSING，需要处理，仍正常列出。"""
    pytest.skip("M1-01：该契约尚未实现")


def test_unregistered_format() -> None:
    """验收7①4：未知格式目录报FORMAT_UNREGISTERED，需要处理且不进入目标扫描。"""
    pytest.skip("M1-01：该契约尚未实现")


def test_unregistered_top_directory() -> None:
    """验收7①4：假VGX_video目录报TOP_LEVEL_UNREGISTERED，需要处理，非数据集登记目录不扫描。"""
    pytest.skip("M1-01：该契约尚未实现")


def test_unregistered_top_file() -> None:
    """验收7①4：顶层未知文件同样报TOP_LEVEL_UNREGISTERED，需要处理。"""
    pytest.skip("M1-01：该契约尚未实现")


def test_removed_directory() -> None:
    """验收7：已移除目录属于L7登记表，不报未知顶层，不扫描内部入口。"""
    pytest.skip("M1-01：该契约尚未实现")


def test_derived_mismatch() -> None:
    """验收7①5：分别改view/format/version及links和sources的entry_path均报DERIVED_FIELD_MISMATCH，需要处理。"""
    pytest.skip("M1-01：该契约尚未实现")


def test_information_mismatch() -> None:
    """验收7②6：修改格式入口信息正文报INFORMATION_MISMATCH，需要处理，展示仍取规范副本。"""
    pytest.skip("M1-01：该契约尚未实现")


def test_source_subset() -> None:
    """验收7②7：格式入口增加规范副本没有的source_id报SOURCE_SUBSET_MISMATCH，需要处理。"""
    pytest.skip("M1-01：该契约尚未实现")


def test_source_content() -> None:
    """验收7②7：相同source_id的非位置字段（包括数据块format/version及未知字段）改变报SOURCE_CONTENT_MISMATCH。"""
    pytest.skip("M1-01：该契约尚未实现")


def test_dataset_header() -> None:
    """验收7②7：格式入口dataset_name或dataset_roots不同报DATASET_HEADER_MISMATCH，需要处理。"""
    pytest.skip("M1-01：该契约尚未实现")


def test_task_subset() -> None:
    """验收7②7：格式入口增加规范副本没有的task_key报TASK_SUBSET_MISMATCH，需要处理。"""
    pytest.skip("M1-01：该契约尚未实现")


def test_task_content() -> None:
    """验收7②7：同task_key非位置字段不同或非依赖tasks结构损坏报TASK_CONTENT_MISMATCH，不影响宽松读取可用性。"""
    pytest.skip("M1-01：该契约尚未实现")


def test_egopro_subset() -> None:
    """验收7②7：EgoProDemo按格式合法筛去source和task引用不报内容差异；位置字段和省略version不制造误报。"""
    pytest.skip("M1-01：该契约尚未实现")


def test_provenance_missing() -> None:
    """ADR0008：缺来源.json产生PROVENANCE_MISSING提示，数据来源未知，不计作业失败或作业警告。"""
    pytest.skip("M1-01：该契约尚未实现")


def test_aggregation() -> None:
    """验收7：同组级别来源规则完整累计超过10条时只保留前10样例，顺序确定；对象、实际、期望、后果、下一步齐全。"""
    pytest.skip("M1-01：该契约尚未实现")


def test_findings_not_failures() -> None:
    """11 Q14：面板需要处理发现不直接决定作业失败；只有无法完整索引的入口和跳过检查分别进入失败与警告计数。"""
    pytest.skip("M1-01：该契约尚未实现")
