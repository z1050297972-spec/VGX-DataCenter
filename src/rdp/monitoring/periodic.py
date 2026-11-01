"""worker 私有周期监控，不提交作业；用单行序号承接手动请求。"""

import logging
from collections.abc import Callable
from threading import Event

from sqlalchemy import text
from sqlalchemy.engine import Engine

from rdp.jobs.downloads.plan import HttpTransport
from rdp.jobs.types import JobClock
from rdp.monitoring.mirror import MIRROR_CHECK_INTERVAL_S, check_mirror

logger = logging.getLogger(__name__)
# 手动检查请求最多一秒后被周期线程观察到。
MONITOR_POLL_INTERVAL_S = 1.0


class _StoppedError(Exception):
    """停止时从监控线程的检查点退出，不伪造镜像失败。"""


class MirrorMonitor:
    """每个 worker 独立持有检查节拍和外部传输，不占用作业队列。"""

    def __init__(
        self,
        engine: Engine,
        transport: HttpTransport,
        clock: JobClock,
        *,
        collect: Callable[[Callable[[], None]], None],
    ) -> None:
        """绑定周期线程依赖，初始化时不访问网络。

        Args:
            engine: 已迁移数据库。
            transport: 无代理、不跟随跳转的镜像传输。
            clock: worker 的墙钟及单调时钟。
            collect: 资源采集回调，接收取消检查点。

        Returns:
            无。

        Raises:
            无。

        Side Effects:
            仅保存依赖和空节拍，不创建线程。

        Time Semantics:
            首次 tick 即检查，随后按单调时间计时。
        """
        self._engine = engine
        self._transport = transport
        self._clock = clock
        self._collect = collect
        self._next: float | None = None
        self._latest = 0.0

    def tick(self, stop: Event) -> bool:
        """到期或收到手动请求时执行一次检查。

        Args:
            stop: worker 的停止事件，等待时用于中止。

        Returns:
            本轮检查过返回 True，否则返回 False。

        Raises:
            SQLAlchemyError: 数据库读取或更新失败。
            Exception: 停止检查或资源采集失败。

        Side Effects:
            只访问镜像和 worker 资源，覆盖状态表，不创建作业。

        Time Semantics:
            周期为 MIRROR_CHECK_INTERVAL_S；检查期间到达的新请求留待下一轮。
        """
        now = max(self._latest, self._clock.monotonic())
        self._latest = now
        with self._engine.connect() as connection:
            row = connection.execute(
                text("SELECT requested_seq, completed_seq FROM monitoring_mirror WHERE id=1")
            ).first()
        requested = row.requested_seq if row else 0
        pending = row is not None and requested > row.completed_seq
        if self._next is not None and now < self._next and not pending:
            return False

        def checkpoint() -> None:
            if stop.is_set():
                raise _StoppedError()

        def wait(seconds: float) -> None:
            if stop.wait(seconds):
                raise _StoppedError()

        checkpoint()
        check_mirror(self._engine, self._transport, now=self._clock.now(), sleep=wait)
        with self._engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE monitoring_mirror SET completed_seq = max(completed_seq, :seq) WHERE id=1"
                ),
                {"seq": requested},
            )
        self._next = now + MIRROR_CHECK_INTERVAL_S
        checkpoint()
        self._collect(checkpoint)
        return True

    def run(self, stop: Event) -> None:
        """运行周期监控，停止后退出线程。

        Args:
            stop: worker 停止事件。

        Returns:
            无。

        Raises:
            无；单次故障记录日志并在下一轮重试。

        Side Effects:
            周期性访问镜像和资源并写状态表，不创建作业。

        Time Semantics:
            两次轮询间最多等待 MONITOR_POLL_INTERVAL_S，网络超时沿用下载传输上限。
        """
        while not stop.is_set():
            try:
                self.tick(stop)
            except _StoppedError:
                return
            except Exception:
                logger.exception("网络与资源监控失败，下轮重试")
            stop.wait(MONITOR_POLL_INTERVAL_S)
