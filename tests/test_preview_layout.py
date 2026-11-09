"""M5-04 布局验收：通过真实 API 读本地 RobotProfile，不连接机器人。"""

from pathlib import Path
from typing import Any

from account_api_support import add_actor, api_case
from pydantic import SecretStr

from rdp.api.robot_profiles import configure_robot_profiles

PROFILES = Path(__file__).parents[1] / "profiles"


def test_r1lite_layout_contains_cameras_and_paired_position_plots(tmp_path: Path) -> None:
    """验收 2：四路相机、五组位置曲线，排除底盘；默认只开首关节，未知单位不冒充 rad。"""
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
            "/viz/camera/head_right",
            "/viz/camera/wrist_left",
            "/viz/camera/wrist_right",
        }
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
        assert left_arm["yAxisLabel"] == "单位未确认"
        assert {path["timestampMethod"] for path in left_arm["paths"]} == {"receiveTime"}

        def leaves(node: Any) -> set[str]:
            if isinstance(node, str):
                return {node}
            return leaves(node["first"]) | leaves(node["second"])

        assert leaves(layout["layout"]) == set(panels)


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
