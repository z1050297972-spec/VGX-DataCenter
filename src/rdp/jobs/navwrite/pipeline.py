"""写入作业的统一流水线（worker 写入侧，领域层，M1-07，ADR 0009 的"一个作业的阶段"）。

建链、新增数据集、改指向、数据来源标注、撤回五种写入共用同一份 NavWritePlan 和同一条流水线，
各自只负责生成计划（M1-08、09、10 加预览作业）。本模块不含任何"该不该改"的决策（规范 2.1）：
只按计划执行，并在写锁内先核对预览状态、再落日志、再逐步写入、失败按日志退回。
只写 nav_root 和状态目录，从不写存储根。import 本模块的只能是 worker 一侧（import-linter 合约）。
"""

from dataclasses import dataclass
from datetime import datetime

from rdp.infra.actors import ActorRef
from rdp.infra.state import StatePaths
from rdp.jobs.datasets.rescan import RescanDependencies
from rdp.jobs.execution import ExecutionContext
from rdp.jobs.navwrite.journal import Journal
from rdp.jobs.navwrite.models import ApplyResult, NavPreview
from rdp.jobs.service import JobService


@dataclass(frozen=True)
class NavWriteDependencies:
    """写入底座所需的 worker 依赖，由 worker 装配，不通过作业参数注入。

    Attributes:
        rescan: 第 01 张的扫描依赖，提供受管引擎、导航根、存储根登记和只读存储检查器；
            写入后的索引更新复用它，写入底座不另造一套。
        paths: 已初始化的状态布局，含 nav-journal、nav-changes、nav-previews 三个子目录。
        service: 作业服务，用来在写入以后提交统计大小作业（系统身份）。
    """

    rescan: RescanDependencies
    paths: StatePaths
    service: JobService


@dataclass(frozen=True)
class LockedWrite:
    """持锁写入段的成功结果。

    Attributes:
        journal: 已落盘并已归档的写入日志内容（日志目录此时已删除）。
        file_count: 实际写入的文件数。
        link_count: 实际建或改的链接数。
        noop: 计划没有步骤、什么都没写。
        started_at: 开始写入的 UTC 时刻，用于变更记录。
        finished_at: 提交点的 UTC 时刻。
    """

    journal: Journal | None
    file_count: int
    link_count: int
    noop: bool
    started_at: datetime
    finished_at: datetime


def write_plan_locked(
    context: ExecutionContext,
    dependencies: NavWriteDependencies,
    preview: NavPreview,
    actor: ActorRef,
) -> LockedWrite:
    """在导航层写锁内完成核对、落日志、逐步写入、归档和删日志；失败按日志退回。

    Args:
        context: 当前写入作业的执行上下文；write_navigation 提供写锁，写锁只在本函数持有期间占用。
        dependencies: 写入依赖。
        preview: 预览作业保存的结果，其 plan 就是要执行的计划，不重新计算。
        actor: 提交人身份快照，写进变更记录。

    Returns:
        LockedWrite。计划无步骤时 noop 为 True，仍完成预览状态核对，不落日志。

    Raises:
        ConflictError: 预览状态已变化（写锁内核对，一行都没写，不落日志）；或等写锁超过 300 秒。
        ExternalError: 写入某一步失败：已按日志逆序退回并归档为 rolled_back，作业失败；
            退回时有对不上的项则同时设置恢复失败标记，日志保留，诊断说明导航层可能处于一半新一半旧。
        InputError: 计划与导航根不符，或计划步骤逃逸 nav_root。
        JobCancelledError: 等写锁期间收到取消；持锁期间的取消延后，不打断半次写入。
        WorkerStoppingError: 等写锁期间 worker 停止；持锁期间延后。
        DefectError: 回调非法或程序缺陷。

    Side Effects:
        context.write_navigation(verify, write) 里依次：verify_preview_state → capture_before_images →
        write_journal → apply_plan → archive_journal(COMMITTED) → discard_journal。
        归档和删日志放在锁内，是为了让提交点（变更记录落盘）和锁一致，避免别的作业在这之间改同样的文件，
        崩溃恢复时才不会把"别人的合法修改"误判成两者都不是。失败时 rollback_journal，再归档为 rolled_back 并删日志；
        回滚也失败（对不上的项）时保留日志并 record_recovery_block。只写 nav_root 与状态目录。

    Time Semantics:
        写锁等待上限 NAVIGATION_LOCK_TIMEOUT_S=300 秒；持锁段在 worker 30 秒停止预算内完成。
        顺序固定：核对 → 落日志 → 写入 → 归档 → 删日志；不能颠倒（规范 2.3，ADR 0005）。
    """
    raise NotImplementedError


