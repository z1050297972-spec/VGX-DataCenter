"""写入作业的统一流水线（worker 写入侧，领域层，M1-07，ADR 0009 的"一个作业的阶段"）。

建链、新增数据集、改指向、字段编辑等写入共用同一份 NavWritePlan 和同一条流水线，
各自只负责生成计划（M1-08、09、10 加预览作业）。本模块不含任何"该不该改"的决策（规范 2.1）：
只按计划执行，并在写锁内先核对预览状态、再落日志、再逐步写入、失败按日志退回。
只写 nav_root 和状态目录，从不写存储根。import 本模块的只能是 worker 一侧（import-linter 合约）。
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from rdp.audit.types import OPS_AUDIT_CONTEXT, OperationResult, OperationType
from rdp.infra.actors import ActorRef
from rdp.infra.db.connection import session_scope
from rdp.infra.diagnostics import (
    ConflictError,
    DefectError,
    Diagnostic,
    DiagnosticCategory,
    DiagnosticLevel,
    ExternalError,
    InputError,
)
from rdp.infra.state import StatePaths
from rdp.jobs.datasets.catalog import SIZING_TYPE
from rdp.jobs.datasets.fingerprint import FileState, fingerprint_dataset
from rdp.jobs.datasets.rescan import (
    RescanDependencies,
    RescanParameters,
    publish_scan,
    scan_navigation,
    scan_storage,
)
from rdp.jobs.execution import ExecutionContext
from rdp.jobs.navwrite.atomic import apply_plan, capture_before_images, rollback_journal
from rdp.jobs.navwrite.audit import (
    NavigationAuditFacts,
    append_navigation_audit,
    navigation_operation_event,
)
from rdp.jobs.navwrite.changes import ArchiveRequest, ChangeOutcome, archive_journal
from rdp.jobs.navwrite.errors import nav_input_error
from rdp.jobs.navwrite.journal import (
    Journal,
    discard_journal,
    journal_directory,
    write_journal,
)
from rdp.jobs.navwrite.marker import record_recovery_block
from rdp.jobs.navwrite.models import ApplyResult, MismatchItem, NavPreview, NavWritePlan
from rdp.jobs.navwrite.policy import AUDIT_DATASET_ID_LIMIT
from rdp.jobs.navwrite.preview_state import verify_preview_state
from rdp.jobs.navwrite.previews import read_preview
from rdp.jobs.policy import JOB_TEXT_MAX_CHARS
from rdp.jobs.records import find_job
from rdp.jobs.service import JobService
from rdp.jobs.types import JobProgress, JobState

logger = logging.getLogger(__name__)
_RULE = "NAV_PIPELINE"
# 写入作业的五个阶段，进度按阶段上报（ADR 0009 的"一个作业的阶段"）。
STAGES = ("核对并写入", "更新索引", "提交统计大小", "记操作日志")


@dataclass(frozen=True)
class NavWriteDependencies:
    """写入底座所需的 worker 依赖，由 worker 装配，不通过作业参数注入。

    Attributes:
        rescan: 第 01 张的扫描依赖，提供受管引擎、导航根、存储根登记和只读存储检查器；
            写入后的索引更新复用它，写入底座不另造一套。
        paths: 已初始化的状态布局，含 nav-journal、nav-changes、nav-previews 三个子目录。
        service: 作业服务，用来在写入以后提交统计大小作业（系统身份）。
        timezone: 调度使用的本地时区；None 时由统计入口读取 /etc/localtime。
    """

    rescan: RescanDependencies
    paths: StatePaths
    service: JobService
    timezone: ZoneInfo | None = None


@dataclass(frozen=True)
class LockedWrite:
    """持锁写入段的成功结果。

    Attributes:
        preview: 锁内核对后实际执行的计划；自动作业可能已剔除变化数据集。
        journal: 已落盘并已归档的写入日志内容（日志目录此时已删除）。
        file_count: 实际写入的文件数。
        link_count: 实际建或改的链接数。
        noop: 计划没有步骤、什么都没写。
        started_at: 开始写入的 UTC 时刻，用于变更记录。
        finished_at: 提交点的 UTC 时刻。
    """

    preview: NavPreview
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
    *,
    prepare_locked: Callable[[NavPreview], NavPreview] | None = None,
) -> LockedWrite:
    """在导航层写锁内完成核对、落日志、逐步写入、归档和删日志；失败按日志退回。

    Args:
        context: 当前写入作业的执行上下文；write_navigation 提供写锁，写锁只在本函数持有期间占用。
        dependencies: 写入依赖。
        preview: 预览作业保存的结果，其 plan 就是要执行的计划，不重新计算。
        actor: 提交人身份快照，写进变更记录。
        prepare_locked: 锁内准备回调；自动作业过滤过期计划，人工血缘仅补写作业审计元数据。
            None 保持确认计划不变，不允许在回调中重算人工关系。

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
    plan = preview.plan
    nav_root = Path(plan.state.nav_root)
    paths = dependencies.paths
    job_id = context.job_id

    def verify() -> None:
        nonlocal preview, plan
        if prepare_locked is not None:
            preview = prepare_locked(preview)
            plan = preview.plan
        # 持写锁之后、落日志之前再核对一次预览状态；取消和停止在保护段内被框架延后，检查点不抛。
        verify_preview_state(nav_root, plan.state, checkpoint=_no_checkpoint)

    def write() -> LockedWrite:
        started = context.clock.now()
        if not plan.steps:
            return LockedWrite(preview, None, 0, 0, True, started, started)
        images = capture_before_images(nav_root, plan)
        journal = write_journal(paths, plan, images, job_id, started)
        current = _InFlight(
            context,
            dependencies,
            preview,
            actor,
            journal,
            journal_directory(paths, job_id),
            started,
        )
        try:
            apply_plan(nav_root, plan, job_id, checkpoint=_no_checkpoint)
            finished = context.clock.now()
            current.archive(ChangeOutcome.COMMITTED, finished)
        except Exception:
            current.roll_back()
            raise
        _discard_after_commit(current.directory)
        return LockedWrite(preview, journal, *_counts(plan), False, started, finished)

    return context.write_navigation(verify, write)


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
    done: list[str] = []
    for dataset_id in dataset_ids:
        scoped = replace(context, parameters=RescanParameters(dataset_id=dataset_id))
        navigation = scan_navigation(scoped, rescan)
        storage = scan_storage(navigation, rescan, checkpoint=context.reporter.check_cancelled)
        publish_scan(scoped, rescan, navigation, storage)
        done.append(dataset_id)
    return tuple(done)


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
    return tuple(
        service.submit_system(SIZING_TYPE, {"dataset_id": dataset_id}, now=now).job_id
        for dataset_id in dataset_ids
    )


