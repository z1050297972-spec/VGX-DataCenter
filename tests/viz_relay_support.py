"""M5-03 的 ROS/通道系统边界替身；消息由测试显式驱动，没有端口和线程。"""

import struct
from collections.abc import Callable

from rdp.robot_side.viz_relay.config import IMAGE_TYPE, Route
from rdp.robot_side.viz_relay.video import VideoFrame

# 工单验收 2 的 SPS/PPS/IDR，各起始码和负载保留有区别的字节。
H264 = bytes.fromhex("0000000167640c33abcd00000168ee3c8000000165888421")


def cdr(timestamp_ns: int, payload: bytes = H264) -> bytes:
    """按 ROS CDR 布局构造含非空 frame_id 的消息，覆盖四字节对齐。"""
    sec, nsec = divmod(timestamp_ns, 1_000_000_000)
    body = bytearray(struct.pack("<iI", sec, nsec))
    for value in (b"head\0", b"h264\0", payload):
        body.extend(b"\0" * (-len(body) % 4))
        body.extend(struct.pack("<I", len(value)))
        body.extend(value)
    return b"\0\1\0\0" + body


def route(*, video: bool = True, max_rate_hz: float | None = None) -> Route:
    """提供不依赖平台 RobotProfile 的测试路由。"""
    return Route(
        "/viz/camera/head_left",
        "/camera",
        IMAGE_TYPE,
        "h264_to_compressed_video" if video else "passthrough",
        max_rate_hz,
    )


class FakeChannel:
    """代替网络端点，保留消费者实际收到的载荷。"""

    def __init__(self) -> None:
        """初始没有查看者。"""
        self.viewers = 0
        self.messages: list[bytes | VideoFrame] = []

    def has_sinks(self) -> bool:
        """模拟 SDK 对有效查看者的判断。"""
        return self.viewers > 0

    def subscriber_count(self) -> int:
        """返回测试驱动的客户端订阅数量。"""
        return self.viewers

    def send(self, message: bytes | VideoFrame) -> None:
        """记录通道输出，不进行编码或网络传输。"""
        self.messages.append(message)


class FakeSource:
    """代替 ROS 订阅源；只允许向仍存活的订阅推送消息。"""

    def __init__(self) -> None:
        """保留活跃订阅以模拟 ROS 资源生命周期。"""
        self.active: dict[object, tuple[Route, Callable[[bytes], None]]] = {}

    def subscribe(self, route: Route, callback: Callable[[bytes], None]) -> object:
        """建立可由测试驱动的原始字节订阅。"""
        handle = object()
        self.active[handle] = (route, callback)
        return handle

    def unsubscribe(self, subscription: object) -> None:
        """销毁订阅后，源不再向它投递消息。"""
        del self.active[subscription]

    def emit(self, channel: str, data: bytes) -> None:
        """按业务通道向活跃订阅投递，不访问转发器内部状态。"""
        for route, callback in tuple(self.active.values()):
            if route.channel == channel:
                callback(data)
