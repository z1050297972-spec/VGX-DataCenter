"""逐条重写 sync.rs 的最近邻及切段规则；标准库没有这一组工具业务语义。

输入是已稳定排序、过滤零 stamp 的纳秒数组；匹配下标指向排序后的数组。
同 stamp 的选择也沿用 Rust 双指针：不晚于基准时前进到最后一个重复值。
"""

from array import array
from collections.abc import Callable, Sequence
from dataclasses import dataclass

# 纯计算每 4096 帧检查取消，避免大量帧对齐期间失去响应。
CHECKPOINT_FRAMES = 4096


@dataclass(frozen=True)
class TopicInput:
    """一个话题的对齐输入。

    Attributes:
        stamps: 升序时间戳，单位纳秒，可为空。
        max_dt: 最大绝对时间差，纳秒，非负。
    """

    stamps: Sequence[int]
    max_dt: int


@dataclass(frozen=True)
class TopicMatch:
    """每帧匹配及时间差，用紧凑数组保存。

    Attributes:
        matched: 排序后消息下标，非负；话题空时为空。
        abs_dt: 与基准的绝对差，纳秒；话题空时为空。
        bad_frames: 超容差的基准帧数，非负。
    """

    matched: array[int]
    abs_dt: array[int]
    bad_frames: int


@dataclass(frozen=True)
class SyncPlan:
    """与 Rust 对应的完整时间计划，不含数值检查。

    Attributes:
        topics: 与输入话题顺序一致的匹配结果。
        bad: 每基准帧的坏帧标记，0 或 1。
        gaps: 当前帧有效且基准间隔超限的断点数，非负。
        segments: 保留段，基准帧下标左闭右开。
        short_segments: 因过短丢弃的段，同样左闭右开。
    """

    topics: tuple[TopicMatch, ...]
    bad: bytearray
    gaps: int
    segments: tuple[range, ...]
    short_segments: tuple[range, ...]


def nearest(
    reference: Sequence[int], stamps: Sequence[int], checkpoint: Callable[[], None]
) -> array[int]:
    """双指针最近邻；严格小于才选后一个，因此距离相同时取较早 stamp。"""
    result = array("Q")
    if not stamps:
        return result
    j = 0
    for i, stamp in enumerate(reference):
        if i % CHECKPOINT_FRAMES == 0:
            checkpoint()
        while j + 1 < len(stamps) and stamps[j + 1] <= stamp:
            j += 1
        chosen = j
        if j + 1 < len(stamps) and stamps[j + 1] - stamp < abs(stamp - stamps[j]):
            chosen = j + 1
        result.append(chosen)
    return result


def plan(
    reference: Sequence[int],
    topics: Sequence[TopicInput],
    options: tuple[int, int],
    checkpoint: Callable[[], None],
) -> SyncPlan:
    """参数 options 为最大间隔纳秒和最小段帧数；坏帧处和有效帧的间隔处切段。"""
    bad = bytearray(len(reference))
    matches = tuple(_match(reference, topic, bad, checkpoint) for topic in topics)
    max_gap_ns, min_frames = options
    runs, gaps = _runs(reference, bad, max_gap_ns, checkpoint)
    return SyncPlan(
        matches,
        bad,
        gaps,
        tuple(run for run in runs if len(run) >= min_frames),
        tuple(run for run in runs if len(run) < min_frames),
    )


def _match(
    reference: Sequence[int], topic: TopicInput, bad: bytearray, checkpoint: Callable[[], None]
) -> TopicMatch:
    """超容差才算坏帧；空话题把全部基准帧标坏。"""
    if not topic.stamps:
        bad[:] = b"\x01" * len(reference)
        return TopicMatch(array("Q"), array("q"), len(reference))
    matched = nearest(reference, topic.stamps, checkpoint)
    deltas = array("q")
    count = 0
    for i, position in enumerate(matched):
        if i % CHECKPOINT_FRAMES == 0:
            checkpoint()
        delta = abs(topic.stamps[position] - reference[i])
        deltas.append(delta)
        if delta > topic.max_dt:
            bad[i] = 1
            count += 1
    return TopicMatch(matched, deltas, count)


def _runs(
    reference: Sequence[int], bad: bytearray, max_gap_ns: int, checkpoint: Callable[[], None]
) -> tuple[list[range], int]:
    """先判坏帧再判间隔；顺序和 Rust 相同，坏帧本身不增加 gaps。"""
    runs: list[range] = []
    start: int | None = None
    gaps = 0
    for i, stamp in enumerate(reference):
        if i % CHECKPOINT_FRAMES == 0:
            checkpoint()
        if bad[i]:
            if start is not None:
                runs.append(range(start, i))
                start = None
            continue
        if i > 0 and stamp - reference[i - 1] > max_gap_ns:
            gaps += 1
            if start is not None:
                runs.append(range(start, i))
                start = None
        if start is None:
            start = i
    if start is not None:
        runs.append(range(start, len(reference)))
    return runs, gaps
