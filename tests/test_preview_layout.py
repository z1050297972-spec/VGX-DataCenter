"""M5-04 布局验收：通过真实 API 读本地 RobotProfile，不连接机器人。"""

from pathlib import Path
from typing import Any

from account_api_support import add_actor, api_case
from pydantic import SecretStr

from rdp.api.robot_profiles import configure_robot_profiles

PROFILES = Path(__file__).parents[1] / "profiles"


def test_r1lite_layout_contains_cameras_and_paired_position_plots(tmp_path: Path) -> None:
    """验收 2：三路相机、五组有已确认单位的位置曲线，排除右目和底盘；默认只开首关节。"""
    with api_case(tmp_path) as case:
        configure_robot_profiles(case.app, profiles_dir=PROFILES)
        add_actor(case)
        case.login("member", SecretStr("member-updated-value"))
        created = case.client.post(
            "/api/robots", json={"name": "预览样本", "robot_model": "Galaxea R1 Lite"}
        )
        assert created.status_code == 201
        identifier = created.json()["robot_id"]
        response = case.client.get(f"/api/robots/{identifier}/preview-layout")
        assert response.status_code == 200
        layout = response.json()
        panels = layout["configById"]
        images = {key: value for key, value in panels.items() if key.startswith("Image!")}
        assert {panel["imageMode"]["imageTopic"] for panel in images.values()} == {
            "/viz/camera/head_left",
            "/viz/camera/wrist_left",
            "/viz/camera/wrist_right",
        }
        assert len(images) == 3
        assert "Image!head_right" not in panels
        assert {key for key in panels if key.startswith("Plot!")} == {
            "Plot!left_arm",
            "Plot!right_arm",
            "Plot!left_gripper",
            "Plot!right_gripper",
            "Plot!torso",
        }
        left_arm = panels["Plot!left_arm"]
        assert len(left_arm["paths"]) == 12
        assert {path["value"] for path in left_arm["paths"] if path["enabled"]} == {
            "/viz/joint/left_arm/obs.position[0]",
            "/viz/joint/left_arm/target.position[0]",
        }
        assert {
            name: panel["yAxisLabel"] for name, panel in panels.items() if name.startswith("Plot!")
        } == {
            "Plot!left_arm": "position (rad)",
            "Plot!right_arm": "position (rad)",
            "Plot!left_gripper": "position (0-100)",
            "Plot!right_gripper": "position (0-100)",
            "Plot!torso": "position (rad)",
        }
        assert {path["timestampMethod"] for path in left_arm["paths"]} == {"receiveTime"}

        def leaves(node: Any) -> set[str]:
            if isinstance(node, str):
                return {node}
            return leaves(node["first"]) | leaves(node["second"])

        assert leaves(layout["layout"]) == set(panels)


def test_unknown_joint_unit_is_not_assumed_to_be_radians(tmp_path: Path) -> None:
    """单位缺省时轴标签仍为单位未确认，不把 R1 Lite 已确认的单位推广到其他说明档。"""
    profiles = tmp_path / "profiles"
    profiles.mkdir()
    source = (PROFILES / "r1lite.toml").read_text(encoding="utf-8")
    (profiles / "unknown-units.toml").write_text(
        "\n".join(line for line in source.splitlines() if not line.startswith("unit =")),
        encoding="utf-8",
    )
    with api_case(tmp_path / "api") as case:
        configure_robot_profiles(case.app, profiles_dir=profiles)
        add_actor(case)
        case.login("member", SecretStr("member-updated-value"))
        created = case.client.post(
            "/api/robots", json={"name": "未知单位样本", "robot_model": "Galaxea R1 Lite"}
        )
        response = case.client.get(f"/api/robots/{created.json()['robot_id']}/preview-layout")
        assert response.status_code == 200
        panels = response.json()["configById"]
        assert {
            panel["yAxisLabel"] for name, panel in panels.items() if name.startswith("Plot!")
        } == {"单位未确认"}


def test_unknown_model_has_actionable_profile_diagnostic(tmp_path: Path) -> None:
    """布局缺少型号说明档时返回 404 五段诊断，不能返回空布局假装可用。"""
    with api_case(tmp_path) as case:
        configure_robot_profiles(case.app, profiles_dir=PROFILES)
        add_actor(case)
        case.login("member", SecretStr("member-updated-value"))
        created = case.client.post(
            "/api/robots", json={"name": "其他型号", "robot_model": "未知型号"}
        )
        response = case.client.get(f"/api/robots/{created.json()['robot_id']}/preview-layout")
        assert response.status_code == 404
        assert "该型号没有 RobotProfile" in response.text
