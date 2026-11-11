"""M5-03 配置验收；只读临时 JSON，不装 ROS，不开启网络。"""

import json
from pathlib import Path

import pytest

from rdp.robot_side.viz_relay.config import load_config


def _config() -> dict[str, object]:
    """使用工单格式和回环地址构造可独立运行的配置。"""
    return {
        "schema_version": 1,
        "profile": "r1lite",
        "profile_version": 3,
        "host": "127.0.0.1",
        "port": 8765,
        "qos_reliability": "best_effort",
        "routes": [
            {
                "channel": "/viz/camera/head_left",
                "source_topic": "/hdas/camera_head/left_raw/image_raw_color/compressed",
                "source_type": "sensor_msgs/msg/CompressedImage",
                "transform": "h264_to_compressed_video",
                "max_rate_hz": None,
            },
            {
                "channel": "/viz/camera/wrist_left",
                "source_topic": "/hdas/camera_wrist_left/color/image_raw/compressed",
                "source_type": "sensor_msgs/msg/CompressedImage",
                "transform": "passthrough",
                "max_rate_hz": None,
            },
            {
                "channel": "/viz/joint/left_arm/obs",
                "source_topic": "/hdas/feedback_arm_left",
                "source_type": "sensor_msgs/msg/JointState",
                "transform": "passthrough",
                "max_rate_hz": 50,
            },
        ],
    }


def test_example_config(tmp_path: Path) -> None:
    """验收 1：工单格式可加载，类型与限频值保留。"""
    path = tmp_path / "config.json"
    path.write_text(json.dumps(_config()))
    config = load_config(path)
    assert (config.host, config.port, config.profile_version) == ("127.0.0.1", 8765, 3)
    assert config.routes[0].max_rate_hz is None
    assert config.routes[0].transform == "h264_to_compressed_video"
    assert len(config.routes) == 3
    assert config.routes[2].max_rate_hz == 50


@pytest.mark.parametrize("invalid", ["missing", "extra", "duplicate", "joint_h264", "version"])
def test_invalid_config(tmp_path: Path, invalid: str) -> None:
    """验收 1：缺键、多键、重复通道、关节 H.264 和错误版本均拒绝。"""
    config = _config()
    route = dict(
        channel="/viz/joint/arm/obs",
        source_topic="/arm",
        source_type="sensor_msgs/msg/JointState",
        transform="h264_to_compressed_video",
        max_rate_hz=50,
    )
    if invalid == "missing":
        del config["host"]
    elif invalid == "extra":
        config["extra"] = True
    elif invalid == "duplicate":
        config["routes"] = [route, route]
        route["transform"] = "passthrough"
    elif invalid == "joint_h264":
        config["routes"] = [route]
    else:
        config["schema_version"] = 2
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config))
    with pytest.raises(ValueError, match="config_invalid"):
        load_config(path)
