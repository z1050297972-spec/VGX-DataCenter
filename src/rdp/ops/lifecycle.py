"""worker 进程生命周期装配（11、ADR 0005），不实现作业循环或自行杀外部工具。

信号复用 signal 与 threading.Event；恢复原处理器，测试使用注入上下文而不影响测试进程。
"""

from collections.abc import Callable
from contextlib import AbstractContextManager
from threading import Event

from rdp.ops.runtime import RuntimeInputs, ServiceRuntime


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
    raise NotImplementedError


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
    raise NotImplementedError
