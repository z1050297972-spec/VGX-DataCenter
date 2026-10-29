"""包顶层的生产组合入口（11），位于 api/ops 两个互不依赖的入口之上。

只负责提供系统默认依赖和交接退出码；业务分派在 ops.cli，Web 生命周期在 api.production。
使用标准库 argparse/sys 及已批准的 uvicorn，不引入 CLI 或依赖注入框架。
"""

import os
import shutil
import signal
import sys
import time
from collections.abc import Callable, Generator, Sequence
from contextlib import contextmanager, suppress
from datetime import UTC, datetime
from getpass import getpass
from importlib.metadata import version
from pathlib import Path
from threading import current_thread, main_thread
from types import FrameType
from typing import Unpack, override

import uvicorn
from fastapi import FastAPI
from uvicorn.config import STARTUP_FAILURE
from uvicorn.server import HANDLED_SIGNALS

import rdp
from rdp.api.production import UvicornOptions, UvicornRunner, WebRuntime, start_web
from rdp.infra.logging import LogTime
from rdp.infra.storage import LinuxMountSource
from rdp.infra.version import deployment_layout
from rdp.jobs.types import JobClock
from rdp.ops.cli import Console, run_cli
from rdp.ops.lifecycle import stop_signals
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
    inputs = RuntimeInputs(
        dict(os.environ),
        Path.home(),
        deployment_layout(Path(rdp.__file__)),
        JobClock(lambda: datetime.now(UTC), time.monotonic),
        LogTime(),
        Path("/etc/localtime"),
        LinuxMountSource(),
        shutil.which,
        version,
    )
    return run_cli(
        list(sys.argv[1:] if argv is None else argv),
        inputs=inputs,
        console=Console(sys.stdout, sys.stderr, getpass),
        web=lambda runtime: run_web(runtime, inputs=inputs, runner=_run_uvicorn),
        signals=stop_signals,
    )


def run_web(runtime: ServiceRuntime, *, inputs: RuntimeInputs, runner: UvicornRunner) -> int:
    """把公共运行资源转换为 Web 入口的显式依赖并交接生命周期。

    Args:
        runtime: prepare_service 返回的 web 资源，包含真实引擎和完整调度/存储登记。
        inputs: 显式部署布局及 UTC 时钟，不从当前目录查找前端。
        runner: 生产 uvicorn 适配器或测试替身，沿用 UvicornRunner 的日志和单进程约束。

    Returns:
        api.production.start_web 的原样退出码，正常 0、运行或清理失败 1。

    Raises:
        BaseException: Web 入口未处理的进程终止原样传播。

    Side Effects:
        构造 WebRuntime 并交接 engine 所有权；实际监听、报错线程等待和释放由 start_web 负责。
        不二次配置日志、检查数据库或 dispose，不将 worker 的存储内容读取能力传给 Web。
        生产适配器让已处理的 SIGTERM/SIGINT 正常返回，不在 uvicorn 关闭后再次终止进程，
        从而使 start_web 能排空报错写入、释放引擎并记录结束。

    Time Semantics:
        同步调用到服务停止；使用 inputs.clock.now，版本使用 runtime 启动快照。
    """
    web_runtime = WebRuntime(
        inputs.layout.web_dist,
        runtime.loaded.config.web,
        runtime.engine,
        runtime.paths,
        runtime.registry,
        runtime.scheduling,
        runtime.inspector,
        inputs.clock.now,
        runtime.version,
        nav_root=runtime.loaded.config.nav_root,
    )
    return start_web(web_runtime, runner=runner)


def _run_uvicorn(app: FastAPI, **options: Unpack[UvicornOptions]) -> None:
    """运行单进程Server并把优雅停止交还Web生命周期，保留uvicorn的启动失败语义。"""
    server = _ManagedServer(uvicorn.Config(app, **options))
    # 沿用uvicorn.run对事件循环外Ctrl+C的处理；尚未启动仍算启动失败。
    with suppress(KeyboardInterrupt):
        server.run()
    if not server.started:
        raise SystemExit(STARTUP_FAILURE)


class _ManagedServer(uvicorn.Server):
    """由平台拥有进程退出的uvicorn适配器，不更改连接、ASGI或优雅关闭实现。"""

    @contextmanager
    @override
    def capture_signals(self) -> Generator[None]:
        """保留handle_exit及原处理器恢复，只取消已处理信号的关闭后重抛。"""
        # uvicorn 0.54的默认上下文在serve结束后raise_signal，SIGTERM会直接杀死进程，
        # 绕过start_web的报错线程排空和引擎释放。平台必须在它返回后决定退出码。
        # 仍由uvicorn.handle_exit处理退出请求及第二次SIGINT的强制停止；升级uvicorn时
        # 需复核此公开上下文钩子，并运行真实CLI信号测试，不能只靠注入运行器的测试。
        if current_thread() is not main_thread():
            yield
            return
        previous: dict[int, Callable[[int, FrameType | None], object] | int | None] = {}
        try:
            for number in HANDLED_SIGNALS:
                previous[number] = signal.signal(number, self.handle_exit)
            yield
        finally:
            # 安装中途失败也恢复已接管的信号；不修改uvicorn包或全局raise_signal。
            for number, handler in previous.items():
                signal.signal(number, handler)
