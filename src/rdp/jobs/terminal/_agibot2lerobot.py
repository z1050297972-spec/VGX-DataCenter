"""AgiBot JSON 行事件适配（领域层，M4.6-02），不执行工具或判断成败。

标准库 json 负责语法解析；自定义有界分行和阶段映射，因为工具的混合文本事件流
不符合整份 JSON 文档接口，也不能复用 mcap2lerobot 的终端重画协议。
"""

import json
from typing import cast

from rdp.jobs.terminal.types import TerminalUpdate
from rdp.jobs.types import JobProgress, ProgressPart

# 工单限定单行最多 64 KiB；按原始字节计数，中文和分块方式不改变上限。
_MAX_LINE_BYTES = 64 * 1024
# 工具三个转换子阶段的展示顺序固定；未上报的总数保持未知，不能伪造完成比例。
_PARTS = (("stage", "逐集处理", "集"), ("data", "数据分片", "个"), ("videos", "视频分片", "个"))


class Agibot2LerobotParser:
    """按到达顺序消费混合日志，扫描和转换阶段只进不退。"""

    def __init__(self, stage_count: int, first_stage: int) -> None:
        """保存已由工厂校验的阶段安排，每次工具执行独占一个实例。"""
        self.stage_count = stage_count
        self.first_stage = first_stage
        self.pending = bytearray()
        self.discarding = False
        self.converting = False
        self.parts = {
            stage: ProgressPart(name=name, done=0, total=None, unit=unit)
            for stage, name, unit in _PARTS
        }
        self.latest: JobProgress | None = None

    def feed(self, chunk: bytes) -> TerminalUpdate:
        """只在换行处分割，超长行不再缓冲，直到下一个换行才恢复。"""
        lines: list[str] = []
        recognized = False
        start = 0
        while start < len(chunk):
            newline = chunk.find(b"\n", start)
            end = len(chunk) if newline < 0 else newline
            if not self.discarding:
                if len(self.pending) + end - start > _MAX_LINE_BYTES:
                    self.pending.clear()
                    self.discarding = True
                else:
                    self.pending.extend(chunk[start:end])
            if newline < 0:
                break
            if not self.discarding:
                recognized = self._record(lines) or recognized
            self.discarding = False
            start = end + 1
        return TerminalUpdate(self.latest if recognized else None, tuple(lines))

    def finish(self) -> TerminalUpdate:
        """关闭时排出未换行文本；不完整事件和已超长的尾部仍然丢弃。"""
        lines: list[str] = []
        if self.pending and not self.discarding:
            self._record(lines)
        self.pending.clear()
        self.discarding = False
        return TerminalUpdate(self.latest, tuple(lines))

    def _record(self, lines: list[str]) -> bool:
        """事件前缀保留给协议，即使 JSON 损坏也不当日志重复显示。"""
        raw = bytes(self.pending)
        self.pending.clear()
        if not raw.startswith(b'{"event"'):
            lines.append(raw.decode("utf-8", errors="replace").rstrip())
            return False
        try:
            value: object = json.loads(raw)
        except ValueError:
            return False
        if not isinstance(value, dict):
            return False
        event = cast(dict[str, object], value)
        stage, done, total = event.get("stage"), event.get("done"), event.get("total")
        if (
            event.get("event") != "progress"
            or not isinstance(stage, str)
            or stage not in ("preview", "probe", *self.parts)
            or type(done) is not int
            or type(total) is not int
            or not 0 <= done <= total
        ):
            return False
        return self._progress(stage, done, total)

    def _progress(self, stage: str, done: int, total: int) -> bool:
        """转换顶层只取逐集处理计数；迟到的扫描事件不能覆盖转换进度。"""
        if stage in self.parts:
            self.converting = True
            previous = self.parts[stage]
            self.parts[stage] = ProgressPart(
                name=previous.name, done=done, total=total, unit=previous.unit
            )
        elif self.converting:
            return False
        main = self.parts["stage"]
        self.latest = JobProgress(
            stage_index=self.first_stage + int(self.converting),
            stage_count=self.stage_count,
            stage_name="转换" if self.converting else "扫描",
            done=main.done if self.converting else done,
            total=main.total if self.converting else total,
            unit="集",
            warning_count=0,
            failed_items=0,
            total_items=0,
            parts=tuple(self.parts.values()) if self.converting else (),
        )
        return True
