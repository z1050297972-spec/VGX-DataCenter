"""M5-01 验收：只读仓库说明档，经真实应用验证读取；不连接机器人。"""

from pathlib import Path

import pytest
from account_api_support import add_actor, api_case
from pydantic import SecretStr

from rdp.api.robot_profiles import configure_robot_profiles
from rdp.collection.profile import find_profile_by_model, load_robot_profiles
from rdp.infra.diagnostics import InputError

PROFILES = Path(__file__).parents[1] / "profiles"


def test_member_reads_profiles_and_paired_joint_sources(tmp_path: Path) -> None:
    """验收 1：登录成员可读两份正式文件，R1 Lite 四组来源成对，AutoLife 有未知事实。"""
    with api_case(tmp_path) as case:
        configure_robot_profiles(case.app, profiles_dir=PROFILES)
        assert case.client.get("/api/robot-profiles").status_code == 401
        add_actor(case)
        assert case.login("member", SecretStr("member-updated-value")).status_code == 200
        response = case.client.get("/api/robot-profiles")
        assert response.status_code == 200
        items = {item["profile"]: item for item in response.json()["items"]}
        assert set(items) == {"autolife", "r1lite"}
        assert items["autolife"]["unknown_count"] > 0
        assert items["r1lite"]["model"] == "Galaxea R1 Lite"
        assert items["r1lite"]["version"] == 1
        response = case.client.get("/api/robot-profiles/r1lite")
        assert response.status_code == 200
        groups = {group["name"]: group for group in response.json()["joint_group"]}
        for name, count, observation, target in (
            (
                "left_arm",
                6,
                "/hdas/feedback_arm_left",
                "/motion_target/target_joint_state_arm_left",
            ),
            (
                "right_arm",
                6,
                "/hdas/feedback_arm_right",
                "/motion_target/target_joint_state_arm_right",
            ),
            (
                "left_gripper",
                1,
                "/hdas/feedback_gripper_left",
                "/motion_target/target_position_gripper_left",
            ),
            (
                "right_gripper",
                1,
                "/hdas/feedback_gripper_right",
                "/motion_target/target_position_gripper_right",
            ),
        ):
            assert groups[name]["joint_count"] == count
            assert groups[name]["observation"]["topic"] == observation
            assert groups[name]["target"]["topic"] == target
        assert {"torso", "chassis"} <= groups.keys()
        assert {camera["name"] for camera in response.json()["camera"]} == {
            "head_left",
            "head_right",
            "wrist_left",
            "wrist_right",
        }
        assert case.client.get("/api/robot-profiles/autolife").status_code == 200


@pytest.mark.parametrize("invalid", ["extra", "missing_dimension"])
def test_bad_profile_rejects_loading_with_file_and_key(tmp_path: Path, invalid: str) -> None:
    """验收 2：未知键或关节名和个数均缺使整批读取失败，诊断指出文件和键路径。"""
    source = (PROFILES / "r1lite.toml").read_text(encoding="utf-8")
    if invalid == "extra":
        source = 'unexpected = "not-a-profile-fact"\n' + source
        expected_key = "unexpected"
    else:
        source = source.replace("joint_count = 6\n", "", 1)
        expected_key = "joint_group.0"
    path = tmp_path / "broken.toml"
    path.write_text(source, encoding="utf-8")
    with pytest.raises(InputError) as caught:
        load_robot_profiles(tmp_path)
    diagnostic = caught.value.diagnostics[0]
    assert {item.key: item.value for item in diagnostic.objects} == {
        "file": str(path),
        "key": expected_key,
    }
    assert diagnostic.rule.startswith("robot_profile.")
    assert diagnostic.actual and diagnostic.expected


def test_find_profile_by_registered_model() -> None:
    """验收 3：按登记的型号精确匹配；没有 Profile 的型号返回 None。"""
    profiles = load_robot_profiles(PROFILES)
    profile = find_profile_by_model(profiles, "Galaxea R1 Lite")
    assert profile is not None and profile.profile == "r1lite"
    assert find_profile_by_model(profiles, "unknown-model") is None
