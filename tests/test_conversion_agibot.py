"""M4.6-04 关键转换契约；假工具走真实受管进程，输入和输出只在临时目录。"""

import json
import os
import shutil
import tomllib
from pathlib import Path
from types import SimpleNamespace

import pytest
from conversion_agibot_support import agibot_case, fake_agibot, seed_agibot_preview
from dataset_api_support import browser_case
from nav_manifest import FakeNavigation
from tool_registry_support import isolated_tool_cache as isolated_tool_cache

from rdp.infra.config import ToolsConfig
from rdp.infra.diagnostics import DiagnosticCategory
from rdp.jobs.conversion.parameters import EpisodeSelection
from rdp.jobs.conversion.registration import register_conversion_jobs
from rdp.jobs.outcome import JobOutcome
from rdp.jobs.registry import production_registry


def test_agibot_conversion_uses_selected_directories_cache_and_offline_environment(
    tmp_path: Path,
    fake_nav: FakeNavigation,
) -> None:
    """范围1/3/5：排除目录变化不影响；两命令输入按 file_index，缓存可写，无环境/GPU仍成功。"""
    with agibot_case(tmp_path, fake_nav) as case:
        excluded = case.inputs[1]
        info = excluded.stat()
        os.utime(excluded, ns=(info.st_atime_ns, info.st_mtime_ns + 1))
        registry = production_registry()
        register_conversion_jobs(registry, case.dependencies.tools, case.dependencies.roots, None)
        definition = registry.lookup("convert_agibot2lerobot")
        assert definition is not None and not definition.requires_gpu
        result = case.run()
        assert result.summary is not None and result.summary.outcome is JobOutcome.SUCCEEDED
        calls = [json.loads(line) for line in case.calls_path.read_text().splitlines()]
        assert [call["command"] for call in calls] == ["check-episodes", "convert-episodes"]
        cache = case.dependencies.tools.cache_root / "agibot2lerobot"
        for call in calls:
            assert call["inputs"] == [str(case.inputs[0]), str(case.inputs[2])]
            assert call["index_cache"] == str(cache)
        assert len(case.sandboxes) == 2
        assert all(spec.writable == (case.stage, cache) for spec in case.sandboxes)
        assert result.progress is not None and result.progress.conversion is not None
        assert result.progress.conversion.total_episodes == 2
        assert result.progress.conversion.total_frames == 7
        assert result.progress.conversion.output_path == str(case.stage / "out")
        receipt = json.loads((case.stage / "转换回执.json").read_text())
        manifest = tomllib.loads((case.files.package / "tool.toml").read_text())
        assert receipt["tool"]["binary_sha256"] != manifest["program"]["tree_sha256"]
        assert receipt["tool"]["source_tree_sha256"] == manifest["program"]["tree_sha256"]
        assert receipt["tool"]["binary_sha256"] != manifest["program"]["sha256"]
        assert receipt["cleaning"]["excluded_episodes"] == []
        assert receipt["cleaning"]["lerobot_version"] is None
        assert receipt["cleaning"]["command"] is None
        assert [item["file_index"] for item in receipt["cleaning"]["excluded_files"]] == [1]


def test_agibot_executor_rejects_episode_exclusion(
    tmp_path: Path,
    fake_nav: FakeNavigation,
) -> None:
    """范围2：绕过 HTTP 直接提交的段剔除也必须拒绝，未建暂存、未运行工具。"""
    with agibot_case(tmp_path, fake_nav) as case:
        case.parameters = case.parameters.model_copy(
            update={
                "excluded_episodes": [EpisodeSelection(file_index=0, segment_index=0)],
            }
        )
        result = case.run()
        assert result.summary is not None and result.summary.outcome is JobOutcome.FAILED
        assert any(
            item.category is DiagnosticCategory.INPUT
            and item.expected == "AgiBot 数据按集剔除，请使用 excluded_files"
            for group in result.diagnostics
            for item in group.samples
        )
        assert not case.stage.exists()
        assert not case.calls_path.exists()


