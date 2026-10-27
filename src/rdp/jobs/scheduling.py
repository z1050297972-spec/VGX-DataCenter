"""worker 调度装配与一轮领取（领域层，09）；不含 HTTP，不持有跨线程 Session。

恢复优先、同类 FIFO 属于平台业务，复用 SQLAlchemy 按类型聚合查询和既有提交服务；不引入队列依赖。
"""

import logging
from dataclasses import dataclass, replace
from pathlib import Path
from typing import cast

from pydantic import ValidationError

from rdp.infra.config import JobsConfig
from rdp.infra.db.connection import session_scope, session_scope_with_lock_timeout
from rdp.infra.db.validation import invalid_field
from rdp.infra.diagnostics import ConflictError, DefectError
from rdp.jobs import _storage, policy
from rdp.jobs._clock import ClockReader
from rdp.jobs.execution import ExecutionWork, ExecutorDependencies
from rdp.jobs.logs import JobLogMetadata, open_job_log
from rdp.jobs.navigation import NavigationWriter
from rdp.jobs.records import (
    StateChange,
    assign_recovery_gpu,
    claim_job,
    find_job,
    queued_type_heads,
    transition_job,
)
from rdp.jobs.registry import JobRegistry
from rdp.jobs.resources import ResourcePool, save_resource_display
from rdp.jobs.schedule_records import latest_submission
from rdp.jobs.schedules import schedule_due
from rdp.jobs.scheduling_types import (
    ResourceClaim,
    ResourceDisplay,
    SchedulingCatalog,
    SchedulingSettings,
    TypeCapacity,
)
from rdp.jobs.service import JobService
from rdp.jobs.types import ExecutionMode, JobRecord, JobState, WaitReason

