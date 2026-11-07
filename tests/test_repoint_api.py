"""M1-09 公开 HTTP、真实 worker、永久变更记录的纵向测试。"""

import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

from creation_support import creation_api_case, run_queued
from nav_manifest import FakeNavigation
from navwrite_support import dataset_id_of, tree_state


def test_repoint_apply_through_http(tmp_path: Path, fake_nav: FakeNavigation) -> None:
    """验证预览→确认→共用写入，导航层更新，HTTP 不传执行正文。"""
    with creation_api_case(tmp_path, fake_nav) as (api, deps):
        old = deps.rescan.roots[1].path
        new = deps.rescan.roots[0].path / "mirror"
        shutil.copytree(old, new)
        before = tree_state(fake_nav.nav_root)
        submitted = api.client.post(
            "/api/datasets/repoint-previews",
            json={
                "dataset_id": dataset_id_of(fake_nav, "EgoProDemo"),
                "old_prefix": str(old),
                "new_prefix": str(new),
            },
        )
        assert submitted.status_code == 201, submitted.text
        preview_id = submitted.json()["job_id"]
        preview_job = run_queued(api, deps, preview_id)
        assert preview_job.summary is not None and not preview_job.summary.aborted
        response = api.client.get(f"/api/navigation/previews/{preview_id}")
        assert response.status_code == 200, response.text
        assert response.json()["operation"] == "repoint_dataset"
        assert "after_content" not in response.text
        write = api.client.post("/api/navigation/writes", json={"preview_job_id": preview_id})
        assert write.status_code == 201, write.text
        write_id = write.json()["job_id"]
        result = run_queued(api, deps, write_id)
        assert result.summary is not None and not result.summary.aborted
        assert (fake_nav.nav_root / "按任务/EgoProDemo/原始数据").readlink().is_relative_to(new)
        assert tree_state(fake_nav.nav_root) != before


def test_queue_requires_explicit_ids_then_confirms(
    tmp_path: Path, fake_nav: FakeNavigation
) -> None:
    """验证创建同款 409/201：新排队同数据集写作业逐项确认，重复编号拒绝，已确认不绕过 L12。"""
    with creation_api_case(tmp_path, fake_nav) as (api, deps):
        old = deps.rescan.roots[1].path
        new = deps.rescan.roots[0].path / "mirror"
        shutil.copytree(old, new)
        body = {
            "dataset_id": dataset_id_of(fake_nav, "EgoProDemo"),
            "old_prefix": str(old),
            "new_prefix": str(new),
        }
        first = api.client.post("/api/datasets/repoint-previews", json=body).json()["job_id"]
        second = api.client.post("/api/datasets/repoint-previews", json=body).json()["job_id"]
        run_queued(api, deps, first)
        run_queued(api, deps, second)
        queued = api.client.post("/api/navigation/writes", json={"preview_job_id": first}).json()[
            "job_id"
        ]
        response = api.client.post("/api/navigation/writes", json={"preview_job_id": second})
        assert response.status_code == 409 and queued in response.text
        view = api.client.get(f"/api/navigation/previews/{second}").json()
        assert [row["job_id"] for row in view["queued_jobs"]] == [queued]
        duplicate = api.client.post(
            "/api/navigation/writes",
            json={"preview_job_id": second, "acknowledged_queue_job_ids": [queued, queued]},
        )
        assert duplicate.status_code == 422
        confirmed = api.client.post(
            "/api/navigation/writes",
            json={"preview_job_id": second, "acknowledged_queue_job_ids": [queued]},
        )
        assert confirmed.status_code == 201, confirmed.text
        run_queued(api, deps, queued)
        before = tree_state(fake_nav.nav_root)
        stale = run_queued(api, deps, confirmed.json()["job_id"])
        assert stale.summary is not None and stale.summary.aborted
        assert tree_state(fake_nav.nav_root) == before
        diagnostics = api.client.get(f"/api/jobs/{stale.job_id}").text
        assert "NAV_PREVIEW_STATE" in diagnostics and "原始路径.json" in diagnostics


def test_preview_rejects_plan_dataset_tampering(tmp_path: Path, fake_nav: FakeNavigation) -> None:
    """验证保存预览的参数/计划关联：文件里的数据集与已提交参数不同则读取和确认均拒绝。"""
    from rdp.jobs.navwrite.models import NavPreview
    from rdp.jobs.navwrite.previews import read_preview, write_preview

    with creation_api_case(tmp_path, fake_nav) as (api, deps):
        old = deps.rescan.roots[1].path
        new = deps.rescan.roots[0].path / "mirror"
        shutil.copytree(old, new)
        response = api.client.post(
            "/api/datasets/repoint-previews",
            json={
                "dataset_id": dataset_id_of(fake_nav, "EgoProDemo"),
                "old_prefix": str(old),
                "new_prefix": str(new),
            },
        )
        identifier = response.json()["job_id"]
        run_queued(api, deps, identifier)
        payload = read_preview(deps.paths, int(identifier)).model_dump(mode="json")
        payload["plan"]["dataset_ids"] = [dataset_id_of(fake_nav, "libero_10")]
        (deps.paths.nav_previews / f"{identifier}.json.gz").unlink()
        write_preview(deps.paths, NavPreview.model_validate(payload))
        assert api.client.get(f"/api/navigation/previews/{identifier}").status_code == 400
        assert (
            api.client.post(
                "/api/navigation/writes", json={"preview_job_id": identifier}
            ).status_code
            == 400
        )