def run_write_plan(
    context: ExecutionContext,
    dependencies: NavWriteDependencies,
    preview_job_id: int | NavPreview,
    *,
    prepare_locked: Callable[[NavPreview], NavPreview] | None = None,
) -> ApplyResult:
    """执行人工确认或平台自动计划，统一写入、更新索引、提交统计并记审计。

    Args:
        context: 当前人工或平台自动写入作业的执行上下文。
        dependencies: 写入依赖。
        preview_job_id: 人工预览的正整数编号；自动作业传已读取的 NavPreview，不要求人工确认。
        prepare_locked: 自动计划过滤或人工血缘审计元数据补齐回调；不改变人工预览冲突即失败的行为。

    Returns:
        ApplyResult。committed：已写入，仅为仍存在的数据集提交统计，删除编号记入 sizing_skipped_dataset_ids；noop：核对通过但计划无步骤，操作日志照记。
        中途失败不返回，抛出下面的异常，导航层已退回（outcome 即 rolled_back，由异常携带的诊断表达）。

    Raises:
        InputError: 预览文件不存在或损坏、预览所属的导航根与当前不同、预览作业不是成功结束的，
            或预览为已下线的历史撤回计划。
        ConflictError: 同 write_plan_locked。
        ExternalError: 同 write_plan_locked；已写完导航层之后的索引、统计、操作日志失败不回滚导航层，
            只记警告并计入作业的 warning_count。
        JobCancelledError: 同 write_plan_locked，持锁段之外的阶段间检查点也会响应。
        WorkerStoppingError: 同 write_plan_locked。
        DefectError: 作业类型或参数不对。

    Side Effects:
        四个进度阶段：1 核对预览状态、落写入日志并逐步写入（同一次持锁，细节见 write_plan_locked）→
        2 更新索引 → 3 提交统计大小 → 4 记操作日志。成功和失败都追加一条操作日志，带变更记录编号；
        写变更记录在阶段 1 的提交点完成。进度每阶段上报一次，单位"阶段"；提交之后的失败累计进作业的警告数。
        不直接给作业结果赋值，作业结果由 M0 的 calculate_outcome 按计数算出。

    Time Semantics:
        锁等待与持锁时长见 write_plan_locked；阶段 3 起不持锁。取消在阶段之间响应；
        进入阶段 2 之后不可打断，直到提交或退回完成。
    """
    engine = dependencies.rescan.engine
    preview = (
        preview_job_id
        if isinstance(preview_job_id, NavPreview)
        else _load_preview(dependencies, preview_job_id)
    )
    # 保留历史计划的解析能力供恢复使用，但不允许旧撤回预览再次执行。
    if preview.plan.operation.value == "revert_change":
        problem = nav_input_error(_RULE, "撤回功能已移除，不能执行历史撤回预览")
        raise problem
    with session_scope(engine, read_only=True) as session:
        submitter = find_job(session, context.job_id).submitted_by
    progress = _Progress(context)
    progress.stage(1)
    try:
        locked = write_plan_locked(
            context, dependencies, preview, submitter, prepare_locked=prepare_locked
        )
    except Exception as error:
        _audit_failure(dependencies, context, preview, submitter, error)
        raise
    plan = locked.preview.plan
    reindexed: tuple[str, ...] = ()
    sizing: tuple[int, ...] = ()
    skipped: tuple[str, ...] = ()
    if not locked.noop:
        progress.stage(2)
        reindexed = _after_commit(
            progress,
            "更新索引",
            lambda: reindex_after_write(context, dependencies.rescan, plan.dataset_ids),
            (),
        )
        progress.stage(3)
        remaining, skipped = _after_commit(
            progress, "核对统计范围", lambda: _sizing_scope(context, dependencies, plan), ((), ())
        )
        sizing = _after_commit(
            progress,
            "提交统计大小",
            lambda: submit_sizing_jobs(dependencies.service, remaining, now=context.clock.now()),
            (),
        )
    progress.stage(4)
    result = ApplyResult(
        job_id=context.job_id,
        operation=plan.operation,
        outcome="noop" if locked.noop else "committed",
        dataset_ids=plan.dataset_ids,
        file_count=locked.file_count,
        link_count=locked.link_count,
        reindexed_dataset_ids=reindexed,
        sizing_job_ids=sizing,
        sizing_skipped_dataset_ids=skipped,
    )
    _after_commit(
        progress,
        "记操作日志",
        lambda: _audit_success(dependencies, context, submitter, result, bool(plan.steps)),
        None,
    )
    if skipped:
        _after_commit(
            progress,
            "记录统计跳过",
            lambda: context.log.write_line(
                "已删除数据集不统计：" + "、".join(skipped), now=context.clock.now()
            ),
            None,
        )
    progress.finish(skipped)
    return result


