"""查看器视频适配器（M1.5-04）：安全fd输入、受限子进程与分片输出，不接收存储路径。

编解码交给本机ffmpeg/ffprobe；标准库Popen、Timer和Semaphore负责流式资源生命周期，
没有现成依赖能同时保留安全描述符、HTTP断开清理和有界stderr，故在此组合这些机制。
"""

import json
import logging
import math
import shutil
import subprocess
from collections import deque
from collections.abc import Callable
from http import HTTPStatus
from threading import BoundedSemaphore, Lock, Thread, Timer
from typing import cast

from pydantic import BaseModel, ConfigDict, Field

from rdp.infra.diagnostics import (
    Diagnostic,
    DiagnosticCategory,
    DiagnosticLevel,
    DiagnosticObject,
    ExternalError,
    InputError,
)

logger = logging.getLogger(__name__)
# M1.5-04限制两路、默认60秒/最多300秒；120秒墙钟预算防止损坏输入或慢客户端长期占GPU。
TRANSCODE_SLOTS = BoundedSemaphore(2)
TRANSCODE_TIMEOUT_S = 120.0
TOOL_TIMEOUT_S = 10.0
VIDEO_CHUNK_BYTES = 64 * 1024
# stderr只保留最后8块，每块4KiB；持续排空以免工具堵塞，不随输入规模增长。
_STDERR_BLOCK_BYTES = 4096
_STDERR_BLOCK_COUNT = 8


class VideoQuery(BaseModel):
    """转码输入，所有时间为视频起点以来的秒数，拒绝非有限浮点数。"""

    model_config = ConfigDict(extra="forbid")
    link_name: str = Field(min_length=1, max_length=255)
    path: str = Field(max_length=4096)
    start_s: float = Field(default=0, ge=0, allow_inf_nan=False)
    duration_s: float = Field(default=60, gt=0, le=300, allow_inf_nan=False)


class VideoInfo(BaseModel):
    """首个视频流的编码名称与有限、非负总时长（秒）。"""

    codec: str
    duration_s: float


class VideoBusyError(InputError):
    """两路转码都已占用；使用已批准的429输入异常映射。"""

    http_status = HTTPStatus.TOO_MANY_REQUESTS


def _diagnostic(actual: str, *, busy: bool = False) -> Diagnostic:
    """复用五段诊断，保留工具、返回码和有界stderr，绝不包含原文件绝对路径。"""
    return Diagnostic(
        level=DiagnosticLevel.ERROR,
        category=DiagnosticCategory.INPUT if busy else DiagnosticCategory.EXTERNAL,
        stage="视频转码预览",
        source="平台",
        objects=(DiagnosticObject(key="tool", value="ffmpeg/ffprobe"),),
        rule="FILE_VIEWER_VIDEO_BUSY" if busy else "FILE_VIEWER_VIDEO_TOOL",
        actual=actual,
        expected="最多两路转码，工具可在预算内输出H.264分片MP4",
        consequence="本次视频预览停止，原文件保持只读",
        next_step="等待其他预览结束后重试"
        if busy
        else "检查ffmpeg/ffprobe、编码器和视频完整性后重试",
    )


def _failure(actual: str) -> ExternalError:
    """构造视频工具失败，不把工具错误当作平台程序缺陷。"""
    return ExternalError((_diagnostic(actual),))


def _executable(name: str) -> str:
    """只运行本机已安装工具，不联网下载或安装。"""
    executable = shutil.which(name)
    if executable is None:
        raise _failure(f"本机缺少{name}")
    return executable


class VideoStream:
    """持有一个工具进程；正常EOF、超时、取消和显式close都幂等回收。"""

    def __init__(
        self,
        command: list[str],
        descriptors: tuple[int, ...],
        timeout_s: float,
        release: Callable[[], None],
    ) -> None:
        """启动工具，持续排空stderr，并从启动时刻计算总时限。"""
        self.command = command
        self._release = release
        self._closed = False
        self._timed_out = False
        self._guard = Lock()
        self._stderr: deque[bytes] = deque(maxlen=_STDERR_BLOCK_COUNT)
        self.process: subprocess.Popen[bytes] = subprocess.Popen(  # noqa: S603 # 理由：固定工具参数，仅继承安全fd，禁用shell。
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            pass_fds=descriptors,
        )
        self._reader = Thread(target=self._drain_stderr, daemon=True, name="viewer-video-stderr")
        self._reader.start()
        self._timer = Timer(timeout_s, self._expire)
        self._timer.daemon = True
        self._timer.start()

    def _drain_stderr(self) -> None:
        """持续消费错误输出，只保留诊断尾部，避免pipe背压导致假超时。"""
        if self.process.stderr is not None:
            while block := self.process.stderr.read(_STDERR_BLOCK_BYTES):
                self._stderr.append(block)

    def _expire(self) -> None:
        """即使客户端没有继续读，也在单调计时预算结束时杀进程并释放槽。"""
        self._timed_out = True
        self.close()

    def read(self) -> bytes:
        """读取最多64KiB；超时或非零退出转成工具诊断，调用方负责finally关闭。"""
        if self._timed_out:
            raise _failure("工具timeout：超过本次预览总时限")
        output = self.process.stdout
        if output is None or self._closed:
            return b""
        block = output.read(VIDEO_CHUNK_BYTES)
        if self._timed_out:
            raise _failure("工具timeout：超过本次预览总时限")
        if len(block) < VIDEO_CHUNK_BYTES:
            code = self.process.wait(timeout=TOOL_TIMEOUT_S)
            self._reader.join(timeout=TOOL_TIMEOUT_S)
            if code:
                raise _failure(
                    f"命令={' '.join(self.command)}；退出码={code}；stderr="
                    + b"".join(self._stderr).decode(errors="replace")[-4096:]
                )
        return block

    def close(self) -> None:
        """幂等杀进程、回收管道和线程，并归还转码槽，不留下缓存或产物。"""
        with self._guard:
            if self._closed:
                return
            self._closed = True
            self._timer.cancel()
            try:
                if self.process.poll() is None:
                    self.process.kill()
                self.process.wait(timeout=TOOL_TIMEOUT_S)
                self._reader.join(timeout=TOOL_TIMEOUT_S)
                if self.process.stdout is not None:
                    self.process.stdout.close()
                if self.process.stderr is not None:
                    self.process.stderr.close()
            finally:
                self._release()


