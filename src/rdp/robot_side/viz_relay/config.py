"""机器人侧配置边界（M5-03），只读 JSON，不创建节点或访问网络。

机器人仅批准标准库、ROS 和 SDK；标准库 json、ipaddress 足以校验这个固定格式，
不引入平台的 Pydantic，也不另造通用配置框架。
"""

import json
from dataclasses import dataclass
from ipaddress import ip_address
from pathlib import Path
from typing import cast

IMAGE_TYPE = "sensor_msgs/msg/CompressedImage"
JOINT_TYPE = "sensor_msgs/msg/JointState"


@dataclass(frozen=True)
class Route:
    """一条已校验的转发路由。

    Attributes:
        channel: /viz/camera/ 或 /viz/joint/ 开头的唯一通道。
        source_topic: 非空 ROS 源话题。
        source_type: IMAGE_TYPE 或 JOINT_TYPE。
        transform: passthrough 或 h264_to_compressed_video。
        max_rate_hz: 接收限频，单位 Hz，0 < 值 <= 1000；None 表示不限频。
    """

    channel: str
    source_topic: str
    source_type: str
    transform: str
    max_rate_hz: float | None


@dataclass(frozen=True)
class Config:
    """第 09 张生成、机器人进程读取的固定版本配置。

    Attributes:
        profile: 非空型号名称，只记录来源，不在机器人侧加载 Profile。
        profile_version: Profile 的正整数版本号。
        host: IPv4 或 IPv6 字面量。
        port: 监听端口，1024 至 65535。
        qos_reliability: best_effort 或 reliable。
        routes: 1 至 64 条路由，顺序与 JSON 相同。
    """

    profile: str
    profile_version: int
    host: str
    port: int
    qos_reliability: str
    routes: tuple[Route, ...]


def _object(value: object, keys: set[str]) -> dict[str, object]:
    """固定字段集合避免第 09 张配置拼写错误被静默忽略。"""
    if not isinstance(value, dict) or value.keys() != keys:
        raise ValueError("config_invalid 配置字段缺失或多余")
    return cast(dict[str, object], value)


def _text(value: object) -> str:
    """要求有意义的文本，不把其他 JSON 标量隐式转为字符串。"""
    if not isinstance(value, str) or not value.strip():
        raise ValueError("config_invalid 文本字段必须非空")
    return value


def _integer(value: object, minimum: int, maximum: int | None = None) -> int:
    """JSON 的布尔值不是版本或端口，必须先排除 bool。"""
    if type(value) is not int or value < minimum or (maximum is not None and value > maximum):
        raise ValueError("config_invalid 整数字段类型或范围不符")
    return value


def _route(value: object) -> Route:
    """把一条完整 JSON 路由校验为供转发器直接使用的值对象。"""
    data = _object(value, {"channel", "source_topic", "source_type", "transform", "max_rate_hz"})
    channel = _text(data["channel"])
    source_type = _text(data["source_type"])
    transform = _text(data["transform"])
    rate = data["max_rate_hz"]
    if not channel.startswith(("/viz/camera/", "/viz/joint/")):
        raise ValueError("config_invalid 通道前缀不符")
    if source_type not in (IMAGE_TYPE, JOINT_TYPE):
        raise ValueError("config_invalid 不支持的消息类型")
    if transform not in ("passthrough", "h264_to_compressed_video"):
        raise ValueError("config_invalid 不支持的转换")
    if transform == "h264_to_compressed_video" and source_type != IMAGE_TYPE:
        raise ValueError("config_invalid H.264 只能用于 CompressedImage")
    if rate is not None and (
        isinstance(rate, bool) or not isinstance(rate, (int, float)) or not 0 < rate <= 1000
    ):
        raise ValueError("config_invalid 限频必须为 null 或 (0, 1000] Hz")
    return Route(
        channel,
        _text(data["source_topic"]),
        source_type,
        transform,
        float(rate) if isinstance(rate, (int, float)) else None,
    )


def load_config(path: Path) -> Config:
    """读取并严格校验第 03/09 张约定的 JSON 配置。

    Args:
        path: 调用方指定的配置文件路径，只读，内容必须为 schema_version=1。

    Returns:
        保留路由顺序的不可变配置；不含未知字段。

    Raises:
        ValueError: 文件不可读、JSON 非法或字段违反约定；说明以 config_invalid 开头。

    Side Effects:
        只读 path，不写文件、不导入机器人依赖。

    Time Semantics:
        同步读取本地配置；不解释消息时刻，也不发起网络等待。
    """
    try:
        raw: object = json.loads(path.read_text(encoding="utf-8"))
        data = _object(
            raw,
            {
                "schema_version",
                "profile",
                "profile_version",
                "host",
                "port",
                "qos_reliability",
                "routes",
            },
        )
        _integer(data["schema_version"], 1, 1)
        host = _text(data["host"])
        ip_address(host)
        reliability = _text(data["qos_reliability"])
        if reliability not in ("best_effort", "reliable"):
            raise ValueError("不支持的 QoS 可靠性")
        values = data["routes"]
        if not isinstance(values, list):
            raise ValueError("路由必须为数组")
        route_values = cast(list[object], values)
        if not 1 <= len(route_values) <= 64:
            raise ValueError("路由数量必须为 1 至 64")
        routes = tuple(_route(value) for value in route_values)
        if len({route.channel for route in routes}) != len(routes):
            raise ValueError("通道重复")
        return Config(
            _text(data["profile"]),
            _integer(data["profile_version"], 1),
            host,
            _integer(data["port"], 1024, 65535),
            reliability,
            routes,
        )
    except (OSError, UnicodeError, ValueError) as error:
        raise ValueError("config_invalid 配置不可读或不符合约定") from error
