"""伪终端读出与进度节流（领域内部，M4-02）；生命周期仍由 processes 统一管理。

标准库 select 让静默工具也能触发进度降级；复用 StreamCapture 的日志尾缓存，不保存重画字节。
"""

import errno
import os
import select
from typing import BinaryIO

from rdp.infra.diagnostics import Diagnostic, DiagnosticCategory, DiagnosticLevel
from rdp.jobs._clock import ClockReader
from rdp.jobs._process_io import OutputReader
from rdp.jobs.logs import JobLog
from rdp.jobs.policy import PROCESS_POLL_INTERVAL_S
from rdp.jobs.progress import ProgressReporter
from rdp.jobs.terminal.types import TerminalParser, TerminalUpdate
from rdp.jobs.types import JobProgress

# M4-02规定：运行时每秒至多两次上报，30秒无进度即降级，同周期记一行快照。
_REPORT_INTERVAL_S = 0.5
_SILENCE_TIMEOUT_S = 30.0
_SNAPSHOT_INTERVAL_S = 30.0


class TerminalReader(OutputReader):
    """单个读线程独占解析器和节流状态；不把重画的条形图写进日志。"""

    def __init__(
        self,
        stream: BinaryIO,
        tool_name: str,
        log: JobLog,
        reporter: ProgressReporter,
        parser: TerminalParser,
    ) -> None:
        """使用作业时钟和已有日志分行器，保留进程开始时的累计条目计数。"""
        super().__init__(stream, f"stderr {tool_name}│", log, reporter.clock)
        self.reporter, self.parser, self.log, self.tool_name = reporter, parser, log, tool_name
        self.clock = ClockReader(reporter.clock)
        now = self.clock.read()
        self.last_progress = self.last_snapshot = now
        self.last_report = now - _REPORT_INTERVAL_S
        self.baseline = reporter.snapshot().progress
        self.latest = self.baseline
        self.parsed_progress = False
        self.dirty = False
        self.degraded = False

    def run(self) -> None:
        """EIO是Linux伪终端关闭的EOF；其他读错误交给统一进程收尾诊断。"""
        try:
            while True:
                ready, _, _ = select.select([self.stream], [], [], PROCESS_POLL_INTERVAL_S)
                if ready:
                    chunk = self._read()
                    if not chunk:
                        break
                    self._update(self.parser.feed(chunk))
                self._tick()
            self._update(self.parser.finish())
            self._report(force=True)
            self.capture.finish()
        except Exception as error:
            self.error = error
        finally:
            self.stream.close()

    def _read(self) -> bytes:
        """主端在最后一个从端关闭后可能返回EIO，与空读同样处理。"""
        try:
            return os.read(self.stream.fileno(), self.capture.chunk_size)
        except OSError as error:
            if error.errno == errno.EIO:
                return b""
            raise

    def _update(self, update: TerminalUpdate) -> None:
        """文本完整写日志，进度只保留最新值等待节流；不重置作业累计计数。"""
        for line in update.lines:
            self.capture.feed((line + "\n").encode())
        if update.progress is not None:
            self.parsed_progress = True
            self.last_progress = self.clock.read()
            progress = update.progress
            counts = self.baseline
            progress = progress.model_copy(
                update={
                    "total_items": 0 if counts is None else counts.total_items,
                    "failed_items": 0 if counts is None else counts.failed_items,
                    "warning_count": (0 if counts is None else counts.warning_count)
                    + int(self.degraded),
                }
            )
            self.latest = self._stage_only(progress) if self.degraded else progress
            self.dirty = True

    def _tick(self) -> None:
        """无输出仍检查30秒期限；降级只警告一次，不改变退出码的成败语义。"""
        now = self.clock.read()
        if not self.degraded and now - self.last_progress >= _SILENCE_TIMEOUT_S:
            self.degraded = True
            self._degrade()
        self._report(force=False)
        if self.latest is not None and now - self.last_snapshot >= _SNAPSHOT_INTERVAL_S:
            self.log.write_line(
                f"进度 {self.tool_name}│{self.latest.model_dump_json()}", now=self.clock.clock.now()
            )
            self.last_snapshot = now

    def _degrade(self) -> None:
        """无解析进度时完整保留作业基线；已有工具进度则降为阶段级，只增加一次警告。"""
        progress = (
            self._stage_only(self.latest)
            if self.parsed_progress and self.latest is not None
            else self.baseline
        )
        progress = progress or JobProgress(
            stage_index=1,
            stage_count=1,
            stage_name="外部工具",
            done=0,
            total=None,
            unit="条",
            warning_count=0,
            failed_items=0,
            total_items=0,
        )
        self.latest = progress.model_copy(update={"warning_count": progress.warning_count + 1})
        self.dirty = True
        self.reporter.diagnostic(
            Diagnostic(
                level=DiagnosticLevel.WARNING,
                category=DiagnosticCategory.EXTERNAL,
                stage=progress.stage_name,
                source=self.tool_name,
                objects=(),
                rule="工具运行期间应持续提供可解析进度",
                actual="连续30秒未解析出进度",
                expected="30秒内出现受支持的进度记录",
                consequence="进度解析不出来，只显示阶段",
                next_step="检查工具版本和终端输出格式；成败仍以退出码判断",
            )
        )

    def _stage_only(self, progress: JobProgress) -> JobProgress:
        """冻结同阶段最后计数以遵守reporter不倒退约束，清除分项和百分比依据。"""
        previous = self.latest
        done = (
            previous.done
            if previous is not None and previous.stage_index == progress.stage_index
            else 0
        )
        return progress.model_copy(update={"done": done, "total": None, "parts": ()})

    def _report(self, *, force: bool) -> None:
        """EOF强制保留最后值；常规上报按单调秒节流，落库仍由reporter的一秒预算控制。"""
        now = self.clock.read()
        if self.latest is not None and (
            force or self.dirty and now - self.last_report >= _REPORT_INTERVAL_S
        ):
            self.reporter.report(self.latest)
            self.last_report, self.dirty = now, False
