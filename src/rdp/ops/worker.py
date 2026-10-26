"""worker 运维入口（08，第 11 张接命令）；仅装配依赖与最外层启动错误，不实现领域调度。"""

import logging
from dataclasses import dataclass
from threading import Event

from rdp.infra.logging import LoggingSettings
from rdp.jobs.execution import ExecutorDependencies

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class WorkerExit:
    """给命令或测试使用的入口结果，不以异常消息拼接退出信息。

    Attributes:
        code: WORKER_EXIT_OK/WORKER_EXIT_FAILURE/WORKER_EXIT_ALREADY_RUNNING。
        message: 固定中文说明；锁冲突含“另一个 worker 正在运行”和实际锁路径，无秘密。
        lock_retained: True表示遗留daemon线程尚存，原始fd保留到进程退出；调用者必须以code退出进程。
    """

    code: int
    message: str
    lock_retained: bool


def run_worker(
    dependencies: ExecutorDependencies, stop: Event, logging_settings: LoggingSettings
) -> WorkerExit:
    """运行一个可在进程内停止的独立 worker 实例。

    Args:
        dependencies: 入口构造的引擎、production_registry 或测试登记表、已初始化状态布局及注入时钟。
        stop: 必填可注入停止 Event；不在函数内安装全局 signal handler。
        logging_settings: process 必须为 worker、log_dir 为 paths.logs；systemd 下 stderr=False。

    Returns:
        正常协作停止为 WORKER_EXIT_OK；非阻塞锁冲突为 WORKER_EXIT_ALREADY_RUNNING，
        返回说明和运行日志都含锁路径；其他启动/主循环故障为WORKER_EXIT_FAILURE。
        停止超预算也返回失败而不抛异常；lock_retained标识是否保留锁，不把遗留线程描述为已回收。

    Raises:
        DefectError: 调用依赖非法，尚未取得锁或创建线程；停止超时和终态持久化失败不从这里抛出。

    Side Effects:
        复用 configure_logging 写 worker.log，校验迁移版本但不自动迁移；取得 worker_lock 后才恢复/调度。
        创建本实例 uuid4/pid/UTC 启动时刻，调用 run_loop。入口只记录未被作业边界报告的故障，
        同一异常不重复ERROR；锁冲突只说明无法启动。run_loop返回后调用WorkerLock.finish，
        所有框架线程均死才关闭原始fd；只要执行线程或读线程还活着就保留fd到进程退出，
        不使用with/finally无条件解锁，也不注册GC/atexit自动关闭。线程均daemon，故不阻止调用方退出。
        失败返回后不写心跳、不重新运行worker；第11张命令必须sys.exit(result.code)，由systemd重启。
        单条恢复失败已在恢复边界隔离，不导致整实例退出；终态写库失败则统一失败收尾。
        不 dispose 调用者引擎，不读取默认 home 配置，不安装包、不访问导航层或存储根。

    Time Semantics:
        进程内停止不等业务跑完；正常停止总预算 30 秒，普通数据库单次锁 5 秒，
        时钟注入非法归DefectError；外部进程取消宽限10秒，全部时长用monotonic。
        第11张systemd服务须KillMode=control-group、TimeoutStopSec>=WORKER_STOP_TIMEOUT_S（30秒），
        以结束worker被SIGKILL后继续运行的孤儿工具；测试由临时夹具清理，不靠worker持锁描述符杀子进程。
    """
    raise NotImplementedError
