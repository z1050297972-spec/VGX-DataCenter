"""逐条移植工具 sync.rs 的八个测试，期望值保留 Rust 的手写常量。"""

import pytest
from cleaning_support import noop

from rdp.jobs.cleaning._sync import TopicInput, nearest, plan


@pytest.mark.parametrize(
    ("reference", "stamps", "expected"),
    [
        ([0, 10, 20, 30], [1, 12, 19, 45], [0, 1, 2, 2]),
        ([30], [19, 40], [1]),
        ([5], [0, 10], [0]),
        ([-100, 100], [0, 10], [0, 1]),
        ([1, 2], [], []),
    ],
    ids=[
        "picks_closest",
        "picks_closest_later",
        "tie_picks_earlier",
        "reference_outside_range",
        "empty_stamps",
    ],
)
def test_nearest(reference: list[int], stamps: list[int], expected: list[int]) -> None:
    """最近邻、同距取早、范围外及空话题语义与 Rust 测试完全一致。"""
    assert list(nearest(reference, stamps, noop)) == expected


@pytest.mark.parametrize(
    ("reference", "stamps", "options", "expected"),
    [
        (
            [0, 10, 20, 30, 40, 50, 60],
            [0, 10, 20, 45, 50, 60],
            (3, 1),
            ([(0, 3), (5, 7)], list[tuple[int, int]](), 2, 0),
        ),
        (
            [0, 10, 20, 50, 60],
            [0, 10, 20, 50, 60],
            (1, 1),
            ([(0, 3), (3, 5)], list[tuple[int, int]](), 0, 1),
        ),
        ([0, 10, 20, 50, 60], [0, 10, 20, 50, 60], (1, 3), ([(0, 3)], [(3, 5)], 0, 1)),
        ([0, 10, 20, 30, 40], [10, 20, 30], (2, 1), ([(1, 4)], list[tuple[int, int]](), 2, 0)),
    ],
    ids=["splits_on_bad_frames", "splits_on_reference_gap", "drops_short_segments", "trims_edges"],
)
def test_plan(
    reference: list[int],
    stamps: list[int],
    options: tuple[int, int],
    expected: tuple[list[tuple[int, int]], list[tuple[int, int]], int, int],
) -> None:
    """坏帧切段、基准间隔切段、短段丢弃和边缘裁切与 Rust 手算一致。"""
    tolerance, minimum = options
    segments, short, bad, gaps = expected
    result = plan(reference, [TopicInput(stamps, tolerance)], (15, minimum), noop)
    assert [(r.start, r.stop) for r in result.segments] == segments
    assert [(r.start, r.stop) for r in result.short_segments] == short
    assert result.topics[0].bad_frames == bad
    assert sum(result.bad) == bad
    assert result.gaps == gaps
