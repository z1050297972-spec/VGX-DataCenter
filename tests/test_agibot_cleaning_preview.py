"""M4.6-03 的工具预览关键契约；仅执行临时假程序，不读取真实数据。"""

import hashlib
import json
import os
import re
from pathlib import Path
from typing import cast

import pytest
from agibot_preview_support import CONFIG, RULES, agibot_case, preview_result

from rdp.infra.diagnostics import DiagnosticCategory
from rdp.jobs.conversion._cleaning_selection import select
from rdp.jobs.conversion.parameters import ConversionOptions
from rdp.jobs.errors import JobInputError, JobNotFoundError
from rdp.jobs.outcome import JobOutcome
from rdp.jobs.types import JobState


def test_preview_maps_tool_result_and_cleans_result(tmp_path: Path) -> None:
    """真实参数、沙箱、指纹和报告映射正确；体检失败剔文件，非有限值剔段，长静止保留。"""
    payload = preview_result(tmp_path / "input/observations/327")
    with agibot_case(tmp_path, payload) as case:
        result = case.run()
        assert result.summary is not None and result.summary.outcome is JobOutcome.SUCCEEDED
        preview = case.preview()
        report = preview.report
        assert preview.binary_sha256 != case.tree_sha256
        assert len(preview.binary_sha256) == 64
        assert report.source_format == "agibot_native"
        assert report.summary.model_dump() == {
            "files": 3,
            "excluded_files": 1,
            "episodes": 2,
            "excluded_episodes": 1,
            "reference_frames": 180,
            "kept_frames": 180,
        }
        assert [f.episode_id for f in report.files] == ["2", "10", "20"]
        assert [
            (f.file_index, f.source_id, f.path, f.size_bytes, f.reference_frames, f.kept_frames)
            for f in report.files
        ] == [
            (0, "source-preview", str(case.task / "2"), 1000, 0, 0),
            (1, "source-preview", str(case.task / "10"), 1000, 60, 60),
            (2, "source-preview", str(case.task / "20"), 1000, 120, 120),
        ]
        assert report.files[1].mtime_ns == (case.task / "10").stat().st_mtime_ns
        assert [f.default_excluded for f in report.files] == [True, False, False]
        assert len(report.files[0].fatal_issues) == 2
        assert all(
            d.rule == "cleaning.agibot_episode_unusable" for d in report.files[0].fatal_issues
        )
        assert [e.file_index for e in report.episodes] == [1, 2]
        assert [e.default_action for e in report.episodes] == ["exclude", "keep"]
        assert [e.duration_s for e in report.episodes] == [2.0, 4.0]
        assert [
            (
                e.segment_index,
                e.start_frame,
                e.end_frame,
                e.frame_count,
                e.start_time_s,
                e.stamp_span_s,
            )
            for e in report.episodes
        ] == [(0, 0, 60, 60, 0, 2.0), (0, 0, 120, 120, 0, 4.0)]
        assert report.episodes[1].issues[0].details.ranges[0].end_s == 3.0
        assert report.tool_config_sha256 == hashlib.sha256(CONFIG.encode()).hexdigest()
        assert report.rules_sha256 == hashlib.sha256(RULES.encode()).hexdigest()
        assert report.reference_topic is None and report.rules.sync is None
        assert report.fps == 30
        assert report.rules.checks.model_dump() == {
            "static_feature": "observation.state",
            "long_static_s": 3.0,
            "jump_feature": "action",
            "frozen_s": None,
            "sample_interval_s": None,
            "dark_below": None,
            "bright_above": None,
            "sources": (
                {
                    "topic": "state/joint/position",
                    "static_threshold": 0.001,
                    "jump_threshold": 0.2,
                    "limits": ((-1.0, 1.0),),
                },
            ),
            "severe_checks": ("non_finite", "entire_static"),
        }
        package = case.tools.registry_dir / "agibot2lerobot"
        assert json.loads((case.cache / "arguments.json").read_text()) == {
            "events": "/dev/stderr",
            "command": "preview",
            "c": str(package / "config.toml"),
            "rules": str(package / "rules.toml"),
            "index_cache": str(case.cache),
            "result": str(case.cache / "preview-71.json"),
            "task_dir": str(case.task),
        }
        assert case.sandbox_calls[0][1].writable == (case.cache,)
        assert case.sandbox_calls[0][2] == (tmp_path / "input",)
        assert not (case.cache / "preview-71.json").exists()
        assert result.progress is not None and result.progress.stage_name == "生成报告"


