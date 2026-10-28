"""Web 报错写入的生命周期边界（05 B3、11），不改变请求侧六秒超时与迟到写入语义。

复用 asyncio.to_thread、threading.Condition；跟踪实际写入完成，而不是已超时的 asyncio 包装。
状态按 app 隔离，不能使用跨应用的全局线程列表。
"""

from collections.abc import Callable

from fastapi import FastAPI


class TrackedReport:
    """一次报错写入的生命周期句柄；保留 asyncio.to_thread 的既有请求等待方式。"""

    def __init__(self, app: FastAPI, write: Callable[[], None]) -> None:
        """在提交线程前登记独立写入，避免关闭时漏掉尚未开始的任务。

        Args:
            app: 已绑定引擎的应用，不允许已进入关闭阶段。
            write: 完整独立 session_scope 写入回调，不携带业务 Session。

        Returns:
            无；得到可交给 asyncio.to_thread(report.run) 的句柄。

        Raises:
            DefectError: 应用已关闭、生命周期状态损坏或 write 不可调用。

        Side Effects:
            仅登记 app 专属待执行任务，不开线程、不写数据库；登记失败不留下半条任务。
            调用方必须在 finally 调用 cancel_if_pending，覆盖调度失败和提前取消。

        Time Semantics:
            登记先于 to_thread 调度；不等待，不在构造时执行回调。
        """
        raise NotImplementedError

    def run(self) -> None:
        """在线程内执行报错写入，并在实际结束时解除生命周期登记。

        Args:
            无；使用构造时绑定的写入回调。

        Returns:
            无；已被 cancel_if_pending 取消的工作不执行写入。

        Raises:
            Exception: 写入回调异常交给已有请求报告边界，不在本层重复记录。
            DefectError: 同一个句柄被重复执行。

        Side Effects:
            原子将待执行转为运行中，然后调用 write；finally 标记完成并唤醒关闭等待者。
            数据库提交/回滚由 write 管理；请求超时不能使运行中的任务提前解除登记。

        Time Semantics:
            同步线程工作，沿用写入约 5 秒锁预算；磁盘永久阻塞不承诺可强制中止。
        """
        raise NotImplementedError

    def cancel_if_pending(self) -> None:
        """回收尚未开始的登记，保持已经运行的写入可被关闭流程观察。

        Args:
            无；针对当前句柄。

        Returns:
            无；未开始时标记取消并解除登记，运行中或已完成时不改变状态。

        Raises:
            DefectError: 生命周期状态损坏。

        Side Effects:
            幂等清理提交失败或等待取消留下的待执行任务；与 run 的启动通过同一锁仲裁。
            不调用线程强杀，不把正在写入或永久阻塞的任务标记为完成。

        Time Semantics:
            调用方在等待结束的 finally 执行；不等待运行中的线程，不延长请求原六秒预算。
        """
        raise NotImplementedError


def drain_error_reports(app: FastAPI, *, timeout_s: float) -> bool:
    """在 Web 停止后限时等待所有已提交报错写入真正结束。

    Args:
        app: 已停止接收请求和后台报告的应用；没有写入任务也允许调用。
        timeout_s: 有限且非负的总预算，单位秒；生产传 10，测试可传 0 检查即时状态。

    Returns:
        没有在途工作或全部结束返回 True，包括写入自身失败但已结束；超时返回 False。
        True 才允许调用方 dispose；重复调用允许继续观察尚未结束的任务。

    Raises:
        DefectError: timeout_s 非有限/负数，或生命周期状态损坏。

    Side Effects:
        关闭新的登记入口并等待已经登记的任务；不接管 asyncio 执行器，不取消正在写入的线程，不关闭数据库。
        超时保留仍运行任务的可观察状态及引擎使用权，不把 asyncio 取消冒充写入完成。

    Time Semantics:
        使用单调时间的一个总截止点，不给每个任务重置预算；不能在事件循环线程里阻塞调用。
        永久磁盘阻塞返回 False，进程最终由 systemd 停止期限处理。
    """
    raise NotImplementedError