def reindex_after_write(
    context: ExecutionContext,
    rescan: RescanDependencies,
    dataset_ids: tuple[str, ...],
) -> tuple[str, ...]:
    """写入以后在同一个作业里更新受影响数据集的索引（ADR 0006）。

    Args:
        context: 当前写入作业的执行上下文。
        rescan: 扫描依赖。
        dataset_ids: 受影响的永久编号，逐个处理。

    Returns:
        已成功更新索引的编号，按输入顺序。

    Raises:
        ConflictError: 导航锁等待超限，或索引事务竞争。
        ExternalError: 索引事务失败；导航层已经写好，作业记警告并由下一次定时重新扫描补上，不回滚导航层。
        JobCancelledError: 阶段间收到取消。
        WorkerStoppingError: 阶段间 worker 停止。

    Side Effects:
        对每个编号以替换了参数的上下文（RescanParameters(dataset_id=…)）调用 scan_navigation、scan_storage、
        publish_scan，复用第 01 张的实现，不另写索引逻辑。每次扫描的第一段和提交复核各自短暂持写锁。

    Time Semantics:
        在 write_plan_locked 返回、写锁已释放之后调用；是 ADR 0009 阶段 4。第二段访问存储根有超时并按离线处理。
    """
    raise NotImplementedError


def submit_sizing_jobs(
    service: JobService, dataset_ids: tuple[str, ...], *, now: datetime
) -> tuple[int, ...]:
    """为受影响的数据集各提交一次统计大小作业（M1-02 的 dataset_sizing）。

    Args:
        service: 作业服务，已登记 dataset_sizing。
        dataset_ids: 受影响的永久编号；统计大小作业的参数一次只接受一个编号，所以每个编号一个作业。
        now: 注入的 aware 时刻，UTC。

    Returns:
        新作业编号，按输入顺序。

    Raises:
        InputError: 参数模型拒绝编号。
        ConflictError: 事务入场后约束冲突；短锁忙时不吞掉，由调用方记警告。
        ExternalError: 数据库 I/O 失败。

    Side Effects:
        调用 JobService.submit_system 插入作业行和提交操作日志，不等待作业完成，不访问存储根。

    Time Semantics:
        写入和重建索引之后调用；统计本身在后台作业里完成，本调用只提交。
    """
    raise NotImplementedError


def run_write_plan(
    context: ExecutionContext,
    dependencies: NavWriteDependencies,
    preview_job_id: int,
) -> ApplyResult:
    """执行一份已确认的预览：读出计划，写入，更新索引，提交统计大小，记操作日志。

    Args:
        context: 当前写入作业的执行上下文，作业类型 nav_write_apply。
        dependencies: 写入依赖。
        preview_job_id: 预览作业编号，≥ 1；计划取自 nav-previews 里同一份文件。

    Returns:
        ApplyResult。committed：已写入并提交了统计大小；noop：核对通过但计划无步骤，操作日志照记。
        中途失败不返回，抛出下面的异常，导航层已退回（outcome 即 rolled_back，由异常携带的诊断表达）。

    Raises:
        InputError: 预览文件不存在或损坏、预览所属的导航根与当前不同、预览作业不是成功结束的。
        ConflictError: 同 write_plan_locked。
        ExternalError: 同 write_plan_locked；已写完导航层之后的索引、统计、操作日志失败不回滚导航层，
            只记警告并计入作业的 warning_count。
        JobCancelledError: 同 write_plan_locked，持锁段之外的阶段间检查点也会响应。
        WorkerStoppingError: 同 write_plan_locked。
        DefectError: 作业类型或参数不对。

    Side Effects:
        五个阶段：1 核对预览状态并落写入日志（持写锁）→ 2 逐步写入（同一次持锁）→ 3 更新索引 →
        4 提交统计大小 → 5 记操作日志。成功和失败都追加一条操作日志，带变更记录编号；
        写变更记录在阶段 2 的提交点完成。进度每阶段上报一次，单位"阶段"，阶段 2 的条目单位为"文件"。
        不直接给作业结果赋值，作业结果由 M0 的 calculate_outcome 按计数算出。

    Time Semantics:
        锁等待与持锁时长见 write_plan_locked；阶段 3 起不持锁。取消在阶段之间响应；
        进入阶段 2 之后不可打断，直到提交或退回完成。
    """
    raise NotImplementedError
