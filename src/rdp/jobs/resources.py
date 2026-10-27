"""worker 内存资源与展示副本写入（领域层，09）；Web 不能拿本模块的锁。

互斥使用标准库 threading.Lock，数据库使用既有短锁事务；业务 FIFO 和领卡规则没有
符合 ADR 0005 恢复语义的通用队列可替代。资源凭据不持久化，重启从空集合恢复。
"""

from sqlalchemy.orm import Session

from rdp.jobs.scheduling_types import (
    Admission,
    GpuCheck,
    ResourceClaim,
    ResourceDisplay,
    SchedulingSettings,
)


class ResourcePool:
    """一个 worker 的容量与 GPU 所有权；锁只保护内存，不在锁内执行 SQL 或工具。"""

    def __init__(self, settings: SchedulingSettings, *, available_gpus: tuple[int, ...]) -> None:
        """建立空资源池，不导入历史展示占用。

        Args:
            settings: 已冻结配置，含全部配置卡及各类型上限；运行期间不可更改。
            available_gpus: 启动核对通过的卡号升序元组，必填；必须是 settings.gpus 的无重复子集。
                空元组包括配置为空及配置卡全部核对失败，不回退到配置列表。

        Returns:
            无；仅核对通过的卡初始空闲，类型占用为零。

        Raises:
            DefectError: 重复卡号/类型、非法上限、可用卡不是配置子集或不是已校验的配置值对象。

        Side Effects:
            仅建立实例内存和 threading.Lock，不读数据库、不探测显卡。

        Time Semantics:
            在线程启动前构造；每个 worker 一份，进程崩溃后所有名额消失。
        """
        raise NotImplementedError

    def reserve(self, job_id: int, type_name: str) -> Admission:
        """同时预留类型名额和最小编号空闲卡。

        Args:
            job_id: 1 至 2^63-1 正编号，不得已持有凭据。
            type_name: 队列头的类型键；调用方已保证同类 FIFO 和恢复优先。

        Returns:
            类型满返回空 claim、空原因；需卡且所有通过启动核对的卡忙返回空 claim、GPU 原因。
            成功返回唯一凭据；本实例可用卡列表为空仍成功、gpu_index=None，执行器以外部失败结束。
            已删除类型使用全实例唯一的诊断名额、不领卡，交执行器失败收尾，不堵死队列。

        Raises:
            DefectError: 非法编号/键、同一作业重复申请或内存锁超过 RESOURCE_POOL_LOCK_TIMEOUT_S。

        Side Effects:
            成功原子增加本类型计数并标记卡主；失败不占任何资源。
            启动核对失败的卡本实例绝不分配，不提供运行期重新启用入口，修复后须重启再核对。
            领取事务失败、线程启动失败或停止前未启动时，调用方必须 release，不能等下次重启。

        Time Semantics:
            只在主循环调用，不等待其他作业结束；内存短锁内不做 I/O。
        """
        raise NotImplementedError

    def release(self, claim: ResourceClaim) -> None:
        """归还当前凭据的类型名额和卡，防止跨作业释放。

        Args:
            claim: 本池 reserve 返回且尚未释放的原凭据。

        Returns:
            无；卡立即可被下一轮选择，不擦除数据库里的历史卡号。

        Raises:
            DefectError: 凭据不属于本池、重复归还、编号/卡主不一致或内存锁超时。

        Side Effects:
            原子移除一次占用；完成、失败、取消、停止及启动失败都必须在 finally 调用。
            资源仍未回收的执行线程不可提前归还；此时整实例失败并保留 worker 锁直到进程退出。

        Time Semantics:
            先停止本作业外部进程并回收输出线程，再归还；锁预算 RESOURCE_POOL_LOCK_TIMEOUT_S 秒。
        """
        raise NotImplementedError

    def claims(self) -> tuple[ResourceClaim, ...]:
        """取得本实例已领名额，用于调度判断及停止核对。

        Args:
            无。

        Returns:
            按 job_id 升序的冻结凭据元组，空池为空；不暴露内部容器。

        Raises:
            DefectError: 内存锁超时或内部凭据不一致。

        Side Effects:
            无；不替代数据库调度页查询，也不探测外部 GPU 使用者。

        Time Semantics:
            单次快照；只持 RESOURCE_POOL_LOCK_TIMEOUT_S 预算的短锁，不等待占用变化。
        """
        raise NotImplementedError


