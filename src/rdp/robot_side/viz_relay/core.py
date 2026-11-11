"""机器人侧转发逻辑（M5-03），只依赖标准库和包内值对象。

Source 与 Channel 是录制回放可替换的两个系统边界。单线程执行器拥有所有路由状态；
SDK 仅在自身有界队列里发送，不在 ROS 回调中等待网络，也不增加发送线程。
"""

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from functools import partial
from typing import Protocol

from .config import Route
from .video import (
    NANOSECONDS_PER_SECOND,
    VideoFrame,
    codec_lichtblick,
    codec_standard,
    parse_compressed_image,
    patch_sps,
)

logger = logging.getLogger(__name__)


class Source(Protocol):
    """只读订阅源，由执行器线程创建、销毁和投递回调。"""

    def subscribe(self, route: Route, callback: Callable[[bytes], None]) -> object:
        """为一路已校验路由建立原始字节订阅。

        Args:
            route: 订阅源话题与类型；不能据此发布 ROS 消息。
            callback: 按源顺序接收完整 CDR 字节，同一执行器线程调用。

        Returns:
            不透明订阅句柄，交给 unsubscribe 回收。

        Raises:
            RuntimeError: 订阅源无法创建订阅。

        Side Effects:
            创建一个订阅资源；失败不得留下半建资源。

        Time Semantics:
            必须在源的执行器线程调用；不能等待第一条消息。
        """
        ...

    def unsubscribe(self, subscription: object) -> None:
        """释放一个先前创建的订阅。

        Args:
            subscription: 此源 subscribe 返回的仍存活句柄。

        Returns:
            无。

        Raises:
            RuntimeError: 底层资源无法销毁。

        Side Effects:
            停止投递并释放句柄对应资源。

        Time Semantics:
            在同一执行器线程调用，返回后不得继续投递此订阅。
        """
        ...


class Channel(Protocol):
    """非阻塞输出端点；实现者负责有界缓冲，满时丢旧数据。"""

    def has_sinks(self) -> bool:
        """判断该通道当前是否有消费者。

        Args:
            无。

        Returns:
            有至少一个消费者为 True。

        Raises:
            无。

        Side Effects:
            只读消费者状态。

        Time Semantics:
            瞬时快照，不等待客户端连接。
        """
        ...

    def subscriber_count(self) -> int:
        """读取该通道的客户端订阅数量。

        Args:
            无。

        Returns:
            当前订阅客户端数，非负整数。

        Raises:
            无。

        Side Effects:
            不修改订阅。

        Time Semantics:
            统计时刻的快照，允许随后发生订阅变化。
        """
        ...

    def send(self, message: bytes | VideoFrame) -> None:
        """把原始 CDR 或换壳后的视频帧交给有界发送队列。

        Args:
            message: bytes 为原样 CDR；VideoFrame 为已修正 H.264 的帧。

        Returns:
            无；返回只表示已交给发送端，不表示客户端已收到。

        Raises:
            RuntimeError: 输出端点失效。

        Side Effects:
            写有界队列，网络慢时允许丢弃最旧消息。

        Time Semantics:
            不等待网络；保留 VideoFrame 的 header 时间戳。
        """
        ...


@dataclass
class Counts:
    """一条通道自进程启动起的累计统计。

    Attributes:
        received: 收到的消息数，非负整数。
        forwarded: 交给输出端点的消息数，不代表网络确认数。
        dropped_rate: 因接收间隔不足丢弃的消息数。
        dropped_timestamp: 因视频 header 重复或回退丢弃的消息数。
        dropped_format: 非 h264 或不可解析 CDR 的消息数。
        subscribers: 统计快照时的订阅客户端数。
    """

    received: int = 0
    forwarded: int = 0
    dropped_rate: int = 0
    dropped_timestamp: int = 0
    dropped_format: int = 0
    subscribers: int = 0


@dataclass
class _State:
    """同一执行器线程独占的路由状态，不在 SDK 回调里读写。

    Attributes:
        route: 固定路由。
        channel: 非阻塞输出边界。
        subscription: 当前源句柄，None 表示无订阅。
        last_receive_ns: 最近一次通过限频的接收单调纳秒；None 表示尚无。
        last_stamp_ns: 最近转发视频的源纳秒；None 表示尚无。
        codec_logged: 本次订阅是否已报告首个 SPS。
        counts: 跨重新订阅累计的统计，不重置。
    """

    route: Route
    channel: Channel
    subscription: object | None = None
    last_receive_ns: int | None = None
    last_stamp_ns: int | None = None
    codec_logged: bool = False
    counts: Counts = field(default_factory=Counts)