def _no_checkpoint() -> None:
    """写锁保护段内的检查点：框架已延后取消和停止，这里什么都不抛。"""


def _counts(plan: NavWritePlan) -> tuple[int, int]:
    """计划里写（或删）的文件数、建或改的链接数。"""
    files = sum(
        step.op == "write_file" or (step.op == "remove_path" and step.entry_kind == "file")
        for step in plan.steps
    )
    links = sum(
        step.op == "set_link" or (step.op == "remove_path" and step.entry_kind == "symlink")
        for step in plan.steps
    )
    return files, links


def _discard_after_commit(directory: Path) -> None:
    """提交点已过：删日志失败只记警告，恢复流程见到"已提交"的记录会补删，不能回滚已提交的写入。"""
    try:
        discard_journal(directory)
    except ExternalError:
        logger.warning("变更记录已落盘，但删除写入日志失败：%s", directory.name, exc_info=True)


@dataclass(frozen=True)
class _InFlight:
    """持锁写入中的一次作业：归档和退回需要的全部上下文。

    Attributes:
        context: 当前写入作业的执行上下文。
        dependencies: 写入依赖。
        preview: 预览作业保存的结果，其 plan 是正在执行的计划。
        actor: 提交人身份快照，写进变更记录。
        journal: 已落盘的写入日志内容。
        directory: 写入日志目录。
        started: 开始写入的 UTC 时刻。
    """

    context: ExecutionContext
    dependencies: NavWriteDependencies
    preview: NavPreview
    actor: ActorRef
    journal: Journal
    directory: Path
    started: datetime

    def archive(self, outcome: ChangeOutcome, finished: datetime) -> None:
        """归档写入日志；只有提交才带计划（后像）。"""
        committed = outcome is ChangeOutcome.COMMITTED
        archive_journal(
            self.dependencies.paths,
            self.directory,
            self.journal,
            ArchiveRequest(
                outcome=outcome,
                actor_id=self.actor.account_id,
                actor_name=self.actor.name,
                preview_job_id=self.preview.preview_job_id,
                started_at=self.started,
                finished_at=finished,
                plan=self.preview.plan if committed else None,
                report=self.preview.report,
                mismatches=(),
            ),
        )

    def roll_back(self) -> None:
        """同一次持锁内按前像退回；退不回的设恢复失败标记并保留日志。"""
        nav_root = Path(self.preview.plan.state.nav_root)
        try:
            stuck = rollback_journal(
                nav_root, self.directory, self.journal, checkpoint=_no_checkpoint
            ).mismatches
        except (InputError, ExternalError):
            stuck = (
                MismatchItem(
                    job_id=self.journal.job_id,
                    step_index=0,
                    path=f"nav-journal/{self.journal.job_id}",
                    expected_before="日志可用于回滚",
                    expected_after="日志可用于回滚",
                    actual="回滚时读取日志或前像失败",
                ),
            )
        if stuck:
            with session_scope(self.dependencies.rescan.engine) as session:
                record_recovery_block(session, stuck, now=self.context.clock.now())
            return
        self.archive(ChangeOutcome.ROLLED_BACK, self.context.clock.now())
        _discard_after_commit(self.directory)