def save_resource_display(session: Session, job_id: int, display: ResourceDisplay) -> None:
    """在调用方事务内保存等待原因和写锁标记，保留历史卡号。

    Args:
        session: 受管写 Session；周期写使用短锁，终态由 transition_job 直接强制清空。
        job_id: 正作业编号；GPU 等待允许 queued 或尚未重新领卡的恢复 running，写锁等待/持锁只允许 running/cancelling。
        display: 完整最新副本；持锁时等待原因为 None，等待和持锁不能同时为真。

    Returns:
        无；flush 后等待调用方提交。

    Raises:
        JobNotFoundError: 作业编号不存在。
        ConflictError: 已终态、状态已变化或持久化约束冲突，旧副本不能覆盖终态清空。
        InputError: 数据库损坏。
        ExternalError: 更新或 flush 的 I/O 失败。
        DefectError: 非法状态组合、编号、非受管写 Session 或 SQL 映射错误。

    Side Effects:
        只更新两个展示列，不改变 state、outcome、gpu_index，不记操作日志；失败整体回滚。
        主循环是 queued 及恢复待领资源作业 GPU 等待原因的唯一周期写入者；每轮重新判断，
        队首不再因缺卡等待（领到卡、类型达到上限或已取消）必须清掉旧 GPU 原因。
        领取成功在领取事务清空，取消由终态事务清空；不能依赖后续还有进度才清空。
        主循环和 reporter 直接开 PROGRESS_LOCK_TIMEOUT_MS 短事务调用本函数；仅 BEGIN 忙可留到下轮，
        入场后的错误向外传播。reporter 只维护本作业写锁等待/持锁副本，不写 queued 的等待原因。
        发布持锁 True 时，在同一事务清除上一个持有者的过期 True 副本，再设置当前作业，
        防止上个释放短锁忙造成页面同时出现两个持锁者；真正互斥仍由内存 NavigationWriter 保证。

    Time Semantics:
        不取墙钟、不重试；锁预算由外层事务提供。展示允许暂时落后于实际内存资源。
    """
    raise NotImplementedError


def reset_resources_on_startup(session: Session) -> int:
    """在恢复准备之前原子清除上个 worker 的全部瞬时资源副本。

    Args:
        session: 已获得单实例 worker 锁后的受管写 Session，尚未开始任何执行或新队列领取。

    Returns:
        已处理的非终态行数，非负；没有遗留非终态行为零，不改变作业状态。

    Raises:
        ConflictError: 普通事务锁/约束冲突；必须成功才能继续启动，不能短锁跳过。
        InputError: 数据库损坏。
        ExternalError: 清除或 flush I/O 失败，整事务回滚。
        DefectError: 非受管写 Session 或 SQL 映射缺陷。

    Side Effects:
        一个事务清所有 queued/running/cancelling 的 wait_reason 和 holds_navigation_lock，
        同时把 running/cancelling 的 gpu_index 清为 NULL；终态历史卡号保持原值。
        不受类型容量或 GPU 数量限制，不逐条等资源，不增加恢复次数、不写中断段。
        失败阻止启动并在入口报告，不能留下部分清空后还继续调度的实例。

    Time Semantics:
        取得实例锁后、所有 recover_job 调用之前执行一次；普通 BUSY_TIMEOUT_MS 预算，无内部重试。
    """
    raise NotImplementedError


def save_gpu_checks(session: Session, instance_id: str, checks: tuple[GpuCheck, ...]) -> None:
    """保存本实例全部配置卡的启动核对结果，供 Web 查询移出池的卡。

    Args:
        session: 受管写 Session，由持有 worker 单实例锁的启动入口提供。
        instance_id: 本次 uuid4 hex 标识，与随后发布的心跳一致。
        checks: 每张配置卡恰好一条结果，按卡号升序、无重复，最多 MAX_CONFIGURED_GPUS 条；无配置卡为空。

    Returns:
        无；flush 后由调用方提交，既有其他实例的核对行被整体替换。

    Raises:
        ConflictError: 写锁/约束竞争，不得假装已发布正确的卡池。
        InputError: 数据库存量损坏。
        ExternalError: 替换、flush 或提交 I/O 失败，外层回滚。
        DefectError: 非法实例标识、卡号、UTC 时刻、诊断与可用性不一致或 Session 缺陷。

    Side Effects:
        原子替换 worker_gpu_checks 展示行，不修改作业历史卡号；失败保留旧实例快照。
        不记录额外操作日志、不探测硬件；核对失败的 ERROR 只由启动边界写 worker.log。

    Time Semantics:
        核对结果来自注入 UTC 时钟；全部核对完成后、发布新实例首个心跳前提交，普通锁预算。
    """
    raise NotImplementedError
