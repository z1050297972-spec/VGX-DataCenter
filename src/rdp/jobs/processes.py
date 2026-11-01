"""外部进程执行边界（08、规范 6.9）；复用 subprocess/POSIX 进程组，不执行 shell。

stdout/stderr 分别读出线程流式捕获；普通 subprocess.run 无法同时满足实时逐行日志与取消升级，
因此用 Popen。JSON上报管道协议由M4接转换实现，本模块只处理原始输出和退出码。
worker被SIGKILL时Python finally不会运行，生产依赖第11张systemd KillMode=control-group清理孤儿工具，
TimeoutStopSec不得小于WORKER_STOP_TIMEOUT_S（30秒）；测试由夹具独立清理。
"""

import math
import os
import signal
import subprocess
import tempfile
import time
import unicodedata
from contextlib import ExitStack
from contextvars import copy_context
from dataclasses import dataclass
from pathlib import Path
from threading import Thread
from typing import BinaryIO, cast

from rdp.infra.diagnostics import (
    DefectError,
    Diagnostic,
    DiagnosticCategory,
    DiagnosticLevel,
    DiagnosticObject,
    ExternalError,
)
from rdp.jobs._clock import ClockReader
from rdp.jobs._process_io import OutputReader
from rdp.jobs.logs import JobLog
from rdp.jobs.policy import (
    OUTPUT_JOIN_TIMEOUT_S,
    PROCESS_POLL_INTERVAL_S,
    PROCESS_REAP_TIMEOUT_S,
    PROCESS_TERM_GRACE_S,
)
from rdp.jobs.progress import ProgressReporter
from rdp.jobs.types import JobClock


@dataclass(frozen=True)
class ToolCommand:
    """可复现且不含秘密的外部命令，不允许 shell 字符串。

    Attributes:
        tool_name: 稳定工具显示名，1-64 码点，无换行/控制字符，作为输出前缀。
        argv: 非空参数元组；argv[0] 为绝对可执行文件路径，所有项无 NUL、无秘密。
        cwd: 显式绝对工作目录；测试仅 tmp_path，不从请求直接接收。
        timeout_s: 有限正秒数，整个执行的单调期限；不能为 None，无隐式无限等待。
    """

    tool_name: str
    argv: tuple[str, ...]
    cwd: Path
    timeout_s: float


