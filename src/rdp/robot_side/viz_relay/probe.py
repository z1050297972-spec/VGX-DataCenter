"""M5-12 数据流探测：只统计原始回调，不依赖 ROS、SDK 或平台模块。

复用 Source 订阅契约，标准库 ExitStack 管理订阅；计数与有界轮询没有额外依赖。
所有回调和计数重置均在单线程执行器中串行发生，不缓存消息载荷。
"""

from collections.abc import Callable
from contextlib import ExitStack
from dataclasses import dataclass
from functools import partial
from typing import Protocol

from .config import Route
from .core import Source

# M5-12 约定：发现匹配预热 2 秒后，测量 5 秒原始数据流；单位均为单调秒。
WARMUP_S = 2.0
WINDOW_S = 5.0
# 每次最多等待 0.1 秒，以便 SIGINT/SIGTERM 尽快进入资源回收。
SPIN_TIMEOUT_S = 0.1


class ProbeSource(Source, Protocol):
    """在订阅契约上增加可由假时钟驱动的单线程轮询。"""

    def spin_once(self, timeout_s: float) -> None:
        """在调用线程最多执行一次源回调。

        Args:
            timeout_s: 最长等待秒数，范围 (0, 0.1]，按单调时间计。

        Returns:
            无。

        Raises:
            RuntimeError: 订阅源或执行器不可用。

        Side Effects:
            可同步投递一条订阅消息，不创建后台线程。

        Time Semantics:
            空闲时最多等待 timeout_s 秒；调用方在返回后检查停止请求。
        """
        ...


@dataclass(frozen=True)
class ProbeResult:
    """完整计数窗口的结果，不包含预热消息。

    Attributes:
        window_s: 实际计数时长，单调秒，保留 3 位小数。
        counts: 每条路由 channel 对应的非负整数，未收到消息时为 0。
    """

    window_s: float
    counts: dict[str, int]


def _spin_window(
    source: ProbeSource,
    duration_s: float,
    clock: Callable[[], float],
    stopped: Callable[[], bool],
) -> float:
    """按实际经过时间计算窗口，末次等待截断至截止时刻，避免空闲窗口多算。"""
    started_s = now_s = clock()
    while not stopped() and now_s - started_s < duration_s:
        source.spin_once(min(SPIN_TIMEOUT_S, duration_s - (now_s - started_s)))
        now_s = clock()
    return now_s - started_s


def run_probe(
    routes: tuple[Route, ...],
    source: ProbeSource,
    clock: Callable[[], float],
    stopped: Callable[[], bool],
) -> ProbeResult | None:
    """订阅全部路由，在预热后测量源消息数并释放订阅。

    Args:
        routes: 已校验的 1 至 64 条唯一通道路由，忽略 max_rate_hz 和 transform。
        source: 只读源，订阅、回调和销毁必须在当前线程串行执行。
        clock: 单调秒时钟，生产传 time.monotonic，测试可注入假时钟。
        stopped: 无参停止判定；返回 True 时结束轮询并丢弃不完整结果。

    Returns:
        预热 2 秒后计数 5 秒的完整结果；收到停止请求返回 None。

    Raises:
        RuntimeError: 订阅创建、轮询或回收失败，由入口转换为 ros_init_failed。

    Side Effects:
        创建并回收全部源订阅；不关闭调用方拥有的节点，不解码、不输出或写文件。

    Time Semantics:
        全部订阅建立后开始预热，预热结束清零，再从单调时钟测量计数窗口。
        统计执行器实际收到的消息，不读取消息时间戳；每次等待最多 0.1 秒。
    """
    counts = dict.fromkeys((route.channel for route in routes), 0)

    def receive(channel: str, _data: bytes) -> None:
        # 探测只数源回调；复用 Relay 会错误地套用查看者状态、限频和视频解析。
        counts[channel] += 1

    with ExitStack() as subscriptions:
        for route in routes:
            if stopped():
                return None
            handle = source.subscribe(route, partial(receive, route.channel))
            subscriptions.callback(source.unsubscribe, handle)
        _spin_window(source, WARMUP_S, clock, stopped)
        # 回调与重置串行，预热结束前收到的消息不会混入正式窗口。
        counts = dict.fromkeys(counts, 0)
        elapsed_s = _spin_window(source, WINDOW_S, clock, stopped)
        if stopped():
            return None
        return ProbeResult(round(elapsed_s, 3), counts)
