"""重新扫描的启动提交（领域层，M1.5-14），与M0每日调度并存，不改其日期语义。

没有新线程或调度依赖：worker主循环每秒调用poll，经JobService提交到同一持久队列。
手动提交仍走JobService.submit及RescanParameters，不共享系统身份入口。
"""

from typing import cast

from rdp.infra.diagnostics import ConflictError, DefectError
from rdp.jobs import _storage
from rdp.jobs.datasets.catalog import RESCAN_TYPE
from rdp.jobs.service import JobService
from rdp.jobs.types import JobClock


class RescanTrigger:
    """每个worker实例私有的扫描触发状态，不是全进程可变单例。"""

    def __init__(self, service: JobService, clock: JobClock) -> None:
        """绑定扫描提交服务与可控时钟，标记首次轮询需要启动扫描。

        Args:
            service: 已登记RESCAN_TYPE的JobService，持有受管数据库。
            clock: worker共享注入时钟，now返回带时区时间；不使用monotonic计算扫描周期。

        Returns:
            无；建立独立启动标记，构造时不提交作业。

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
        self._submitted = False

    def poll(self) -> tuple[int, ...]:
        """在首次成功轮询时提交一次全量重新扫描。

        Args:
            无；范围固定全量，时钟及服务来自构造注入。

        Returns:
            成功提交返回单个job_id的元组；已提交或BEGIN短锁忙返回空。
            首次成功提交消耗启动标记，本实例后续不再提交。

        Raises:
            JobInputError: 已登记扫描参数/类型失效，不能静默丢弃触发。
            InputError: 数据库或作业记录损坏。
            ConflictError: 事务入场后的约束/提交竞争；只将BEGIN锁忙作为下轮再试。
            ExternalError: 提交或审计不可恢复I/O失败，交worker主循环停止实例。
            DefectError: 注入墙钟不带时区或服务返回非法编号。

        Side Effects:
            调用JobService.submit_system(RESCAN_TYPE,{dataset_id:None},now=clock.now())，
            提交人是SYSTEM_ACTOR；只有事务成功才更新本实例触发状态。
            主循环完成恢复准备后尝试提交；新实例启动仍提交一次全量扫描。

        Time Semantics:
            UTC墙钟只用于持久化提交时刻，不按经过时长触发。
            短锁忙保留启动状态，下轮重试，不在内部sleep。
        """
        if self._submitted:
            return ()
        now = _storage.moment(self.clock.now())
        try:
            record = self.service.submit_system(RESCAN_TYPE, {"dataset_id": None}, now=now)
        except ConflictError as error:
            if _storage.entry_busy(error):
                return ()
            raise
        # 只有持久化成功才消耗启动标记，短锁忙或事务失败仍可在下一轮重试。
        self._submitted = True
        return (record.job_id,)
