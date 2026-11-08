"""M4-04 验收2至5：从真实HTTP、worker和导航写入边界验证入库。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from conversion_workflow_support import conversion_case
from creation_support import run_queued
from nav_manifest import FakeNavigation
from tool_registry_support import isolated_tool_cache as isolated_tool_cache


def test_warning_check_is_persisted_and_waits_for_confirmation(
    tmp_path: Path, fake_nav: FakeNavigation
) -> None:
    """验收3：自动检查有警告时不排队入库、不建入口，人工确认后才入库。"""
    from rdp.jobs.conversion.ingest_models import CHECK_TYPE

    with conversion_case(tmp_path, fake_nav, warning=True) as (api, deps, stage):
        check = deps.service.submit_system(
            CHECK_TYPE, {"conversion_job_id": 60, "automatic": True}, now=api.clock()
        )
        identifier = str(check.job_id)
        result = run_queued(api, deps, identifier)
        assert result.progress is not None
        report = json.loads((stage.parent / "入库检查.json").read_text())
        assert report["result"] == "有警告" and report["warning_count"] == 1
        assert result.progress.ingest_check is not None
        assert result.progress.ingest_check.report.model_dump(mode="json") == report
        jobs = api.client.get("/api/jobs")
        assert jobs.status_code == 200, jobs.text
        assert not any(
            job["type_name"] == "conversion_ingest_apply" for job in jobs.json()["items"]
        )
        target = deps.rescan.roots[0].path / "转换/EgoProDemo_lerobot"
        entries = (
            fake_nav.nav_root / "按任务/EgoProDemo_lerobot",
            fake_nav.nav_root / "按格式/lerobot/3.0/EgoProDemo_lerobot",
        )
        assert not target.exists()
        assert all(not entry.exists() for entry in entries)
        preview = api.client.get(f"/api/jobs/{identifier}/conversion-ingest-preview")
        assert preview.status_code == 200, preview.text
        assert len(preview.json()["fields"]) == 14
        assert preview.json()["parameters"]["dataset_name"] == "EgoProDemo_lerobot"
        assert stage.is_dir()
        staging = api.client.get("/api/conversions/staging")
        assert staging.status_code == 200, staging.text
        assert staging.json()["items"][0]["status"] == "待确认"
        assert staging.json()["items"][0]["check"]["result"] == "有警告"
        confirmation = api.client.post(
            "/api/jobs/conversion-ingest", json={"preview_job_id": identifier}
        )
        assert confirmation.status_code == 201, confirmation.text
        applied = run_queued(api, deps, confirmation.json()["job_id"])
        assert applied.summary is not None and not applied.summary.aborted
        assert not stage.exists()
        assert target.is_dir()
        for entry in entries:
            assert (entry / "原始数据").readlink() == target


def test_pass_automatically_ingests_with_conversion_lineage(
    tmp_path: Path, fake_nav: FakeNavigation
) -> None:
    """验收2：自动入库保留输入分类、采用产物FPS，并写入两视图与血缘。"""
    from rdp.jobs.conversion.ingest_models import CHECK_TYPE

    source_path = fake_nav.nav_root / "按任务/EgoProDemo/数据集信息.json"
    source_info = json.loads(source_path.read_text())
    source_info.update(
        robot_model="Galaxea R1 Lite", scene=["室内", "桌面"], tasks=["收纳", "抓取"], fps=15
    )
    source_path.write_text(json.dumps(source_info, ensure_ascii=False))
    with conversion_case(tmp_path, fake_nav) as (api, deps, stage):
        source_info = json.loads(source_path.read_text())
        output_info = json.loads((stage / "meta/info.json").read_text())
        # 输入帧率与产物不同，避免错误沿用输入FPS也能通过。
        assert output_info["fps"] != source_info["fps"]
        check = deps.service.submit_system(
            CHECK_TYPE, {"conversion_job_id": 60, "automatic": True}, now=api.clock()
        )
        result = run_queued(api, deps, str(check.job_id))
        assert result.summary is not None and not result.summary.aborted
        jobs = api.client.get("/api/jobs").json()["items"]
        applies = [job for job in jobs if job["type_name"] == "conversion_ingest_apply"]
        assert len(applies) == 1
        applied = run_queued(api, deps, applies[0]["job_id"])
        assert applied.summary is not None and not applied.summary.aborted
        target = deps.rescan.roots[0].path / "转换/EgoProDemo_lerobot"
        assert target.is_dir() and not stage.exists()
        staging = api.client.get("/api/conversions/staging")
        assert staging.status_code == 200, staging.text
        assert staging.json()["items"][0]["status"] == "已入库"
        for entry in ("按任务/EgoProDemo_lerobot", "按格式/lerobot/3.0/EgoProDemo_lerobot"):
            directory = fake_nav.nav_root / entry
            assert (directory / "原始数据").readlink() == target
            info = json.loads((directory / "数据集信息.json").read_text())
            assert info["data_origin"] == source_info["data_origin"]
            for key in ("robot_model", "scene", "tasks"):
                assert info[key] == source_info[key]
            assert type(info["fps"]) is int and info["fps"] == output_info["fps"]
            assert "collection" not in info
        provenance = json.loads(
            (fake_nav.nav_root / "按任务/EgoProDemo_lerobot/来源.json").read_text()
        )
        lineage = provenance["lineage"][0]
        assert lineage["kind"] == "转换" and lineage["status"] == "完整"
        assert lineage["recorded_by"]["kind"] == "worker"
        assert lineage["job_id"] == 60
        assert lineage["tool"]["binary_sha256"] == "f" * 64
        assert lineage["config"]["text"] == "[robot]\nname = 'r1lite'\n"
        assert lineage["outputs"][0]["source_id"]
        assert lineage["outputs"][0]["format"] == "lerobot"
        assert lineage["ingest_check"] == {"result": "通过", "warning_count": 0}


def test_default_name_collision_waits_for_confirmation(
    tmp_path: Path, fake_nav: FakeNavigation
) -> None:
    """验收4：默认名占用时仅提供带编号的人工建议，不自动提交入库。"""
    from rdp.jobs.conversion.ingest_models import CHECK_TYPE

    with conversion_case(tmp_path, fake_nav) as (api, deps, stage):
        import shutil

        destination = fake_nav.nav_root / "按任务/EgoProDemo_lerobot"
        shutil.copytree(fake_nav.nav_root / "按任务/EgoProDemo", destination, symlinks=True)
        for document in destination.glob("*.json"):
            payload = json.loads(document.read_text())
            payload.update(dataset_id="dataset-100", dataset_name="EgoProDemo_lerobot")
            document.write_text(json.dumps(payload, ensure_ascii=False))
        check = deps.service.submit_system(
            CHECK_TYPE, {"conversion_job_id": 60, "automatic": True}, now=api.clock()
        )
        result = run_queued(api, deps, str(check.job_id))
        assert result.progress is not None and result.progress.ingest_check is not None
        assert result.progress.ingest_check.report.result == "通过"
        assert not result.progress.ingest_check.automatic_ready
        preview = api.client.get(f"/api/jobs/{check.job_id}/conversion-ingest-preview")
        assert preview.status_code == 200
        assert preview.json()["parameters"]["dataset_name"] == "EgoProDemo_lerobot_60"
        assert stage.is_dir()
        assert not any(
            job["type_name"] == "conversion_ingest_apply"
            for job in api.client.get("/api/jobs").json()["items"]
        )


def test_navigation_failure_restores_conversion(
    tmp_path: Path, fake_nav: FakeNavigation, monkeypatch: pytest.MonkeyPatch
) -> None:
    """验收5：实际移动后模拟导航写失败，导航回滚且产物退回原暂存位置。"""
    import os

    from navwrite_support import tree_state

    with conversion_case(tmp_path, fake_nav) as (api, deps, stage):
        response = api.client.post("/api/jobs/60/conversion-ingest-preview", json={})
        identifier = response.json()["job_id"]
        run_queued(api, deps, identifier)
        confirmation = api.client.post(
            "/api/jobs/conversion-ingest", json={"preview_job_id": identifier}
        )
        assert confirmation.status_code == 201
        before = tree_state(fake_nav.nav_root)
        original = os.write
        injected: list[bool] = []

        def fail(fd: int, data: bytes | memoryview[int]) -> int:
            if str(fake_nav.nav_root) in str(Path(f"/proc/self/fd/{fd}").readlink()):
                assert not stage.exists()
                injected.append(True)
                raise OSError("模拟导航写失败")
            return original(fd, data)

        monkeypatch.setattr(os, "write", fail)
        result = run_queued(api, deps, confirmation.json()["job_id"])
        assert result.summary is not None and result.summary.aborted
        assert injected == [True]
        assert stage.is_dir()
        assert not (deps.rescan.roots[0].path / "转换/EgoProDemo_lerobot").exists()
        assert tree_state(fake_nav.nav_root) == before


def test_conversion_completion_enqueues_one_check(tmp_path: Path, fake_nav: FakeNavigation) -> None:
    """验收2的触发入口：真实转换执行成功后，在终态事务中自动排队一次检查。"""
    from conversion_support import fake_converter, no_sandbox, settings, storage_checker

    from rdp.jobs.conversion.job import ConversionDependencies
    from rdp.jobs.conversion.registration import register_conversion_jobs

    with conversion_case(tmp_path, fake_nav) as (api, deps, _stage):
        files = fake_converter(tmp_path / "tool")
        # 假外部程序只写固定小JSON，不使用GPU；只改tmp内的登记副本。
        manifest = files.package / "tool.toml"
        manifest.write_text(manifest.read_text().replace("needs_gpu = true", "needs_gpu = false"))
        tools = settings(files)
        conversion = ConversionDependencies(
            api.engine,
            tools,
            deps.rescan.roots,
            no_sandbox,
            storage=storage_checker(deps.rescan.roots),
        )
        registry = deps.service.registry
        register_conversion_jobs(registry, tools, deps.rescan.roots, conversion)
        submitted = deps.service.submit_system(
            "convert_mcap2lerobot",
            {
                "dataset_id": "dataset-35",
                "source_ids": ["src_01e0bc7e9cc8"],
                "robot_model": "Galaxea R1 Lite",
                "output_format": "v3.0",
            },
            now=api.clock(),
        )
        result = run_queued(api, deps, str(submitted.job_id), registry=registry)
        assert result.summary is not None and not result.summary.aborted
        jobs = api.client.get("/api/jobs").json()["items"]
        checks = [job for job in jobs if job["type_name"] == "conversion_ingest_preview"]
        assert len(checks) == 1
        assert checks[0]["parameters"]["conversion_job_id"] == submitted.job_id
        assert checks[0]["parameters"]["automatic"] is True
        assert checks[0]["state"] == "queued"
