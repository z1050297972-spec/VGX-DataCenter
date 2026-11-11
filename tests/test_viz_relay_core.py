"""M5-03 转发验收，只在可替换订阅源与通道这条公开边界观察行为。"""

from dataclasses import replace

from viz_relay_support import H264, FakeChannel, FakeSource, cdr, route

from rdp.robot_side.viz_relay.core import Relay
from rdp.robot_side.viz_relay.video import VideoFrame


def test_video_rewrap_preserves_header_and_payload() -> None:
    """验收 2：换成视频外壳，保留 header、PPS/IDR，只清 SPS 约束位。"""
    source, channel = FakeSource(), FakeChannel()
    item = route()
    relay = Relay((item,), source, {item.channel: channel}, lambda: 0)
    try:
        channel.viewers = 1
        relay.reconcile()
        source.emit(item.channel, cdr(12_345_678_901))
        assert channel.messages == [
            VideoFrame(
                12_345_678_901,
                "head",
                "h264",
                bytes.fromhex("0000000167640833abcd00000168ee3c8000000165888421"),
            )
        ]
    finally:
        relay.close()


def test_duplicate_and_backwards_timestamps_are_dropped() -> None:
    """验收 3：重复和回退各计一次；重新订阅后旧时间基准被清除。"""
    source, channel = FakeSource(), FakeChannel()
    item = route()
    relay = Relay((item,), source, {item.channel: channel}, lambda: 0)
    try:
        channel.viewers = 1
        relay.reconcile()
        for stamp in (20, 20, 19, 21):
            source.emit(item.channel, cdr(stamp))
        counts = relay.statistics()[item.channel]
        assert (counts.received, counts.forwarded, counts.dropped_timestamp) == (4, 2, 2)
        channel.viewers = 0
        relay.reconcile()
        channel.viewers = 1
        relay.reconcile()
        source.emit(item.channel, cdr(1))
        assert len(channel.messages) == 3
    finally:
        relay.close()


def test_200_hz_input_is_limited_to_50_hz() -> None:
    """验收 4：每 5 ms 输入在 50 Hz 配置下每 20 ms 输出，CDR 原样保留。"""
    source, channel = FakeSource(), FakeChannel()
    item = route(video=False, max_rate_hz=50)
    now_ns = 0
    relay = Relay((item,), source, {item.channel: channel}, lambda: now_ns)
    try:
        channel.viewers = 1
        relay.reconcile()
        for index in range(200):
            now_ns = index * 5_000_000
            source.emit(item.channel, bytes([index]))
        assert channel.messages == [bytes([index]) for index in range(0, 200, 4)]
        counts = relay.statistics()[item.channel]
        assert (counts.received, counts.forwarded, counts.dropped_rate) == (200, 50, 150)
    finally:
        relay.close()


def test_subscriptions_follow_viewers_and_are_released() -> None:
    """验收 5：按通道有人看才订阅，离开即销毁，关闭时回收剩余订阅。"""
    source = FakeSource()
    first, second = route(), replace(route(), channel="/viz/camera/head_right")
    channels = {first.channel: FakeChannel(), second.channel: FakeChannel()}
    relay = Relay((first, second), source, channels, lambda: 0)
    try:
        relay.reconcile()
        assert not source.active
        channels[second.channel].viewers = 1
        relay.reconcile()
        relay.reconcile()
        assert [item.channel for item, _ in source.active.values()] == [second.channel]
        channels[second.channel].viewers = 0
        relay.reconcile()
        assert not source.active
        channels[first.channel].viewers = 1
        relay.reconcile()
        source.emit(first.channel, cdr(1, H264))
        assert len(channels[first.channel].messages) == 1
    finally:
        relay.close()
    assert not source.active