@pytest.mark.parametrize("invalid", ["two_sources", "wrong_directory", "outside_root"])
def test_invalid_task_selection_never_runs_tool(tmp_path: Path, invalid: str) -> None:
    """多选、非任务观测目录或登记根外路径属于输入问题，工具不得运行或保存报告。"""
    task = tmp_path / "input/observations/327"
    payload = preview_result(task)
    match invalid:
        case "two_sources":
            other = task.with_name("328")
            other.mkdir()
            inputs = (task, other)
        case "outside_root":
            other = tmp_path / "outside/observations/327"
            other.mkdir(parents=True)
            inputs = (other,)
        case _:
            inputs = (task.parent,)
    with agibot_case(tmp_path, payload, inputs=inputs) as case:
        result = case.run(
            ("source-preview", "source-1") if len(inputs) == 2 else ("source-preview",)
        )
        assert result.summary is not None and result.summary.outcome is JobOutcome.FAILED
        diagnostic = result.diagnostics[0].samples[0]
        assert diagnostic.category is DiagnosticCategory.INPUT
        assert diagnostic.expected is not None
        assert "请选择一个已解压的任务观测目录" in diagnostic.expected
        assert not case.sandbox_calls
        with pytest.raises(JobNotFoundError):
            case.preview()


@pytest.mark.parametrize(
    "invalid", ["extra", "episode_extra", "escape", "check", "sha256", "version"]
)
def test_invalid_tool_result_is_external_failure(tmp_path: Path, invalid: str) -> None:
    """未知字段、越界 episode、未知检查、配置指纹或版本类型不符拒绝结果，删除文件且不落库。"""
    task = tmp_path / "input/observations/327"
    payload = preview_result(task)
    episodes = cast(list[dict[str, object]], payload["episodes"])
    match invalid:
        case "extra":
            payload["unexpected"] = True
        case "episode_extra":
            episodes[0]["unexpected"] = True
        case "escape":
            episodes[0]["observation_dir"] = str(task.parent / "999/1")
        case "check":
            cast(list[dict[str, object]], episodes[1]["issues"])[0]["check"] = "unknown"
        case "sha256":
            cast(dict[str, object], payload["robot_config"])["sha256"] = "0" * 64
        case "version":
            payload["schema_version"] = True
        case _:
            pytest.fail("未知测试场景")
    with agibot_case(tmp_path, payload) as case:
        result = case.run()
        assert result.summary is not None and result.summary.outcome is JobOutcome.FAILED
        group = next(d for d in result.diagnostics if d.rule == "cleaning.tool_preview_invalid")
        diagnostic = group.samples[0]
        assert diagnostic.category is DiagnosticCategory.EXTERNAL
        assert diagnostic.actual and diagnostic.expected and diagnostic.next_step
        assert "未保存报告" in diagnostic.consequence
        assert any(
            item.key == "path" and item.value == str(case.cache / "preview-71.json")
            for item in diagnostic.objects
        )
        assert not (case.cache / "preview-71.json").exists()
        with pytest.raises(JobNotFoundError):
            case.preview()


def test_failed_tool_removes_partial_result(tmp_path: Path) -> None:
    """工具写出结果后非零退出仍失败，不能读取部分报告，结果文件必须清理。"""
    payload = preview_result(tmp_path / "input/observations/327")
    with agibot_case(tmp_path, payload, exit_code=1) as case:
        result = case.run()
        assert result.summary is not None and result.summary.outcome is JobOutcome.FAILED
        assert result.summary.tool_exit_code == 1
        assert len(case.sandbox_calls) == 1
        assert not (case.cache / "preview-71.json").exists()
        with pytest.raises(JobNotFoundError):
            case.preview()


def test_cancelled_preview_removes_result(tmp_path: Path) -> None:
    """结果已写出时取消，作业进入取消终态，回收工具后删除结果且不保存报告。"""
    payload = preview_result(tmp_path / "input/observations/327")
    with agibot_case(tmp_path, payload) as case:
        result = case.run(cancel_after_result=True)
        assert result.state is JobState.CANCELLED
        assert (case.cache / "arguments.json").exists()
        assert not (case.cache / "preview-71.json").exists()
        with pytest.raises(JobNotFoundError):
            case.preview()


