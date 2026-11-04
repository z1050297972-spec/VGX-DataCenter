"""存储根API契约清单（10、L3），所有权限与错误经真实应用测试。"""

import os
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import replace
from datetime import timedelta, timezone
from pathlib import Path
from typing import cast, override
from unittest.mock import Mock

import pytest
from account_api_support import ApiCase, add_actor, api_case
from accounts_support import NOW
from fastapi.testclient import TestClient
from httpx import Client
from pydantic import SecretStr, ValidationError

from rdp.api import create_app
from rdp.api.storage import configure_storage
from rdp.api.storage_schemas import StorageRootResponse
from rdp.infra.config import StorageRootConfig
from rdp.infra.diagnostics import DefectError
from rdp.infra.storage import DeviceNumber, MountInspector, OfflineReason, StorageRootStatus


class _InconsistentInspector(MountInspector):
    """在公开装配边界注入不可信结果，检查入口不会将矛盾状态发给页面。"""

    @override
    def inspect(self) -> tuple[StorageRootStatus, ...]:
        """返回一条在线却带离线原因的非法值对象。"""
        root = self.roots[0]
        return (
            StorageRootStatus(root.name, root.path, False, True, OfflineReason.NOT_MOUNTED, NOW),
        )


@contextmanager
def _case(root: Path, inspector: MountInspector | None = None) -> Generator[ApiCase]:
    """复用真实账号与临时数据库，在客户端开始前装配独立应用。"""
    with api_case(root) as base:
        app = create_app(None, database=base.engine, clock=base.clock)
        app.state.account_service = base.service
        if inspector is not None:
            configure_storage(app, inspector=inspector)
        with TestClient(
            app, raise_server_exceptions=False, headers={"Origin": "http://testserver"}
        ) as client:
            yield replace(base, app=app, client=cast(Client, client))


def _inspector(tmp_path: Path) -> tuple[MountInspector, Mock]:
    """表与设备号显式注入，根路径不要求存在。"""
    root = StorageRootConfig(
        name="disk", path=tmp_path / "disk", uuid="12345678-1234-1234-1234-123456789abc"
    )
    read = Mock(return_value=f"20 1 8:1 / {root.path} rw - ext4 /dev/hidden-source rw\n")
    return MountInspector((root,), read, lambda _: DeviceNumber(8, 1), lambda: NOW), read


def test_unauthenticated(tmp_path: Path) -> None:
    """验证GET接口未登录401并清cookie，系统读取回调不调用。"""
    inspector, read = _inspector(tmp_path)
    with _case(tmp_path, inspector) as case:
        response = case.client.get("/api/storage-roots")
        assert response.status_code == 401
        assert "Max-Age=0" in response.headers["set-cookie"]
        read.assert_not_called()


def test_member_can_read(tmp_path: Path) -> None:
    """验证已完成改密的成员与管理员均可看，不使用管理员专属权限；无配置返回200空items。"""
    forbidden = Mock(side_effect=AssertionError("空配置不读系统"))
    with _case(tmp_path, MountInspector((), forbidden, forbidden, forbidden)) as case:
        assert case.login().status_code == 200
        assert case.client.get("/api/storage-roots").json() == {"items": []}
        add_actor(case)
        case.client.cookies.clear()
        assert case.login("member", SecretStr("member-updated-value")).status_code == 200
        response = case.client.get("/api/storage-roots")
        assert response.status_code == 200 and response.json() == {"items": []}
        forbidden.assert_not_called()


def test_password_change_required(tmp_path: Path) -> None:
    """验证必须改密码的账号403且不检查挂载，沿用第6张请求边界。"""
    inspector, read = _inspector(tmp_path)
    with _case(tmp_path, inspector) as case:
        add_actor(case, ready=False)
        assert case.login("member").status_code == 200
        assert case.client.get("/api/storage-roots").status_code == 403
        read.assert_not_called()


def test_request_checks_once(tmp_path: Path) -> None:
    """验证每次真实GET恰好一次inspect，按配置顺序返回全字段，连续请求取新状态而非缓存。"""
    inspector, read = _inspector(tmp_path)
    clock = Mock(side_effect=[NOW, NOW + timedelta(seconds=3)])
    with _case(tmp_path, replace(inspector, clock=clock)) as case:
        case.login()
        first = case.client.get("/api/storage-roots")
        assert first.status_code == 200
        item = first.json()["items"][0]
        assert item == {
            "name": "disk",
            "path": str(tmp_path / "disk"),
            "writable": False,
            "online": True,
            "reason": None,
            "checked_at": NOW.isoformat().replace("+00:00", "Z"),
        }
        read.return_value = ""
        second = case.client.get("/api/storage-roots").json()["items"][0]
        assert second["online"] is False and second["reason"] == "not_mounted"
        assert second["checked_at"] == (NOW + timedelta(seconds=3)).isoformat().replace(
            "+00:00", "Z"
        )
        assert read.call_count == 2 and clock.call_count == 2


