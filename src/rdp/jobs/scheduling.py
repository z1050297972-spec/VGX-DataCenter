"""worker 调度装配与一轮领取（领域层，09）；不含 HTTP，不持有跨线程 Session。

恢复优先、同类 FIFO 属于平台业务，复用 SQLAlchemy 按类型聚合查询和既有提交服务；不引入队列依赖。
"""

from dataclasses import dataclass
from pathlib import Path

from rdp.infra.config import JobsConfig
from rdp.jobs.execution import ExecutionWork, ExecutorDependencies
from rdp.jobs.navigation import NavigationWriter
from rdp.jobs.registry import JobRegistry
from rdp.jobs.resources import ResourcePool
from rdp.jobs.scheduling_types import SchedulingCatalog, SchedulingSettings


@dataclass(frozen=True)
class WorkerScheduling:
    """worker 入口资源配置，不在 Web 构造显卡命令或执行依赖。

    Attributes:
        catalog: 配置、定时登记与本地时区。
        nvidia_smi: 注入的绝对命令路径；只有配置卡列表为空时允许 None，测试用临时假脚本。
        error_retention_days: [errors] retention_days，严格整数 1 至 MAX_RETENTION_DAYS。
    """

    catalog: SchedulingCatalog
    nvidia_smi: Path | None
    error_retention_days: int


@dataclass(frozen=True)
class WorkerResources:
    """当前实例共享的资源对象；入口在拿到 worker 锁后构造。

    Attributes:
        configuration: 本实例最终配置。
        pool: 所有执行线程共用的类型/GPU 名额池。
        navigation: 所有上下文共用的一把写锁。
    """

    configuration: WorkerScheduling
    pool: ResourcePool
    navigation: NavigationWriter


class Scheduler:
    """主循环拥有的按类型队首调度器；资源归还不改变各类型提交顺序。"""

    def __init__(
        self,
        dependencies: ExecutorDependencies,
        resources: WorkerResources,
        *,
        recovered: tuple[ExecutionWork, ...],
    ) -> None:
        """绑定资源及已经完成全部恢复准备的候选。

        Args:
            dependencies: 受管数据库、状态路径、登记表及注入时钟。
            resources: 当前实例共享资源，池中只包含启动核对通过的卡。
            recovered: 所有遗留行已准备完后得到的 resume/restart 候选，claim=None；按 job_id 升序。
                取消/直接中断/隔离失败的行不在此集合，每项恢复资格已经持久化，不再次加次数。

        Returns:
            无；每个恢复候选位于本类型新 queued 之前，同类内部按 job_id 排序。

        Raises:
            DefectError: 依赖非法、恢复候选重复/未准备、带有旧资源凭据或时钟非法。

        Side Effects:
            保存本实例按类型恢复候选及定时启动检查状态，不领取资源、不执行恢复、不启动线程。

        Time Semantics:
            worker 先统一清副本，再不受容量限制完成全部恢复准备，最后构造本对象开始调度。
        """
        raise NotImplementedError

    def claim_next(self) -> ExecutionWork | None:
        """按本类型恢复优先及跨类型 job_id 顺序选择可领取的队首。

        Args:
            无。

        Returns:
            一个已提交资源领取的 ExecutionWork，携带本实例 claim；所有类型均无可领队首时 None。
            GPU 可用集合为空时仍领取需卡作业，由执行器以“平台没有可用的卡”外部失败结束，不无限排队。

        Raises:
            InputError: 查询发现数据库或作业记录损坏。
            ExternalError: 队首查询、领取或日志路径检查 I/O 失败，交主循环停止实例。
            ConflictError: 已入场事务发生非正常竞争；BEGIN 短锁忙或候选被 Web 先取消则归还凭据并返回 None。
            DefectError: 配置、记录、恢复资格或资源凭据不一致。

        Side Effects:
            一条 queued_type_heads 查询按 type_name 聚合 MIN(job_id)，结果按 job_id 升序。
            每类有恢复候选时用其最小 job_id 替换该类 queued 队首，合并后再次按 job_id 排序逐个判断。
            准备后的恢复候选若收到取消，不等名额或卡，先用普通终态事务转已取消并移出候选、清展示；
            不再次调用 recover_job 或增加恢复次数，终态写失败按整实例失败处理，不能永久卡在 cancelling。
            类型上限满则跳过此类；可用卡全部忙时记录 GPU 等待，同类后项不能越过；别类照常领取。
            跨类型抢卡也以此 job_id 顺序，不能因登记顺序或上轮游标让后提交的 B 越过等卡的 A。
            主循环每轮重判所有 queued 队首，旧 GPU 等待在领卡、上限阻挡或取消后清空；
            被恢复队首挡住的 queued 不再标等待 GPU。等待标记不能作为调度资格或跳过查询的依据。
            先 reserve，再短锁事务领取；新 queued 调 claim_job，恢复候选调 assign_recovery_gpu，
            提交成功才启动线程；事务或线程启动失败 finally 归还本次名额。
            可多次查询队首填满类型容量，不扫描同类全部排队行、不维护跨轮游标、批次或排除集合。

        Time Semantics:
            每秒一轮，查询与每次展示/领取写入使用既有短锁预算；无卡/容量等待不在事务内阻塞。
            恢复准备已经完成，资源不足只阻挡本类型的执行资格，不阻挡其他类型或定时检查。
        """
        raise NotImplementedError

    def tick_schedules(self) -> tuple[int, ...]:
        """检查并提交本轮到期或启动需补跑的每日作业。

        Args:
            无。

        Returns:
            新提交 job_id 元组，按登记名字排序；重复日期和未到点不返回编号。

        Raises:
            InputError: 数据库或定时记录损坏。
            ExternalError: 非锁忙的提交/审计 I/O 故障，由主循环失败退出。
            ConflictError: 入场后约束/提交失败，正常重复日期除外。
            DefectError: 注入时钟、登记或提交结果非法。

        Side Effects:
            run_loop 每轮必调用，即使存在等卡/到上限的队首；同一次 clock.now 判断本轮规则。
            经 JobService.submit_scheduled 原子提交作业、系统审计和日期去重行，随后参与普通队首领取。
            BEGIN 忙只跳过本规则，启动补跑标记保留到下轮；成功或正常无资格才完成首次检查。
            当日最多一次，不逐日补历史；清除作业可由当前主循环领取并运行到终态。

        Time Semantics:
            单调时钟驱动每秒调用，UTC 墙钟判断当地日期及严格超过24小时；每规则至多一次短锁等待。
            不因恢复候选未领到资源而停止每日检查，不在事务中计算日历或等待定时点。
        """
        raise NotImplementedError


def resolve_scheduling(config: JobsConfig, registry: JobRegistry) -> SchedulingSettings:
    """校验类型覆盖并冻结最终生效的调度要求。

    Args:
        config: 已解析 jobs 配置；卡号无重复，覆盖上限 1 至 MAX_JOB_CONCURRENCY。
        registry: 完成登记的入口私有对象；每个类型有默认上限及 GPU 要求。

    Returns:
        卡号和类型键分别升序的不可变快照；未覆盖的类型使用声明值，空 GPU 元组原样保留。

    Raises:
        InputError: 覆盖中出现未登记类型，诊断指出 jobs.concurrency 的键，拒绝启动。
        DefectError: 登记声明的上限/GPU 标记非法，或调用依赖不符合约定。

    Side Effects:
        无；不更改输入登记表或配置，也不读取配置文件、数据库或 GPU。

    Time Semantics:
        入口在启动线程和服务请求之前调用；仅本次快照生效，修改配置需要重启。
    """
    raise NotImplementedError
