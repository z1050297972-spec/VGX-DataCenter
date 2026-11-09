"""逐条移植工具 h264.rs 三个测试，并用合成 MCAP 检查门控及文件级拒绝。"""

from pathlib import Path

from cleaning_support import B_SLICE, IDR, P_SLICE, configs, ignore_progress, noop, write_scene

from rdp.jobs.cleaning import build_cleaning_report
from rdp.jobs.cleaning._h264 import KeyframeGate, has_b_slice, is_keyframe, nal_units


def test_splits_nal_units() -> None:
    """Rust 的 IDR 测试码流得到 SPS/PPS/IDR，四字节起始码的尾零不污染 NAL。"""
    units = list(nal_units(IDR))
    assert [nal[0] & 0x1F for nal in units] == [7, 8, 5]
    assert units[0] == bytes([0x67, 0x64])


def test_detects_keyframe_and_b_slice() -> None:
    """Rust 的 P、B、IDR 最小头能区分关键帧和 B slice。"""
    assert is_keyframe(IDR)
    assert not is_keyframe(P_SLICE)
    assert not has_b_slice(P_SLICE)
    assert not has_b_slice(IDR)
    assert has_b_slice(B_SLICE)


def test_gate_waits_for_keyframe() -> None:
    """门控先拒绝 P，在 IDR 后接受 P，与 Rust gate_waits_for_keyframe 一致。"""
    gate = KeyframeGate()
    assert not gate.accept(P_SLICE)
    assert gate.accept(IDR)
    assert gate.accept(P_SLICE)


def test_pre_keyframe_messages_do_not_align(tmp_path: Path) -> None:
    """每个文件重新等待关键帧；两条前导 P 不进入基准，H.264 标记未检查画面。"""
    tool, rules = configs(tmp_path)
    paths = [tmp_path / "first.mcap", tmp_path / "second.mcap"]
    for path in paths:
        write_scene(path, "gate")
    report = build_cleaning_report(
        [("source", p) for p in paths], tool, rules, checkpoint=noop, progress=ignore_progress
    )
    assert [file.reference_frames for file in report.files] == [118, 118]
    assert [file.kept_frames for file in report.files] == [118, 118]
    assert all(not file.fatal_issues for file in report.files)
    assert report.files[0].topics[0].image_check == "unchecked_h264"
    warning = next(d for d in report.files[0].warnings if d.rule == "cleaning.pre_keyframe")
    assert "2" in warning.actual
    assert dict((obj.key, obj.value) for obj in warning.objects)["topic"] == "/camera"


def test_b_slice_is_fatal(tmp_path: Path) -> None:
    """含 B slice 的文件有带话题身份的致命诊断，默认剔除且不产出 episode。"""
    tool, rules = configs(tmp_path)
    path = tmp_path / "b.mcap"
    write_scene(path, "b_slice")
    report = build_cleaning_report(
        [("source", path)], tool, rules, checkpoint=noop, progress=ignore_progress
    )
    assert report.files[0].default_excluded
    issue = report.files[0].fatal_issues[0]
    assert "B slice" in issue.actual
    assert "剔除" in issue.consequence
    assert {o.key: o.value for o in issue.objects} == {"file": str(path), "topic": "/camera"}
    assert report.episodes == ()