class _Progress:
    """阶段进度与累计警告；提交之后的失败只计警告。"""

    def __init__(self, context: ExecutionContext) -> None:
        """绑定上下文。"""
        self.context = context
        self.warnings = 0

    def stage(self, index: int) -> None:
        """进入第 index 个阶段（1 起），上报一次进度。"""
        self.context.reporter.report(
            JobProgress(
                stage_index=index,
                stage_count=len(STAGES),
                stage_name=STAGES[index - 1],
                done=0,
                total=1,
                unit="阶段",
                warning_count=self.warnings,
                failed_items=0,
                total_items=index - 1,
            )
        )

    def finish(self, skipped: tuple[str, ...] = ()) -> None:
        """全部阶段完成：把累计警告数连同最后一阶段的完成上报一次。"""
        self.context.reporter.report(
            JobProgress(
                stage_index=len(STAGES),
                stage_count=len(STAGES),
                stage_name=(
                    STAGES[-1] + ("；已删除数据集不统计：" + "、".join(skipped) if skipped else "")
                )[:JOB_TEXT_MAX_CHARS],
                done=1,
                total=1,
                unit="阶段",
                warning_count=self.warnings,
                failed_items=0,
                total_items=len(STAGES),
            )
        )

    def warn(self, stage: str, error: Exception) -> None:
        """提交之后的失败：记一条警告诊断并累计，不回滚导航层。"""
        self.warnings += 1
        logger.warning(
            "写导航层作业 #%s 的%s失败，导航层已写好", self.context.job_id, stage, exc_info=True
        )
        self.context.reporter.diagnostic(
            Diagnostic(
                level=DiagnosticLevel.WARNING,
                category=DiagnosticCategory.EXTERNAL,
                stage=stage,
                source="平台",
                objects=(),
                rule="NAV_POST_COMMIT_FAILED",
                actual=f"{stage}失败：{type(error).__name__}",
                expected=None,
                consequence="导航层已经写好并有变更记录；索引或统计稍后由定时重新扫描补上",
                next_step="无需处理；若长期不更新，查看 worker 日志",
            )
        )


def _after_commit[T](progress: _Progress, stage: str, action: Callable[[], T], fallback: T) -> T:
    """提交之后的阶段：失败只记警告，返回回退值。"""
    try:
        return action()
    except (ConflictError, ExternalError, InputError, DefectError) as error:
        progress.warn(stage, error)
        return fallback


