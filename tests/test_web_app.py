"""工单 02 的公开边界回归测试，只使用临时目录与受控的外部依赖替身。"""

from pathlib import Path
from typing import cast
from unittest.mock import patch

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from httpx import Client, Response
from pydantic import ValidationError

from rdp.api import create_app
from rdp.api.health import HealthResponse


def _request(app: FastAPI, path: str, method: str = "GET") -> Response:
    """用真实 TestClient 观察 HTTP 边界；类型桥接只适配 Starlette 的 httpx 回退。"""
    with TestClient(app) as client:
        return cast(Client, client).request(method, path)


def test_health_response() -> None:
    """使用 TestClient 验证 /api/health 返回 200 和固定 ok JSON。"""
    response = _request(create_app(None), "/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert response.headers["content-type"] == "application/json"


def test_health_openapi(tmp_path: Path) -> None:
    """使用 TestClient 验证健康响应模型进入 OpenAPI 且仅允许 ok。"""
    response = _request(create_app(None), "/openapi.json")
    assert response.status_code == 200
    schema = response.json()
    health = schema["paths"]["/api/health"]["get"]["responses"]["200"]
    assert health["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/HealthResponse"
    }
    assert (
        schema["components"]["schemas"]["HealthResponse"]["properties"]["status"]["const"] == "ok"
    )
    with pytest.raises(ValidationError):
        HealthResponse.model_validate({"status": "failed"})


def test_api_only_root(tmp_path: Path) -> None:
    """使用 TestClient 验证 web_dist=None 时首页返回 404。"""
    response = _request(create_app(None), "/")
    assert response.status_code == 404
    assert response.json() == {"detail": "Not Found"}


def test_spa_root(tmp_path: Path) -> None:
    """使用 TestClient 验证 tmp_path 构建目录首页返回 index.html。"""
    (tmp_path / "index.html").write_text("<main>平台首页</main>", encoding="utf-8")
    response = _request(create_app(tmp_path), "/")
    assert response.status_code == 200
    assert response.text == "<main>平台首页</main>"
    assert response.headers["content-type"].startswith("text/html")


def test_spa_nested_route(tmp_path: Path) -> None:
    """使用 TestClient 验证不存在的嵌套路由 GET 返回 index.html。"""
    (tmp_path / "index.html").write_text("<main>前端路由入口</main>", encoding="utf-8")
    response = _request(create_app(tmp_path), "/datasets/x")
    assert response.status_code == 200
    assert response.text == "<main>前端路由入口</main>"


def test_static_file(tmp_path: Path) -> None:
    """使用 TestClient 验证 tmp_path 中静态文件原样返回。"""
    (tmp_path / "index.html").write_text("首页", encoding="utf-8")
    expected = b"console.log('static asset');\n"
    (tmp_path / "app.js").write_bytes(expected)
    response = _request(create_app(tmp_path), "/app.js")
    assert response.status_code == 200
    assert response.content == expected
    assert "javascript" in response.headers["content-type"]


def test_unknown_api(tmp_path: Path) -> None:
    """使用 TestClient 验证 /api 和未知 /api/ 路径是 404 JSON，不回退 HTML。"""
    (tmp_path / "index.html").write_text("不能返回的首页", encoding="utf-8")
    (tmp_path / "api").mkdir()
    (tmp_path / "api" / "asset.txt").write_text("不能作为 API 返回", encoding="utf-8")
    for directory in (None, tmp_path):
        app = create_app(directory)
        for path in ("/api", "/api/不存在", "/api/asset.txt"):
            response = _request(app, path)
            assert response.status_code == 404
            assert response.json() == {"detail": "Not Found"}


def test_api_404_preserves_detail(tmp_path: Path) -> None:
    """验证 API 404 契约：接口抛出的业务 detail 和响应头原样保留，不回退为首页。"""
    (tmp_path / "index.html").write_text("不能返回的首页", encoding="utf-8")
    app = create_app(tmp_path)

    def missing_record() -> None:
        """通过真实接口抛出带业务上下文的 404。"""
        raise HTTPException(
            status_code=404,
            detail={"reason": "记录不存在", "record_id": "missing"},
            headers={"X-Error-Source": "record"},
        )

    app.add_api_route("/api/missing-record", missing_record, methods=["GET"])
    # 后加的测试接口须排在兜底路由与静态挂载之前，确保请求真正进入抛错接口。
    app.router.routes.insert(0, app.router.routes.pop())
    response = _request(app, "/api/missing-record")
    assert response.status_code == 404
    assert response.json() == {"detail": {"reason": "记录不存在", "record_id": "missing"}}
    assert response.headers["content-type"] == "application/json"
    assert response.headers["X-Error-Source"] == "record"


def test_non_get_no_fallback(tmp_path: Path) -> None:
    """使用 TestClient 验证非 GET 请求不使用 SPA 回退。"""
    (tmp_path / "index.html").write_text("首页", encoding="utf-8")
    app = create_app(tmp_path)
    for method in ("POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"):
        response = _request(app, "/datasets/x", method)
        assert response.status_code in (404, 405)
        assert response.content != "首页".encode()


def test_static_boundary(tmp_path: Path) -> None:
    """使用 TestClient 验证路径穿越及越界软链接不能读取构建目录外文件。"""
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("安全首页", encoding="utf-8")
    secret = tmp_path / "secret.txt"
    secret.write_text("目录外内容不可读取", encoding="utf-8")
    (dist / "escape.txt").symlink_to(secret)
    app = create_app(dist)
    for path in ("/%2e%2e/secret.txt", "/escape.txt"):
        response = _request(app, path)
        assert "目录外内容不可读取" not in response.text
        assert response.status_code in (200, 404)
    assert secret.read_text(encoding="utf-8") == "目录外内容不可读取"


def test_missing_dist(tmp_path: Path) -> None:
    """验证不存在的构建目录在 create_app 调用时抛 FileNotFoundError。"""
    with pytest.raises(FileNotFoundError):
        create_app(tmp_path / "missing")


def test_dist_is_file(tmp_path: Path) -> None:
    """验证构建路径是普通文件时在创建阶段抛 NotADirectoryError。"""
    target = tmp_path / "dist"
    target.write_text("不是目录", encoding="utf-8")
    with pytest.raises(NotADirectoryError):
        create_app(target)


def test_missing_index(tmp_path: Path) -> None:
    """验证缺少 index.html 时在创建阶段抛 FileNotFoundError。"""
    with pytest.raises(FileNotFoundError):
        create_app(tmp_path)


def test_index_is_directory(tmp_path: Path) -> None:
    """验证 index.html 是目录时在创建阶段抛 ValueError。"""
    (tmp_path / "index.html").mkdir()
    with pytest.raises(ValueError, match="index.html"):
        create_app(tmp_path)


def test_index_symlink_outside(tmp_path: Path) -> None:
    """验证 index.html 软链接指向构建目录外时创建应用抛 ValueError。"""
    dist = tmp_path / "dist"
    dist.mkdir()
    outside = tmp_path / "outside.html"
    outside.write_text("外部页面", encoding="utf-8")
    (dist / "index.html").symlink_to(outside)
    with pytest.raises(ValueError, match="index.html"):
        create_app(dist)


def test_dist_permission_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """验证构建目录状态读取失败时保留 OSError，不伪装为缺失。"""
    original_stat = Path.stat

    def denied(path: Path, *, follow_symlinks: bool = True):
        """只在文件系统边界模拟权限失败，避免依赖测试执行账号的权限。"""
        if path == tmp_path:
            raise PermissionError("构建目录不可读")
        return original_stat(path, follow_symlinks=follow_symlinks)

    monkeypatch.setattr(Path, "stat", denied)
    with pytest.raises(PermissionError, match="构建目录不可读"):
        create_app(tmp_path)


def test_relative_dist(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """验证相对构建路径以创建时工作目录解释。"""
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("创建时的页面", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    app = create_app(Path("dist"))
    monkeypatch.chdir(dist)
    response = _request(app, "/")
    assert response.status_code == 200
    assert response.text == "创建时的页面"


def test_independent_apps(tmp_path: Path) -> None:
    """验证多个应用的托管目录相互独立且创建不写文件或建立 socket。"""
    first = tmp_path / "first"
    second = tmp_path / "second"
    for directory, text in ((first, "第一份"), (second, "第二份")):
        directory.mkdir()
        (directory / "index.html").write_text(text, encoding="utf-8")
    before = {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    # 只在创建阶段拦截系统边界；TestClient 本身的本地线程通信不属于应用创建。
    with patch("socket.socket", side_effect=AssertionError("创建应用不得建立 socket")):
        first_app = create_app(first)
        second_app = create_app(second)
    assert _request(first_app, "/").text == "第一份"
    assert _request(second_app, "/").text == "第二份"
    assert {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()} == before


def test_api_namespace_all_methods(tmp_path: Path) -> None:
    """验证 API 命名空间契约：非 GET 也不能读取同名静态文件，未知接口返回 JSON 404。"""
    (tmp_path / "index.html").write_text("首页", encoding="utf-8")
    (tmp_path / "api").mkdir()
    (tmp_path / "api" / "asset.txt").write_text("静态内容", encoding="utf-8")
    app = create_app(tmp_path)
    for method in ("HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "TRACE"):
        for path in ("/api", "/api/不存在", "/api/asset.txt"):
            response = _request(app, path, method)
            assert response.status_code == 404
            assert response.headers["content-type"] == "application/json"
            if method != "HEAD":
                assert response.json() == {"detail": "Not Found"}


def test_custom_404_does_not_override_spa(tmp_path: Path) -> None:
    """验证 SPA 回退契约：构建目录自带 404.html 也不能代替首页处理前端路由。"""
    (tmp_path / "index.html").write_text("首页路由入口", encoding="utf-8")
    (tmp_path / "404.html").write_text("不能回退到这里", encoding="utf-8")
    response = _request(create_app(tmp_path), "/datasets/x")
    assert response.status_code == 200
    assert response.text == "首页路由入口"