def run_external_process(
    command: ToolCommand,
    reporter: ProgressReporter,
    log: JobLog,
    clock: JobClock,
    *,
    gpu_index: int | None = None,
) -> int:
    """完整捕获工具输出，并在取消时终止整个进程组。

    Args:
        command: 不含秘密的 ToolCommand，shell=False、start_new_session=True、close_fds=True。
        reporter: 当前作业上报对象，供检查取消/停止和保存真实 returncode。
        log: 当前作业线程安全日志；不另建输出文件或把整份输出留内存。
        clock: UTC 记录时刻与单调期限提供器，不修改全局时钟。
        gpu_index: 当前作业所领非负物理卡号；None 沿用继承环境，不接受前端输入。

    Returns:
        工具正常退出时的零退出码；读线程排空并回收之后才返回。

    Raises:
        JobCancelledError: 收到取消且有界清理成功后抛出；工具恰好返回零仍保留取消语义。
        WorkerStoppingError: worker 停止导致清理；保持运行中记录，不伪装用户取消。
        ExternalError: 启动失败、非零退出、信号结束、超过 timeout_s、输出读取/日志写入或清理失败。
            诊断包含工具名、argv、退出码或信号、stderr 最后 PROCESS_STDERR_TAIL_LINES 行、
            最后进度、后果和下一步；stderr摘要另限PROCESS_STDERR_TAIL_MAX_BYTES，截断须标记。
            SIGKILL后PROCESS_REAP_TIMEOUT_S仍收不回（例如D状态），或读线程join超时也抛ExternalError，
            不伪造退出码；诊断注明资源未回收，即使已有取消也报告此清理失败，执行器仍按数据库取消态决定结局。
        DefectError: 参数、依赖或时钟非法；未通过校验不启动任何进程。

    Side Effects:
        gpu_index 非空时复制当前环境并强制设置 CUDA_VISIBLE_DEVICES 为该编号十进制文本、
        CUDA_DEVICE_ORDER=PCI_BUS_ID；不修改父进程环境，并发作业不能串卡。
        启动前把最终传给 Popen 的这两项实际值写入当前 JobLog 一行，不记录其他环境变量或秘密；
        GPU 示例因此能展示隔离设置，不依赖 nvidia-smi 是否遵守 CUDA 环境。
        启动独立进程组，worker 锁文件描述符不可继承。stdout/stderr 每行追加前缀
        “stdout <工具名>│”/“stderr <工具名>│”并刷新，两个流各自保序，不伪造跨流总顺序。
        超长无换行输出按 PROCESS_OUTPUT_CHUNK_BYTES 分段并标记续行，内容不丢弃；
        UTF-8 非法字节以可逆转义写入日志，stderr 摘要有界，完整流只保存在日志中。
        取消/停止/超时先向进程组 SIGTERM，宽限到期仍存活则 SIGKILL；使用组是因为工具还会派生子进程。
        两个读线程daemon=True，先reporter.track_output_thread登记到monitor再start。
        finally终止组并有界wait/join，正常完成排空并回收；D状态或读线程不退出时不可无限等，
        读线程以daemon遗留且继续留在monitor，不关闭正被阻塞线程使用的文件对象来制造另一处无界等待。
        清理失败以ExternalError保留原异常链及安全诊断，不在中间层ERROR，交执行器一次报告；
        run_loop发现遗留线程就失败收尾并保留实例锁。

    Time Semantics:
        每PROCESS_POLL_INTERVAL_S检查信号并调用reporter.flush_due，等待取该周期与next_flush_deadline较早者，
        不因工具长时间无输出而漏掉待写进度；BEGIN短锁忙跳过，下秒再试，不共享输出线程的读锁。
        无锁竞争补写目标1秒，另计至多100毫秒获锁及I/O/调度；每次连续短锁跳过另加1秒。
        TERM宽限PROCESS_TERM_GRACE_S=10秒，
        KILL 后 wait 最多 PROCESS_REAP_TIMEOUT_S、读线程回收最多 OUTPUT_JOIN_TIMEOUT_S。
        直接子进程退出但后代仍持管道时也终止组，不能无限等 EOF；所有期限用 monotonic。
    """
    _validate_command(command)
    environment = None
    if gpu_index is not None:
        if type(gpu_index) is not int or gpu_index < 0:
            raise DefectError()
        environment = dict(os.environ)
        environment["CUDA_VISIBLE_DEVICES"] = str(gpu_index)
        environment["CUDA_DEVICE_ORDER"] = "PCI_BUS_ID"
    reader = ClockReader(clock)
    reader.read()
    return _ProcessRun(command, reporter, log, reader, environment).run()


class ManagedExternalProcess:
    """可由作业驱动 RPC 的长进程，复用 M0 捕获与进程组清理设施。"""

    def __init__(
        self,
        command: ToolCommand,
        reporter: ProgressReporter,
        log: JobLog,
        clock: JobClock,
        *,
        stdin_data: bytes | None = None,
    ) -> None:
        """验证命令并绑定此次作业的日志和停止上下文。

        Args:
            command: 非秘密参数、绝对路径及有限超时。
            reporter: 当前作业的信号和输出线程登记对象。
            log: 作业日志。
            clock: UTC 与单调时钟。
            stdin_data: 可选标准输入，可能含凭据，不放命令行或日志。

        Returns:
            无，尚未启动进程。

        Raises:
            DefectError: 命令或时钟非法。

        Side Effects:
            无。

        Time Semantics:
            启动前校验，不等待外部进程。
        """
        _validate_command(command)
        self._run = _ProcessRun(command, reporter, log, ClockReader(clock), None)
        self._stopped = False
        self._stdin_data = stdin_data

    def start(self) -> None:
        """启动独立进程组及受管输出读取线程。

        Args:
            无。

        Returns:
            无；进程创建后返回，不等待应用就绪。

        Raises:
            DefectError: 重复启动。
            ExternalError: 子进程或日志输出线程启动失败。

        Side Effects:
            启动并登记子进程及输出线程；失败尝试有界清理。

        Time Semantics:
            应用层必须另设就绪等待预算。
        """
        if self._run.process is not None or self._stopped:
            raise DefectError()
        try:
            with ExitStack() as stack:
                if self._stdin_data is not None:
                    # 匿名临时文件不携带可见路径，避免凭据进入命令行或残留文件。
                    input_file = stack.enter_context(tempfile.TemporaryFile(mode="w+b"))
                    input_file.write(self._stdin_data)
                    input_file.seek(0)
                    self._run.stdin = input_file
                self._run.start()
        except BaseException:
            self._run.cleanup(terminate=True)
            raise
        finally:
            self._stdin_data = None

    def running(self) -> bool:
        """观察直接子进程是否仍存活。

        Args:
            无。

        Returns:
            已启动且尚未退出时为 True。

        Raises:
            无。

        Side Effects:
            无；只读取进程状态。

        Time Semantics:
            观察值可能在返回后立即变化。
        """
        process = self._run.process
        return process is not None and process.poll() is None

    def returncode(self) -> int | None:
        """读取直接子进程退出码。

        Args:
            无。

        Returns:
            进程未退出或未启动时为 None，否则为退出码。

        Raises:
            无。

        Side Effects:
            无；只读取进程状态。

        Time Semantics:
            非阻塞，返回的是本次轮询快照。
        """
        process = self._run.process
        return None if process is None else process.poll()

    def stop(self) -> None:
        """按 M0 的 TERM、KILL 和线程回收规则停止进程组。

        Args:
            无。

        Returns:
            无；重复停止无操作。

        Raises:
            ExternalError: 进程组或输出线程无法在预算内回收。

        Side Effects:
            终止进程组并登记退出码。

        Time Semantics:
            遵循 PROCESS_TERM_GRACE_S 和 PROCESS_REAP_TIMEOUT_S。
        """
        if not self._stopped:
            self._run.cleanup(terminate=True)
            self._stopped = True