@pytest.mark.parametrize("use_default_duration", [False, True])
def test_tool_rule_snapshot_accepts_zero_and_default_duration(
    tmp_path: Path, use_default_duration: bool
) -> None:
    """规则快照与真实 parse_rules 一致：阈值允许零，long_static_s 缺省为 3 秒。"""
    payload = preview_result(tmp_path / "input/observations/327")
    with agibot_case(tmp_path, payload) as case:
        rules = RULES.replace("0.001", "0.0").replace("0.2", "0.0")
        rules = rules.replace(
            "long_static_s = 3.0\n", "" if use_default_duration else "long_static_s = 0.0\n"
        )
        (case.tools.registry_dir / "agibot2lerobot/rules.toml").write_text(rules)
        result = case.run()
        assert result.summary is not None and result.summary.outcome is JobOutcome.SUCCEEDED
        checks = case.preview().report.rules.checks
        assert checks.long_static_s == (3.0 if use_default_duration else 0.0)
        assert checks.sources[0].static_threshold == checks.sources[0].jump_threshold == 0.0


@pytest.mark.parametrize(
    ("field", "value"), [("task_id", 327), ("task_id", "task-327"), ("task", 123)]
)
def test_tool_identity_and_task_do_not_coerce_types(
    tmp_path: Path, field: str, value: object
) -> None:
    """接受真实字符串 ID 和可空任务文本时，仍拒绝整数 ID、非数字 ID 及数值任务文本。"""
    payload = preview_result(tmp_path / "input/observations/327")
    if field == "task_id":
        payload[field] = value
    else:
        cast(list[dict[str, object]], payload["episodes"])[0][field] = value
    with agibot_case(tmp_path, payload) as case:
        result = case.run()
        assert result.summary is not None and result.summary.outcome is JobOutcome.FAILED
        assert any(group.rule == "cleaning.tool_preview_invalid" for group in result.diagnostics)
        assert not (case.cache / "preview-71.json").exists()
        with pytest.raises(JobNotFoundError):
            case.preview()


def _partial_task_result(task: Path) -> dict[str, object]:
    """模拟真实联合集号报告：两集有观测，另三集只在标注/本体感知中出现且体检失败。"""
    payload = preview_result(task)
    episodes = cast(list[dict[str, object]], payload["episodes"])
    (task / "2").rmdir()
    missing = {
        **episodes[0],
        "observation_mtime_ns": None,
        "size_bytes": 0,
        "problems": ["观测目录不存在"],
    }
    payload["episodes"] = [
        *episodes[1:],
        *(
            {**missing, "episode_id": identifier, "observation_dir": str(task / identifier)}
            for identifier in ("2", "3", "4")
        ),
    ]
    return payload


def test_alpha_partial_task_attaches_only_existing_snapshots(tmp_path: Path) -> None:
    """缺观测 fatal 行不阻断预览且不能保留；两集实际观测各自持有平台快照。"""
    payload = _partial_task_result(tmp_path / "input/observations/327")
    with agibot_case(tmp_path, payload) as case:
        result = case.run()
        assert result.summary is not None and result.summary.outcome is JobOutcome.SUCCEEDED
        preview = case.preview()
        missing = [item for item in preview.report.files if item.episode_id in {"2", "3", "4"}]
        existing = [item for item in preview.report.files if item.episode_id in {"10", "20"}]
        assert len(missing) == 3 and len(existing) == 2
        assert all(
            item.alpha_input_snapshot is None and item.fatal_issues and item.default_excluded
            for item in missing
        )
        assert all(item.alpha_input_snapshot for item in existing)
        excluded = [item.file_index for item in missing]
        selection = select(preview, ConversionOptions(excluded_files=excluded))
        assert selection.files == tuple(existing)
        assert [item.file_index for item in selection.episodes] == [
            item.file_index for item in existing
        ]
        for retained in excluded:
            with pytest.raises(JobInputError):
                select(
                    preview,
                    ConversionOptions(
                        excluded_files=[index for index in excluded if index != retained]
                    ),
                )


