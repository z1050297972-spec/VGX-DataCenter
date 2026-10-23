"""工单 02 的契约测试清单，A2 跳过，B 使用临时目录逐项先红后绿。"""

from pathlib import Path

import pytest


def test_source_test_prefix(tmp_path: Path) -> None:
    """验证 W3：仓库 src/ 下公开 test_ 函数仍检查六项。"""
    pytest.skip("A2 契约骨架：派工 B 实现并验证")


def test_script_test_prefix(tmp_path: Path) -> None:
    """验证 W3：仓库 scripts/ 下公开 test_ 函数仍检查六项。"""
    pytest.skip("A2 契约骨架：派工 B 实现并验证")


def test_repository_tests_prefix(tmp_path: Path) -> None:
    """验证 W3：仅仓库根 tests/ 及其子目录的 test_ 函数跳过六项。"""
    pytest.skip("A2 契约骨架：派工 B 实现并验证")


def test_unrelated_tests_directory(tmp_path: Path) -> None:
    """验证 W3：临时目录或 src/ 下名为 tests 的目录不获得豁免。"""
    pytest.skip("A2 契约骨架：派工 B 实现并验证")


def test_scope_independent_of_cwd(tmp_path: Path) -> None:
    """验证 W3：绝对路径、相对路径及切换工作目录不改变判定。"""
    pytest.skip("A2 契约骨架：派工 B 实现并验证")


def test_resolved_symlink_scope(tmp_path: Path) -> None:
    """验证 W3：check_file 按解析后的文件位置判断，不用 tests/ 内软链接扩大豁免。"""
    pytest.skip("A2 契约骨架：派工 B 实现并验证")
