"""M2-05 只覆盖验收 1-4 的关键入库行为，不访问真实存储。"""

from __future__ import annotations

import json
import os
from dataclasses import replace
from pathlib import Path

import pytest
from download_ingest_support import COMMIT, PREVIEW_ID, build, ingest_case, save
from nav_manifest import FakeNavigation
from navwrite_support import tree_state

from rdp.infra.diagnostics import InputError
from rdp.jobs.navwrite.create_models import INFORMATION_FIELD_NAMES
from rdp.jobs.navwrite.jobs import NavApplyParameters


@pytest.mark.parametrize("failure", ["missing", "size", "not_lerobot", "occupied"])
def test_preview_rejects_without_writes(
    tmp_path: Path, fake_nav: FakeNavigation, failure: str
) -> None:
    """验收 1：缺文件、大小错误、非 LeRobot 和目标已存在均给诊断且预览不写数据。"""
    with ingest_case(tmp_path, fake_nav) as (h, stage):
        if failure == "missing":
            (stage / "data/sample.parquet").unlink()
        elif failure == "size":
            (stage / "data/sample.parquet").write_bytes(b"bad")
        elif failure == "not_lerobot":
            (stage / "meta/info.json").unlink()
        else:
            target = h.case.scanning.roots[0].path / "下载/org/repo@aaaaaaaaaaaa"
            target.mkdir(parents=True)
        before = tree_state(h.nav), tree_state(h.case.scanning.roots[0].path)
        with pytest.raises(InputError) as caught:
            build(h)
        diagnostic = caught.value.diagnostics[0]
        assert diagnostic.objects and diagnostic.actual and diagnostic.consequence
        assert (tree_state(h.nav), tree_state(h.case.scanning.roots[0].path)) == before


def test_confirm_moves_and_creates_navigation(tmp_path: Path, fake_nav: FakeNavigation) -> None:
    """验收 2：同根改名后两视图链接和来源血缘一致，正式位置是唯一数据位置。"""
    from rdp.jobs.downloads.ingest import execute_ingest_apply

    with ingest_case(tmp_path, fake_nav) as (h, stage):
        save(h, build(h))
        record = h.case.run(
            execute=lambda context: execute_ingest_apply(
                h.dependencies,
                replace(context, parameters=NavApplyParameters(preview_job_id=PREVIEW_ID)),
            )
        )
        assert record.summary is not None and not record.summary.aborted
        target = h.case.scanning.roots[0].path / "下载/org/repo@aaaaaaaaaaaa"
        assert target.is_dir() and not stage.exists()
        for entry in ("按任务/repo", "按格式/lerobot/3.0/repo"):
            assert (h.nav / entry / "原始数据").readlink() == target
            assert (h.nav / entry / "原始数据/data/sample.parquet").read_bytes() == b"sample"
        source = json.loads((h.nav / "按任务/repo/来源.json").read_text())
        assert source["schema_version"] == 2 and "data_origin" not in source
        for entry in ("按任务/repo", "按格式/lerobot/3.0/repo"):
            information = json.loads((h.nav / entry / "数据集信息.json").read_text())
            assert information["data_origin"] == "开源下载"
        lineage = source["lineage"][0]
        assert lineage["parameters"]["repo_id"] == "org/repo"
        assert lineage["parameters"]["commit"] == COMMIT
        assert lineage["parameters"]["download_job_id"] == 60
        assert lineage["job_id"] == record.job_id
        assert lineage["started_at"] and lineage["finished_at"]


def test_navigation_failure_restores_staging(
    tmp_path: Path, fake_nav: FakeNavigation, monkeypatch: pytest.MonkeyPatch
) -> None:
    """验收 3：模拟导航写入失败，M1 回滚导航后目录不覆盖地改回暂存位置。"""
    from rdp.jobs.downloads.ingest import execute_ingest_apply

    with ingest_case(tmp_path, fake_nav) as (h, stage):
        save(h, build(h))
        before = tree_state(h.nav)
        original = os.write
        injected: list[bool] = []

        def fail(fd: int, data: bytes | memoryview[int]) -> int:
            if str(h.nav) in str(Path(f"/proc/self/fd/{fd}").readlink()):
                assert not stage.exists()
                assert (h.case.scanning.roots[0].path / "下载/org/repo@aaaaaaaaaaaa").is_dir()
                injected.append(True)
                raise OSError("模拟导航存储写入失败")
            return original(fd, data)

        monkeypatch.setattr(os, "write", fail)
        record = h.case.run(
            execute=lambda context: execute_ingest_apply(
                h.dependencies,
                replace(context, parameters=NavApplyParameters(preview_job_id=PREVIEW_ID)),
            )
        )
        assert record.summary is not None and record.summary.aborted
        assert injected == [True]
        assert stage.is_dir() and (stage / "data/sample.parquet").read_bytes() == b"sample"
        assert not (h.case.scanning.roots[0].path / "下载/org/repo@aaaaaaaaaaaa").exists()
        assert tree_state(h.nav) == before


def test_information_autofill_and_empty_unknowns(tmp_path: Path, fake_nav: FakeNavigation) -> None:
    """验收 4：14 项从已知样本填机器人、FPS、相机、维度和计数，不能推断的项留空。"""
    with ingest_case(tmp_path, fake_nav) as (h, _stage):
        result = build(h)
        content = next(
            step.after_content
            for step in result.plan.steps
            if step.op == "write_file" and step.path == "按任务/repo/数据集信息.json"
        )
        fields = {item["name"]: item["value_markdown"] for item in json.loads(content)["fields"]}
        assert len(fields) == 14
        assert fields["采集机器人型号"] == "so101"
        assert fields["FPS"] == "30"
        assert fields["数据格式"] == "v3.0"
        assert fields["相机配置"] == "observation.images.front: 480 x 640 x 3"
        assert fields["状态维度"] == "6" and fields["动作维度"] == "7"
        assert fields[INFORMATION_FIELD_NAMES[12]] == "2 episodes / 42 frames"
        assert fields["数据集标识"] == "org/repo"
        assert fields["地址"] == "https://hf-mirror.com/datasets/org/repo/tree/" + COMMIT
        assert fields["信息来源与核验日期"].startswith("hf-mirror 下载，org/repo@" + COMMIT)
        assert fields["类型与组成"] == fields["任务与场景"] == fields["动作控制方式及单位"] == ""
        assert any("部分下载" in notice.message for notice in result.report.notices)