class Relay:
    """有人看才订阅的只读转发器，生命周期由调用方执行器控制。"""

    def __init__(
        self,
        routes: tuple[Route, ...],
        source: Source,
        channels: Mapping[str, Channel],
        clock_ns: Callable[[], int],
    ) -> None:
        """把已校验路由与可替换的订阅源、输出通道连接起来。

        Args:
            routes: 已校验的 1 至 64 条唯一通道路由。
            source: 只读订阅源，回调与对账在同一个线程执行。
            channels: 每条路由的通道名到非阻塞输出端点的完整映射。
            clock_ns: 接收时刻的单调纳秒时钟，生产传 time.monotonic_ns。

        Returns:
            无。

        Raises:
            KeyError: channels 缺少路由对应端点，属于调用方接线错误。

        Side Effects:
            仅初始化内存；不立即创建源订阅。

        Time Semantics:
            构造时不取时间；限频在每次回调刚进入时取 clock_ns。
        """
        self._source = source
        self._clock_ns = clock_ns
        self._states = tuple(_State(route, channels[route.channel]) for route in routes)

    def reconcile(self) -> None:
        """按当前消费者状态创建或销毁对应源订阅。

        Args:
            无。

        Returns:
            无；无消费者的路由不会保留源订阅。

        Raises:
            RuntimeError: 源无法创建或销毁订阅，由运行入口停止进程并清理。

        Side Effects:
            修改源订阅，首次订阅和重新订阅均清空限频及视频时间基准。

        Time Semantics:
            调用方在执行器线程每 0.2 秒调用，与源回调串行。
        """
        for state in self._states:
            if state.channel.has_sinks():
                if state.subscription is None:
                    state.last_receive_ns = state.last_stamp_ns = None
                    state.codec_logged = False
                    state.subscription = self._source.subscribe(
                        state.route, partial(self._receive, state)
                    )
                    logger.info("开始订阅 channel=%s", state.route.channel)
            elif state.subscription is not None:
                self._source.unsubscribe(state.subscription)
                state.subscription = None
                logger.info("停止订阅 channel=%s", state.route.channel)

    def _receive(self, state: _State, data: bytes) -> None:
        """先判断消费者和接收限频，再解析视频，避免无用的大载荷转换。"""
        now_ns = self._clock_ns()
        state.counts.received += 1
        if not state.channel.has_sinks():
            return
        rate = state.route.max_rate_hz
        if (
            rate is not None
            and state.last_receive_ns is not None
            and now_ns - state.last_receive_ns < NANOSECONDS_PER_SECOND / rate
        ):
            state.counts.dropped_rate += 1
            return
        state.last_receive_ns = now_ns
        message: bytes | VideoFrame = data
        if state.route.transform == "h264_to_compressed_video":
            frame = self._video(state, data)
            if frame is None:
                return
            message = frame
        state.channel.send(message)
        state.counts.forwarded += 1

    def _video(self, state: _State, data: bytes) -> VideoFrame | None:
        """只保留可解析、格式匹配且相对上次输出严格递增的视频帧。"""
        try:
            frame = parse_compressed_image(data)
        except ValueError:
            state.counts.dropped_format += 1
            return None
        if frame.format != "h264":
            state.counts.dropped_format += 1
            return None
        if state.last_stamp_ns is not None and frame.timestamp_ns <= state.last_stamp_ns:
            state.counts.dropped_timestamp += 1
            return None
        payload, sps = patch_sps(frame.data)
        if sps is not None and not state.codec_logged:
            standard, lichtblick = codec_standard(sps), codec_lichtblick(sps)
            logger.info(
                "编解码器自检 channel=%s standard=%s lichtblick=%s",
                state.route.channel,
                standard,
                lichtblick,
            )
            if standard != lichtblick:
                logger.warning("编解码器不一致，画面可能不可用 channel=%s", state.route.channel)
            state.codec_logged = True
        state.last_stamp_ns = frame.timestamp_ns
        return replace(frame, data=payload)

    def statistics(self) -> dict[str, Counts]:
        """返回每条通道的累计计数和当前订阅者数量快照。

        Args:
            无。

        Returns:
            按配置顺序排列的独立计数副本；调用方修改不会影响内部统计。

        Raises:
            无。

        Side Effects:
            只读通道的当前订阅数量。

        Time Semantics:
            与回调串行调用；计数从进程启动累计，重新订阅不清零。
        """
        return {
            state.route.channel: replace(state.counts, subscribers=state.channel.subscriber_count())
            for state in self._states
        }

    def close(self) -> None:
        """销毁全部仍存活的源订阅。

        Args:
            无。

        Returns:
            无；可在没有活跃订阅时调用。

        Raises:
            RuntimeError: 订阅源拒绝释放资源；外层仍须销毁整个节点。

        Side Effects:
            释放 ROS 或回放源订阅，不关闭调用方拥有的输出端点。

        Time Semantics:
            停止执行器轮询后，在同一线程调用，不能与回调并发。
        """
        for state in self._states:
            if state.subscription is not None:
                self._source.unsubscribe(state.subscription)
                state.subscription = None
