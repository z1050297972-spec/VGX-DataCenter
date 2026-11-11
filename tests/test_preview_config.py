"""M5-09 配置协议验收；只读取仓库说明档，不导入机器人端程序。"""

from pathlib import Path

from rdp.collection.preview_config import build_relay_config
from rdp.collection.profile import load_robot_profiles


def test_r1lite_routes_and_hostname_binding() -> None:
    """验收 7：四相机不限频，十一 JointState 限 50 Hz，主机名绑定所有接口。"""
    profile = next(p for p in load_robot_profiles(Path("profiles")) if p.profile == "r1lite")
    config = build_relay_config(profile, "robot.local")
    assert config["host"] == "0.0.0.0"  # noqa: S104  # 理由：只核对配置字面量，不监听端口。
    assert config["profile_version"] == 4
    assert config["qos_reliability"] == "best_effort"
    routes = config["routes"]
    assert isinstance(routes, list)
    assert len(routes) == 15
    cameras = [
        r for r in routes if isinstance(r, dict) and str(r["channel"]).startswith("/viz/camera/")
    ]
    assert [(r["channel"], r["transform"], r["max_rate_hz"]) for r in cameras] == [
        ("/viz/camera/head_left", "h264_to_compressed_video", None),
        ("/viz/camera/head_right", "h264_to_compressed_video", None),
        ("/viz/camera/wrist_left", "passthrough", None),
        ("/viz/camera/wrist_right", "passthrough", None),
    ]
    joints = [
        r for r in routes if isinstance(r, dict) and str(r["channel"]).startswith("/viz/joint/")
    ]
    assert {str(r["channel"]) for r in joints} == {
        f"/viz/joint/{group}/{source}"
        for group in ("left_arm", "right_arm", "left_gripper", "right_gripper", "torso")
        for source in ("obs", "target")
    } | {"/viz/joint/chassis/obs"}
    assert all(r["max_rate_hz"] == 50 and r["transform"] == "passthrough" for r in joints)
    assert build_relay_config(profile, "127.0.0.1")["host"] == "127.0.0.1"
