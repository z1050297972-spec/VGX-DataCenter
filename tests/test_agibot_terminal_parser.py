"""M4.6-02 事件解析验收；内联工单的真实终端样本，不运行工具或访问数据路径。"""

import pytest

from rdp.jobs.terminal import create_terminal_parser
from rdp.jobs.types import JobProgress, ProgressPart

# 工单里的两集 stderr 节选，保留中文、前导空格和伪终端的 CRLF。
_SAMPLE = (
    "任务 327：检查 2 集 ...\r\n"
    '{"event": "log", "time": 1794749000.1, "message": "任务 327：检查 2 集 ..."}\r\n'
    '{"event": "progress", "time": 1794749001.2, "stage": "probe", "done": 1, "total": 2, "task_id": "327"}\r\n'
    "  [probe] 1/2\r\n"
    '{"event": "progress", "time": 1794749001.3, "stage": "probe", "done": 2, "total": 2, "task_id": "327"}\r\n'
    '{"event": "progress", "time": 1794749020.0, "stage": "stage", "done": 1, "total": 2, "task_id": "327"}\r\n'
    '{"event": "progress", "time": 1794749025.0, "stage": "stage", "done": 2, "total": 2, "task_id": "327"}\r\n'
    '{"event": "progress", "time": 1794749026.0, "stage": "data", "done": 1, "total": 1, "task_id": "327"}\r\n'
    '{"event": "progress", "time": 1794749030.0, "stage": "videos", "done": 8, "total": 8, "task_id": "327"}\r\n'
    "任务 327 转换完成：/x/out（392.9 MB，info 57372a1bfc66）\r\n"
    '{"event": "result", "time": 1794749031.0, "command": "convert-episodes", "ok": true, "result": {"task_id": "327"}}\r\n'
).encode()


@pytest.mark.parametrize("chunk_size", [1, 7, len(_SAMPLE)])
def test_sample_chunk_boundaries(chunk_size: int) -> None:
    """验收1：任意字节分块后，最终进度、三个分项和普通日志与真实样本一致。"""
    parser = create_terminal_parser("agibot2lerobot-events", stage_count=5, first_stage=3)
    lines: list[str] = []
    for offset in range(0, len(_SAMPLE), chunk_size):
        lines.extend(parser.feed(_SAMPLE[offset : offset + chunk_size]).lines)
    final = parser.finish()
    lines.extend(final.lines)
    assert final.progress == JobProgress(
        stage_index=4,
        stage_count=5,
        stage_name="转换",
        done=2,
        total=2,
        unit="集",
        warning_count=0,
        failed_items=0,
        total_items=0,
        parts=(
            ProgressPart(name="逐集处理", done=2, total=2, unit="集"),
            ProgressPart(name="数据分片", done=1, total=1, unit="个"),
            ProgressPart(name="视频分片", done=8, total=8, unit="个"),
        ),
    )
    assert lines == [
        "任务 327：检查 2 集 ...",
        "  [probe] 1/2",
        "任务 327 转换完成：/x/out（392.9 MB，info 57372a1bfc66）",
    ]


@pytest.mark.parametrize("scan_stage", ["preview", "probe"])
def test_stage_only_moves_forward(scan_stage: str) -> None:
    """验收1：预览或扫描完成仍在 first_stage，逐集处理才推进阶段，迟到扫描不回退。"""
    parser = create_terminal_parser("agibot2lerobot-events", stage_count=5, first_stage=3)
    scan = f'{{"event":"progress","stage":"{scan_stage}","done":2,"total":2}}\r\n'.encode()
    progress = parser.feed(scan).progress
    assert progress is not None
    assert (
        progress.stage_index,
        progress.stage_name,
        progress.done,
        progress.total,
        progress.unit,
    ) == (3, "扫描", 2, 2, "集")
    converting = parser.feed(b'{"event":"progress","stage":"stage","done":1,"total":2}\n').progress
    assert converting is not None
    assert converting.stage_index == 4
    assert [(part.name, part.done, part.total, part.unit) for part in converting.parts] == [
        ("逐集处理", 1, 2, "集"),
        ("数据分片", 0, None, "个"),
        ("视频分片", 0, None, "个"),
    ]
    assert parser.feed(scan).progress is None
    assert parser.finish().progress == converting


@pytest.mark.parametrize(
    "event",
    [
        b'{"event":"progress","stage":"probe","done":3,"total":2}',
        b'{"event":"progress","stage":"probe","done":1}',
        b'{"event":"progress","stage":"probe","done":',
        b'{"event":"progress","stage":"probe","done":true,"total":2}',
        b'{"event":"progress","stage":"probe","done":-1,"total":2}',
        b'{"event":"progress","stage":"other","done":1,"total":2}',
    ],
)
def test_invalid_events_are_discarded(event: bytes) -> None:
    """验收2：非法事件既不产生进度，也不泄漏到普通日志；普通日志只去尾部空白。"""
    parser = create_terminal_parser("agibot2lerobot-events", stage_count=2, first_stage=1)
    update = parser.feed(event + b"\r\n  ordinary log \t\r\n")
    assert update.progress is None
    assert update.lines == ("  ordinary log",)
    assert parser.finish().progress is None


def test_long_line_is_discarded_until_newline() -> None:
    """验收2：64 KiB 内保留文本，越界的长行持续丢弃，换行后的日志及进度恢复。"""
    parser = create_terminal_parser("agibot2lerobot-events", stage_count=2, first_stage=1)
    assert parser.feed(b"x" * (64 * 1024) + b"\n").lines == ("x" * (64 * 1024),)
    for _ in range(100):
        update = parser.feed(b"x" * (64 * 1024))
        assert update.lines == () and update.progress is None
    update = parser.feed(
        'ignored\r\nnext\n{"event":"progress","stage":"probe","done":2,"total":2}\n尾部'.encode()
    )
    assert update.lines == ("next",)
    assert update.progress is not None and update.progress.done == 2
    assert parser.finish().lines == ("尾部",)
    assert parser.finish().lines == ()