@pytest.mark.parametrize(
    "invalid", ["missing_without_fatal", "omitted_existing", "duplicate_path", "duplicate_id"]
)
def test_alpha_partial_task_rejects_incomplete_or_ambiguous_report(
    tmp_path: Path, invalid: str
) -> None:
    """仅 fatal 缺观测行可无快照；遗漏已有集、重复路径或集号仍拒绝整份报告。"""
    payload = _partial_task_result(tmp_path / "input/observations/327")
    episodes = cast(list[dict[str, object]], payload["episodes"])
    match invalid:
        case "missing_without_fatal":
            episodes[2] = {
                **episodes[0],
                "episode_id": "2",
                "observation_dir": episodes[2]["observation_dir"],
                "observation_mtime_ns": None,
            }
        case "omitted_existing":
            del episodes[0]
        case "duplicate_path":
            episodes.append({**episodes[0], "episode_id": "11"})
        case "duplicate_id":
            episodes[1]["episode_id"] = episodes[0]["episode_id"]
        case _:
            pytest.fail("未知测试场景")
    with agibot_case(tmp_path, payload) as case:
        result = case.run()
        assert result.summary is not None and result.summary.outcome is JobOutcome.FAILED
        assert any(
            item.category is DiagnosticCategory.INPUT
            and "请重新预览：Alpha 报告集身份重复、遗漏已有观测或可转集缺少输入快照"
            in (item.expected or "")
            for group in result.diagnostics
            for item in group.samples
        )
        assert not (case.cache / "preview-71.json").exists()
        with pytest.raises(JobNotFoundError):
            case.preview()


@pytest.mark.parametrize("partial", [False, True])
@pytest.mark.parametrize("change", ["video_content", "video_mtime", "depth_added", "depth_removed"])
def test_alpha_preview_rejects_input_changed_while_tool_runs(
    tmp_path: Path, partial: bool, change: str
) -> None:
    """完整/部分任务均复核子文件内容、mtime 和深度集合；根/集目录 mtime 不变也拒绝。"""
    task = tmp_path / "input/observations/327"
    payload = _partial_task_result(task) if partial else preview_result(task)
    task_info = task.stat()
    episode = task / "10"
    info = episode.stat()
    video = episode / "videos/head.mp4"
    video.parent.mkdir()
    video.write_bytes(b"before")
    video_info = video.stat()
    depth = episode / "depth/head/000001.png"
    depth.parent.mkdir(parents=True)
    if change == "depth_removed":
        depth.write_bytes(b"depth")
    os.utime(episode, ns=(info.st_atime_ns, info.st_mtime_ns))
    video_mtime = (
        f"os.utime({str(video)!r}, "
        f"ns=({video_info.st_atime_ns}, {video_info.st_mtime_ns + 1_000_000_000}))"
    )
    mutations = {
        "video_content": f'pathlib.Path({str(video)!r}).write_bytes(b"change")\n{video_mtime}',
        "video_mtime": video_mtime,
        "depth_added": f'pathlib.Path({str(depth)!r}).write_bytes(b"depth")',
        "depth_removed": f"pathlib.Path({str(depth)!r}).unlink()",
    }
    with agibot_case(tmp_path, payload) as case:
        launcher = case.tools.library_root / "agibot2lerobot/preview"
        source = launcher.read_text().replace(
            'with pathlib.Path(a.result).open("x") as stream:',
            mutations[change] + '\nwith pathlib.Path(a.result).open("x") as stream:',
        )
        launcher.write_text(source)
        manifest = case.tools.registry_dir / "agibot2lerobot/tool.toml"
        text = re.sub(r"size = [0-9]+", f"size = {len(source.encode())}", manifest.read_text())
        text = re.sub(
            r'(?m)^sha256 = "[0-9a-f]+"',
            f'sha256 = "{hashlib.sha256(source.encode()).hexdigest()}"',
            text,
        )
        manifest.write_text(text)
        result = case.run()
        assert result.summary is not None and result.summary.outcome is JobOutcome.FAILED
        assert any(
            "输入文件集合或元信息在预览期间变化" in (item.expected or "")
            for group in result.diagnostics
            for item in group.samples
        )
        assert episode.stat().st_mtime_ns == info.st_mtime_ns
        assert task.stat().st_mtime_ns == task_info.st_mtime_ns
        if change.startswith("video_"):
            assert video.stat().st_size == video_info.st_size
            assert video.stat().st_mtime_ns != video_info.st_mtime_ns
            assert video.read_bytes() == (b"change" if change == "video_content" else b"before")
        else:
            assert depth.exists() == (change == "depth_added")
        assert not (case.cache / "preview-71.json").exists()
        with pytest.raises(JobNotFoundError):
            case.preview()