def _load_preview(dependencies: NavWriteDependencies, preview_job_id: int) -> NavPreview:
    """读预览并核对它属于当前导航根、预览作业成功结束。"""
    preview = read_preview(dependencies.paths, preview_job_id)
    if preview.plan.state.nav_root != str(dependencies.rescan.nav_root):
        problem = nav_input_error(
            _RULE,
            "预览属于另一个导航根，不能执行",
            objects=(("preview_job_id", str(preview_job_id)),),
        )
        raise problem
    with session_scope(dependencies.rescan.engine, read_only=True) as session:
        state = find_job(session, preview_job_id).state
    if state is not JobState.COMPLETED:
        problem = nav_input_error(
            _RULE,
            "预览作业没有成功结束，不能执行",
            objects=(("preview_job_id", str(preview_job_id)),),
        )
        raise problem
    return preview


def _audit_success(
    dependencies: NavWriteDependencies,
    context: ExecutionContext,
    submitter: ActorRef,
    result: ApplyResult,
    has_record: bool,
) -> None:
    """成功（含无事可做）的操作日志，带变更记录编号。"""
    event = navigation_operation_event(
        NavigationAuditFacts(
            operation=OperationType(result.operation.value),
            job_id=result.job_id,
            actor=submitter,
            context=OPS_AUDIT_CONTEXT,
            occurred_at=context.clock.now(),
            result=OperationResult.SUCCESS,
            failure_category=None,
            dataset_ids=result.dataset_ids[:AUDIT_DATASET_ID_LIMIT],
            dataset_count=len(result.dataset_ids),
            file_count=result.file_count,
            link_count=result.link_count,
            change_record_id=str(result.job_id) if has_record else None,
            reverts_job_id=None,
        )
    )
    append_navigation_audit(dependencies.rescan.engine, event)


def _audit_failure(
    dependencies: NavWriteDependencies,
    context: ExecutionContext,
    preview: NavPreview,
    submitter: ActorRef,
    error: Exception,
) -> None:
    """写入失败（冲突或已退回）也留一条失败的操作日志；补记失败不掩盖原异常。"""
    category = getattr(error, "category", DiagnosticCategory.EXTERNAL)
    plan = preview.plan
    has_record = (dependencies.paths.nav_changes / f"{context.job_id}.json.gz").exists()
    try:
        event = navigation_operation_event(
            NavigationAuditFacts(
                operation=OperationType(plan.operation.value),
                job_id=context.job_id,
                actor=submitter,
                context=OPS_AUDIT_CONTEXT,
                occurred_at=context.clock.now(),
                result=OperationResult.FAILURE,
                failure_category=category,
                dataset_ids=plan.dataset_ids[:AUDIT_DATASET_ID_LIMIT],
                dataset_count=len(plan.dataset_ids),
                file_count=0,
                link_count=0,
                change_record_id=str(context.job_id) if has_record else None,
                reverts_job_id=plan.reverts_job_id,
            )
        )
        append_navigation_audit(dependencies.rescan.engine, event)
    except Exception:
        logger.error("写导航层失败的操作日志补记失败 job_id=%s", context.job_id, exc_info=True)


def _sizing_scope(
    context: ExecutionContext, dependencies: NavWriteDependencies, plan: NavWritePlan
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """以导航事实核对统计范围；索引发布失败时也不能给已删除入口提交统计。"""
    remaining: list[str] = []
    removed: list[str] = []
    for identifier in plan.dataset_ids:
        known = tuple(
            entry.path
            for dataset in plan.state.datasets
            if dataset.dataset_id == identifier
            for entry in dataset.entries
        )
        if plan.state.new_dataset is not None:
            known = (*known, plan.state.new_dataset.destination_path)
        observed = fingerprint_dataset(
            dependencies.rescan.nav_root,
            identifier,
            known_entry_paths=known,
            checkpoint=context.reporter.check_cancelled,
        )
        if not observed.verifiable:
            problem = nav_input_error("NAV_SIZING_SCOPE", "写入后数据集状态不可验证，未提交统计")
            raise problem
        if any(entry.state is FileState.PRESENT for entry in observed.entries):
            remaining.append(identifier)
        else:
            removed.append(identifier)
    return tuple(remaining), tuple(removed)
