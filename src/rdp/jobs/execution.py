"""作业执行器最外层边界（08、规范 6.3）；唯一收口执行异常，不拥有 worker 主循环。

线程执行使用 contextvars.copy_context 与 infra.logging.log_context 关联作业编号。
终态普通事务先保存最新进度，再经过 records.transition_job；禁止执行函数设置状态或结果。
"""

import logging
from dataclasses import dataclass

from pydantic import BaseModel
from sqlalchemy import Engine

from rdp.infra.state import StatePaths
from rdp.jobs.logs import JobLog
from rdp.jobs.processes import ToolCommand
from rdp.jobs.progress import ExecutionSignals, ProgressReporter
from rdp.jobs.registry import JobRegistry
from rdp.jobs.types import ExecutionMode, JobClock, JobProgress, JobRecord

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
    """

    job_id: int
    parameters: BaseModel
    mode: ExecutionMode
    previous_progress: JobProgress | None
    reporter: ProgressReporter
    log: JobLog
    clock: JobClock

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
            委托 run_external_process，完整捕获两个输出流；本方法不写状态，不增加并行子进程。

        Time Semantics:
            执行有 command.timeout_s 上限，取消 TERM 宽限 10 秒后升级 KILL，随后有界回收。
        """
        raise NotImplementedError


@dataclass(frozen=True)
class ExecutionWork:
    """当前实例待执行的一个作业，不表示新增队列记录。

    Attributes:
        record: 已领取或恢复后保持 running 的记录。
        mode: 本次执行原因，fresh/resume/restart。
        previous_progress: 恢复前持久化快照；fresh 为 None。
    """

    record: JobRecord
    mode: ExecutionMode
    previous_progress: JobProgress | None


@dataclass(frozen=True)
class ExecutorDependencies:
    """执行器显式基础设施；不在模块导入时连接数据库或创建目录。

    Attributes:
        engine: 已迁移受管引擎，各线程各开 Session。
        registry: 本 worker 的只读登记表。
        paths: 已初始化的状态布局，只写此布局下作业日志。
        clock: 注入时钟，墙钟持久化，monotonic 计时。
    """

    engine: Engine
    registry: JobRegistry
    paths: StatePaths
    clock: JobClock


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
        日志路径已随queued→running事务提交，只打开该路径，needs_header时先写开头，不再另开事务登记路径。
        构造reporter后在monitor锁内发布供主循环取消警告使用；每个daemon输出读线程独立copy_context。
        执行开始前普通日志打开/写头失败也先作为本条失败尝试提交终态，只有终态无法提交或资源不可回收才传播退出实例；
        恢复准备阶段的日志故障则已由recover_job隔离，不能混成整实例失败。
        先查当前类型并校验参数，未登记/模型过时也作为已领取作业失败结束，诊断指出 job_id/type/原因，
        worker 继续其他作业。类型函数异常只在此记一次 ERROR，作业记录保留统一诊断与有界样例；
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
    raise NotImplementedError


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
    raise NotImplementedError
