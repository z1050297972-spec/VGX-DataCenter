"""重新扫描的启动/间隔提交（领域层，M1-01），与M0每日调度并存，不改其日期语义。

没有新线程或调度依赖：worker主循环每秒调用poll，经JobService提交到同一持久队列。
手动提交仍走JobService.submit及RescanParameters，不共享系统身份入口。
"""

import math
from typing import cast

from rdp.infra.diagnostics import ConflictError, DefectError
from rdp.jobs import _storage
from rdp.jobs.datasets.catalog import RESCAN_INTERVAL_S, RESCAN_TYPE
from rdp.jobs.service import JobService
from rdp.jobs.types import JobClock


class RescanTrigger:
    """每个worker实例私有的扫描触发状态，不是全进程可变单例。"""

    def __init__(self, service: JobService, clock: JobClock) -> None:
        """绑定扫描提交服务与可控时钟，标记首次轮询需要启动扫描。

        Args:
            service: 已登记RESCAN_TYPE的JobService，持有受管数据库。
            clock: worker共享注入时钟，now返回aware时间，monotonic返回有限秒数。

        Returns:
            无；建立独立启动标记和单调累计状态，构造时不提交作业。

        Raises:
            DefectError: 服务缺少扫描登记、依赖类型错误或时钟读数非法。

        Side Effects:
            仅保留实例内状态，不访问导航、存储根，不读默认配置或创建调度线程。

        Time Semantics:
            worker取得单实例锁并完成恢复准备后使用；每次进程启动有一个新触发器。
        """
        if not isinstance(cast(object, service), JobService) or not isinstance(
            cast(object, clock), JobClock
        ):
            raise DefectError()
        if service.registry.lookup(RESCAN_TYPE) is None:
            raise DefectError()
        _storage.moment(clock.now())
        self.service = service
        self.clock = clock
        self._next_at_s: float | None = None
        self._latest_s = _monotonic(clock)

    def poll(self) -> tuple[int, ...]:
        """在首次轮询或距上次提交满十分钟时提交一次全量重新扫描。

        Args:
            无；范围固定全量，时钟及服务来自构造注入。

        Returns:
            成功提交返回单个job_id的元组；未到点或BEGIN短锁忙返回空。
            首次成功提交消耗启动标记并开始600秒周期，不能同轮再补一个定时作业。

        Raises:
            JobInputError: 已登记扫描参数/类型失效，不能静默丢弃触发。
            InputError: 数据库或作业记录损坏。
            ConflictError: 事务入场后的约束/提交竞争；只将BEGIN锁忙作为下轮再试。
            ExternalError: 提交或审计不可恢复I/O失败，交worker主循环停止实例。
            DefectError: 注入时钟非有限值、naive墙钟或服务返回非法编号。

        Side Effects:
            调用JobService.submit_system(RESCAN_TYPE,{dataset_id:None},now=clock.now())，
            提交人是SYSTEM_ACTOR；只有事务成功才更新本实例触发状态。
            主循环忙于恢复/资源不足时仍在完成恢复准备后的每轮检查；不等待前次扫描完成。
            停机错过的多个周期只补一个，不逐周期堆积；新实例启动仍提交一次全量扫描。

        Time Semantics:
            RESCAN_INTERVAL_S=600秒按monotonic累计非负增量，回拨冻结已累计时间直到恢复，
            不延长已累计等待，也不提前触发；UTC墙钟只用于持久化提交时刻。
            599.999秒不提交、600秒提交；短锁忙保留启动/到期状态，下轮重试，不在内部sleep。
        """
        now = _storage.moment(self.clock.now())
        # 回拨只冻结已观察到的单调进度；不重置已积累的等待，也不以UTC墙钟计算间隔。
        now_s = max(self._latest_s, _monotonic(self.clock))
        self._latest_s = now_s
        if self._next_at_s is not None and now_s < self._next_at_s:
            return ()
        try:
            record = self.service.submit_system(RESCAN_TYPE, {"dataset_id": None}, now=now)
        except ConflictError as error:
            if _storage.entry_busy(error):
                return ()
            raise
        # 多个错过周期合并成这一次成功提交；下一期限从本次单调时刻算起，不循环补历史。
        self._next_at_s = now_s + RESCAN_INTERVAL_S
        return (record.job_id,)


def _monotonic(clock: JobClock) -> float:
    """非法注入值是程序缺陷，不能让NaN比较落入到期提交分支。"""
    value = clock.monotonic()
    if type(value) not in {int, float} or not math.isfinite(value):
        raise DefectError()
    return value
