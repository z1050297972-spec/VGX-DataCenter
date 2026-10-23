"""工单 02 的契约测试清单，A2 跳过，B 使用临时目录逐项先红后绿。"""

from pathlib import Path

import pytest


def test_deterministic_export(tmp_path: Path) -> None:
    """验证同一应用导出两次逐字节相同，UTF-8、键排序、两空格缩进及末尾换行。"""
    pytest.skip("A2 契约骨架：派工 B 实现并验证")


def test_export_matches_app(tmp_path: Path) -> None:
    """验证导出 JSON 与 create_app(None).openapi() 一致，包含健康响应模型。"""
    pytest.skip("A2 契约骨架：派工 B 实现并验证")


def test_overwrite_export(tmp_path: Path) -> None:
    """验证只覆盖指定输出文件，不创建额外文件或启动服务。"""
    pytest.skip("A2 契约骨架：派工 B 实现并验证")


def test_invalid_output(tmp_path: Path) -> None:
    """验证父目录缺失、目标是目录或写入失败时抛 OSError，不自动建父目录。"""
    pytest.skip("A2 契约骨架：派工 B 实现并验证")


def test_serialization_error(tmp_path: Path) -> None:
    """验证不可序列化值抛 TypeError、非有限数抛 ValueError，原文件不变。"""
    pytest.skip("A2 契约骨架：派工 B 实现并验证")


def test_cli_success(tmp_path: Path) -> None:
    """验证 python -m rdp.api.openapi_export 写入指定相对路径并以 0 退出。"""
    pytest.skip("A2 契约骨架：派工 B 实现并验证")


def test_cli_help(tmp_path: Path) -> None:
    """验证 -h 和 --help 输出帮助且不导出文件，退出 0。"""
    pytest.skip("A2 契约骨架：派工 B 实现并验证")


def test_cli_arguments(tmp_path: Path) -> None:
    """验证缺失、多余或未知参数写 stderr 且退出 2，不写文件。"""
    pytest.skip("A2 契约骨架：派工 B 实现并验证")


def test_cli_export_error(tmp_path: Path) -> None:
    """验证导出失败写 stderr 并包含输出路径和原因，退出 1。"""
    pytest.skip("A2 契约骨架：派工 B 实现并验证")


def test_cli_stream_error(tmp_path: Path) -> None:
    """验证 stdout 或 stderr 写失败时保留 OSError。"""
    pytest.skip("A2 契约骨架：派工 B 实现并验证")


def test_cli_argv_source(tmp_path: Path) -> None:
    """验证显式 argv 不读取进程参数，None 读取 sys.argv[1:]。"""
    pytest.skip("A2 契约骨架：派工 B 实现并验证")