@pytest.mark.parametrize("change", ["mtime", "not_directory"])
def test_agibot_changed_retained_directory_fails_before_staging(
    tmp_path: Path,
    fake_nav: FakeNavigation,
    change: str,
) -> None:
    """范围3和目录安全底线：保留集 mtime 或目录类型变动时，在暂存和工具执行前拒绝。"""
    with agibot_case(tmp_path, fake_nav) as case:
        path = case.inputs[0]
        info = path.stat()
        if change == "mtime":
            os.utime(path, ns=(info.st_atime_ns, info.st_mtime_ns + 1))
        else:
            shutil.rmtree(path)
            path.write_bytes(b"file")
            os.utime(path, ns=(info.st_atime_ns, info.st_mtime_ns))
        result = case.run()
        assert result.summary is not None and result.summary.outcome is JobOutcome.FAILED
        assert any(
            item.category is DiagnosticCategory.INPUT
            and "输入目录类型或 mtime 已变化" in item.actual
            for group in result.diagnostics
            for item in group.samples
        )
        assert not case.stage.exists()
        assert not case.calls_path.exists()


def test_agibot_output_frame_mismatch_is_reported(
    tmp_path: Path,
    fake_nav: FakeNavigation,
) -> None:
    """范围4：第二集帧数少一帧，以 cleaning.output_mismatch 失败并保留暂存，不写成功回执。"""
    with agibot_case(tmp_path, fake_nav, lengths=(2, 4)) as case:
        result = case.run()
        assert result.summary is not None and result.summary.outcome is JobOutcome.FAILED
        assert any(
            item.rule == "cleaning.output_mismatch" and "episode 1 帧数 4，预览 5" in item.actual
            for group in result.diagnostics
            for item in group.samples
        )
        assert (case.stage / "out").exists()
        assert not (case.stage / "转换回执.json").exists()


