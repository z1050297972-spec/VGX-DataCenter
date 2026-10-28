"""包顶层的生产组合入口（11），位于 api/ops 两个互不依赖的入口之上。

只负责提供系统默认依赖和交接退出码；业务分派在 ops.cli，Web 生命周期在 api.production。
使用标准库 argparse/sys 及已批准的 uvicorn，不引入 CLI 或依赖注入框架。
"""

from collections.abc import Sequence

from rdp.api.production import UvicornRunner
from rdp.ops.runtime import RuntimeInputs, ServiceRuntime


def main(argv: Sequence[str] | None = None) -> int:
    """提供 rdp 控制台入口，绑定真实系统依赖并返回最终退出码。

    Args:
        argv: 不含程序名的参数；None 使用 sys.argv[1:]，显式空序列表示没有命令。

    Returns:
        run_cli 的原样退出码；参数错误 2，正常 0，故障 1，活跃作业 3，用户取消 130。
        worker 的锁冲突或失败结果不改写；控制台生成的包装器通过 sys.exit(main()) 结束进程。

    Raises:
        BaseException: run_cli 不处理的进程级终止原样传播。

    Side Effects:
        调用时绑定 os.environ 快照、Path.home、UTC/monotonic、LogTime、LinuxMountSource、
        shutil.which、importlib.metadata.version、getpass 和标准流；导入模块不访问这些资源。
        用 run_web 适配 WebRuntime 后将 Web 回调与 ops.lifecycle.stop_signals 注入 run_cli；
        各命令副作用以 run_cli 为准，帮助不初始化状态或连接数据库。

    Time Semantics:
        系统依赖在调用时绑定；入口只运行一次，返回后由 console script 或 python -m 包装退出。
    """
    raise NotImplementedError


def run_web(runtime: ServiceRuntime, *, inputs: RuntimeInputs, runner: UvicornRunner) -> int:
    """把公共运行资源转换为 Web 入口的显式依赖并交接生命周期。

    Args:
        runtime: prepare_service 返回的 web 资源，包含真实引擎和完整调度/存储登记。
        inputs: 显式部署布局及 UTC 时钟，不从当前目录查找前端。
        runner: uvicorn.run 或测试替身，沿用 UvicornRunner 的日志和单进程约束。

    Returns:
        api.production.start_web 的原样退出码，正常 0、运行或清理失败 1。

    Raises:
        BaseException: Web 入口未处理的进程终止原样传播。

    Side Effects:
        构造 WebRuntime 并交接 engine 所有权；实际监听、报错线程等待和释放由 start_web 负责。
        不二次配置日志、检查数据库或 dispose，不将 worker 的存储内容读取能力传给 Web。

    Time Semantics:
        同步调用到服务停止；使用 inputs.clock.now，版本使用 runtime 启动快照。
    """
    raise NotImplementedError