def probe(descriptor: int, timeout_s: float) -> VideoInfo:
    """只通过继承fd读取首个视频流的编码和时长，并总是回收工具。"""
    command = [
        _executable("ffprobe"),
        "-v",
        "error",
        "-protocol_whitelist",
        "fd",
        "-fd",
        str(descriptor),
        "-i",
        "fd:",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=codec_name,duration:format=duration",
        "-of",
        "json",
    ]
    try:
        stream = VideoStream(command, (descriptor,), timeout_s, lambda: None)
        try:
            data = stream.read()
            value = cast(dict[str, object], json.loads(data))
            tracks = cast(list[dict[str, object]], value["streams"])
            track = tracks[0]
            duration_s = float(
                str(cast(dict[str, object], value["format"]).get("duration", track.get("duration")))
            )
            codec = str(track["codec_name"])
            if not math.isfinite(duration_s) or duration_s < 0 or not codec:
                raise ValueError("视频时长或编码不可用")
            return VideoInfo(codec=codec, duration_s=duration_s)
        finally:
            stream.close()
    except (
        OSError,
        ValueError,
        KeyError,
        IndexError,
        TypeError,
        subprocess.TimeoutExpired,
    ) as error:
        raise _failure("ffprobe无法取得有效编码和时长") from error


def _encoder(timeout_s: float) -> str:
    """实际试编码一帧，避免仅凭编译列表误判NVENC在无GPU或驱动故障时可用。"""
    failures: list[str] = []
    for encoder in ("h264_nvenc", "libx264"):
        command = [
            _executable("ffmpeg"),
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=size=16x16:rate=1",
            "-frames:v",
            "1",
            "-c:v",
            encoder,
            "-threads",
            "1",
            "-f",
            "null",
            "-",
        ]
        stream = VideoStream(command, (), timeout_s, lambda: None)
        try:
            stream.read()
            return encoder
        except ExternalError as error:
            failures.append(error.diagnostics[0].actual)
        finally:
            stream.close()
    raise _failure("编码器均不可用：" + "; ".join(failures))


def transcode(descriptor: int, query: VideoQuery, startup_timeout_s: float) -> VideoStream:
    """取得两路许可之一并启动分片MP4；输入fd只在启动期间借用，子进程继承独立引用。"""
    if not TRANSCODE_SLOTS.acquire(blocking=False):
        raise VideoBusyError((_diagnostic("当前两路转码均在使用", busy=True),))
    try:
        encoder = _encoder(startup_timeout_s)
        command = [
            _executable("ffmpeg"),
            "-v",
            "error",
            "-nostdin",
            "-protocol_whitelist",
            "fd,pipe",
            "-ss",
            str(query.start_s),
            "-fd",
            str(descriptor),
            "-i",
            "fd:",
            "-t",
            str(query.duration_s),
            "-map",
            "0:v:0",
            "-an",
            "-c:v",
            encoder,
            "-threads",
            "2",
            "-vf",
            "scale=trunc(iw/2)*2:trunc(ih/2)*2",
            "-pix_fmt",
            "yuv420p",
            "-g",
            "30",
            "-movflags",
            "frag_keyframe+empty_moov",
            "-f",
            "mp4",
            "pipe:1",
        ]
        if encoder == "libx264":
            command[command.index("-threads") : command.index("-threads")] = ["-preset", "veryfast"]
        stream = VideoStream(command, (descriptor,), TRANSCODE_TIMEOUT_S, TRANSCODE_SLOTS.release)
    except BaseException:
        TRANSCODE_SLOTS.release()
        raise
    logger.info(
        "视频转码开始",
        extra={
            "fields": {"encoder": encoder, "start_s": query.start_s, "duration_s": query.duration_s}
        },
    )
    return stream
