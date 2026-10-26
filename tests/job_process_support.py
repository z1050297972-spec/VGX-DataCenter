"""08真实子进程测试的隔离夹具契约；所有状态/日志/握手文件均位于pytest临时目录。"""

from dataclasses import dataclass
from pathlib import Path

from rdp.jobs.policy import WORKER_STOP_TIMEOUT_S
from rdp.jobs.processes import ToolCommand
from rdp.jobs.types import JobProgress, JobRecord
from rdp.ops.worker import WorkerExit

# 真实进程握手预算，单位秒；不以固定sleep猜测worker已经持锁或写完进度。
PROCESS_READY_TIMEOUT_S = 15.0
PROCESS_EXIT_TIMEOUT_S = 5.0
# 等入口返回的预算必须覆盖生产30秒收尾；额外5秒仅留给进程调度。
PROCESS_STOP_TIMEOUT_S = WORKER_STOP_TIMEOUT_S + PROCESS_EXIT_TIMEOUT_S
# 超时锁测试刻意在入口失败返回后继续保活，最多60秒，父进程授权退出或finally强制清理。
FAILED_WORKER_HOLD_S = 60.0
# SIGTERM宽限10秒，计时断言留出主循环一秒及机器调度余量，不接受立即KILL。
CANCEL_MIN_ELAPSED_S = 9.5
CANCEL_MAX_ELAPSED_S = 15.0


@dataclass(frozen=True)
class ProcessCase:
    """临时数据库里的测试账号、测试类型和可观测握手，不依赖真实账号或数据。"""

    root: Path
    job_id: int
    queued_job_id: int

    def wait_running(self, timeout_s: float) -> JobRecord:
        """有界等待worker持锁、已上报第3条且数据库确实保存第3条，返回数据库快照。

        执行函数第三次report后进入长reporter.wait；其到期补写确保无竞争时约1秒内落库，
        父进程以已提交数据库内容作为握手，不能把“report返回”当持久化完成。
        """
        raise NotImplementedError

    def wait_terminal(self, timeout_s: float) -> JobRecord:
        """有界等待测试作业终态；超时附子进程日志，不把超时当通过。"""
        raise NotImplementedError

    def wait_queued_terminal(self, timeout_s: float) -> JobRecord:
        """有界等待原恢复作业后面的新queued作业结束，再断言完整执行顺序。"""
        raise NotImplementedError

    def interruption(self) -> tuple[JobProgress | None, str]:
        """解析最后中断段的结构化进度和处理方式，与数据库独立逐字段比较。"""
        raise NotImplementedError

    def execution_modes(self) -> tuple[str, ...]:
        """读取测试执行函数写入的模式握手，fresh后应为resume/restart，interrupt没有第二次执行。"""
        raise NotImplementedError

    def resumed_progress(self) -> tuple[JobProgress | None, JobProgress | None]:
        """返回测试函数收到的previous_progress和本次起始进度，检查续跑保留与重跑清零。"""
        raise NotImplementedError

    def wait_claimed_before_log(self, timeout_s: float) -> JobRecord:
        """等待claim_gap夹具在领取提交后、打开日志前暂停；读库确认running和log_path均已提交。"""
        raise NotImplementedError

    def log_section_order(self) -> tuple[str, ...]:
        """从真实日志的段落标记提取header/interruption/summary顺序；没有开头不能用中断段字段冒充。"""
        raise NotImplementedError

    def wait_tool_ready(self, timeout_s: float) -> None:
        """有界等待本工具的stdout前缀ready完整行已flush到作业日志，再允许取消或读取pid。

        ready只能在工具安装SIGTERM忽略处理器之后打印；超时失败，不能仅以作业running替代。
        """
        raise NotImplementedError

    def wait_worker_return(self, timeout_s: float) -> WorkerExit:
        """读取真实子进程夹具记录的run_worker返回结果；调用方保活，不能把进程退出当入口返回。"""
        raise NotImplementedError

    def allow_process_exit(self) -> None:
        """通知超时锁夹具结束失败返回后的保活，用原WorkerExit.code退出，不手动解锁。"""
        raise NotImplementedError

    def request_cancel(self) -> None:
        """以另一测试账号经JobService取消当前作业，不能直接UPDATE状态绕开状态机。"""
        raise NotImplementedError

    def stop(self) -> None:
        """写临时停止握手，子进程夹具将其转换成注入Event，不修改生产信号处理。"""
        raise NotImplementedError

    def tool_pid(self) -> int:
        """读已就绪工具的正pid；就绪握手只在SIGTERM忽略处理器安装后产生。"""
        raise NotImplementedError

    def execution_order(self) -> tuple[int, ...]:
        """读取执行顺序握手，恢复作业必须早于新queued作业。"""
        raise NotImplementedError

    def cleanup_orphans(self) -> None:
        """finally读取本夹具登记的worker/工具pid和进程组，有界清理；一个wait超时也继续清理其余对象，不操作无关进程。"""
        raise NotImplementedError


def prepare_process_case(root: Path, mode: str, command: ToolCommand | None = None) -> ProcessCase:
    """在临时目录迁移0004、建两账号，登记测试专用resume/restart/interrupt/外部进程类型。

    提交测试作业和排在它后面的示例；前三条在一秒内report后写“已上报”握手并进入长reporter.wait，
    父进程wait_running独立读数据库确认第3条真正落库；补写不依赖父进程放行或下一次report。
    claim_gap夹具在claim_job事务提交后、execute_job打开日志前暂停，重启的interrupt模式不再暂停。
    shutdown_timeout类型先确认第3条已持久化，再进入不检查停止的daemon阻塞制造超时；
    该类型提交快照为interrupt，保证第一进程退出后新实例不会再次执行坏函数。正常类型仍遵守检查点。
    外部进程类型通过ExecutionContext.run_process启动command，不借用真实数据或网络。
    """
    raise NotImplementedError


def worker_main(root: Path, mode: str) -> None:
    """真实子进程入口：从临时夹具构造引擎/测试登记表/时钟，调用rdp.ops.worker.run_worker。

    不跨进程传Engine；停止握手按实例uuid命名，旧请求不影响新实例；监视线程也有截止且finally回收。锁冲突把入口退出码交sys.exit。
    worker与所有测试工具pid在运行前写root供最终清理，生产依赖systemd control-group，测试不能假设SIGKILL会杀工具。
    shutdown_timeout模式记录run_worker返回值后最多保活FAILED_WORKER_HOLD_S，等allow_process_exit才以失败码退出，
    以验证返回后原始锁fd仍在；其余模式立即以返回码退出。测试类型不进入production_registry。
    """
    raise NotImplementedError
