"""作业执行器最外层边界（08、规范 6.3）；唯一收口执行异常，不拥有 worker 主循环。

线程执行使用 contextvars.copy_context 与 infra.logging.log_context 关联作业编号。
终态普通事务先保存最新进度，再经过 records.transition_job；禁止执行函数设置状态或结果。
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import BaseModel, ValidationError
from sqlalchemy import Engine

from rdp.infra.db.connection import session_scope
from rdp.infra.db.records import ErrorRecord, write_error
from rdp.infra.diagnostics import (
    ConflictError,
    DefectError,
    Diagnostic,
    DiagnosticCategory,
    DiagnosticLevel,
    DiagnosticObject,
    ExternalError,
    InputError,
)
from rdp.infra.exception_report import format_exception_report
from rdp.infra.logging import log_context
from rdp.infra.state import StatePaths
from rdp.infra.storage import StorageAccessChecker
from rdp.jobs import _diagnostics, _storage, policy
from rdp.jobs.errors import JobCancelledError, WorkerStoppingError
from rdp.jobs.gpu import verify_gpu
from rdp.jobs.logs import JobLog, JobLogMetadata, open_job_log
from rdp.jobs.policy import OUTPUT_JOIN_TIMEOUT_S
from rdp.jobs.processes import ToolCommand, run_external_process
from rdp.jobs.progress import ExecutionSignals, ProgressReporter
from rdp.jobs.records import StateChange, find_job, save_progress, transition_job
from rdp.jobs.registry import (
    EXAMPLE_GPU_TYPE,
    EXAMPLE_NAVIGATION_TYPE,
    MAINTENANCE_JOB_TYPES,
    JobRegistry,
)
from rdp.jobs.resources import save_resource_display
from rdp.jobs.storage import check_storage_before_job
from rdp.jobs.types import (
    ExecutionMode,
    ExecutionSnapshot,
    JobClock,
    JobProgress,
    JobRecord,
    JobState,
)

if TYPE_CHECKING:
    from rdp.jobs.maintenance import MaintenanceActions
    from rdp.jobs.navigation import NavigationWriter
    from rdp.jobs.scheduling import WorkerResources
    from rdp.jobs.scheduling_types import ResourceClaim


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ExecutionContext:
    """类型执行函数唯一输入，不提供数据库 Session 或 HTTP 对象。

    Attributes:
        job_id: 当前永久作业正编号。
        parameters: 按当前登记 Pydantic 模型校验的参数对象，不含秘密。
        mode: fresh/resume/restart；恢复时不重写 started_at。
        previous_progress: 上次最后持久化进度；fresh为None，restart仍提供旧快照供诊断。
            resume必须以它作累计基线：执行函数自己加增量，同阶段done及全部累计计数均不得减小；
            进入更高阶段仅done可从零计，累计条目/失败/警告接着加，不能把续跑局部计数直接上报。
        reporter: 当前上报/取消/等待对象，每个条目完成后 report。
        log: 当前追加日志，已写开头或中断段。
        clock: 注入的两种时钟，供外部进程期限使用。
        _navigation: 必填关键字，实例共享导航写入能力；不使用导航写入的直接执行调用可明确传 None。
            类型只能用 write_navigation 入口，不暴露资源池、发布者或调度配置。
        gpu_index: 当前领到的物理卡号，非负整数；无 GPU 为 None，不接受类型函数覆盖。
        maintenance: 必填关键字，只有两个清除回调的 MaintenanceActions；非维护作业明确传 None。
        gpu_example_command: 必填关键字，占卡示例的可信 ToolCommand；其他类型为 None，不让示例读取配置找路径。
        navigation_example_path: 必填关键字，状态目录的示例文件绝对路径；其他类型为 None，不暴露整份路径配置。
    """

    job_id: int
    parameters: BaseModel
    mode: ExecutionMode
    previous_progress: JobProgress | None
    reporter: ProgressReporter
    log: JobLog
    clock: JobClock
    _navigation: NavigationWriter | None = field(kw_only=True)
    gpu_index: int | None = field(kw_only=True)
    maintenance: MaintenanceActions | None = field(kw_only=True)
    gpu_example_command: ToolCommand | None = field(kw_only=True)
    navigation_example_path: Path | None = field(kw_only=True)

    def write_navigation[T](self, verify: Callable[[], None], write: Callable[[], T]) -> T:
        """用本 worker 共享写锁保护执行前核对与写入。

        Args:
            verify: 无参数同步核对函数，冲突抛 ConflictError，诊断由类型给出最后修改者。
            write: 核对通过才执行的同步写入函数，不在返回后留下异步写入。

        Returns:
            write 的原返回值；不重新计算或重复调用两个回调。

        Raises:
            ConflictError: 核对失败或等锁超过 NAVIGATION_LOCK_TIMEOUT_S。
            JobCancelledError: 等锁或进入保护段前取消，持锁期间延后到下一检查点。
            WorkerStoppingError: 等锁/进入前停止，保护段内延后。
            InputError: 回调输入拒绝或资源存储损坏。
            ExternalError: 回调或展示副本发生不可跳过的 I/O 失败。
            DefectError: _navigation 缺失、回调非法、递归取锁或其他程序异常。

        Side Effects:
            委托 _navigation.run(reporter, verify, write)，顺序和 finally 释放唯一由框架保证。
            不由类型直接拿锁；写入残留按类型契约，取消不清产物。

        Time Semantics:
            分段等待 50 毫秒，总等待最多 300 秒；写锁内取消/停止不抛，释放后下一检查点响应。
        """
        if self._navigation is None:
            raise DefectError()
        return self._navigation.run(self.reporter, verify, write)

    def run_process(self, command: ToolCommand) -> int:
        """以本作业的取消、日志和时钟执行一个外部命令。

        Args:
            command: 绝对程序路径、工作目录和有界 timeout_s；不含秘密。

        Returns:
            正常完成为 0；完整输出已进入当前日志，真实退出码已保存供摘要。

        Raises:
            JobCancelledError: 用户取消，进程组回收后传播。
            WorkerStoppingError: 入口停止，进程组回收后传播。
            ExternalError: 启动、非零/信号退出、超时或输出清理失败，诊断沿用 run_external_process。
            DefectError: 非法命令或上下文，不在此重复记录。

        Side Effects:
            委托 run_external_process 并传入 gpu_index，完整捕获两个输出流；
            有卡时框架强制 CUDA_VISIBLE_DEVICES=<卡号>、CUDA_DEVICE_ORDER=PCI_BUS_ID，不能由作业覆盖。
            本方法不写状态、不增加并行子进程、不修改全进程 os.environ。

        Time Semantics:
            执行有 command.timeout_s 上限，取消 TERM 宽限 10 秒后升级 KILL，随后有界回收。
        """
        return run_external_process(
            command, self.reporter, self.log, self.clock, gpu_index=self.gpu_index
        )


@dataclass(frozen=True)
class ExecutionWork:
    """当前实例待执行的一个作业，不表示新增队列记录。

    Attributes:
        record: 已领取或恢复后保持 running 的记录。
        mode: 本次执行原因，fresh/resume/restart。
        previous_progress: 恢复前持久化快照；fresh 为 None。
        claim: 必填关键字；执行时为本次资源凭据，刚完成恢复准备但尚未领资源时必须显式 None。
    """

    record: JobRecord
    mode: ExecutionMode
    previous_progress: JobProgress | None
    claim: ResourceClaim | None = field(kw_only=True)


@dataclass(frozen=True)
class ExecutorDependencies:
    """执行器显式基础设施；不在模块导入时连接数据库或创建目录。

    Attributes:
        engine: 已迁移受管引擎，各线程各开 Session。
        registry: 本 worker 的只读登记表。
        paths: 已初始化的状态布局，只写此布局下作业日志。
        clock: 注入时钟，墙钟持久化，monotonic 计时。
        resources: 必填关键字，本实例资源对象；仅入口装配前或无资源的直接执行调用可显式 None，调度前必须装配完成。
        storage: 必填关键字，worker 的只读存储检查器；仅全部类型不声明根时允许显式 None，
            非空需求缺失检查器属于 DefectError，不默认读取系统路径。
        platform_version: 本 worker 启动时的版本文字，1-128 个码点；生产入口必须提供。
            None 仅表示没有部署信息的独立领域调用；不在领域层读取包元数据或 git。
        poll_submissions: worker每轮恢复准备完成后、领取前调用的内部提交回调；默认None表示没有额外触发。
            返回本轮已提交作业编号元组，M1用RescanTrigger.poll；不访问导航或存储根，不启动线程。
            停止后不再调用，回调只能有界等待数据库短锁，不改变现有每日调度语义。
        recover_navigation: 无参回调，默认 None（M1-07，ADR 0005 修订）。worker 在全部旧 running/cancelling
            作业判为中断之后、第一次领取之前调用一次，内容是 recover_navigation_writes（回滚没收尾的写入、
            必要时设置"导航层恢复失败"标记）；抛出的异常按全局基础设施故障处理，整实例失败退出。
            回调返回之前没有任何作业被领取。
        navigation_blocked: 无参回调，默认 None。每轮领取前调用，返回 True 表示"导航层恢复失败"标记在，
            此时 writes_navigation 的作业类型整类跳过、留在排队中；回调只读数据库，抛出异常时同样整实例失败。
    """

    engine: Engine
    registry: JobRegistry
    paths: StatePaths
    clock: JobClock
    resources: WorkerResources | None = field(kw_only=True)
    storage: StorageAccessChecker | None = field(kw_only=True)
    platform_version: str | None = field(default=None, kw_only=True)
    poll_submissions: Callable[[], tuple[int, ...]] | None = field(default=None, kw_only=True)
    recover_navigation: Callable[[], None] | None = field(default=None, kw_only=True)
    navigation_blocked: Callable[[], bool] | None = field(default=None, kw_only=True)


def execute_job(
    work: ExecutionWork, dependencies: ExecutorDependencies, signals: ExecutionSignals
) -> JobRecord | None:
    """执行一次类型函数并按数据库当前取消状态统一收尾。

    Args:
        work: 已经 running 的新作业或恢复作业；开始时间不能重置。
        dependencies: 当前 worker 的引擎、登记、路径与两种时钟。
        signals: 主循环维护的取消与停止信号，执行线程不得清除。

    Returns:
        正常完成、失败或取消的已提交终态记录；仅入口停止且尚未终态提交时返回 None，
        保留 running/cancelling 给下一实例处理，不等待正常业务跑完。
        最终事务重读状态：已是 cancelling 时，无论函数正常返回还是抛异常均 cancelled；
        running 正常返回为 completed，非取消异常为 completed 且 aborted=True；结果只由转换函数计算。
        取消控制异常也不能凭空添加 running→cancelled，只有数据库已提交 cancelling 才走取消收尾。

    Raises:
        ExternalError: 终态持久化或不可回收资源的收尾失败；本边界已报告，run_loop停止领取及心跳，
            按30秒预算收尾并返回WORKER_EXIT_FAILURE，入口退出进程交systemd重启。
        InputError: 执行收尾遇数据库/持久化记录损坏，按同一整实例失败路径退出。
        ConflictError: 正常BUSY_TIMEOUT_MS用尽仍无法提交终态；留running/cancelling，由run_loop统一失败收尾退出，不能半活空转。
        DefectError: 上下文、状态边或持久化映射非法。

    Side Effects:
        本执行线程为daemon，主循环start前登记到monitor；入口绑定job_id，finally恢复。
        有 GPU 要求时，领取提交后在类型执行前用 verify_gpu 再核对；本实例可用卡集合为空（无配置或启动全失败）直接 ExternalError，诊断明确“平台没有可用的卡”，禁止 CPU 回退。
        开头/中断段后写一行分配卡号；卡号由领取事务保存，作业终态后保留历史。
        资源等待/持锁副本共用短锁补写；最终事务强制清等待和持锁标记，失败沿用整实例退出。
        完成、失败、取消、停止、开日志/参数校验失败都 finally 归还 claim；必须先回收工具和输出资源，
        仍存活的线程不可提前释放名额，主循环失败并保锁到退出。
        日志路径已随queued→running事务提交，只打开该路径，needs_header时先写开头，不再另开事务登记路径。
        构造reporter后在monitor锁内发布供主循环取消警告使用；每个daemon输出读线程独立copy_context。
        执行开始前普通日志打开/写头失败也先作为本条失败尝试提交终态，只有终态无法提交或资源不可回收才传播退出实例；
        恢复准备阶段的日志故障则已由recover_job隔离，不能混成整实例失败。
        先查当前类型并校验参数，未登记/模型过时也作为已领取作业失败结束，诊断指出 job_id/type/原因。
        类型调用前在事务和导航层写锁之外调用 check_storage_before_job；
        无存储声明不查挂载表，有声明时只读违规/离线/检查 I/O 失败均以外部失败收尾，
        类型 execute 一次也不调用，存储根不产生新文件；新执行、续跑、重跑都适用。
        存储检查前后及等待中均到达取消/停止检查点，终态取消优先规则不变。
        单条作业失败后 worker 继续其他作业。类型函数异常只在此记一次 ERROR，作业记录保留统一诊断与有界样例；
        程序缺陷完整报告经 infra.db.records.write_error 以作业编号保存，报告失败不掩盖原失败。
        最终事务保存内存最新进度、计数、产物、耗时和诊断，再 transition_job；提交后以同一摘要写结尾。
        终态写失败只在此ERROR，向run_loop传播使其立即停止领取/心跳并返回失败，不留下持续心跳的半活实例；
        日志结尾失败保留已提交终态并报告不一致。
        取消不删除产物；停止时仅尝试保存最后进度，不写终态。finally有界回收进程/输出线程；
        SIGKILL后仍不可回收的进程抛ExternalError，阻塞的输出线程保留为daemon并留在monitor，
        不关闭仍被它们使用的日志句柄；run_loop据存活资源决定失败和保留实例锁。

    Time Semantics:
        执行在线程内，主循环/心跳独立；进度周期短锁，最终普通锁最多 BUSY_TIMEOUT_MS。
        停止依赖登记函数的协作检查点（至多 JOB_CHECKPOINT_MAX_S），外部工具另有 TERM/KILL 预算；
        执行器只执行有界收尾，不判断自己是否越过总预算；run_loop负责超时一次ERROR、失败返回及锁保留。
        被节流的最新进度即使不再report，也由wait/check_cancelled/外部进程轮询在补写截止处理。
    """
    _storage.identifier(work.record.job_id, internal=True)
    if work.record.state is not JobState.RUNNING:
        raise DefectError()
    with log_context(job_id=work.record.job_id):
        return _ExecutionRun(work, dependencies, signals).run()


def recover_job(job_id: int, dependencies: ExecutorDependencies) -> ExecutionWork | None:
    """隔离恢复一条遗留记录，先写中断段，再安全决定是否执行当前代码。

    Args:
        job_id: 从启动恢复扫描读取的正编号；在本边界内解码完整记录，使单条JSON损坏也能隔离。
        dependencies: 新实例引擎、当前登记、状态路径和时钟；调用者已持单实例锁，不共享Session。

    Returns:
        本条可恢复时返回保持running的ExecutionWork，mode取当前登记的resume/restart，开始时间不变；
        以下情况返回None：cancelling收尾为cancelled；任一历史/当前声明为interrupt、类型已删除或
        recovery_count已达JOB_RECOVERY_LIMIT=3时running→interrupted；单条恢复失败也隔离后返回None。
        历史recovery_mode只作记录及保守中断保护，不决定当前执行方式；当前代码/参数模型永远生效。
        resume/restart但参数按当前模型不兼容时仍由execute_job以已完成失败收尾，不重新运行旧代码。

    Raises:
        DefectError: 调用编号或dependencies本身非法；单条记录、日志、SQL/解码错误不从本边界抛出。

    Side Effects:
        调用前 worker 已用一个事务统一清全部非终态等待/持锁，并清 running/cancelling 卡号。
        本函数只做恢复准备，不需要 GPU 或类型名额，不等待容量；全部遗留行先完成此准备。
        续跑/重跑返回 claim=None 的候选，只排在本类型新 queued 之前，调度时重新领资源，其他类型照常开始。
        不新增 queued 状态边；准备只增加一次恢复次数，后续等待资源不重复调用本函数。
        在本边界读记录；已登记log_path但文件不存在/为空时新建原路径，先write_header再写中断段。
        中断段含旧阶段、完整最后进度、当前处理方式和原因：包括缺类型、任一声明interrupt或次数已达3。
        每种正常分支先flush中断段再写事务；事务重读状态，若Web已提交cancelling则改走取消收尾。
        续跑/重跑资格在普通事务中将recovery_count加一并提交，最多0→1→2→3；第四次不执行也不增到4。
        加一在执行之前，提交后立即崩溃也消耗一次资格；重跑清计数/诊断/退出码但不清恢复次数、
        累计耗时或原产物，续跑保留全部累计基线；两者不改state/started_at，不新增状态边。
        任一单条恢复故障（含记录损坏、日志写不进、计数提交失败）先回滚，再仅尝试一次最小终态事务：
        可安全读取/校验的running经transition_job标interrupted，cancelling经同函数标cancelled；
        不猜损坏计数、不绕过状态机。能提交则保留诊断；仍不能落终态就边界ERROR注明编号/实际/后果，
        保留原行并返回None。本实例扫描游标继续前进，不反复碰这条、不阻止别条恢复或新的排队作业。
        日志故障时允许上述隔离终态没有中断段，但必须ERROR明确缺失；不伪造已写日志，不记人为取消审计。

    Time Semantics:
        恢复准备扫描按job_id ASC，有界keyset且先于新queued；单条处理和至多一次失败终态尝试均有普通锁预算，
        无无限重试。正常无锁竞争下最新进度按1秒补写目标保存，另计短锁/I/O/调度；连续跳过n次短锁另落后n秒，
        持续锁忙没有有限延迟保证。资格提交并交execute_job实际执行后，其终态提交失败归整实例失败退出，
        不使用本函数的准备阶段隔离规则。恢复不把墙钟回拨当冲突，不将停机时间计入运行耗时。
    """
    from rdp.jobs._recovery import prepare

    _storage.identifier(job_id, internal=True)
    _storage.moment(dependencies.clock.now())
    if not dependencies.engine.get_execution_options().get("rdp_managed"):
        raise DefectError()
    try:
        return prepare(job_id, dependencies)
    except Exception as error:
        _isolate_recovery(job_id, dependencies, error)
        return None


class _ExecutionRun:
    """一个调用的文件/上报生命周期；终态失败必须离开本边界，不能吞成业务失败再继续领取。"""

    def __init__(
        self, work: ExecutionWork, dependencies: ExecutorDependencies, signals: ExecutionSignals
    ) -> None:
        """为单次调用保存执行输入和文件生命周期，不在构造时打开日志或执行类型函数。"""
        self.work, self.dependencies, self.signals = work, dependencies, signals
        self.log: JobLog | None = None
        self.reporter: ProgressReporter | None = None
        self.failures: tuple[Diagnostic, ...] = ()
        self.aborted = False

    def run(self) -> JobRecord | None:
        """只收口执行阶段错误；最终事务与摘要分开，不回滚已完成记录来弥补文件失败。"""
        try:
            try:
                self._invoke()
            except WorkerStoppingError:
                pass
            except JobCancelledError:
                pass
            except Exception as error:
                self.aborted = True
                self._failure(error)
            if self.signals.stopping.is_set() and not self.signals.cancelled.is_set():
                self._save_stopping()
                return None
            try:
                result = self._finish()
            except Exception:
                logger.error("作业终态持久化失败，worker将停止领取和心跳", exc_info=True)
                raise
            if self.log is not None and result.summary is not None:
                try:
                    self.log.write_summary(result.summary, now=self.dependencies.clock.now())
                except Exception:
                    logger.error("作业已提交终态，但日志结尾写入失败", exc_info=True)
            return result
        finally:
            self._close()

    def _invoke(self) -> None:
        """领取已保存路径；先头后执行，类型/参数升级失败也在作业边界统一结束。"""
        record, dependencies = self.work.record, self.dependencies
        self.log, needs_header = open_job_log(dependencies.paths, record)
        if needs_header:
            self.log.write_header(record, JobLogMetadata(None, None, None))
        self.reporter = ProgressReporter(
            dependencies.engine, record, self.log, dependencies.clock, self.signals
        )
        monitor = self.signals.monitor
        if not monitor.lock.acquire(timeout=OUTPUT_JOIN_TIMEOUT_S):
            raise DefectError()
        try:
            monitor.reporter = self.reporter
        finally:
            monitor.lock.release()
        definition = dependencies.registry.lookup(record.type_name)
        if definition is None:
            raise InputError((_execution_diagnostic(record, "当前登记表已无此作业类型"),))
        try:
            parameters = definition.parameters_model.model_validate(record.parameters)
        except ValidationError:
            raise InputError(
                (_execution_diagnostic(record, "历史参数不满足当前类型模型"),)
            ) from None
        gpu_example_command = None
        if definition.requires_gpu:
            if record.gpu_index is None:
                raise ExternalError(
                    (
                        _execution_diagnostic(
                            record,
                            "平台没有可用的卡：GPU配置为空或配置卡在启动核对时全部被移出",
                            DiagnosticCategory.EXTERNAL,
                        ),
                    )
                )
            if dependencies.resources is None:
                raise DefectError()
            command = dependencies.resources.configuration.nvidia_smi
            if command is None:
                raise DefectError()
            self.log.write_line(f"领到GPU卡号：{record.gpu_index}", now=dependencies.clock.now())
            verify_gpu(record.gpu_index, command, log=self.log)
            if record.type_name == EXAMPLE_GPU_TYPE:
                gpu_example_command = ToolCommand(
                    "nvidia-smi",
                    (str(command), "-i", str(record.gpu_index)),
                    dependencies.paths.root,
                    policy.GPU_PROBE_TIMEOUT_S,
                )
        context = ExecutionContext(
            record.job_id,
            parameters,
            self.work.mode,
            self.work.previous_progress,
            self.reporter,
            self.log,
            dependencies.clock,
            _navigation=None
            if dependencies.resources is None
            else dependencies.resources.navigation,
            gpu_index=record.gpu_index,
            maintenance=self._maintenance_actions(),
            gpu_example_command=gpu_example_command,
            navigation_example_path=dependencies.paths.navigation_example
            if record.type_name == EXAMPLE_NAVIGATION_TYPE
            else None,
        )
        self.reporter.check_cancelled()
        check_storage_before_job(
            definition.storage,
            checker=dependencies.storage,
            checkpoint=self.reporter.check_cancelled,
        )
        self.reporter.check_cancelled()
        definition.execute(context)

    def _maintenance_actions(self) -> MaintenanceActions | None:
        """只给两个清除类型注入已绑定的最小服务，不把引擎或配置放进上下文。"""
        if self.work.record.type_name not in MAINTENANCE_JOB_TYPES:
            return None
        from rdp.jobs.maintenance import MaintenanceActions, MaintenanceService

        if self.dependencies.resources is None:
            raise DefectError()
        service = MaintenanceService(
            self.dependencies.engine, self.dependencies.resources.configuration.error_retention_days
        )
        return MaintenanceActions(service.purge_errors, service.purge_logs)

    def _failure(self, error: Exception) -> None:
        """统一诊断进入记录；日志失败时仍尝试落终态，不能在失败日志上递归报告。"""
        self.failures = (
            error.diagnostics
            if isinstance(error, (InputError, ConflictError, ExternalError, DefectError))
            else ()
        )
        if not self.failures:
            self.failures = (
                _execution_diagnostic(
                    self.work.record,
                    f"执行函数异常：{type(error).__name__}",
                    DiagnosticCategory.DEFECT,
                ),
            )
        self.failures = tuple(
            _with_job_identity(self.work.record.job_id, item) for item in self.failures
        )
        report = format_exception_report(error)
        logger.error("作业执行失败\n%s", report)
        if not isinstance(error, (InputError, ConflictError, ExternalError)):
            try:
                with session_scope(self.dependencies.engine) as session:
                    write_error(
                        session,
                        ErrorRecord(
                            error_id=str(self.work.record.job_id),
                            occurred_at=self.dependencies.clock.now(),
                            category=DiagnosticCategory.DEFECT,
                            summary="作业执行发生程序缺陷",
                            report=report,
                            source_kind="job",
                        ),
                    )
            except Exception:
                # 保留第一条原始失败；报告存储故障不能掩盖它，也不递归写报错表。
                error.add_note("完整作业报错保存失败，请查看运行日志")
        if self.reporter is not None:
            for diagnostic in self.failures:
                try:
                    self.reporter.diagnostic(diagnostic)
                except Exception:
                    # 文件已不可写时保留原失败；最终快照仍会合并诊断。
                    break

    def _snapshot(self) -> ExecutionSnapshot:
        """日志尚未打开的失败也保留历史快照，不抹去续跑的计数与耗时。"""
        record = self.work.record
        snapshot = (
            self.reporter.snapshot()
            if self.reporter is not None
            else ExecutionSnapshot(
                record.progress,
                record.diagnostics,
                record.artifacts,
                record.tool_exit_code,
                record.elapsed_s,
            )
        )
        if self.failures and self.reporter is None:
            groups = snapshot.diagnostics
            for diagnostic in self.failures:
                groups = _diagnostics.append(groups, diagnostic)
            snapshot = ExecutionSnapshot(
                snapshot.progress,
                groups,
                snapshot.artifacts,
                snapshot.tool_exit_code,
                snapshot.elapsed_s,
            )
        return snapshot

    def _finish(self) -> JobRecord:
        """最终普通事务重读取消态；快照和唯一状态转换同一提交，失败整个回滚。"""
        snapshot = self._snapshot()
        with session_scope(self.dependencies.engine) as session:
            current = find_job(session, self.work.record.job_id)
            save_progress(session, current.job_id, snapshot, now=self.dependencies.clock.now())
            target = (
                JobState.CANCELLED if current.state is JobState.CANCELLING else JobState.COMPLETED
            )
            result = transition_job(
                session,
                current.job_id,
                StateChange(
                    current.state,
                    target,
                    self.dependencies.clock.now(),
                    aborted=self.aborted and target is JobState.COMPLETED,
                ),
            )
        return result

    def _save_stopping(self) -> None:
        """停止只保存最后进度，不新增终态；失败上交主循环统一退出。"""
        with session_scope(self.dependencies.engine) as session:
            save_progress(
                session,
                self.work.record.job_id,
                self._snapshot(),
                now=self.dependencies.clock.now(),
            )

            # 执行函数已经退出保护段，最终进度事务同时清掉可能尚未补写的资源副本。
            from rdp.jobs.scheduling_types import ResourceDisplay

            save_resource_display(session, self.work.record.job_id, ResourceDisplay(None, False))

    def _close(self) -> None:
        """只关闭无读线程使用的文件，活资源留在monitor交主循环保锁。"""
        monitor = self.signals.monitor
        if not monitor.lock.acquire(timeout=OUTPUT_JOIN_TIMEOUT_S):
            raise DefectError()
        try:
            from threading import current_thread

            alive = any(
                thread.is_alive() and thread is not current_thread() for thread in monitor.threads
            )
        finally:
            monitor.lock.release()
        if self.log is not None and not alive:
            try:
                self.log.close()
            except Exception:
                logger.error("关闭作业日志失败，已保存的状态不回滚", exc_info=True)
        if not alive and self.work.claim is not None and self.dependencies.resources is not None:
            self.dependencies.resources.pool.release(self.work.claim)


def _execution_diagnostic(
    record: JobRecord, actual: str, category: DiagnosticCategory = DiagnosticCategory.INPUT
) -> Diagnostic:
    """类型兼容与未知执行异常的安全诊断，不复制整份参数或异常载荷。"""
    return Diagnostic(
        level=DiagnosticLevel.ERROR,
        category=category,
        stage="作业执行",
        source="平台",
        objects=(
            DiagnosticObject(key="job_id", value=str(record.job_id)),
            DiagnosticObject(key="type", value=record.type_name),
        ),
        rule="作业必须能由当前登记类型执行",
        actual=actual,
        expected="类型存在且参数兼容",
        consequence="本次作业整体失败，其他排队作业不受影响",
        next_step="检查当前类型和参数后重新提交",
    )


def _isolate_recovery(job_id: int, dependencies: ExecutorDependencies, error: Exception) -> None:
    """至多一次安全终态尝试；解码仍失败就保留原行，扫描方继续下个编号。"""
    try:
        with session_scope(dependencies.engine) as session:
            record = find_job(session, job_id)
            if record.state not in {JobState.RUNNING, JobState.CANCELLING}:
                return
            diagnostic = _execution_diagnostic(
                record,
                f"恢复准备失败：{type(error).__name__}，中断段可能缺失",
                DiagnosticCategory.EXTERNAL,
            )
            snapshot = ExecutionSnapshot(
                record.progress,
                _diagnostics.append(record.diagnostics, diagnostic),
                record.artifacts,
                record.tool_exit_code,
                record.elapsed_s,
            )
            save_progress(session, job_id, snapshot, now=dependencies.clock.now())
            target = (
                JobState.CANCELLED if record.state is JobState.CANCELLING else JobState.INTERRUPTED
            )
            transition_job(
                session, job_id, StateChange(record.state, target, dependencies.clock.now())
            )
    except Exception:
        logger.error(
            "作业 job_id=%s 恢复失败且不能安全写终态；跳过该条，中断段可能缺失",
            job_id,
            exc_info=True,
        )
    else:
        logger.error("作业 job_id=%s 恢复失败，已隔离终态；中断段可能缺失", job_id, exc_info=error)


def _with_job_identity(job_id: int, diagnostic: Diagnostic) -> Diagnostic:
    """在掌握作业编号的执行边界补上下文，工具边界只掌握命令与退出状态。"""
    if any(item.key == "job_id" for item in diagnostic.objects):
        return diagnostic
    objects = (DiagnosticObject(key="job_id", value=str(job_id)),) + diagnostic.objects
    return Diagnostic.model_validate(diagnostic.model_dump() | {"objects": objects})
