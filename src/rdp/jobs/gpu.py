"""GPU 存在性核对（领域层，09）；只在 worker 调用，不配置驱动或管理平台外的占用。

使用标准库 subprocess 流式捕获输出，避免无界 PIPE 内存；校验失败只补诊断，
由启动/执行边界分别记录一次 ERROR。CUDA 环境注入在 processes，不由作业类型拼接。
"""

import logging
import os
import selectors
import signal
import subprocess
import time
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from rdp.infra.config import MAX_GPU_INDEX
from rdp.infra.diagnostics import (
    DefectError,
    Diagnostic,
    DiagnosticCategory,
    DiagnosticLevel,
    DiagnosticObject,
    ExternalError,
)
from rdp.jobs import policy
from rdp.jobs._process_io import StreamCapture
from rdp.jobs.logs import JobLog

logger = logging.getLogger(__name__)


def verify_gpu(gpu_index: int, nvidia_smi: Path, *, log: JobLog | None) -> None:
    """在有界时间内确认指定物理卡号可被 nvidia-smi 查询。

    Args:
        gpu_index: 严格整数 0 至 MAX_GPU_INDEX，PCI_BUS_ID 顺序的物理编号。
        nvidia_smi: 入口注入的绝对可执行路径；测试只提供临时假脚本。
        log: 必填；作业执行时传入当前 JobLog，所有输出通过其线程安全写入接口；
            只有启动核对传 None，输出由当前模块 logger 写 worker.log，不另建日志文件。

    Returns:
        无；仅工具零退出且查询结果明确包含此编号时成功。

    Raises:
        ExternalError: 启动失败、非零/信号退出、GPU_PROBE_TIMEOUT_S 超时、缺卡、输出格式损坏
            或输出捕获失败；诊断含卡号、命令、退出码/信号、stderr 有界尾部、后果和检查驱动建议。
            无 stderr 或纯空白使用固定说明，不能因诊断空字段退化为程序缺陷；禁止回退 CPU。
        DefectError: 卡号、路径或调用依赖不合法；不启动进程。

    Side Effects:
        shell=False 执行 nvidia-smi --query-gpu=index --format=csv,noheader,nounits；
        两路输出保留 stdout/stderr 与 nvidia-smi 行前缀，作业中只通过 JobLog 写入，禁止直接打开日志路径；
        启动时只写已配置的 worker.log。完整流式保留输出，stderr 尾限 PROCESS_STDERR_TAIL_LINES/PROCESS_STDERR_TAIL_MAX_BYTES。
        超时终止并有界回收进程，不改 GPU 占用；调用者负责 finally 归还已领名额。
        本层不 ERROR；启动边界对失败卡记一次 ERROR 并移出本实例名额池，CPU 作业继续。
        作业执行前核对失败仍由执行器令该作业外部失败并归还卡，不在此更改启动池成员。

    Time Semantics:
        超时 GPU_PROBE_TIMEOUT_S=5 秒，用单调时长；回收另限 PROCESS_REAP_TIMEOUT_S。
        启动逐卡核对；作业领卡提交后、执行类型函数前再次使用同一核对函数，不在写事务中执行。
    """
    if (
        type(gpu_index) is not int
        or not 0 <= gpu_index <= MAX_GPU_INDEX
        or not isinstance(cast(object, nvidia_smi), Path)
        or not nvidia_smi.is_absolute()
        or (log is not None and not isinstance(cast(object, log), JobLog))
    ):
        raise DefectError()
    _Probe(gpu_index, nvidia_smi, log).run()


