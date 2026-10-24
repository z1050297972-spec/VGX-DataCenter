"""工单 04 的公开契约测试；只用内存输入和临时目录，验证诊断与失败边界。"""

from pathlib import Path
from typing import cast

import httpx
import pytest
from diagnostics_demo import mount_diagnostic_demo
from fastapi.testclient import TestClient

from rdp.api import create_app


def test_mount_demo_only_in_tests() -> None:
    """验证契约：mount_diagnostic_demo 只挂测试app；create_app返回的生产app不存在/api/_diagnostics-demo，配置不新增字段。"""
    production = create_app(None)
    demo = create_app(None)
    mount_diagnostic_demo(demo)
    assert not any("_diagnostics-demo" in getattr(route, "path", "") for route in production.routes)
    assert (
        len([route for route in demo.routes if "_diagnostics-demo" in getattr(route, "path", "")])
        == 5
    )


def test_demo_five_errors() -> None:
    """验证契约：演示的input/conflict/external/defect/validation五条路由分别触发400/409/502/500/422且错误编号可关联日志。"""
    app = create_app(None)
    mount_diagnostic_demo(app)
    with TestClient(app) as client:
        for name, status, category in (
            ("input", 400, "input"),
            ("conflict", 409, "conflict"),
            ("external", 502, "external"),
            ("defect", 500, "defect"),
            ("validation", 422, "input"),
        ):
            response = cast(httpx.Client, client).get("/api/_diagnostics-demo/" + name)
            assert response.status_code == status
            assert response.json()["category"] == category
            assert response.json()["error_id"] == response.headers["X-Request-ID"]


def test_demo_route_order_and_schema() -> None:
    """验证契约：演示路由排在/api兜底前，挂载后清OpenAPI缓存；重复挂载和已启动应用均抛ValueError且不留下部分路由。"""
    app = create_app(None)
    app.openapi()
    mount_diagnostic_demo(app)
    assert app.openapi_schema is None
    assert "/api/_diagnostics-demo/input" in app.openapi()["paths"]
    before = list(app.routes)
    with pytest.raises(ValueError):
        mount_diagnostic_demo(app)
    assert app.routes == before
    started = create_app(None)
    started.middleware_stack = started.build_middleware_stack()
    before = list(started.routes)
    with pytest.raises(ValueError):
        mount_diagnostic_demo(started)
    assert started.routes == before


def test_demo_no_external_effects(tmp_path: Path) -> None:
    """验证契约：演示仅使用内存造诊断和异常；不建socket、不写磁盘、不访问导航层或存储根，不含真实凭据。"""
    app = create_app(None)
    mount_diagnostic_demo(app)
    assert not list(tmp_path.iterdir())
    with TestClient(app) as client:
        response = cast(httpx.Client, client).get("/api/_diagnostics-demo/validation?count=3")
    assert response.status_code == 200 and response.json() == {"count": 3}
    assert not list(tmp_path.iterdir())
