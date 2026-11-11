"""rclpy 适配边界（M5-03），只订阅不发布，生命周期仅由主线程控制。"""

# 工作站未安装 ROS；豁免只覆盖此系统边界，标准库转发器不豁免。
# pyright: reportMissingImports=false
# rclpy 和消息包未安装，导入的符号类型无法推导。
# pyright: reportUnknownVariableType=false
# ROS 成员的签名在工作站不可解析。
# pyright: reportUnknownMemberType=false
# ROS 创建的 Context、Node、QoS 传参类型在工作站不可解析。
# pyright: reportUnknownArgumentType=false

from collections.abc import Callable
from contextlib import ExitStack

import rclpy
from rclpy.context import Context
from rclpy.executors import SingleThreadedExecutor
from rclpy.qos import HistoryPolicy, QoSProfile, ReliabilityPolicy
from rclpy.signals import SignalHandlerOptions
from sensor_msgs.msg import CompressedImage, JointState

from .config import IMAGE_TYPE, Route


class RosSource:
    """可被录制回放源替换的原始 CDR 订阅源。"""

    def __init__(self, reliability: str) -> None:
        """创建独立上下文与单线程执行器；部分初始化失败也释放已创建资源。"""
        self._reliability = reliability
        self._context = Context()
        with ExitStack() as resources:
            resources.callback(self._context.try_shutdown)
            # 由入口统一处理 SIGINT/SIGTERM，避免 rclpy 抢先关闭导致清理次序失控。
            rclpy.init(
                args=[], context=self._context, signal_handler_options=SignalHandlerOptions.NO
            )
            self._node = rclpy.create_node("rdp_viz_relay", context=self._context)
            resources.callback(self._node.destroy_node)
            self._executor = SingleThreadedExecutor(context=self._context)
            resources.callback(self._executor.shutdown, timeout_sec=0.0)
            self._executor.add_node(self._node)
            self._resources = resources.pop_all()

    def subscribe(self, route: Route, callback: Callable[[bytes], None]) -> object:
        """创建 raw=True 的 KEEP_LAST 订阅；相机深度 2，关节深度 10（工单）。"""
        qos = QoSProfile(
            history=HistoryPolicy.KEEP_LAST,
            depth=2 if route.source_type == IMAGE_TYPE else 10,
            reliability=(
                ReliabilityPolicy.BEST_EFFORT
                if self._reliability == "best_effort"
                else ReliabilityPolicy.RELIABLE
            ),
        )
        return self._node.create_subscription(
            CompressedImage if route.source_type == IMAGE_TYPE else JointState,
            route.source_topic,
            callback,
            qos,
            raw=True,
        )

    def unsubscribe(self, subscription: object) -> None:
        """执行器线程销毁订阅，不在 SDK 回调线程调用。"""
        self._node.destroy_subscription(subscription)

    def add_timer(self, interval_s: float, callback: Callable[[], None]) -> None:
        """由节点持有定时器，和消息回调串行执行，销毁节点时一并回收。"""
        self._node.create_timer(interval_s, callback)

    def spin_once(self, timeout_s: float) -> None:
        """最多等待 timeout_s 秒取一个回调，不创建后台执行器线程。"""
        self._executor.spin_once(timeout_sec=timeout_s)

    def close(self) -> None:
        """停止执行器后销毁节点、关闭上下文；构造失败的资源由构造期自动回收。"""
        self._resources.close()
