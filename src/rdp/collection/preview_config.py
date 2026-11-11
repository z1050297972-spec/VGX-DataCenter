"""M5-09 转发配置生成（领域层）；复用共享通道和 Profile，不读取机器人或部署文件。"""

from ipaddress import ip_address

from pydantic import JsonValue

from rdp.collection.preview import PREVIEW_CHANNELS
from rdp.collection.profile_models import JointSource, RobotProfile


def build_relay_config(profile: RobotProfile, address: str) -> dict[str, JsonValue]:
    """把型号来源转换为第 03 张转发程序的 JSON 配置。

    Args:
        profile: 已校验的型号事实；相机使用已知的 ROS 压缩话题。
        address: 机器人登记地址，IP 字面量或非空主机名。

    Returns:
        schema_version 为 1 的配置；相机按文件顺序不限频，JointState 来源限 50 Hz。
        主机名绑定 0.0.0.0；不会把非 JointState 目标作为关节路由。

    Raises:
        无。

    Side Effects:
        无。

    Time Semantics:
        配置只反映传入快照；50 Hz 是接收时刻的转发上限，不改变消息时间戳。
    """
    try:
        ip_address(address)
        host = address
    except ValueError:
        host = "0.0.0.0"  # noqa: S104  # 理由：第 09 张要求主机名登记绑定全部接口。
    routes: list[JsonValue] = [
        {
            "channel": PREVIEW_CHANNELS["camera_topic"].format(name=camera.name),
            "source_topic": camera.topic,
            "source_type": camera.message_type,
            "transform": "h264_to_compressed_video" if camera.encoding == "h264" else "passthrough",
            "max_rate_hz": None,
        }
        for camera in profile.camera
    ]
    for group in profile.joint_group:
        for name, source in (("obs", group.observation), ("target", group.target)):
            if (
                isinstance(source, JointSource)
                and source.message_type == PREVIEW_CHANNELS["joint_schema"]
            ):
                routes.append(
                    {
                        "channel": PREVIEW_CHANNELS["joint_topic"].format(
                            name=group.name, source=name
                        ),
                        "source_topic": source.topic,
                        "source_type": source.message_type,
                        "transform": "passthrough",
                        # M5 D6：关节原样转发，接收频率最多 50 Hz。
                        "max_rate_hz": 50,
                    }
                )
    return {
        "schema_version": 1,
        "profile": profile.profile,
        "profile_version": profile.version,
        "host": host,
        "port": PREVIEW_CHANNELS["port"],
        "qos_reliability": profile.ros.qos_subscribe.lower(),
        "routes": routes,
    }