def test_no_root_access_or_source_leak(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """验证接口只读表及UUID元数据，不调用根stat；响应无挂载原文、UUID和NFS来源。"""
    inspector, _ = _inspector(tmp_path)
    with _case(tmp_path, inspector) as case:
        case.login()
        original_stat = Path.stat

        def stat_without_storage(path: Path, *, follow_symlinks: bool = True) -> os.stat_result:
            if any(path.is_relative_to(root.path) for root in inspector.roots):
                raise AssertionError("API不能stat存储根")
            return original_stat(path, follow_symlinks=follow_symlinks)

        with monkeypatch.context() as patch:
            patch.setattr(Path, "stat", stat_without_storage)
            response = case.client.get("/api/storage-roots")
        assert response.status_code == 200
        item = response.json()["items"][0]
        assert set(item) == {"name", "path", "writable", "online", "reason", "checked_at"}
        assert (
            "hidden-source" not in response.text
            and str(inspector.roots[0].uuid) not in response.text
        )


def test_unconfigured(tmp_path: Path) -> None:
    """验证未configure_storage时真实GET返回带诊断502，不假装空配置。"""
    with _case(tmp_path) as case:
        case.login()
        response = case.client.get("/api/storage-roots")
        assert response.status_code == 502
        assert response.headers["content-type"].startswith("application/problem+json")
        assert response.json()["diagnostics"][0]["rule"] == "storage.configuration"


@pytest.mark.parametrize("malformed", [False, True])
def test_external_failure(tmp_path: Path, malformed: bool) -> None:
    """验证系统表读失败和解析失败通过真实应用返回502及统一诊断，不返回三种离线状态之一。"""
    inspector, read = _inspector(tmp_path)
    if malformed:
        read.return_value = "broken-private-record"
    else:
        read.side_effect = PermissionError(13, "hidden-table")
    with _case(tmp_path, inspector) as case:
        case.login()
        response = case.client.get("/api/storage-roots")
        assert response.status_code == 502
        diagnostic = response.json()["diagnostics"][0]
        assert diagnostic["rule"] == "storage.mount_table"
        assert diagnostic["objects"] == [{"key": "storage_root", "value": "disk"}]
        assert "items" not in response.json() and "hidden-table" not in response.text


@pytest.mark.parametrize("fault", ["dependency", "clock", "result"])
def test_defect_failure(tmp_path: Path, fault: str) -> None:
    """验证依赖损坏、时钟非法和状态矛盾由真实应用归500，响应不泄露内部细节。"""
    inspector, _ = _inspector(tmp_path)
    with _case(tmp_path, inspector) as case:
        case.login()
        if fault == "dependency":
            case.app.state.storage_inspector = object()
        elif fault == "clock":
            case.app.state.storage_inspector = replace(
                inspector, clock=Mock(return_value=NOW.replace(tzinfo=None))
            )
        else:
            case.app.state.storage_inspector = _InconsistentInspector(
                inspector.roots,
                inspector.read_mountinfo,
                inspector.resolve_uuid_device,
                inspector.clock,
            )
        response = case.client.get("/api/storage-roots")
        assert response.status_code == 500
        assert response.json()["error_id"] and "hidden-source" not in response.text


def test_configure_lifecycle(tmp_path: Path) -> None:
    """验证configure_storage只改app.state且不I/O，重复或运行后装配/非法依赖拒绝；各应用互不污染。"""
    inspector, read = _inspector(tmp_path)
    first = create_app(None, database=None)
    second = create_app(None, database=None)
    configure_storage(first, inspector=inspector)
    read.assert_not_called()
    assert first.state.storage_inspector is inspector
    assert not hasattr(second.state, "storage_inspector")
    with pytest.raises(DefectError):
        configure_storage(first, inspector=inspector)
    with pytest.raises(DefectError):
        configure_storage(second, inspector=cast(MountInspector, object()))
    with pytest.raises(DefectError):
        configure_storage(
            second,
            inspector=replace(inspector, roots=cast(tuple[StorageRootConfig, ...], (object(),))),
        )
    with TestClient(second) as client:
        cast(Client, client).get("/api/health")
        with pytest.raises(DefectError):
            configure_storage(second, inspector=inspector)


def test_openapi_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    """验证OpenAPI含GET路径、SessionCookie认证、响应全部字段与三种原因枚举；离线导出不触发读表。"""
    forbidden = Mock(side_effect=AssertionError("OpenAPI不读系统"))
    monkeypatch.setattr(Path, "read_text", forbidden)
    schema = create_app(None, database=None).openapi()
    operation = schema["paths"]["/api/storage-roots"]["get"]
    assert operation["security"] == [{"SessionCookie": []}]
    assert operation["responses"]["200"]["content"]["application/json"]["schema"]["$ref"].endswith(
        "/StorageRootsResponse"
    )
    models = schema["components"]["schemas"]
    assert models["OfflineReason"]["enum"] == ["not_mounted", "source_mismatch", "timeout"]
    assert models["StorageRootResponse"]["properties"]["reason"]["x-display-labels"] == {
        "not_mounted": "没挂载",
        "source_mismatch": "挂错了盘",
        "timeout": "超时",
    }
    assert set(models["StorageRootResponse"]["required"]) == {
        "name",
        "path",
        "writable",
        "online",
        "reason",
        "checked_at",
    }
    forbidden.assert_not_called()


def test_response_invariants() -> None:
    """验证在线原因须空、离线原因必填、checked_at必须aware UTC，错误响应模型不能悄悄通过。"""
    valid: dict[str, object] = {
        "name": "disk",
        "path": "/fake",
        "writable": False,
        "online": True,
        "reason": None,
        "checked_at": NOW,
    }
    assert StorageRootResponse.model_validate(valid).online
    for reason in OfflineReason:
        assert not StorageRootResponse.model_validate(
            valid | {"online": False, "reason": reason}
        ).online
    for changes in (
        {"online": False},
        {"reason": "not_mounted"},
        {"checked_at": NOW.replace(tzinfo=None)},
        {"checked_at": NOW.astimezone(timezone(timedelta(hours=1)))},
    ):
        with pytest.raises(ValidationError):
            StorageRootResponse.model_validate(valid | changes)
