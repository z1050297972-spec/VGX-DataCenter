"""worker 单实例、心跳和串行调度（08/J1-J3）；不解析 CLI、不包含 Web 类型。

fcntl.flock 管锁生命周期，threading.Thread/Event 管执行与停止，数据库只作短轮询。
主循环不等作业函数返回才写心跳；不引入消息队列或新的调度依赖。
"""

import fcntl
import logging
import os
import stat
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from threading import Event, Thread

from rdp.infra.diagnostics import (
    ConflictError,
    DefectError,
    Diagnostic,
    DiagnosticCategory,
    DiagnosticLevel,
    DiagnosticObject,
    ExternalError,
)
from rdp.infra.state import StatePaths
from rdp.jobs import _storage
from rdp.jobs.execution import ExecutorDependencies
from rdp.jobs.policy import WORKER_OFFLINE_AFTER_S
from rdp.jobs.types import WorkerHeartbeat

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class WorkerLoopResult:
    """主循环已经停止后的资源归属，不让失败变成继续报心跳的半活状态。

    Attributes:
        code: WORKER_EXIT_OK或WORKER_EXIT_FAILURE；不包含单实例锁竞争码。
        unreaped_threads: 预算用尽时仍存活的本实例执行/读输出线程元组，全部daemon；正常退出为空。
            仅包含本实例monitor登记的线程，不枚举或清理调用方的其他线程。
    """

    code: int
    unreaped_threads: tuple[Thread, ...]


class WorkerLock:
    """显式持有原始fd的实例锁，不使用文件对象、with或析构自动释放。"""

    def __init__(self, descriptor: int) -> None:
        """接管已经flock成功且不可继承的原始文件描述符。

        Args:
            descriptor: worker_lock刚获得的非负整数fd，不接受任意调用者文件或bool。

        Returns:
            无；保存整数fd，不创建会在GC时自动close的文件对象。

        Raises:
            DefectError: 非法描述符或锁所有权不满足调用前提。

        Side Effects:
            接管关闭责任；无__del__、weakref.finalize或atexit解锁钩子，不能因对象被回收提前放锁。

        Time Semantics:
            同步接管，无重试和等待；调用者必须最终调用finish明确正常释放或保留到进程退出。
        """
        if type(descriptor) is not int or descriptor < 0:
            raise DefectError()
        try:
            if os.get_inheritable(descriptor) or not stat.S_ISREG(os.fstat(descriptor).st_mode):
                raise DefectError()
        except OSError:
            raise DefectError() from None
        self._descriptor = descriptor
        self._finished = False

    def finish(self, unreaped_threads: tuple[Thread, ...]) -> bool:
        """确认框架线程是否已结束，再释放锁或交操作系统在进程退出时释放。

        Args:
            unreaped_threads: run_loop结果中的全部遗留线程；已停止领取且不再启动线程，调用者不得漏报。

        Returns:
            仍有存活线程时True，锁保持；否则False并关闭fd。确认保留后永久不再主动close该fd，
            即使线程后来退出或WorkerLock对象被GC，也等进程退出再释放。

        Raises:
            ExternalError: 正常释放时close失败；不能误报已解锁。
            DefectError: 非法线程归属或重复处分同一个句柄。

        Side Effects:
            非空存活集合时刻意保留不可继承原始fd，不调用LOCK_UN、不删除锁文件；
            没有存活线程才关闭。保留路径只丢弃Python持有关系，整数fd不会被析构关闭。

        Time Semantics:
            不再join，立即决定归属；失败返回的入口调用者须退出当前进程，不能在此进程重启worker。
        """
        if self._finished or any(not thread.daemon for thread in unreaped_threads):
            raise DefectError()
        self._finished = True
        if any(thread.is_alive() for thread in unreaped_threads):
            # 原始整数fd没有析构动作；故意保留到调用方sys.exit，不能用文件对象包装。
            return True
        try:
            os.close(self._descriptor)
        except OSError as error:
            failure = ExternalError(
                (
                    _lock_diagnostic(
                        Path(f"fd:{self._descriptor}"),
                        "关闭实例锁失败",
                        DiagnosticCategory.EXTERNAL,
                    ),
                )
            )
            raise failure from error
        return False


def worker_lock(paths: StatePaths) -> WorkerLock:
    """非阻塞取得单实例锁并返回显式生命周期句柄。

    Args:
        paths: 显式可信状态布局，worker_lock来自state_paths，不接收客户端路径。

    Returns:
        已fcntl.flock(LOCK_EX|LOCK_NB)成功的WorkerLock；禁止把它包装成无条件释放的上下文管理器。

    Raises:
        ConflictError: 另一个worker正持锁，诊断明确“另一个 worker 正在运行”及锁路径。
        ExternalError: 打开文件或flock的非竞争I/O错误。
        DefectError: 非绝对/越界/软链接锁路径或错误依赖。

    Side Effects:
        用os.open取得不可继承原始fd，不删除/替换inode；申请失败关闭本次fd。
        取得成功后仅WorkerLock.finish能处分：无遗留线程才释放，有遗留线程保留到进程退出。
        外部进程close_fds=True，worker被SIGKILL后孤儿工具不能靠继承fd继续占锁。

    Time Semantics:
        无等待和重试；锁覆盖恢复、调度、收尾以及超预算后的进程剩余寿命。
    """
    path = paths.worker_lock
    if not path.is_absolute() or path != paths.root / "worker.lock" or path.is_symlink():
        raise DefectError()
    descriptor: int | None = None
    try:
        descriptor = os.open(path, os.O_RDWR | os.O_CREAT | os.O_CLOEXEC | os.O_NOFOLLOW, 0o600)
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return WorkerLock(descriptor)
    except BlockingIOError as error:
        if descriptor is not None:
            os.close(descriptor)
        raise ConflictError(
            (_lock_diagnostic(path, "另一个 worker 正在运行", DiagnosticCategory.CONFLICT),)
        ) from error
    except OSError as error:
        if descriptor is not None:
            os.close(descriptor)
        raise ExternalError(
            (_lock_diagnostic(path, "打开或取得实例锁失败", DiagnosticCategory.EXTERNAL),)
        ) from error


