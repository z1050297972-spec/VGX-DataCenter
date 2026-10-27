"""外部进程的流式读出；标准库os.read限制每次分配，只在内存保留有界stderr尾部。"""

import os
from collections import deque
from typing import BinaryIO

from rdp.jobs.logs import JobLog
from rdp.jobs.policy import (
    JOB_LOG_TAIL_MAX_BYTES,
    PROCESS_OUTPUT_CHUNK_BYTES,
    PROCESS_STDERR_TAIL_LINES,
    PROCESS_STDERR_TAIL_MAX_BYTES,
)
from rdp.jobs.types import JobClock


class OutputReader:
    """一个流对应一个daemon线程；故障交主执行线程收口，不在读线程记ERROR。"""

    def __init__(self, stream: BinaryIO, prefix: str, log: JobLog, clock: JobClock) -> None:
        """绑定一个输出流与前缀，建立有限stderr尾缓存，不启动线程。"""
        self.stream, self.prefix, self.log, self.clock = stream, prefix, log, clock
        self.error: Exception | None = None
        self.tail: deque[bytes] = deque()
        self.tail_bytes = 0
        self.truncated = False

    def run(self) -> None:
        """即使一行无限长也最多缓存一个块；非法UTF8可逆转义而不丢原字节。"""
        chunk_size = min(
            PROCESS_OUTPUT_CHUNK_BYTES,
            (JOB_LOG_TAIL_MAX_BYTES - len(self.prefix.encode()) - len("[续行]".encode())) // 4,
        )
        pending = b""
        continuation = False
        try:
            while data := os.read(self.stream.fileno(), chunk_size):
                pending += data
                while b"\n" in pending or len(pending) >= chunk_size:
                    newline = pending.find(b"\n")
                    complete = 0 <= newline < chunk_size
                    end = newline if complete else chunk_size
                    self._line(pending[:end], continuation)
                    continuation = not complete
                    pending = pending[end + (1 if complete else 0) :]
            if pending:
                self._line(pending, continuation)
        except Exception as error:
            self.error = error
        finally:
            self.stream.close()

    def _line(self, raw: bytes, continuation: bool) -> None:
        """先记录完整输出，再维护有字节/条数双上限的故障尾部。"""
        escaped = (
            raw.replace(b"\\", b"\\\\")
            .replace(b"\r", b"\\r")
            .decode("utf-8", errors="backslashreplace")
        )
        self.log.write_line(
            self.prefix + ("[续行]" if continuation else "") + escaped, now=self.clock.now()
        )
        encoded = escaped.encode()
        self.tail.append(encoded)
        self.tail_bytes += len(encoded)
        while (
            len(self.tail) > PROCESS_STDERR_TAIL_LINES
            or self.tail_bytes > PROCESS_STDERR_TAIL_MAX_BYTES
        ):
            self.tail_bytes -= len(self.tail.popleft())
            self.truncated = True

    def tail_text(self) -> str:
        """返回有界诊断尾部；纯空白用固定说明，完整原始输出仍保留在日志文件。"""
        text = b"\n".join(self.tail)
        marker = (
            "[stderr尾部已截断]\n".encode()
            if self.truncated or len(text) > PROCESS_STDERR_TAIL_MAX_BYTES
            else b""
        )
        budget = PROCESS_STDERR_TAIL_MAX_BYTES - len(marker)
        rendered = (
            marker.decode() + text[-budget:].decode("utf-8", errors="ignore")
            if text
            else "（无stderr）"
        )
        return rendered if rendered.strip() else "（stderr仅含空白）"
