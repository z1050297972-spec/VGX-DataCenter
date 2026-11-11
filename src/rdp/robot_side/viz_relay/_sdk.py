"""Foxglove SDK 0.30.3 适配边界（M5-03），不调用 ROS，不创建发送线程。

SDK 自带每客户端有界队列，满时丢最旧数据，不需要再实现队列。
仅本模块允许缺失 SDK 的工作站类型检查豁免；核心逻辑仍严格检查。
"""

# 工作站不安装机器人专用 SDK，因此该边界的第三方导入无法静态解析。
# pyright: reportMissingImports=false
# SDK 未安装，导入符号的类型无法推导。
# pyright: reportUnknownVariableType=false
# SDK 未安装，成员类型在这一适配边界不可用。
# pyright: reportUnknownMemberType=false
# 传给 SDK 的 schema 与消息构造值无法在工作站核对第三方类型。
# pyright: reportUnknownArgumentType=false

from typing import Protocol

from ._schemas import ROS_SCHEMAS
from .config import Config, Route
from .video import NANOSECONDS_PER_SECOND, VideoFrame

# M5-03 要求每客户端缓冲有界；64 条消息约覆盖短暂抖动，避免默认 1024 条积压。
MESSAGE_BACKLOG_SIZE = 64


class _Client(Protocol):
    """SDK 监听回调所需的最小客户端身份。"""

    id: int


class _ChannelView(Protocol):
    """SDK 监听回调所需的通道名称。"""

    topic: str


class Server(Protocol):
    """运行入口只持有服务器的释放能力。"""

    def stop(self) -> None:
        """关闭 SDK 服务器及其后台任务。"""
        ...


class Listener:
    """只跟踪客户端身份，SDK 线程绝不直接调用 rclpy。"""

    def __init__(self, routes: tuple[Route, ...]) -> None:
        """只为已登记通道保存当前客户端集合，退订即删除身份。"""
        self.clients: dict[str, set[int]] = {route.channel: set() for route in routes}

    def on_subscribe(self, client: _Client, channel: _ChannelView) -> None:
        """SDK 回调只更新集合；Python 3.10 GIL 下单次 set 操作不会并发迭代。"""
        self.clients[channel.topic].add(client.id)

    def on_unsubscribe(self, client: _Client, channel: _ChannelView) -> None:
        """SDK 在退订或断线时移除当前客户端，不保存历史客户端身份。"""
        self.clients[channel.topic].discard(client.id)


class OutputChannel:
    """把标准库转发消息编码后交给 SDK 的非阻塞数据队列。"""

    def __init__(self, route: Route, listener: Listener) -> None:
        """启动时一次性登记通道，passthrough 使用完整 ros2msg 定义。"""
        import foxglove
        from foxglove.messages import CompressedVideo

        video = route.transform == "h264_to_compressed_video"
        self._clients = listener.clients[route.channel]
        self._channel = foxglove.Channel(
            route.channel,
            message_encoding="protobuf" if video else "cdr",
            schema=CompressedVideo.get_schema()
            if video
            else foxglove.Schema(
                name=route.source_type, encoding="ros2msg", data=ROS_SCHEMAS[route.source_type]
            ),
        )

    def has_sinks(self) -> bool:
        """使用 SDK 的真实消费者状态作为建立 ROS 订阅的依据。"""
        return bool(self._channel.has_sinks())

    def subscriber_count(self) -> int:
        """读取当前客户端集合的长度；不遍历，避免 SDK 回调修改集合的竞争。"""
        return len(self._clients)

    def send(self, message: bytes | VideoFrame) -> None:
        """保持 CDR 原字节；视频保留 ROS header 纳秒和 frame_id。"""
        from foxglove.messages import CompressedVideo, Timestamp

        if isinstance(message, VideoFrame):
            sec, nsec = divmod(message.timestamp_ns, NANOSECONDS_PER_SECOND)
            payload = CompressedVideo(
                timestamp=Timestamp(sec=sec, nsec=nsec),
                frame_id=message.frame_id,
                format=message.format,
                data=message.data,
            ).encode()
            self._channel.log(payload)
        else:
            self._channel.log(message)

    def close(self) -> None:
        """取消通道登记，释放 SDK 引用。"""
        self._channel.close()


def start_server(config: Config, listener: Listener) -> Server:
    """启动只读服务器；SDK 返回时端口已监听，失败异常留给命令行边界映射。"""
    import foxglove

    return foxglove.start_server(
        host=config.host,
        port=config.port,
        capabilities=[],
        server_listener=listener,
        message_backlog_size=MESSAGE_BACKLOG_SIZE,
    )
