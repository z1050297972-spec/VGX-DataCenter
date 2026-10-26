"""外部进程执行边界（08、规范 6.9）；复用 subprocess/POSIX 进程组，不执行 shell。

stdout/stderr 分别读出线程流式捕获；普通 subprocess.run 无法同时满足实时逐行日志与取消升级，
因此用 Popen。JSON上报管道协议由M4接转换实现，本模块只处理原始输出和退出码。
worker被SIGKILL时Python finally不会运行，生产依赖第11张systemd KillMode=control-group清理孤儿工具，
TimeoutStopSec不得小于WORKER_STOP_TIMEOUT_S（30秒）；测试由夹具独立清理。
"""

from dataclasses import dataclass
from pathlib import Path

from rdp.jobs.logs import JobLog
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
    command: ToolCommand, reporter: ProgressReporter, log: JobLog, clock: JobClock
) -> int:
    """完整捕获工具输出，并在取消时终止整个进程组。

    Args:
        command: 不含秘密的 ToolCommand，shell=False、start_new_session=True、close_fds=True。
        reporter: 当前作业上报对象，供检查取消/停止和保存真实 returncode。
        log: 当前作业线程安全日志；不另建输出文件或把整份输出留内存。
        clock: UTC 记录时刻与单调期限提供器，不修改全局时钟。

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
    raise NotImplementedError
