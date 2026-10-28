"""worker 进程生命周期装配（11、ADR 0005），不实现作业循环或自行杀外部工具。

信号复用 signal 与 threading.Event；恢复原处理器，测试使用注入上下文而不影响测试进程。
"""

import signal
from collections.abc import Callable, Generator
from contextlib import AbstractContextManager, contextmanager
from threading import Event, current_thread, main_thread
from types import FrameType

from rdp.infra.diagnostics import DefectError
from rdp.infra.storage import StorageAccessChecker, read_storage_root
from rdp.jobs.execution import ExecutorDependencies
from rdp.jobs.scheduling import WorkerScheduling
from rdp.ops.runtime import RuntimeInputs, ServiceRuntime, resolve_nvidia_smi
from rdp.ops.worker import run_worker


def stop_signals(stop: Event) -> AbstractContextManager[None]:
    """在主线程临时安装 SIGTERM/SIGINT 到停止事件的映射。

    Args:
        stop: 本次 worker 专用 Event；进入时不清空已设置状态。

    Returns:
        上下文管理器；进入安装两个处理器，退出恢复进入前的两个处理器。

    Raises:
        DefectError: 非主线程调用，或处理器安装/恢复失败。

    Side Effects:
        只改当前进程两个信号处理器，处理器仅 stop.set，不做日志、数据库或等待。
        部分安装失败也恢复已替换的处理器；不终止其他进程。

    Time Semantics:
        在 run_worker 前安装，重复信号幂等；具体退出期限由 worker 和 systemd 负责。
    """
    return _signal_context(stop)


def start_worker(
    runtime: ServiceRuntime,
    *,
    inputs: RuntimeInputs,
    signals: Callable[[Event], AbstractContextManager[None]],
) -> int:
    """装配存储与调度并执行一个 worker，将结果原样交给进程入口。

    Args:
        runtime: worker 的公共资源；本函数接管 engine 释放责任。
        inputs: 时钟、nvidia-smi 查找及日志时钟依赖。
        signals: 停止信号上下文工厂；测试不安装真实处理器。

    Returns:
        run_worker 返回的 result.code，不因锁冲突、停止超时或失败改成 0。

    Raises:
        InputError: 配了 GPU 却无法找到绝对 nvidia-smi 路径。
        ExternalError: 命令定位文件系统故障。
        DefectError: 依赖或回调不合法，或信号安装/恢复失败。

    Side Effects:
        构造 StorageAccessChecker(runtime.inspector, config.storage, read_storage_root)，
        注入 ExecutorDependencies(storage=..., platform_version=runtime.version)。
        WorkerScheduling 使用公共 catalog、resolve_nvidia_smi 结果及 config.errors.retention_days。
        用注入日志时钟调用 run_worker；SIGTERM/SIGINT 只设置独立 Event。
        result.lock_retained=False 或启动前失败时释放引擎；True 时保留引擎和锁到进程退出，
        调用方必须立即 sys.exit(result.code)，不重新运行 worker、不删除锁文件。

    Time Semantics:
        配置完成后才安装信号并执行；停止总预算沿用 30 秒，外部工具宽限沿用 10 秒。
        不额外等待遗留执行线程，不绕过 worker 的锁保留语义。
    """
    retained = False
    try:
        config = runtime.loaded.config
        scheduling = WorkerScheduling(
            runtime.scheduling,
            resolve_nvidia_smi(inputs, gpus=config.jobs.gpus),
            config.errors.retention_days,
        )
        storage = StorageAccessChecker(runtime.inspector, config.storage, read_storage_root)
        dependencies = ExecutorDependencies(
            runtime.engine,
            runtime.registry,
            runtime.paths,
            inputs.clock,
            resources=None,
            storage=storage,
            platform_version=runtime.version,
        )
        stop = Event()
        with signals(stop):
            result = run_worker(
                dependencies, stop, runtime.logging, scheduling=scheduling, log_time=inputs.log_time
            )
            # 即使信号恢复抛错，也不能dispose仍有线程使用的引擎。
            retained = result.lock_retained
        return result.code
    finally:
        if not retained:
            runtime.engine.dispose()


@contextmanager
def _signal_context(stop: Event) -> Generator[None]:
    """只在主线程接管信号；部分安装失败也逐项恢复已经替换的处理器。"""
    if current_thread() is not main_thread():
        raise DefectError
    previous: list[tuple[int, Callable[[int, FrameType | None], object] | int | None]] = []

    def requested(_number: int, _frame: FrameType | None) -> None:
        stop.set()

    try:
        try:
            for number in (signal.SIGTERM, signal.SIGINT):
                old = signal.getsignal(number)
                signal.signal(number, requested)
                previous.append((number, old))
        except Exception as error:
            raise DefectError from error
        yield
    finally:
        failure: Exception | None = None
        for number, old in reversed(previous):
            try:
                signal.signal(number, old)
            except Exception as error:
                failure = error
        if failure is not None:
            raise DefectError from failure
