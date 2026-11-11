"""工单限定的工具配置与输入展开测试。"""

import tomllib
from pathlib import Path

import pytest
from cleaning_support import CONFIG, noop
from pydantic import ValidationError

from rdp.infra.diagnostics import InputError
from rdp.jobs.cleaning._config import ToolConfig, load_configs
from rdp.jobs.cleaning._io import collect_inputs


def test_r1lite_configuration_and_tolerances() -> None:
    """登记副本可解析，三个相机及夹爪目标的容差与人工读取值一致。"""
    root = Path(__file__).resolve().parents[1]
    config, rules, tool_hash, rules_hash = load_configs(
        root / "tools/mcap2lerobot/configs/r1lite.toml",
        root / "tools/mcap2lerobot/cleaning/r1lite.toml",
    )
    assert config.fps == 30
    assert config.sync.min_episode_frames == 90
    assert config.topic_tolerances() == (
        ("/hdas/camera_head/left_raw/image_raw_color/compressed", 10),
        ("/hdas/camera_wrist_left/color/image_raw/compressed", 35),
        ("/hdas/camera_wrist_right/color/image_raw/compressed", 35),
        ("/hdas/feedback_arm_left", 10),
        ("/hdas/feedback_gripper_left", 10),
        ("/hdas/feedback_arm_right", 10),
        ("/hdas/feedback_gripper_right", 10),
        ("/motion_target/target_joint_state_arm_left", 10),
        ("/motion_target/target_position_gripper_left", 30),
        ("/motion_target/target_joint_state_arm_right", 10),
        ("/motion_target/target_position_gripper_right", 30),
    )
    assert config.is_optional_topic("/motion_target/target_position_gripper_left")
    assert not config.is_optional_topic(config.sync.reference_topic)
    assert rules.static.feature == "observation.state"
    assert len(tool_hash) == len(rules_hash) == 64


@pytest.mark.parametrize("case", ["optional_reference", "missing_fill"])
def test_optional_configuration_is_rejected(case: str) -> None:
    """可选话题不能做基准，optional 没有 fill 也必须拒绝。"""
    text = CONFIG
    if case == "optional_reference":
        text = text.replace('reference_topic = "/camera"', 'reference_topic = "/optional"')
    else:
        text = text.replace(", fill = [100.0]", "")
    with pytest.raises(ValidationError):
        ToolConfig.model_validate(tomllib.loads(text))


def test_collects_recursively_sorted_and_deduped(tmp_path: Path) -> None:
    """移植 Rust 递归排序去重测试；另用前缀路径区分分量排序与整串排序。"""
    (tmp_path / "sub").mkdir()
    for name in ("b.mcap", "a.MCAP", "note.txt", "sub/c.mcap"):
        (tmp_path / name).write_bytes(b"")
    files, warnings = collect_inputs(
        [("directory", tmp_path), ("duplicate", tmp_path / "b.mcap")], noop
    )
    assert [str(p.relative_to(tmp_path)) for _, p in files] == ["a.MCAP", "b.mcap", "sub/c.mcap"]
    assert [source for source, _ in files] == ["directory"] * 3
    assert not warnings
    (tmp_path / "empty").mkdir()
    with pytest.raises(InputError):
        collect_inputs([("empty", tmp_path / "empty")], noop)
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "z.mcap").write_bytes(b"")
    (tmp_path / "a.mcap").write_bytes(b"")
    files, _ = collect_inputs([("directory", tmp_path)], noop)
    names = [str(p.relative_to(tmp_path)) for _, p in files]
    assert names.index("a/z.mcap") < names.index("a.mcap")
