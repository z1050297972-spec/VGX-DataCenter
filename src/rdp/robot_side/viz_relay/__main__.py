"""机器人命令行入口（M5-03/09），保持固定启动协议，不读平台模块或写文件。"""

import argparse
import importlib
import logging
import sys
import time
from contextlib import ExitStack
from pathlib import Path
from typing import NoReturn

from . import _sdk
from ._lifecycle import shutdown_signals
from .config import Config, load_config
from .core import Relay

logger = logging.getLogger(__name__)

# 工单对账周期 0.2 秒；spin 等待取一半，使停止事件及时被主线程观察到。
RECONCILE_INTERVAL_S = 0.2
SPIN_TIMEOUT_S = 0.1
# 工单统计周期，按单调时钟衡量经过时间，不受系统时间校准影响。
REPORT_INTERVAL_S = 60.0


class _Parser(argparse.ArgumentParser):
    """参数错误也走与第 09 张一致的单行错误协议。"""

    def error(self, message: str) -> NoReturn:
        """把 argparse 退出路径转为 config_invalid，由入口统一输出。"""
        raise ValueError(message)


class _StartupError(RuntimeError):
    """只在进程边界携带约定错误码，不创建平台异常依赖。"""

    def __init__(self, code: str, explanation: str) -> None:
        """保留固定代码和不会包含换行或原始配置的中文说明。"""
        super().__init__(explanation)
        self.code = code


def _line(message: str) -> None:
    """及时输出一行协议，不能等待 stdout 缓冲自动刷出。"""
    sys.stdout.write(message + "\n")
    sys.stdout.flush()


def _report(relay: Relay) -> None:
    """每通道一行累计统计，订阅数取报告时刻，不写任何文件。"""
    for channel, counts in relay.statistics().items():
        logger.info(
            "转发统计 channel=%s received=%d forwarded=%d dropped_rate=%d "
            "dropped_timestamp=%d dropped_format=%d subscribers=%d",
            channel,
            counts.received,
            counts.forwarded,
            counts.dropped_rate,
            counts.dropped_timestamp,
            counts.dropped_format,
            counts.subscribers,
        )


def _serve(config: Config) -> None:
    """按相反顺序回收订阅、节点、服务器和通道，部分启动失败也清理。"""
    from ._ros import RosSource

    with shutdown_signals() as stopped, ExitStack() as resources:
        listener = _sdk.Listener(config.routes)
        channels: dict[str, _sdk.OutputChannel] = {}
        try:
            for route in config.routes:
                channel = _sdk.OutputChannel(route, listener)
                resources.callback(channel.close)
                channels[route.channel] = channel
        except Exception as error:
            raise _StartupError("import_failed", "Foxglove 消息接口不可用") from error
        try:
            server = _sdk.start_server(config, listener)
        except Exception as error:
            raise _StartupError("port_in_use", "预览端口无法监听，请检查地址和端口占用") from error
        resources.callback(server.stop)
        try:
            source = RosSource(config.qos_reliability)
            resources.callback(source.close)
            relay = Relay(config.routes, source, channels, time.monotonic_ns)
            resources.callback(relay.close)
            source.add_timer(RECONCILE_INTERVAL_S, relay.reconcile)
        except Exception as error:
            raise _StartupError("ros_init_failed", "ROS 节点或订阅对账定时器初始化失败") from error
        if stopped.is_set():
            return
        _line(f"RDP_VIZ_READY port={config.port}")
        last_report_s = time.monotonic()
        while not stopped.is_set():
            source.spin_once(SPIN_TIMEOUT_S)
            now_s = time.monotonic()
            if now_s - last_report_s >= REPORT_INTERVAL_S:
                _report(relay)
                last_report_s = now_s


def main(argv: list[str] | None = None) -> int:
    """执行配置自检或启动机器人只读转发服务，输出第 09 张约定的单行协议。

    Args:
        argv: 不含程序名的参数列表；None 使用进程参数。必须提供 --config 路径。

    Returns:
        自检成功或收到停止信号返回 0；配置、依赖导入或启动失败返回 2。

    Raises:
        SystemExit: argparse 在 --help 时按标准命令行行为退出 0。

    Side Effects:
        读取配置，写 stdout/stderr；非自检模式建立 ROS 节点和只读 WebSocket，
        退出时回收。程序不写文件；ROS 日志位置由外部 ROS_LOG_DIR 决定。

    Time Semantics:
        自检不建节点、不开端口；服务持续到 SIGINT/SIGTERM，停止期限为 3 秒。
        接收限频用单调纳秒，视频时刻保留源 header，统计每 60 秒输出。
    """
    parser = _Parser(description="R1 Lite 只读预览转发")
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--self-test", action="store_true")
    try:
        args = parser.parse_args(argv)
        config = load_config(Path(args.config))
    except (ValueError, TypeError):
        _line("RDP_VIZ_ERROR config_invalid 配置文件或命令行不符合约定")
        return 2
    try:
        for module in ("foxglove", "rclpy", "sensor_msgs.msg"):
            importlib.import_module(module)
    except (ImportError, OSError):
        _line("RDP_VIZ_ERROR import_failed 无法导入 Foxglove 或 ROS 消息依赖")
        return 2
    if args.self_test:
        _line("RDP_VIZ_SELFTEST ok")
        return 0
    logging.basicConfig(
        level=logging.INFO, stream=sys.stdout, format="%(levelname)s %(name)s %(message)s"
    )
    try:
        _serve(config)
    except _StartupError as error:
        _line(f"RDP_VIZ_ERROR {error.code} {error}")
        logger.exception("转发启动失败 code=%s", error.code)
        return 2
    except Exception:
        _line("RDP_VIZ_ERROR ros_init_failed ROS 转发执行失败")
        logger.exception("转发执行失败，资源已进入清理")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
