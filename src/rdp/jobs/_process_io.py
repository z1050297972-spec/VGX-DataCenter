"""外部进程的流式读出；标准库os.read限制每次分配，只在内存保留有界stderr尾部。"""

import os
from collections import deque
from collections.abc import Callable
from typing import BinaryIO

from rdp.jobs.logs import JobLog
from rdp.jobs.policy import (
    JOB_LOG_TAIL_MAX_BYTES,
    PROCESS_OUTPUT_CHUNK_BYTES,
    PROCESS_STDERR_TAIL_LINES,
    PROCESS_STDERR_TAIL_MAX_BYTES,
)
from rdp.jobs.types import JobClock


class StreamCapture:
    """线程读出与选择器读出共用的有界分行、转义和尾部缓存；写入能力由调用者提供。"""

    def __init__(
        self, prefix: str, write: Callable[[str], None], tail_lines: int = PROCESS_STDERR_TAIL_LINES
    ) -> None:
        """建立单流的有界缓冲，不打开日志或读取进程。"""
        self.prefix, self.write = prefix, write
        self.tail_lines = tail_lines
        self.chunk_size = min(
            PROCESS_OUTPUT_CHUNK_BYTES,
            (JOB_LOG_TAIL_MAX_BYTES - len(prefix.encode()) - len("[续行]".encode())) // 4,
        )
        self.pending = b""
        self.continuation = False
        self.tail: deque[bytes] = deque()
        self.tail_bytes = 0
        self.truncated = False

    def feed(self, data: bytes) -> None:
        """每次最多送入一个标准输出块，完整行即时写出，不积累整个工具输出。"""
        self.pending += data
        while b"\n" in self.pending or len(self.pending) >= self.chunk_size:
            newline = self.pending.find(b"\n")
            complete = 0 <= newline < self.chunk_size
            end = newline if complete else self.chunk_size
            self._line(self.pending[:end], self.continuation)
            self.continuation = not complete
            self.pending = self.pending[end + (1 if complete else 0) :]

    def finish(self) -> None:
        """EOF时保留未换行的最后片段，重复结束不重复写出。"""
        if self.pending:
            self._line(self.pending, self.continuation)
            self.pending = b""

    def _line(self, raw: bytes, continuation: bool) -> None:
        """先记录完整输出，再维护有字节/条数双上限的故障尾部。"""
        escaped = (
            raw.replace(b"\\", b"\\\\")
            .replace(b"\r", b"\\r")
            .decode("utf-8", errors="backslashreplace")
        )
        self.write(self.prefix + ("[续行]" if continuation else "") + escaped)
        encoded = escaped.encode()
        self.tail.append(encoded)
        self.tail_bytes += len(encoded)
        while len(self.tail) > self.tail_lines or self.tail_bytes > PROCESS_STDERR_TAIL_MAX_BYTES:
            self.tail_bytes -= len(self.tail.popleft())
            self.truncated = True

    def tail_text(self) -> str:
        """返回有界诊断尾部；纯空白用固定说明，完整原始输出仍保留在日志文件。"""
        text = b"\n".join(self.tail)
        label = "stdout" if self.prefix.startswith("stdout ") else "stderr"
        marker = (
            f"[{label}尾部已截断]\n".encode()
            if self.truncated or len(text) > PROCESS_STDERR_TAIL_MAX_BYTES
            else b""
        )
        budget = PROCESS_STDERR_TAIL_MAX_BYTES - len(marker)
        rendered = (
            marker.decode() + text[-budget:].decode("utf-8", errors="ignore")
            if text
            else f"（无{label}）"
        )
        return rendered if rendered.strip() else f"（{label}仅含空白）"


class OutputReader:
    """一个流对应一个daemon线程；故障交主执行线程收口，不在读线程记ERROR。"""

    def __init__(
        self,
        stream: BinaryIO,
        prefix: str,
        log: JobLog,
        clock: JobClock,
        tail_lines: int = PROCESS_STDERR_TAIL_LINES,
    ) -> None:
        """绑定一个输出流与前缀，建立有限stderr尾缓存，不启动线程。"""
        self.stream = stream
        self.capture = StreamCapture(
            prefix, lambda line: log.write_line(line, now=clock.now()), tail_lines
        )
        self.error: Exception | None = None

    def run(self) -> None:
        """即使一行无限长也最多缓存一个块；非法UTF8可逆转义而不丢原字节。"""
        try:
            while data := os.read(self.stream.fileno(), self.capture.chunk_size):
                self.capture.feed(data)
            self.capture.finish()
        except Exception as error:
            self.error = error
        finally:
            self.stream.close()

    def tail_text(self) -> str:
        """返回共用分行器保留的有界stderr摘要。"""
        return self.capture.tail_text()