class _Probe:
    """一次同步核对使用非阻塞管道和选择器；没有额外读线程或无界communicate缓存。"""

    def __init__(self, index: int, command: Path, log: JobLog | None) -> None:
        """保存目标卡与调用者的日志能力，进程尚未启动。"""
        self.index, self.command, self.log = index, command, log
        self.found = False
        self.invalid = False
        self.process: subprocess.Popen[bytes] | None = None
        self.stdout = StreamCapture("stdout nvidia-smi│", self._stdout)
        self.stderr = StreamCapture("stderr nvidia-smi│", self._write)
        self.argv = (str(command), "--query-gpu=index", "--format=csv,noheader,nounits")

    def run(self) -> None:
        """总超时包括输出排空；所有异常路径都按进程组有界回收。"""
        try:
            self.process = subprocess.Popen(  # noqa: S603  # 理由：注入的绝对程序和固定查询参数，禁止shell。
                self.argv,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=True,
                close_fds=True,
            )
            try:
                self._read()
            finally:
                self._cleanup()
        except (OSError, subprocess.SubprocessError) as error:
            raise self._failure("核对进程启动、读取或回收失败") from error
        if self.process.returncode != 0:
            raise self._failure("nvidia-smi非零退出或被信号终止")
        if self.invalid or not self.found:
            raise self._failure(
                "nvidia-smi输出格式损坏" if self.invalid else "nvidia-smi看不到指定卡"
            )

    def _read(self) -> None:
        """轮询单调期限并实时写两路输出，后代持管道时也不能越过总期限。"""
        if self.process is None:
            raise DefectError()
        deadline = time.monotonic() + policy.GPU_PROBE_TIMEOUT_S
        with selectors.DefaultSelector() as selector:
            for stream, capture in (
                (self.process.stdout, self.stdout),
                (self.process.stderr, self.stderr),
            ):
                if stream is None:
                    raise DefectError()
                os.set_blocking(stream.fileno(), False)
                selector.register(stream, selectors.EVENT_READ, capture)
            while selector.get_map():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise self._failure("nvidia-smi核对超时")
                for key, _mask in selector.select(min(remaining, policy.PROCESS_POLL_INTERVAL_S)):
                    capture = cast(StreamCapture, key.data)
                    data = os.read(key.fd, capture.chunk_size)
                    if data:
                        capture.feed(data)
                    else:
                        capture.finish()
                        selector.unregister(key.fileobj)
            try:
                self.process.wait(timeout=max(0, deadline - time.monotonic()))
            except subprocess.TimeoutExpired as error:
                raise self._failure("nvidia-smi核对超时") from error

    def _cleanup(self) -> None:
        """核对无需保留外部产物，结束整个独立进程组后有界wait并关闭管道。"""
        if self.process is None:
            raise DefectError()
        try:
            with suppress(ProcessLookupError):
                os.killpg(self.process.pid, signal.SIGKILL)
            self.process.wait(timeout=policy.PROCESS_REAP_TIMEOUT_S)
        finally:
            for stream in (self.process.stdout, self.process.stderr):
                if stream is not None:
                    stream.close()

    def _write(self, text: str) -> None:
        """作业输出走JobLog锁，启动输出只进当前worker日志。"""
        if self.log is None:
            logger.info("%s", text)
        else:
            self.log.write_line(text, now=datetime.now(UTC))

    def _stdout(self, text: str) -> None:
        """逐行核对严格ASCII编号，内存只保存命中和格式状态，不保存整份卡清单。"""
        self._write(text)
        value = text.removeprefix("stdout nvidia-smi│").strip()
        if (
            not value
            or len(value) > len(str(MAX_GPU_INDEX))
            or not value.isascii()
            or not value.isdecimal()
            or int(value) > MAX_GPU_INDEX
        ):
            self.invalid = True
        elif int(value) == self.index:
            self.found = True

    def _failure(self, actual: str) -> ExternalError:
        """有界stderr保留真实尾部，空白输出同样能构成合法统一诊断。"""
        return ExternalError(
            (
                Diagnostic(
                    level=DiagnosticLevel.ERROR,
                    category=DiagnosticCategory.EXTERNAL,
                    stage="GPU存在性核对",
                    source="nvidia-smi",
                    objects=(
                        DiagnosticObject(key="gpu_index", value=str(self.index)),
                        DiagnosticObject(key="command", value=repr(self.argv)),
                        DiagnosticObject(
                            key="returncode",
                            value=str(None if self.process is None else self.process.returncode),
                        ),
                        DiagnosticObject(key="stderr_tail", value=self.stderr.tail_text()),
                    ),
                    rule="所领物理卡必须可被nvidia-smi查询",
                    actual=actual,
                    expected="工具零退出且结果包含所领卡号",
                    consequence="本次核对失败，作业不回退CPU执行",
                    next_step="检查卡号、驱动、nvidia-smi的stderr及完整日志",
                ),
            )
        )
