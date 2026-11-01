"""worker 运维入口（08，第 11 张接命令）；仅装配依赖与最外层启动错误，不实现领域调度。"""

import logging
import os
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from threading import Event, Thread
from typing import cast
from uuid import uuid4

from rdp.infra.db.connection import session_scope
from rdp.infra.db.migration import check_database_version
from rdp.infra.diagnostics import ConflictError, DefectError, ExternalError
from rdp.infra.logging import LoggingSettings, LogTime, configure_logging
from rdp.jobs._clock import ClockReader
from rdp.jobs.execution import ExecutorDependencies
from rdp.jobs.gpu import verify_gpu
from rdp.jobs.navigation import NavigationWriter
from rdp.jobs.policy import (
    WORKER_EXIT_ALREADY_RUNNING,
    WORKER_EXIT_FAILURE,
    WORKER_EXIT_OK,
    WORKER_STOP_TIMEOUT_S,
)
from rdp.jobs.resources import ResourcePool, reset_resources_on_startup, save_gpu_checks
from rdp.jobs.scheduling import WorkerResources, WorkerScheduling
from rdp.jobs.scheduling_types import GpuCheck
from rdp.jobs.types import WorkerHeartbeat
from rdp.jobs.worker import WorkerLoopResult, run_loop, worker_lock

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
    dependencies: ExecutorDependencies,
    stop: Event,
    logging_settings: LoggingSettings,
    *,
    scheduling: WorkerScheduling,
    log_time: LogTime | None = None,
) -> WorkerExit:
    """运行一个可在进程内停止的独立 worker 实例。

    Args:
        dependencies: 入口构造的引擎、production_registry 或测试登记表、已初始化状态布局及注入时钟。
        stop: 必填可注入停止 Event；不在函数内安装全局 signal handler。
        logging_settings: process 必须为 worker、log_dir 为 paths.logs；systemd 下 stderr=False。
        scheduling: 必填关键字，显式资源/定时配置；nvidia_smi 仅在配置卡列表为空时允许 None。
        log_time: configure_logging 使用的时钟和本地日历依赖；None 沿用其系统默认值。
            生产入口与 prepare_service 共用同一对象，测试传固定时钟，不改全局 TZ。

    Returns:
        正常协作停止为 WORKER_EXIT_OK；非阻塞锁冲突为 WORKER_EXIT_ALREADY_RUNNING，
        返回说明和运行日志都含锁路径；其他启动/主循环故障为WORKER_EXIT_FAILURE。
        停止超预算也返回失败而不抛异常；lock_retained标识是否保留锁，不把遗留线程描述为已回收。

    Raises:
        DefectError: 调用依赖非法，或配置卡列表非空但 nvidia_smi 为 None/非绝对路径；
            尚未取得锁或创建线程。停止超时和终态持久化失败不从这里抛出。

    Side Effects:
        复用 configure_logging 写 worker.log，校验迁移版本但不自动迁移；取得 worker_lock 后才恢复/调度。
        验证全部类型覆盖，拿到实例锁后先用一个事务清所有非终态等待/持锁及 running/cancelling 卡号。
        启动逐卡调用 verify_gpu(log=None)，失败卡记一次 ERROR 到 worker.log 并移出本实例名额池，
        通过的卡才交 ResourcePool；修复后须重启重新核对，本实例不再分配被移出的卡。
        原子 save_gpu_checks 保存全部配置卡的核对结果，再发布同 instance_id 的首个心跳，Web 只读数据库。
        全部配置卡失败等同空卡池，需卡作业领取后以“平台没有可用的卡”外部失败，CPU 作业继续。
        构造实例共享 NavigationWriter 并注入 ExecutorDependencies；每次核卡前检查 stop，停止后不继续后续卡。
        依赖/配置非法拒绝启动，不伪装成硬件故障。
        注入定时登记及维护服务，不在启动时清理上个实例的孤儿外部进程。
        创建本实例 uuid4/pid/UTC 启动时刻，调用 run_loop。入口只记录未被作业边界报告的故障，
        同一异常的详细诊断不重复ERROR；锁冲突说明无法启动。日志配置后以INFO记录版本、PID和实例号，
        每个返回结果另记退出码及中文含义，正常为INFO、非零为ERROR；结束记录沿用同一实例号，
        不重复异常堆栈。run_loop返回后调用WorkerLock.finish，
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
    if (
        logging_settings.process != "worker"
        or logging_settings.log_dir != dependencies.paths.logs
        or not dependencies.engine.get_execution_options().get("rdp_managed")
    ):
        raise DefectError()
    _validate_scheduling(scheduling)
    ClockReader(dependencies.clock).read()
    instance_id = uuid4().hex
    try:
        if log_time is None:
            configure_logging(logging_settings)
        else:
            configure_logging(logging_settings, time_source=log_time)
        logger.info(
            "worker开始运行",
            extra={
                "fields": {
                    "platform_version": dependencies.platform_version,
                    "pid": os.getpid(),
                    "instance_id": instance_id,
                }
            },
        )
        check_database_version(dependencies.paths.database)
    except Exception:
        logger.error("worker启动检查失败", exc_info=True)
        return _worker_exit(
            WorkerExit(WORKER_EXIT_FAILURE, "worker启动检查失败", False), instance_id
        )
    try:
        lock = worker_lock(dependencies.paths)
    except ConflictError:
        message = f"另一个 worker 正在运行，锁文件：{dependencies.paths.worker_lock}"
        logger.warning(message)
        return _worker_exit(WorkerExit(WORKER_EXIT_ALREADY_RUNNING, message, False), instance_id)
    except Exception:
        logger.error("worker实例锁无法取得", exc_info=True)
        return _worker_exit(
            WorkerExit(WORKER_EXIT_FAILURE, "worker实例锁无法取得", False), instance_id
        )
    now = dependencies.clock.now()
    heartbeat = WorkerHeartbeat(instance_id, os.getpid(), now, now)
    try:
        with session_scope(dependencies.engine) as session:
            reset_resources_on_startup(session)
        resources = _start_resources(dependencies, scheduling, stop, heartbeat.instance_id)
        if resources is None:
            lock.finish(())
            return _worker_exit(WorkerExit(WORKER_EXIT_OK, "worker已停止", False), instance_id)
        dependencies = replace(dependencies, resources=resources)
    except Exception:
        logger.error("worker资源副本初始化失败，未开始恢复或领取", exc_info=True)
        lock.finish(())
        return _worker_exit(
            WorkerExit(WORKER_EXIT_FAILURE, "worker资源副本初始化失败", False), instance_id
        )
    result = _run_monitored_loop(dependencies, stop, heartbeat, dependencies.monitoring_loop)
    retained = lock.finish(result.unreaped_threads)
    message = "worker已停止" if result.code == WORKER_EXIT_OK else "worker失败退出，需要重启"
    return _worker_exit(WorkerExit(result.code, message, retained), instance_id)


def _run_monitored_loop(
    dependencies: ExecutorDependencies,
    stop: Event,
    heartbeat: WorkerHeartbeat,
    monitor: Callable[[Event], None] | None,
) -> WorkerLoopResult:
    """持锁运行周期监控，退出时有界回收并保留仍存活的线程。"""
    thread: Thread | None = None
    try:
        if monitor is not None and not stop.is_set():
            candidate = Thread(target=monitor, args=(stop,), name="network-monitor", daemon=True)
            candidate.start()
            thread = candidate
        result = run_loop(dependencies, stop, heartbeat)
    except Exception:
        logger.exception("worker 主循环或网络监控启动失败")
        result = WorkerLoopResult(WORKER_EXIT_FAILURE, ())
    finally:
        stop.set()
        if thread is not None:
            thread.join(timeout=WORKER_STOP_TIMEOUT_S)
    if thread is not None and thread.is_alive():
        logger.error("网络监控线程未在停止预算内退出，保留 worker 锁")
        return WorkerLoopResult(WORKER_EXIT_FAILURE, (*result.unreaped_threads, thread))
    return result


def _worker_exit(result: WorkerExit, instance_id: str) -> WorkerExit:
    """统一记录所有返回分支的退出原因，保持退出码和锁保留决定原样交接。"""
    logger.log(
        logging.INFO if result.code == WORKER_EXIT_OK else logging.ERROR,
        "worker结束运行：%s",
        result.message,
        extra={"fields": {"exit_code": result.code, "instance_id": instance_id}},
    )
    return result


def _start_resources(
    dependencies: ExecutorDependencies, scheduling: WorkerScheduling, stop: Event, instance_id: str
) -> WorkerResources | None:
    """核卡在任何数据库事务之外；全部结果发布成功后才让主循环取得新的资源池。"""
    checks: list[GpuCheck] = []
    for index in scheduling.catalog.settings.gpus:
        if stop.is_set():
            return None
        if scheduling.nvidia_smi is None:
            raise DefectError()
        try:
            verify_gpu(index, scheduling.nvidia_smi, log=None)
        except ExternalError as error:
            logger.error("GPU启动核对失败，移出本实例名额池 gpu_index=%d", index, exc_info=True)
            checks.append(GpuCheck(index, False, error.diagnostics, dependencies.clock.now()))
        else:
            checks.append(GpuCheck(index, True, (), dependencies.clock.now()))
    if stop.is_set():
        return None
    with session_scope(dependencies.engine) as session:
        save_gpu_checks(session, instance_id, tuple(checks))
    return WorkerResources(
        scheduling,
        ResourcePool(
            scheduling.catalog.settings,
            available_gpus=tuple(item.gpu_index for item in checks if item.available),
        ),
        NavigationWriter(),
    )


def _validate_scheduling(scheduling: WorkerScheduling) -> None:
    """调用者配置在取得锁和探测硬件之前校验，缺命令不是硬件故障。"""
    if not isinstance(cast(object, scheduling), WorkerScheduling):
        raise DefectError()
    command = scheduling.nvidia_smi
    if command is None:
        if scheduling.catalog.settings.gpus:
            raise DefectError()
    elif not isinstance(cast(object, command), Path) or not command.is_absolute():
        raise DefectError()