def test_http_guards_validation_and_web_no_storage(
    tmp_path: Path, fake_nav: FakeNavigation
) -> None:
    """验证真实应用 Origin/认证/成员权限、422/404，Web 不 stat/lstat/open 任何存储目标。"""
    import os

    import pytest
    from account_api_support import add_actor
    from pydantic import SecretStr

    with creation_api_case(tmp_path, fake_nav) as (api, deps):
        body = {
            "dataset_id": dataset_id_of(fake_nav, "EgoProDemo"),
            "old_prefix": str(deps.rescan.roots[1].path),
            "new_prefix": str(deps.rescan.roots[0].path / "not-created"),
        }
        assert (
            api.client.post(
                "/api/datasets/repoint-previews", json={}, headers={"Origin": ""}
            ).status_code
            == 403
        )
        api.client.cookies.clear()
        assert api.client.post("/api/datasets/repoint-previews", json=body).status_code == 401
        assert api.login().status_code == 200
        add_actor(api, name="ready_member")
        assert api.login("ready_member", SecretStr("member-updated-value")).status_code == 200
        stat, lstat = Path.stat, Path.lstat
        open_file: Callable[..., Any] = Path.open

        def guard(path: Path) -> None:
            assert not any(path.is_relative_to(root.path) for root in deps.rescan.roots), (
                "Web访问数据盘"
            )

        def checked_stat(path: Path, *, follow_symlinks: bool = True) -> os.stat_result:
            guard(path)
            return stat(path, follow_symlinks=follow_symlinks)

        def checked_lstat(path: Path) -> os.stat_result:
            guard(path)
            return lstat(path)

        def checked_open(path: Path, *args: Any, **kwargs: Any) -> Any:
            guard(path)
            return open_file(path, *args, **kwargs)

        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(Path, "stat", checked_stat)
            patch.setattr(Path, "lstat", checked_lstat)
            patch.setattr(Path, "open", checked_open)
            response = api.client.post("/api/datasets/repoint-previews", json=body)
            assert response.status_code == 201, response.text
        identifier = response.json()["job_id"]
        assert api.client.get(f"/api/navigation/previews/{identifier}").status_code == 400
        assert (
            api.client.post(
                "/api/navigation/writes", json={"preview_job_id": identifier}
            ).status_code
            == 400
        )
        for prefix in ("relative", "/", "/absolute/", "/a/../b", "/bad\x00path"):
            invalid = api.client.post(
                "/api/datasets/repoint-previews", json={**body, "old_prefix": prefix}
            )
            assert invalid.status_code == 422, invalid.text
        assert (
            api.client.post(
                "/api/datasets/repoint-previews", json={**body, "dataset_id": "dataset-99999"}
            ).status_code
            == 404
        )
        assert api.client.get("/api/navigation/previews/01").status_code == 422


def test_preview_expiry_missing_file_and_clock_rollback(
    tmp_path: Path, fake_nav: FakeNavigation
) -> None:
    """验证七天保留期：时钟回拨不提前过期，超过七天拒绝；丢失文件不变成可确认空计划。"""
    from datetime import timedelta

    with creation_api_case(tmp_path, fake_nav) as (api, deps):
        old = deps.rescan.roots[1].path
        new = deps.rescan.roots[0].path / "mirror"
        shutil.copytree(old, new)
        response = api.client.post(
            "/api/datasets/repoint-previews",
            json={
                "dataset_id": dataset_id_of(fake_nav, "EgoProDemo"),
                "old_prefix": str(old),
                "new_prefix": str(new),
            },
        )
        identifier = response.json()["job_id"]
        run_queued(api, deps, identifier)
        saved_time = api.clock.value
        api.clock.value -= timedelta(days=1)
        assert api.client.get(f"/api/navigation/previews/{identifier}").status_code == 200
        api.clock.value = saved_time + timedelta(days=8)
        assert api.login().status_code == 200
        assert api.client.get(f"/api/navigation/previews/{identifier}").status_code == 400
        assert (
            api.client.post(
                "/api/navigation/writes", json={"preview_job_id": identifier}
            ).status_code
            == 400
        )
        (deps.paths.nav_previews / f"{identifier}.json.gz").unlink()
        assert api.client.get(f"/api/navigation/previews/{identifier}").status_code == 400
