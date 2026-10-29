"""预览状态的契约测试清单（M1-07，L12）：记录与核对。

骨架阶段全部跳过。三样状态各改一处都必须以冲突失败，并且一行都没写。
"""

import pytest


def test_capture_includes_all_entries_and_provenance() -> None:
    """L12：capture_preview_state 对数据集的按任务入口和全部按格式入口各记一份指纹，来源.json 缺失也占一项。"""
    pytest.skip("M1-07：该契约尚未实现")


def test_capture_new_dataset_records_destination_and_max_number() -> None:
    """L12：新增数据集另记目的目录不存在和当时的最大编号。"""
    pytest.skip("M1-07：该契约尚未实现")


def test_capture_unknown_dataset_is_input_error() -> None:
    """契约 capture_preview_state：编号在导航层找不到入口时报 InputError。"""
    pytest.skip("M1-07：该契约尚未实现")


def test_verify_passes_when_nothing_changed() -> None:
    """契约 verify_preview_state：状态没变时通过，且不写任何文件。"""
    pytest.skip("M1-07：该契约尚未实现")


def test_verify_conflicts_when_json_hash_changes() -> None:
    """L12 验收（样一）：改动入口里一份 JSON 的内容（哪怕只多一个空格），冲突失败，诊断指出文件名，导航层一行都没写。"""
    pytest.skip("M1-07：该契约尚未实现")


def test_verify_conflicts_when_entry_names_change() -> None:
    """L12 验收（样二）：入口目录多出或少了一个条目，冲突失败，导航层一行都没写。"""
    pytest.skip("M1-07：该契约尚未实现")


def test_verify_conflicts_when_link_target_changes() -> None:
    """L12 验收（样三）：某条链接的 readlink 改了，冲突失败，导航层一行都没写。"""
    pytest.skip("M1-07：该契约尚未实现")


def test_verify_conflicts_when_entry_added_or_removed() -> None:
    """L12：数据集多了或少了一个按格式入口，冲突失败。"""
    pytest.skip("M1-07：该契约尚未实现")


def test_verify_conflicts_when_destination_appears() -> None:
    """L12：新增数据集的目的目录在预览之后出现，冲突失败。"""
    pytest.skip("M1-07：该契约尚未实现")


def test_verify_conflicts_when_max_number_changes() -> None:
    """L12：新增数据集的最大编号在预览之后变了，冲突失败。"""
    pytest.skip("M1-07：该契约尚未实现")


def test_unverifiable_fingerprints_never_equal() -> None:
    """契约 diff_preview_state：任一方 verifiable=False 时产生 unverifiable 差异，两个不可验证的值不算没变。"""
    pytest.skip("M1-07：该契约尚未实现")


def test_verify_rejects_other_nav_root() -> None:
    """契约 diff_preview_state：nav_root 与预览所用不同时整体视为差异。"""
    pytest.skip("M1-07：该契约尚未实现")


def test_conflict_diagnostic_lists_differences() -> None:
    """契约 verify_preview_state：冲突诊断列出差异（数据集、入口、文件或链接、预期与实际），后果写一行都没写，下一步写重新预览。"""
    pytest.skip("M1-07：该契约尚未实现")


def test_verify_checkpoint_cancellation_propagates() -> None:
    """契约 verify_preview_state：非保护段的 checkpoint 抛出的取消和停止异常原样传播。"""
    pytest.skip("M1-07：该契约尚未实现")
