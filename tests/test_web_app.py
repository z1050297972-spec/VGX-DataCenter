"""工单 02 的契约测试清单，A2 跳过，B 使用临时目录逐项先红后绿。"""

from pathlib import Path

import pytest


def test_health_response(tmp_path: Path) -> None:
    """使用 TestClient 验证 /api/health 返回 200 和固定 ok JSON。"""
    pytest.skip("A2 契约骨架：派工 B 实现并验证")


def test_health_openapi(tmp_path: Path) -> None:
    """使用 TestClient 验证健康响应模型进入 OpenAPI 且仅允许 ok。"""
    pytest.skip("A2 契约骨架：派工 B 实现并验证")


def test_api_only_root(tmp_path: Path) -> None:
    """使用 TestClient 验证 web_dist=None 时首页返回 404。"""
    pytest.skip("A2 契约骨架：派工 B 实现并验证")


def test_spa_root(tmp_path: Path) -> None:
    """使用 TestClient 验证 tmp_path 构建目录首页返回 index.html。"""
    pytest.skip("A2 契约骨架：派工 B 实现并验证")


def test_spa_nested_route(tmp_path: Path) -> None:
    """使用 TestClient 验证不存在的嵌套路由 GET 返回 index.html。"""
    pytest.skip("A2 契约骨架：派工 B 实现并验证")


def test_static_file(tmp_path: Path) -> None:
    """使用 TestClient 验证 tmp_path 中静态文件原样返回。"""
    pytest.skip("A2 契约骨架：派工 B 实现并验证")


def test_unknown_api(tmp_path: Path) -> None:
    """使用 TestClient 验证 /api 和未知 /api/ 路径是 404 JSON，不回退 HTML。"""
    pytest.skip("A2 契约骨架：派工 B 实现并验证")


def test_non_get_no_fallback(tmp_path: Path) -> None:
    """使用 TestClient 验证非 GET 请求不使用 SPA 回退。"""
    pytest.skip("A2 契约骨架：派工 B 实现并验证")


def test_static_boundary(tmp_path: Path) -> None:
    """使用 TestClient 验证路径穿越及越界软链接不能读取构建目录外文件。"""
    pytest.skip("A2 契约骨架：派工 B 实现并验证")


def test_missing_dist(tmp_path: Path) -> None:
    """验证不存在的构建目录在 create_app 调用时抛 FileNotFoundError。"""
    pytest.skip("A2 契约骨架：派工 B 实现并验证")


def test_dist_is_file(tmp_path: Path) -> None:
    """验证构建路径是普通文件时在创建阶段抛 NotADirectoryError。"""
    pytest.skip("A2 契约骨架：派工 B 实现并验证")


def test_missing_index(tmp_path: Path) -> None:
    """验证缺少 index.html 时在创建阶段抛 FileNotFoundError。"""
    pytest.skip("A2 契约骨架：派工 B 实现并验证")


def test_index_is_directory(tmp_path: Path) -> None:
    """验证 index.html 是目录时在创建阶段抛 ValueError。"""
    pytest.skip("A2 契约骨架：派工 B 实现并验证")


def test_index_symlink_outside(tmp_path: Path) -> None:
    """验证 index.html 软链接指向构建目录外时创建应用抛 ValueError。"""
    pytest.skip("A2 契约骨架：派工 B 实现并验证")


def test_dist_permission_error(tmp_path: Path) -> None:
    """验证构建目录状态读取失败时保留 OSError，不伪装为缺失。"""
    pytest.skip("A2 契约骨架：派工 B 实现并验证")


def test_relative_dist(tmp_path: Path) -> None:
    """验证相对构建路径以创建时工作目录解释。"""
    pytest.skip("A2 契约骨架：派工 B 实现并验证")


def test_independent_apps(tmp_path: Path) -> None:
    """验证多个应用的托管目录相互独立且创建不写文件或建立 socket。"""
    pytest.skip("A2 契约骨架：派工 B 实现并验证")