def test_agibot_space_estimate_uses_report_bytes_and_manifest_ratio(
    tmp_path: Path,
    fake_nav: FakeNavigation,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """范围1的空间前提：两保留集内容共200字节，清单130%需260，259字节拒绝且不建暂存。"""
    with agibot_case(tmp_path, fake_nav) as case:

        def disk_usage(path: Path) -> SimpleNamespace:
            return SimpleNamespace(free=259)

        monkeypatch.setattr(shutil, "disk_usage", disk_usage)
        result = case.run()
        assert result.summary is not None and result.summary.outcome is JobOutcome.FAILED
        diagnostic = next(
            item
            for group in result.diagnostics
            for item in group.samples
            if item.rule == "conversion.insufficient_space"
        )
        assert "输入 200 字节" in diagnostic.actual
        assert "估算产物 260 字节" in diagnostic.actual
        assert not case.stage.exists()
        assert not case.calls_path.exists()


def test_agibot_preview_convert_rejects_episode_exclusion_http(
    tmp_path: Path,
    fake_nav: FakeNavigation,
) -> None:
    """范围2：经真实应用 POST 返回422，并给出按集剔除的指定文案。"""
    files = fake_agibot(tmp_path / "tool")
    registry = production_registry()
    register_conversion_jobs(
        registry,
        ToolsConfig(
            registry_dir=files.registry,
            library_root=files.library,
            cache_root=tmp_path / "cache",
        ),
        fake_nav.storage_roots,
        None,
    )
    with browser_case(tmp_path / "state", fake_nav, registry=registry) as api:
        seed_agibot_preview(api.engine, files)
        response = api.client.post(
            "/api/cleaning-previews/59/convert",
            json={
                "excluded_episodes": [{"file_index": 0, "segment_index": 0}],
            },
        )
        assert response.status_code == 422
        assert "AgiBot 数据按集剔除，请使用 excluded_files" in response.text


def test_alpha_nested_change_without_directory_mtime_rejects_conversion(
    tmp_path: Path, fake_nav: FakeNavigation
) -> None:
    """回归：增加深度文件后恢复集目录 mtime，仍须拒绝旧预览且不建暂存。"""
    with agibot_case(tmp_path, fake_nav) as case:
        episode = case.inputs[0]
        before = episode.stat()
        depth = episode / "depth"
        depth.mkdir(exist_ok=True)
        (depth / "head_depth_000002.png").write_bytes(b"new depth")
        os.utime(episode, ns=(before.st_atime_ns, before.st_mtime_ns))
        result = case.run()
        assert result.summary is not None and result.summary.outcome is JobOutcome.FAILED
        assert not case.stage.exists()


def test_reregistered_launcher_requires_new_preview(
    tmp_path: Path, fake_nav: FakeNavigation
) -> None:
    """回归：源码树不变但启动器更新且重新登记，也不能复用启动器更新前的预览。"""
    import hashlib

    with agibot_case(tmp_path, fake_nav) as case:
        old = case.files.program.read_bytes()
        new = old + b"\n# launcher changed\n"
        case.files.program.write_bytes(new)
        manifest = case.files.package / "tool.toml"
        manifest.write_text(
            manifest.read_text()
            .replace(f"size = {len(old)}", f"size = {len(new)}")
            .replace(hashlib.sha256(old).hexdigest(), hashlib.sha256(new).hexdigest())
        )
        result = case.run()
        assert result.summary is not None and result.summary.outcome is JobOutcome.FAILED
        assert not case.stage.exists()


@pytest.mark.parametrize("target", ["video", "depth", "h5", "task_info", "tar", "delete_depth"])
def test_alpha_file_changes_with_unchanged_observation_mtime(
    tmp_path: Path, fake_nav: FakeNavigation, target: str
) -> None:
    """回归：只改变实际输入文件或删除深度图，观测目录 mtime 不变仍拒绝旧预览。"""
    with agibot_case(tmp_path, fake_nav) as case:
        episode = case.inputs[0]
        dataset = episode.parent.parent.parent
        candidates = {
            "video": episode / "videos/head.mp4",
            "depth": episode / "depth/head_000001.png",
            "delete_depth": episode / "depth/head_000001.png",
            "h5": dataset
            / "proprio_stats"
            / episode.parent.name
            / episode.name
            / "proprio_stats.h5",
            "task_info": dataset / f"task_info/task_{episode.parent.name}.json",
            "tar": dataset / "proprio_stats/shared.tar",
        }
        before = episode.stat().st_mtime_ns
        path = candidates[target]
        if target == "delete_depth":
            path.unlink()
        else:
            info = path.stat()
            # 同大小的内容改写；纳秒 mtime 显式改变，不能让大小变化代替回归条件。
            path.write_bytes(b"x" * info.st_size)
            os.utime(path, ns=(info.st_atime_ns, info.st_mtime_ns + 1))
        assert episode.stat().st_mtime_ns == before
        result = case.run()
        assert result.summary is not None and result.summary.outcome is JobOutcome.FAILED
        assert any(
            "请重新清洗预览" in item.actual
            for group in result.diagnostics
            for item in group.samples
        )
        assert not case.stage.exists()


def test_alpha_snapshot_rejects_nested_link(tmp_path: Path, fake_nav: FakeNavigation) -> None:
    """保留集新增越界深度链接时不得跟随链接，也不能复用旧预览。"""
    with agibot_case(tmp_path, fake_nav) as case:
        outside = tmp_path / "outside"
        outside.mkdir()
        (case.inputs[0] / "depth/escape").symlink_to(outside, target_is_directory=True)
        result = case.run()
        assert result.summary is not None and result.summary.outcome is JobOutcome.FAILED
        assert not case.stage.exists()


def test_old_alpha_report_remains_readable_but_requires_preview(
    tmp_path: Path, fake_nav: FakeNavigation
) -> None:
    """缺少新字段的历史 Alpha 报告可读；转换不能以目录 mtime 替代缺失快照。"""
    from typing import cast

    from rdp.infra.db.connection import session_scope
    from rdp.jobs.cleaning.records import CleaningPreviewRow, read_preview

    with agibot_case(tmp_path, fake_nav) as case:
        with session_scope(case.dependencies.engine) as session:
            row = session.get(CleaningPreviewRow, 59)
            assert row is not None
            report = dict(row.report)
            report["files"] = [
                {key: value for key, value in item.items() if key != "alpha_input_snapshot"}
                for item in cast(list[dict[str, object]], report["files"])
            ]
            row.report = report
        with session_scope(case.dependencies.engine, read_only=True) as session:
            assert all(
                item.alpha_input_snapshot is None for item in read_preview(session, 59).report.files
            )
        result = case.run()
        assert result.summary is not None and result.summary.outcome is JobOutcome.FAILED
        assert not case.stage.exists()
