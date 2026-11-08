"""M4-02 解析器验收；只回放执行线录制的字节，不运行真实工具或访问样本中的路径。"""

import base64
import json
from pathlib import Path

from rdp.jobs.terminal import create_terminal_parser
from rdp.jobs.types import JobProgress


def _chunks(name: str) -> list[bytes]:
    """原样保留样本的 read 边界，来源见只读样本目录的 meta.json。"""
    path = Path(__file__).parent / "fixtures" / "mcap2lerobot" / name
    return [base64.b64decode(json.loads(line)["b64"]) for line in path.read_text().splitlines()]


def test_replay_conversion() -> None:
    """验收1：真实转换最终五项各1647帧，同阶段计数不减，完成文字只返回一次。"""
    parser = create_terminal_parser("mcap2lerobot-pty", stage_count=3, first_stage=1)
    progresses: list[JobProgress] = []
    lines: list[str] = []
    for chunk in _chunks("convert-v3.ptylog.jsonl"):
        update = parser.feed(chunk)
        if update.progress is not None:
            progresses.append(update.progress)
        lines.extend(update.lines)
    final = parser.finish()
    lines.extend(final.lines)
    assert final.progress is not None
    assert [(part.name, part.done, part.total, part.unit) for part in final.progress.parts] == [
        ("head_left", 1647, 1647, "帧"),
        ("wrist_left", 1647, 1647, "帧"),
        ("wrist_right", 1647, 1647, "帧"),
        ("state", 1647, 1647, "帧"),
        ("action", 1647, 1647, "帧"),
    ]
    assert (
        final.progress.stage_index,
        final.progress.stage_name,
        final.progress.done,
        final.progress.total,
        final.progress.stage_count,
    ) == (2, "转换", 8235, 8235, 3)
    # 消息和帧不能跨单位比较；原 JobProgress 契约允许进入下一阶段归零。
    assert all(
        (a.stage_index, a.done) <= (b.stage_index, b.done)
        for a, b in zip(progresses, progresses[1:], strict=False)
    )
    assert any(
        p.stage_name == "扫描" and p.done == 93606 and p.total == 281370 and p.unit == "条消息"
        for p in progresses
    )
    assert len([line for line in lines if line.startswith("完成：5 个 episode，1647 帧")]) == 1


def test_every_byte_split() -> None:
    """验收2：真实样本最后一次重画在每个字节处分块，含汉字/CSI中间，结果均相同。"""
    data = _chunks("convert-v3.ptylog.jsonl")[-1]
    reference = create_terminal_parser("mcap2lerobot-pty", stage_count=2, first_stage=1)
    whole = reference.feed(data)
    end = reference.finish()
    for split in range(len(data) + 1):
        parser = create_terminal_parser("mcap2lerobot-pty", stage_count=2, first_stage=1)
        first, second = parser.feed(data[:split]), parser.feed(data[split:])
        final = parser.finish()
        assert final.progress == end.progress
        assert first.lines + second.lines + final.lines == whole.lines + end.lines


def test_replay_conversion_after_prechecks() -> None:
    """评审回归：五阶段作业从第3阶段扫描推进到第4阶段转换，最终五项各1647帧。"""
    parser = create_terminal_parser("mcap2lerobot-pty", stage_count=5, first_stage=3)
    progresses: list[JobProgress] = []
    for chunk in _chunks("convert-v3.ptylog.jsonl"):
        update = parser.feed(chunk)
        if update.progress is not None:
            progresses.append(update.progress)
    final = parser.finish().progress
    assert final is not None
    progresses.append(final)
    stages = [(progress.stage_index, progress.stage_name) for progress in progresses]
    assert list(dict.fromkeys(stages)) == [(3, "扫描"), (4, "转换")]
    assert all(progress.stage_count == 5 for progress in progresses)
    assert all(
        a.stage_index <= b.stage_index for a, b in zip(progresses, progresses[1:], strict=False)
    )
    assert [(part.done, part.total) for part in final.parts] == [(1647, 1647)] * 5


def test_replay_truncated_input_error() -> None:
    """验收3：真实失败输出保留转换错误、Caused by链及根因，不把进度条当日志。"""
    parser = create_terminal_parser("mcap2lerobot-pty", stage_count=2, first_stage=1)
    lines = [
        line
        for chunk in _chunks("error-truncated-input.ptylog.jsonl")
        for line in parser.feed(chunk).lines
    ]
    lines.extend(parser.finish().lines)
    assert any(line.startswith("Error: 转换 ") and line.endswith(" 失败") for line in lines)
    assert "Caused by:" in lines and "Bad magic number" in lines
    assert not any("0/0 帧" in line for line in lines)