def heartbeat_online(heartbeat: WorkerHeartbeat | None, *, now: datetime) -> bool:
    """按跨进程 UTC 心跳判断 worker 在线。

    Args:
        heartbeat: 单行快照，None 表示从未有心跳。
        now: aware 当前时刻，规范化 UTC；注入非法时刻为程序缺陷。

    Returns:
        None 为 False；max(0,now-last_seen_at) 不超过 WORKER_OFFLINE_AFTER_S 为 True，
        严格超过 15 秒为 False；未来心跳按经过零秒判在线，不探测 PID。

    Raises:
        DefectError: 心跳字段或时刻类型/时区非法，UTC 换算溢出。

    Side Effects:
        无；不更新 last_seen_at，不查操作系统进程或获取文件锁。

    Time Semantics:
        UTC 墙钟跨进程比较，不用 monotonic；边界恰好 15 秒在线，回拨不修改原记录。
    """
    moment = _storage.moment(now)
    if heartbeat is None:
        return False
    checked = _storage.heartbeat(heartbeat)
    return max(0.0, (moment - checked.last_seen_at).total_seconds()) <= WORKER_OFFLINE_AFTER_S


def run_loop(
    dependencies: ExecutorDependencies, stop: Event, heartbeat: WorkerHeartbeat
) -> WorkerLoopResult:
    """恢复遗留作业并串行调度，失败时停止心跳、有限收尾并返回失败结果。

    Args:
        dependencies: 当前实例依赖，入口已持单实例锁、检查版本并配置worker.log。
        stop: 注入Event，入口将停止信号转为置位；测试可在当前进程触发。
        heartbeat: 本实例uuid4、pid及UTC启动时刻，不复用旧标识。

    Returns:
        正常停止且全部框架线程已回收为WORKER_EXIT_OK、空线程元组；终态写库失败、全局基础设施故障
        或停止超时均为WORKER_EXIT_FAILURE。超预算仍活的执行/读线程全部列入unreaped_threads，
        不为超时抛异常，不再领取或写心跳，入口据此保留锁并让调用方退出进程。

    Raises:
        DefectError: 调用依赖/初始时钟非法，尚未创建任何线程；运行中的故障统一收尾并返回失败。

    Side Effects:
        启动立即心跳，此后每HEARTBEAT_INTERVAL_S短事务写一次；BEGIN忙只WARNING并下周期重试。
        旧running/cancelling按job_id的有界keyset逐条recover_job；单条损坏/日志失败只处理该编号，
        能落终态就落，不能则ERROR并跳过，本实例不再扫描它；随后恢复其他条并放行新queued。
        不能枚举队列等全局基础设施故障、已执行作业终态无法提交、执行线程结束后仍有未回收输出资源，
        都走整实例失败退出；不能因主执行线程已死就忽略monitor中的daemon读线程并领取下一作业。
        每个作业建立ExecutionMonitor；执行Thread在start前登记且daemon=True，读输出线程同样登记为daemon。
        每轮查当前状态；首次观察cancelling用monotonic起算，超过CANCEL_STALL_WARNING_S=60秒仍未退出，
        在边界记一次WARNING并通过monitor.reporter向作业日志写统一诊断（编号、阶段、已等时长、后果、下一步），
        不增加业务警告计数、不改变状态。先置一次性标记，后续轮询不重复；日志失败只补安全报告，不替代原取消。
        空闲时只读next_queued_job，关闭读事务后claim_job，提交含日志路径的领取事务再启动线程；
        同时最多WORKER_CONCURRENCY=1个执行线程，所有线程独立Session。
        stop或执行器终态写失败后立即停止领取和心跳、通知stopping，30秒共同预算内join全部登记线程。
        执行器已报告的持久化失败不重复ERROR；超预算另记一次停止超时ERROR，返回存活线程，不能先放锁。
        不清空历史心跳；失败结果由入口交给第11张命令退出，systemd重启后再走恢复，禁止半活空转。

    Time Semantics:
        单调时钟驱动1秒主轮询、5秒心跳、60秒取消警告和WORKER_STOP_TIMEOUT_S=30秒收尾，
        run_loop的每次join只用同一截止的剩余时间；执行器TERM10秒、reap2秒、输出join2秒和DB5秒预算不能延长主循环30秒截止。
        单条恢复失败有界尝试终态一次后跳过，无无限重试；恢复执行也在线程，不阻塞主循环心跳。
    """
    from rdp.jobs._loop import Loop

    checked = _storage.heartbeat(heartbeat)
    if not dependencies.engine.get_execution_options().get("rdp_managed"):
        raise DefectError()
    return Loop(dependencies, stop, checked).run()


def _lock_diagnostic(path: Path, actual: str, category: DiagnosticCategory) -> Diagnostic:
    """锁竞争和I/O失败各自分类，安全说明包含实际锁路径。"""
    return Diagnostic(
        level=DiagnosticLevel.ERROR,
        category=category,
        stage="worker启动",
        source="平台",
        objects=(DiagnosticObject(key="lock_path", value=str(path)),),
        rule="同一状态目录只允许一个worker",
        actual=actual,
        expected="独占状态目录的worker锁",
        consequence="本实例未启动或未完整释放锁",
        next_step="确认已有worker状态，检查锁文件路径和权限",
    )