logger = logging.getLogger(__name__)


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
        if not isinstance(cast(object, dependencies), ExecutorDependencies) or not isinstance(
            cast(object, resources), WorkerResources
        ):
            raise DefectError()
        if not dependencies.engine.get_execution_options().get("rdp_managed"):
            raise DefectError()
        ClockReader(dependencies.clock).read()
        _validate_recovered(recovered)
        self.dependencies = dependencies
        self.resources = resources
        self._recovered = {item.record.job_id: item for item in recovered}
        self._startup_pending = {
            item.name for item in resources.configuration.catalog.schedules.definitions()
        }

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
            取消终态已提交后，作业日志摘要失败只记一次带 job_id 的 ERROR，继续领取其他作业。
            类型上限满则跳过此类；可用卡全部忙时记录 GPU 等待，同类后项不能越过；别类照常领取。
            跨类型抢卡也以此 job_id 顺序，不能因登记顺序或上轮游标让后提交的 B 越过等卡的 A。
            同轮已有队首等卡时，后续需卡队首不再领取途中归还的卡；不需卡的类型照常领取。
            主循环每轮重判所有 queued 队首，旧 GPU 等待在领卡、上限阻挡或取消后清空；
            被恢复队首挡住的 queued 不再标等待 GPU。等待标记不能作为调度资格或跳过查询的依据。
            先 reserve，再短锁事务领取；新 queued 调 claim_job，恢复候选调 assign_recovery_gpu，
            提交成功才启动线程；领取事务失败 finally 归还本次名额。
            提交后若停止或线程未能启动，由主循环短事务退回本实例未启动领取并归还名额，退回失败停止实例。
            可多次查询队首填满类型容量，不扫描同类全部排队行、不维护跨轮游标、批次或排除集合。

        Time Semantics:
            每秒一轮，查询与每次展示/领取写入使用既有短锁预算；无卡/容量等待不在事务内阻塞。
            恢复准备已经完成，资源不足只阻挡本类型的执行资格，不阻挡其他类型或定时检查。
        """
        capacities = {
            item.type_name: item for item in self.resources.configuration.catalog.settings.types
        }
        gpu_waiting = False
        for candidate in self._heads():
            capacity = capacities.get(candidate.type_name)
            if gpu_waiting and capacity is not None and capacity.requires_gpu:
                # 卡可能在扫描途中归还；本轮为更早的需卡队首保留优先权，CPU类型仍继续判断。
                running = sum(
                    item.type_name == candidate.type_name for item in self.resources.pool.claims()
                )
                self._display(
                    candidate, None if running >= capacity.concurrency else WaitReason.GPU
                )
                continue
            admission = self.resources.pool.reserve(candidate.job_id, candidate.type_name)
            if admission.claim is not None:
                return self._claim(candidate, admission.claim)
            self._display(candidate, admission.wait_reason)
            if admission.wait_reason is WaitReason.GPU:
                gpu_waiting = True
        return None

    def _heads(self) -> tuple[JobRecord, ...]:
        """恢复只替换同类型队首；先关闭读事务，再收尾取消或发布排队展示。"""
        cancelling: list[int] = []
        # 复用受管连接的局部预算选项，BEGIN前生效，不修改父引擎或已有连接。
        reader = self.dependencies.engine.execution_options(
            rdp_lock_timeout_ms=policy.PROGRESS_LOCK_TIMEOUT_MS
        )
        with session_scope(reader, read_only=True) as session:
            queued = {record.type_name: record for record in queued_type_heads(session)}
            recovering: dict[str, JobRecord] = {}
            for number in sorted(self._recovered):
                record = find_job(session, number)
                if record.state is JobState.CANCELLING:
                    cancelling.append(number)
                elif record.state is JobState.RUNNING:
                    recovering.setdefault(record.type_name, record)
                else:
                    self._recovered.pop(number)
        for number in cancelling:
            self._cancel_recovered(number)
        for name in recovering:
            if name in queued:
                self._display(queued[name], None)
        return tuple(sorted((queued | recovering).values(), key=lambda record: record.job_id))

    def _cancel_recovered(self, number: int) -> None:
        """待领资源的取消不等卡；终态提交后移出候选，日志摘要失败仅报告，不停止后续领取。"""
        with session_scope(self.dependencies.engine) as session:
            record = find_job(session, number)
            if record.state is JobState.CANCELLING:
                record = transition_job(
                    session,
                    number,
                    StateChange(record.state, JobState.CANCELLED, self.dependencies.clock.now()),
                )
        self._recovered.pop(number, None)
        if record.summary is not None:
            try:
                log, needs_header = open_job_log(self.dependencies.paths, record)
                try:
                    if needs_header:
                        log.write_header(record, JobLogMetadata(None, None, None))
                    log.write_summary(record.summary, now=self.dependencies.clock.now())
                finally:
                    log.close()
            except Exception:
                logger.error(
                    "作业已提交取消终态，但日志结尾写入失败 job_id=%s", number, exc_info=True
                )

    def _display(self, candidate: JobRecord, reason: WaitReason | None) -> None:
        """主循环重算排队展示；入场忙可跳过，已入场故障不能当成竞争成功。"""
        if candidate.wait_reason is reason and not candidate.holds_navigation_lock:
            return
        entered = False
        try:
            with session_scope_with_lock_timeout(
                self.dependencies.engine, busy_timeout_ms=policy.PROGRESS_LOCK_TIMEOUT_MS
            ) as session:
                entered = True
                current = find_job(session, candidate.job_id)
                if current.state not in {JobState.QUEUED, JobState.RUNNING}:
                    return
                save_resource_display(session, candidate.job_id, ResourceDisplay(reason, False))
        except ConflictError as error:
            if not entered and _storage.entry_busy(error):
                return
            raise

    def _claim(self, candidate: JobRecord, claim: ResourceClaim) -> ExecutionWork | None:
        """凭据在提交前归本调用，失败归还；恢复资格只在成功提交后移出待领集合。"""
        committed = entered = False
        previous = self._recovered.get(candidate.job_id)
        try:
            try:
                with session_scope_with_lock_timeout(
                    self.dependencies.engine, busy_timeout_ms=policy.PROGRESS_LOCK_TIMEOUT_MS
                ) as session:
                    entered = True
                    current = find_job(session, candidate.job_id)
                    if current.state in {JobState.CANCELLED, JobState.CANCELLING}:
                        return None
                    if previous is None:
                        record = claim_job(
                            session,
                            candidate.job_id,
                            now=self.dependencies.clock.now(),
                            paths=self.dependencies.paths,
                            gpu_index=claim.gpu_index,
                        )
                        work = ExecutionWork(record, ExecutionMode.FRESH, None, claim=claim)
                    else:
                        record = assign_recovery_gpu(session, candidate.job_id, claim.gpu_index)
                        work = replace(previous, record=record, claim=claim)
                committed = True
                self._recovered.pop(candidate.job_id, None)
                return work
            except ConflictError as error:
                if not entered and _storage.entry_busy(error):
                    return None
                raise
        finally:
            if not committed:
                self.resources.pool.release(claim)

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
        catalog = self.resources.configuration.catalog
        definitions = catalog.schedules.definitions()
        if not definitions:
            return ()
        now = _storage.moment(self.dependencies.clock.now())
        service = JobService(self.dependencies.engine, self.dependencies.registry)
        submitted: list[int] = []
        # 读快照不等待锁，唯一可能等待的是提交服务的短写锁；不在事务内算日历。
        reader = self.dependencies.engine.execution_options(rdp_lock_timeout_ms=0)
        for definition in definitions:
            try:
                with session_scope(reader, read_only=True) as session:
                    previous = latest_submission(session, definition.name)
                day = schedule_due(
                    definition,
                    previous,
                    now=now,
                    zone=catalog.timezone,
                    startup=definition.name in self._startup_pending,
                )
                result = None if day is None else service.submit_scheduled(definition, day, now=now)
            except ConflictError as error:
                if _storage.entry_busy(error):
                    continue
                raise
            self._startup_pending.discard(definition.name)
            if result is not None:
                submitted.append(result.job_id)
        return tuple(submitted)


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
    if not isinstance(cast(object, config), JobsConfig) or not isinstance(
        cast(object, registry), JobRegistry
    ):
        raise DefectError()
    try:
        checked = JobsConfig.model_validate(config.model_dump())
    except ValidationError as error:
        raise DefectError() from error
    definitions = registry.definitions()
    names = {definition.type_name for definition in definitions}
    for name in checked.concurrency:
        if name not in names:
            failure = invalid_field(f"jobs.concurrency.{name}", "已经登记的作业类型")
            raise failure
    # 再验定义，避免入口传入受损登记；只复制标量到不可变快照，不共享配置字典。
    validated = JobRegistry()
    for definition in definitions:
        validated.register(definition)
    return SchedulingSettings(
        tuple(sorted(checked.gpus)),
        tuple(
            TypeCapacity(
                item.type_name,
                item.display_name,
                checked.concurrency.get(item.type_name, item.concurrency),
                item.requires_gpu,
            )
            for item in definitions
        ),
    )


def _validate_recovered(recovered: tuple[ExecutionWork, ...]) -> None:
    """准备结果必须尚未领资源且只消费过一次本次恢复资格，不能悄悄去重丢掉输入。"""
    if type(recovered) is not tuple:
        raise DefectError()
    numbers: list[int] = []
    for work in recovered:
        if not isinstance(cast(object, work), ExecutionWork):
            raise DefectError()
        _storage.identifier(work.record.job_id, internal=True)
        if work.claim is not None or work.mode not in {ExecutionMode.RESUME, ExecutionMode.RESTART}:
            raise DefectError()
        if (
            work.record.state is not JobState.RUNNING
            or not 1 <= work.record.recovery_count <= policy.JOB_RECOVERY_LIMIT
        ):
            raise DefectError()
        numbers.append(work.record.job_id)
    if numbers != sorted(set(numbers)):
        raise DefectError()
