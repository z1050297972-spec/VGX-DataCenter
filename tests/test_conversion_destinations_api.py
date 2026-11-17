"""输出根 HTTP 契约：临时索引、预览和合成挂载表；不访问任何真实数据盘。"""

import os
import shutil
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from account_api_support import add_actor
from conversion_cleaning_support import seed_preview
from conversion_support import fake_converter, settings, storage_checker
from dataset_api_support import browser_case
from nav_manifest import FakeNavigation
from pydantic import SecretStr

from rdp.infra.config import StorageRootConfig
from rdp.jobs.conversion.parameters import ConversionParameters
from rdp.jobs.conversion.registration import register_conversion_jobs
from rdp.jobs.registry import production_registry
from rdp.jobs.service import JobService


def _roots(path: Path) -> tuple[StorageRootConfig, ...]:
    """输出目录故意不存在，Web 只能从登记和挂载元信息生成路径。"""
    return tuple(
        StorageRootConfig(
            name=name, path=path / name, writable=name != "readonly", nfs_export=f"nas:/{name}"
        )
        for name in ("a", "b", "readonly")
    )


def test_destinations_are_mount_only_and_authenticated(
    tmp_path: Path, fake_nav: FakeNavigation, monkeypatch: pytest.MonkeyPatch
) -> None:
    """GET 只查挂载，保留离线/只读状态与 UTC 时刻；普通成员可读，不存在预览 404。"""
    files = fake_converter(tmp_path / "tool")
    roots = _roots(tmp_path)
    inspector = storage_checker(roots).mounts
    inspector = replace(inspector, read_mountinfo=storage_checker(roots[1:]).mounts.read_mountinfo)
    with browser_case(tmp_path / "state", fake_nav, inspector=inspector) as api:
        seed_preview(
            api.engine,
            files,
            ConversionParameters(
                dataset_id="dataset-35",
                source_ids=["src_01e0bc7e9cc8"],
                robot_model="Galaxea R1 Lite",
            ),
        )
        add_actor(api)
        assert api.login("member", SecretStr("member-updated-value")).status_code == 200
        original_stat, original_scandir = os.stat, os.scandir

        def guard(path: object) -> None:
            if isinstance(path, (str, Path)) and any(
                Path(path).is_relative_to(root.path) for root in roots
            ):
                raise AssertionError("Web 不能访问存储根目录")

        def stat(path: Any, *args: Any, **kwargs: Any):
            guard(path)
            return original_stat(path, *args, **kwargs)

        def scandir(path: Any):
            guard(path)
            return original_scandir(path)

        def capacity(path: Path):
            raise AssertionError("Web 不能读取容量")

        monkeypatch.setattr(os, "stat", stat)
        monkeypatch.setattr(os, "scandir", scandir)
        monkeypatch.setattr(shutil, "disk_usage", capacity)
        response = api.client.get("/api/cleaning-previews/59/destinations")
        assert response.status_code == 200, response.text
        a, b, readonly = response.json()["items"]
        assert not a["online"] and a["reason"] == "not_mounted"
        assert b["online"] and b["writable"] and b["reason"] is None
        assert not readonly["writable"]
        assert b["checked_at"].endswith("Z")
        assert b["staging_template"] == str(tmp_path / "b/暂存/转换/{job_id}/out")
        assert b["expected_output_path"] == str(
            tmp_path / "b/转换/R1_lite_table_withdrawing_lerobot"
        )
        assert api.client.get("/api/cleaning-previews/999/destinations").status_code == 404


@pytest.mark.parametrize("selected", [None, "b", "readonly", "missing", "absolute"])
def test_submit_and_resubmit_freeze_registered_root(
    tmp_path: Path, fake_nav: FakeNavigation, selected: str | None
) -> None:
    """专用和通用提交不能绕过根权限；缺省固化 a，显式 b 在重排配置与重提后保持。"""
    files = fake_converter(tmp_path / "tool")
    roots = _roots(tmp_path)
    registry = production_registry()
    register_conversion_jobs(registry, settings(files), roots, None)
    with browser_case(tmp_path / "state", fake_nav, registry=registry) as api:
        parameters = seed_preview(
            api.engine,
            files,
            ConversionParameters(
                dataset_id="dataset-35",
                source_ids=["src_01e0bc7e9cc8"],
                robot_model="Galaxea R1 Lite",
            ),
        )
        payload = (
            {}
            if selected is None
            else {"output_root": str(tmp_path / "absolute") if selected == "absolute" else selected}
        )
        response = api.client.post("/api/cleaning-previews/59/convert", json=payload)
        expected = "a" if selected is None else selected
        valid = selected in (None, "b")
        assert response.status_code == (201 if valid else 422), response.text
        generic = api.client.post(
            "/api/jobs",
            json={
                "type_name": "convert_mcap2lerobot",
                "parameters": {**parameters.model_dump(mode="json"), **payload},
            },
        )
        assert generic.status_code == (201 if valid else 422), generic.text
        if not valid:
            return
        assert response.json()["parameters"]["output_root"] == expected
        identifier = response.json()["job_id"]
        assert api.client.post(f"/api/jobs/{identifier}/cancel").status_code == 200
        reordered = production_registry()
        register_conversion_jobs(reordered, settings(files), roots[::-1], None)
        api.app.state.job_service = JobService(api.engine, reordered)
        resubmitted = api.client.post(f"/api/jobs/{identifier}/resubmit")
        assert resubmitted.status_code == 201, resubmitted.text
        assert resubmitted.json()["parameters"]["output_root"] == expected
