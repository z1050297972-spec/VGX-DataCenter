"""mcap2lerobot 的版本限定进度适配（领域层，M4-02）。

标准库 codecs/re 处理 UTF-8 和固定模板；现有依赖没有该工具的 indicatif 适配器。
工具无上报协议且禁止修改，故只解析进度；工具支持协议后可替换本适配器，不以解析决定成败。
"""

import codecs
import re
from collections import deque

from rdp.jobs.policy import PROCESS_OUTPUT_CHUNK_BYTES
from rdp.jobs.terminal.types import TerminalUpdate
from rdp.jobs.types import JobProgress, ProgressPart

# 真实200列样本以长空格补位；模板字段之间至多3空格，8空格可区分补位和内容。
_PADDING_SPACES = 8
# 只记住一个50行终端屏幕的文字，避免日志规模决定内存占用。
_SCREEN_LINES = 50
_COUNT = re.compile(
    r"(?P<name>\w+)\s*\[[^]]*\]\s*(?P<done>[\d,]+)/(?P<total>[\d,]+) (?P<unit>帧|条消息)"
)
_OVERALL = re.compile(r"总进度\s*\[[^]]*\]\s*(\d+)%")


class Mcap2LerobotParser:
    """按单条重画记录推进状态，保留不完整的字符和终端控制序列。"""

    def __init__(self, stage_count: int, first_stage: int) -> None:
        """保存调用方的阶段安排，避免工具进度倒退到先前核对阶段。"""
        self.stage_count = stage_count
        self.first_stage = first_stage
        self.decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        self.control = ""
        self.pending = ""
        self.in_bar = False
        self.spaces = 0
        self.seen: deque[str] = deque(maxlen=_SCREEN_LINES)
        self.parts: dict[str, ProgressPart] = {}
        self.converting = False
        self.scanned = 0
        self.scan_total: int | None = None
        self.latest: JobProgress | None = None

    def feed(self, chunk: bytes) -> TerminalUpdate:
        """流式清理控制序列；块边界不视为文本或进度记录边界。"""
        lines: list[str] = []
        recognized = False
        for char in self.decoder.decode(chunk):
            if self._control_character(char):
                continue
            if self._append(char):
                recognized = self._record(lines) or recognized
        return TerminalUpdate(self.latest if recognized else None, tuple(lines))

    def finish(self) -> TerminalUpdate:
        """排出未补位、未换行的最后一条记录，重复结束不会重复返回文字。"""
        self.pending += self.decoder.decode(b"", final=True)
        lines: list[str] = []
        self._record(lines)
        return TerminalUpdate(self.latest, tuple(lines))

    def _control_character(self, char: str) -> bool:
        """CSI参数只保留状态，不累积原始重画字节。"""
        if char == "\x1b":
            self.control = "escape"
            return True
        if self.control == "escape":
            self.control = "csi" if char == "[" else ""
            return True
        if self.control == "csi":
            if "@" <= char <= "~":
                self.control = ""
            return True
        return False

    def _append(self, char: str) -> bool:
        """只在回车、换行、条外补位或有界长文本处分隔，不按read边界切行。"""
        if char in "\r\n":
            return True
        if not self.pending and char.isspace():
            return False
        if char == "[":
            self.in_bar = True
        elif char == "]":
            self.in_bar = False
        self.spaces = self.spaces + 1 if char == " " and not self.in_bar else 0
        self.pending += char
        return self.spaces >= _PADDING_SPACES or len(self.pending) >= PROCESS_OUTPUT_CHUNK_BYTES

    def _record(self, lines: list[str]) -> bool:
        """完整模板更新进度，非进度文字去补位后按屏幕去重。"""
        text, self.pending = self.pending.strip(), ""
        self.in_bar, self.spaces = False, 0
        if not text:
            return False
        match = _COUNT.match(text)
        if match is not None:
            self._count(match)
        elif (overall := _OVERALL.match(text)) is not None:
            self.converting = self.converting or int(overall[1]) > 0
        else:
            if text not in self.seen:
                lines.append(text)
                self.seen.append(text)
            return False
        self.latest = self._progress()
        return True

    def _count(self, match: re.Match[str]) -> None:
        """重画可能重复旧值；每项保留已经确认的完成量，扫描不能让阶段倒退。"""
        name = match["name"]
        done, total = int(match["done"].replace(",", "")), int(match["total"].replace(",", ""))
        if match["unit"] == "条消息":
            if name == "扫描":
                self.scanned, self.scan_total = max(self.scanned, done), total or None
            elif name == "转换":
                self.converting = True
            return
        previous = self.parts.get(name)
        if previous is not None:
            done = max(previous.done, done)
        self.parts[name] = ProgressPart(name=name, done=done, total=total or None, unit="帧")
        self.converting = self.converting or total > 0 or done > 0

    def _progress(self) -> JobProgress:
        """扫描用消息数；转换总帧数由分项汇总，任何未知分项使总数未知。"""
        parts = tuple(self.parts.values()) if self.converting else ()
        return JobProgress(
            stage_index=self.first_stage + int(self.converting),
            stage_count=self.stage_count,
            stage_name="转换" if self.converting else "扫描",
            done=sum(part.done for part in parts) if self.converting else self.scanned,
            total=(
                sum(part.total for part in parts if part.total is not None)
                if parts and all(part.total is not None for part in parts)
                else None
            )
            if self.converting
            else self.scan_total,
            unit="帧" if self.converting else "条消息",
            warning_count=0,
            failed_items=0,
            total_items=0,
            parts=parts,
        )
