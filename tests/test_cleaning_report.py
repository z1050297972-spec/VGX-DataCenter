"""只用现场生成的小 MCAP 验证工单的对齐报告和五项数值检查。"""

from pathlib import Path

import pytest
from cleaning_support import configs, ignore_progress, noop, write_scene

from rdp.jobs.cleaning import CleaningReport, build_cleaning_report


def test_alignment_segments_and_file_failure_isolation(tmp_path: Path) -> None:
    """验证坏帧、短段和文件失败隔离，以及报告保存 R1 Lite 生效规则和严重检查清单。"""
    tool, rules = configs(tmp_path)
    bad = tmp_path / "bad.mcap"
    good = tmp_path / "good.mcap"
    write_scene(bad, "missing")
    write_scene(good, "gaps", 320)
    report = build_cleaning_report(
        [("bad-source", bad), ("good-source", good)],
        tool,
        rules,
        checkpoint=noop,
        progress=ignore_progress,
    )
    assert report.files[0].default_excluded
    issue = report.files[0].fatal_issues[0]
    assert issue.rule == "cleaning.missing_topic"
    assert "没有消息" in issue.actual
    assert "其他文件继续" in issue.consequence
    assert {obj.key: obj.value for obj in issue.objects} == {"file": str(bad), "topic": "/wrist"}
    file = report.files[1]
    assert not file.fatal_issues
    assert not file.default_excluded
    assert (file.reference_frames, file.kept_frames, file.bad_frames, file.gaps) == (320, 262, 8, 1)
    assert (file.short_segments, file.short_frames) == (1, 50)
    assert [
        (e.file_index, e.segment_index, e.start_frame, e.end_frame, e.frame_count)
        for e in report.episodes
    ] == [(1, 0, 0, 101, 101), (1, 1, 109, 270, 161)]
    assert all(e.default_action == "keep" for e in report.episodes)
    wrist = next(t for t in file.topics if t.topic == "/wrist")
    assert wrist.bad_frames == 8
    assert wrist.reused_frames == 10
    assert next(t for t in file.topics if t.topic == "/optional").missing_optional
    assert report.summary.files == 2
    assert report.summary.excluded_files == 1
    assert report.summary.kept_frames == 262
    assert CleaningReport.model_validate_json(report.model_dump_json()) == report
    # 正式登记配置只读；空输入即可核对规则快照，无需访问真实 MCAP 或存储根。
    package = Path(__file__).parents[1] / "tools/mcap2lerobot"
    r1lite = build_cleaning_report(
        [],
        package / "configs/r1lite.toml",
        package / "cleaning/r1lite.toml",
        checkpoint=noop,
        progress=ignore_progress,
    )
    assert r1lite.rules.sync.max_frame_gap_ms == pytest.approx(53.333333333333336)
    assert r1lite.rules.sync.min_episode_frames == 90
    assert r1lite.rules.checks.model_dump(mode="json")["severe_checks"] == [
        "non_finite",
        "entire_static",
    ]


@pytest.mark.parametrize(
    ("mode", "expected"),
    [
        ("static", ("entire_static", 120, 0.0, "exclude")),
        ("nan", ("non_finite", 1, 2.0, "exclude")),
        ("jump", ("action_jump", 1, 2.0, "keep")),
        ("frozen", ("camera_frozen", 1, 0.0, "keep")),
        ("black", ("dark_image", 4, 0.0, "keep")),
    ],
)
def test_episode_quality_checks(
    tmp_path: Path, mode: str, expected: tuple[str, int, float, str]
) -> None:
    """整段静止和 NaN 默认剔除；一次跳变、相同 JPEG 冻结、黑屏只提示。"""
    check, count, first_s, action = expected
    tool, rules = configs(tmp_path)
    path = tmp_path / f"{mode}.mcap"
    write_scene(path, mode)
    report = build_cleaning_report(
        [("source", path)], tool, rules, checkpoint=noop, progress=ignore_progress
    )
    assert not report.files[0].fatal_issues
    assert len(report.episodes) == 1
    episode = report.episodes[0]
    issue = next(issue for issue in episode.issues if issue.check == check)
    assert issue.details.count == count
    assert issue.details.first_time_s == first_s
    assert episode.default_action == action
    assert issue.severity == ("severe" if action == "exclude" else "hint")
    assert {obj.key: obj.value for obj in issue.diagnostic.objects}["file"] == str(path)
    assert report.summary.excluded_episodes == (1 if action == "exclude" else 0)