class _ProcessRun:
    """一个直接进程及其两个读线程；独立进程组便于取消工具派生的后代。"""

    def __init__(
        self,
        command: ToolCommand,
        reporter: ProgressReporter,
        log: JobLog,
        clock: ClockReader,
        environment: dict[str, str] | None,
    ) -> None:
        """保存当前命令及上报依赖，进程和读线程由run显式启动。"""
        self.command, self.reporter, self.log, self.clock = command, reporter, log, clock
        self.environment = environment
        self.stdin: BinaryIO | None = None
        self.process: subprocess.Popen[bytes] | None = None
        self.readers: list[OutputReader] = []
        self.threads: list[Thread] = []

    def run(self) -> int:
        """任何路径都进入有限清理；清理失败优先报告，不能伪称取消已完成。"""
        try:
            self.start()
            reason = self._poll()
        except BaseException:
            self.cleanup(terminate=True)
            raise
        else:
            self.cleanup(terminate=reason is not None)
        if reason is not None:
            failure = self._failure(reason)
            raise failure
        if not (self.process is not None):
            raise DefectError()
        returncode = self.process.returncode
        if returncode != 0:
            failure = self._failure("工具非零退出或被信号终止")
            raise failure
        self.reporter.check_cancelled()
        return 0

    def start(self) -> None:
        """绝对程序及无shell参数来自登记执行函数，锁fd不可继承。"""
        if self.environment is not None:
            self.log.write_line(
                "CUDA_VISIBLE_DEVICES="
                + self.environment["CUDA_VISIBLE_DEVICES"]
                + " CUDA_DEVICE_ORDER="
                + self.environment["CUDA_DEVICE_ORDER"],
                now=self.clock.clock.now(),
            )
        try:
            self.process = subprocess.Popen(  # noqa: S603  # 理由：已校验绝对程序路径，登记函数提供argv，禁止shell。
                self.command.argv,
                cwd=self.command.cwd,
                env=self.environment,
                stdin=self.stdin,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=True,
                close_fds=True,
            )
        except OSError as error:
            failure = self._failure("启动外部工具失败")
            raise failure from error
        for name, stream in (("stdout", self.process.stdout), ("stderr", self.process.stderr)):
            if not (stream is not None):
                raise DefectError()
            reader = OutputReader(
                cast(BinaryIO, stream),
                f"{name} {self.command.tool_name}│",
                self.log,
                self.clock.clock,
            )
            context = copy_context()
            thread = Thread(target=context.run, args=(reader.run,), daemon=True)
            self.reporter.track_output_thread(thread)
            self.readers.append(reader)
            self.threads.append(thread)
            thread.start()

    def _poll(self) -> str | None:
        """无输出也检查取消及补写截止，不能阻塞在readline里。"""
        if not (self.process is not None):
            raise DefectError()
        deadline = self.clock.read() + self.command.timeout_s
        while self.process.poll() is None:
            self.reporter.check_cancelled()
            if any(reader.error is not None for reader in self.readers):
                return "输出读取或日志写入失败"
            remaining = deadline - self.clock.read()
            if remaining <= 0:
                return "工具执行超过timeout_s"
            self.reporter.wait(min(PROCESS_POLL_INTERVAL_S, remaining))
        return None

    def cleanup(self, *, terminate: bool) -> None:
        """TERM有宽限，KILL后仍有独立回收上限；存活daemon读线程交monitor保留。"""
        process = self.process
        if process is None:
            return
        if terminate or process.poll() is None:
            self._signal(signal.SIGTERM)
            deadline = self.clock.read() + PROCESS_TERM_GRACE_S
            while process.poll() is None and self.clock.read() < deadline:
                time.sleep(min(PROCESS_POLL_INTERVAL_S, max(0, deadline - self.clock.read())))
            self._signal(signal.SIGKILL)
        try:
            process.wait(timeout=PROCESS_REAP_TIMEOUT_S)
        except subprocess.TimeoutExpired as error:
            failure = self._failure("SIGKILL后进程仍未回收")
            raise failure from error
        self.reporter.tool_exit(process.returncode)
        # 父工具退出不代表后代关闭了管道；先结束剩余组再等EOF，不能无限读。
        if any(thread.is_alive() for thread in self.threads):
            self._signal(signal.SIGTERM)
        deadline = self.clock.read() + OUTPUT_JOIN_TIMEOUT_S
        for thread in self.threads:
            thread.join(timeout=max(0, deadline - self.clock.read()))
        if any(thread.is_alive() for thread in self.threads):
            self._signal(signal.SIGKILL)
            deadline = self.clock.read() + OUTPUT_JOIN_TIMEOUT_S
            for thread in self.threads:
                thread.join(timeout=max(0, deadline - self.clock.read()))
        if any(thread.is_alive() for thread in self.threads) or any(
            reader.error is not None for reader in self.readers
        ):
            failure = self._failure("输出线程或日志资源未完整回收")
            raise failure

    def _signal(self, number: signal.Signals) -> None:
        """进程组可能恰好退出，ESRCH允许忽略，其他系统错误不能伪装成功。"""
        if not (self.process is not None):
            raise DefectError()
        try:
            os.killpg(self.process.pid, number)
        except ProcessLookupError:
            pass
        except OSError as error:
            failure = self._failure("终止工具进程组失败")
            raise failure from error

    def _failure(self, actual: str) -> ExternalError:
        """诊断只保留有界stderr尾和当前进度，完整流留在文件。"""
        code = None if self.process is None else self.process.returncode
        tail = self.readers[-1].tail_text() if len(self.readers) == 2 else "（无stderr）"
        progress = self.reporter.snapshot().progress
        return ExternalError(
            (
                Diagnostic(
                    level=DiagnosticLevel.ERROR,
                    category=DiagnosticCategory.EXTERNAL,
                    stage="外部工具",
                    source=self.command.tool_name,
                    objects=(
                        DiagnosticObject(key="command", value=repr(self.command.argv)),
                        DiagnosticObject(key="returncode", value=str(code)),
                        DiagnosticObject(key="stderr_tail", value=tail),
                        DiagnosticObject(
                            key="progress",
                            value="尚未上报" if progress is None else progress.model_dump_json(),
                        ),
                    ),
                    rule="外部工具须在预算内正常退出并完整回收",
                    actual=actual,
                    expected="退出码0且输出完整",
                    consequence="本次工具执行失败，作业可能整体失败或取消",
                    next_step="检查工具命令、stderr尾部和完整作业日志",
                ),
            )
        )


def _validate_command(command: ToolCommand) -> None:
    """校验不可变命令再启动；参数来自登记代码也不能隐式开启shell或无界等待。"""
    if (
        not command.tool_name
        or len(command.tool_name) > 64
        or any(unicodedata.category(char) == "Cc" for char in command.tool_name)
    ):
        raise DefectError()
    if (
        not command.argv
        or not Path(command.argv[0]).is_absolute()
        or any(not isinstance(cast(object, arg), str) or "\0" in arg for arg in command.argv)
    ):
        raise DefectError()
    if (
        not command.cwd.is_absolute()
        or type(command.timeout_s) not in {int, float}
        or not math.isfinite(command.timeout_s)
        or command.timeout_s <= 0
    ):
        raise DefectError()
