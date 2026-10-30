"""启动时的中断恢复（worker 写入侧，领域层，M1-07，ADR 0009 L14、ADR 0005 修订）。

worker 启动顺序：拿单实例锁 → 把上一个实例的"运行中"作业判为已中断（M0）→ 本模块的
recover_navigation_writes → 之后才领取任何作业。恢复期间还没有任何作业在跑，所以不拿导航层写锁。
本模块只做编排：回滚用 atomic.rollback_journal，归档用 changes，标记用 marker，
每一份日志产生一条操作日志。不做决策之外的写。
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path

from sqlalchemy import Engine

from rdp.audit.records import append_operation
from rdp.audit.types import OPS_AUDIT_CONTEXT, OperationEvent, OperationResult, OperationType
from rdp.infra.actors import SYSTEM_ACTOR
from rdp.infra.db.connection import session_scope
from rdp.infra.diagnostics import DiagnosticCategory, InputError
from rdp.infra.state import StatePaths
from rdp.jobs.navwrite.atomic import rollback_journal
from rdp.jobs.navwrite.audit import NavigationAuditFacts, navigation_operation_event
from rdp.jobs.navwrite.changes import (
    ArchiveRequest,
    ChangeOutcome,
    archive_journal,
    change_record_path,
    read_change_record,
)
from rdp.jobs.navwrite.errors import nav_input_error
from rdp.jobs.navwrite.journal import (
    Journal,
    JournalLocation,
    discard_journal,
    list_journals,
    read_journal,
)
from rdp.jobs.navwrite.marker import is_navigation_write_blocked, record_recovery_block
from rdp.jobs.navwrite.models import MismatchItem
from rdp.jobs.types import JobClock


class JournalFate(StrEnum):
    """一份写入日志的处理结果。

    Attributes:
        INCOMPLETE_DISCARDED: incomplete_discarded，日志没落完整（无 journal.json），导航层未动，已删除。
        ALREADY_COMMITTED: already_committed，日志与一份"已提交"的变更记录并存，说明写完了、只差删日志，
            已删除日志，不回滚。
        ROLLED_BACK: rolled_back，全部退回前像，已归档并删除日志；作业是"已中断"。
        MISMATCH: mismatch，有两者都不是的项，能退的已退，日志保留，已设置恢复失败标记。
    """

    INCOMPLETE_DISCARDED = "incomplete_discarded"
    ALREADY_COMMITTED = "already_committed"
    ROLLED_BACK = "rolled_back"
    MISMATCH = "mismatch"


@dataclass(frozen=True)
class JournalRecovery:
    """一份写入日志的恢复结果。

    Attributes:
        job_id: 日志所属作业编号，≥ 1。
        fate: 处理结果。
        restored_count: 退回了前像的步骤数，≥ 0。
        mismatches: 对不上的项；仅 MISMATCH 非空。
    """

    job_id: int
    fate: JournalFate
    restored_count: int
    mismatches: tuple[MismatchItem, ...]


@dataclass(frozen=True)
class RecoveryReport:
    """一次启动恢复的总结果。

    Attributes:
        journals: 每份日志的结果，按作业编号升序；没有日志时为空元组。
        blocked: 是否存在恢复失败标记（本次新设的，或此前就有、尚未被管理员确认的）。
    """

    journals: tuple[JournalRecovery, ...]
    blocked: bool


@dataclass(frozen=True)
class RecoveryDependencies:
    """启动恢复所需的显式依赖，由 worker 装配。

    Attributes:
        engine: 已迁移的受管 SQLite 引擎，用来读写恢复失败标记和操作日志。
        paths: 已初始化的状态布局。
        nav_root: 导航层根目录绝对路径。
        clock: 注入时钟，墙钟写操作日志和标记，不读系统时间。
    """

    engine: Engine
    paths: StatePaths
    nav_root: Path
    clock: JobClock


def recover_navigation_writes(
    dependencies: RecoveryDependencies, *, checkpoint: Callable[[], None]
) -> RecoveryReport:
    """读每一份还在的写入日志，逐项比对、回滚，决定是否设置"导航层恢复失败"标记。

    Args:
        dependencies: 恢复所需依赖。
        checkpoint: 必填检查点，在日志之间调用；回滚中的单份日志不被它打断。

    Returns:
        RecoveryReport。没有日志时 journals 为空，blocked 取决于是否已有标记。已有标记时仍处理新发现的日志
        （能退回的退回、对不上的并入标记），但不清除标记：清除只能由管理员确认（marker.acknowledge_recovery_block）。

    Raises:
        InputError: 状态目录结构损坏（例如 journal.json 无法解析）：该日志按 MISMATCH 处理并保留，不抛；
            只有 nav_root 与日志不是同一个导航根时才在此抛出，避免对错误的树做回滚。
        ExternalError: 无法枚举 nav-journal，或数据库写入标记/操作日志失败（worker 启动失败，由 systemd 重试）。
        WorkerStoppingError: 日志之间的 checkpoint 检出 worker 停止。

    Side Effects:
        对每份日志调用 recover_journal；有 MISMATCH 时写 marker（同一事务内合并对不上的项）；
        每份日志追加一条 rollback_navigation_write 操作日志。不放行任何作业（放行由作业循环在本函数返回之后做）。

    Time Semantics:
        只在 worker 启动、作业循环领取之前调用一次；不拿导航层写锁（此时没有别的写者，单实例锁已持有）。
        每份日志用 dependencies.clock.now() 取墙钟（UTC）。重启 worker 不会清除标记。
    """
    results: list[JournalRecovery] = []
    for location in list_journals(dependencies.paths):
        checkpoint()
        result = recover_journal(dependencies, location, checkpoint=checkpoint)
        results.append(result)
    now = dependencies.clock.now()
    mismatches = tuple(item for result in results for item in result.mismatches)
    with session_scope(dependencies.engine) as session:
        if mismatches:
            record_recovery_block(session, mismatches, now=now)
        for result in results:
            append_operation(session, _audit_event(dependencies, result, now))
        blocked = is_navigation_write_blocked(session)
    return RecoveryReport(tuple(results), blocked)


def recover_journal(
    dependencies: RecoveryDependencies,
    location: JournalLocation,
    *,
    checkpoint: Callable[[], None],
) -> JournalRecovery:
    """处理一份写入日志：不完整的删除，已提交的删日志，其余按日志回滚并归档。

    Args:
        dependencies: 恢复所需依赖。
        location: list_journals 发现的日志目录。
        checkpoint: 必填检查点。

    Returns:
        JournalRecovery。日志没有 journal.json 为 INCOMPLETE_DISCARDED；`nav-changes/<job_id>.json.gz` 已存在且
        outcome 为 committed 为 ALREADY_COMMITTED（写完了，崩在删日志之前，不回滚）；否则调用 rollback_journal：
        无对不上的项时归档为 rolled_back_by_recovery 并删除日志（ROLLED_BACK），有则保留日志（MISMATCH）。

    Raises:
        InputError: 日志的 nav_root 与当前配置不同。日志内容损坏不抛，按 MISMATCH 保留。
        ExternalError: 归档变更记录或删除日志失败：日志保留，下次启动重试，不当作成功。

    Side Effects:
        可能回滚导航层、写 nav-changes、删除 nav-journal/<job_id>。MISMATCH 不删日志，供管理员核对。

    Time Semantics:
        同 recover_navigation_writes；幂等，崩溃在任何一步之后重新运行得到同样的结论。
    """
    directory = location.directory
    if not location.complete:
        discard_journal(directory)
        return JournalRecovery(location.job_id, JournalFate.INCOMPLETE_DISCARDED, 0, ())
    try:
        journal = read_journal(directory)
    except InputError:
        return _unreadable(location, "日志损坏，无法回滚")
    if journal.nav_root != str(dependencies.nav_root):
        problem = nav_input_error(
            "NAV_RECOVERY",
            "写入日志属于另一个导航根，拒绝回滚",
            objects=(("job_id", str(journal.job_id)), ("journal_nav_root", journal.nav_root)),
        )
        raise problem
    if _already_committed(dependencies, journal):
        discard_journal(directory)
        return JournalRecovery(journal.job_id, JournalFate.ALREADY_COMMITTED, 0, ())
    try:
        outcome = rollback_journal(dependencies.nav_root, directory, journal, checkpoint=checkpoint)
    except InputError:
        return _unreadable(location, "前像文件损坏，无法回滚")
    if outcome.mismatches:
        return JournalRecovery(
            journal.job_id, JournalFate.MISMATCH, len(outcome.restored_steps), outcome.mismatches
        )
    archive_journal(
        dependencies.paths,
        directory,
        journal,
        ArchiveRequest(
            outcome=ChangeOutcome.ROLLED_BACK_BY_RECOVERY,
            actor_id=None,
            actor_name=SYSTEM_ACTOR.name,
            preview_job_id=None,
            started_at=journal.created_at,
            finished_at=dependencies.clock.now(),
            plan=None,
            report=None,
            mismatches=(),
        ),
    )
    discard_journal(directory)
    return JournalRecovery(journal.job_id, JournalFate.ROLLED_BACK, len(outcome.restored_steps), ())


def _unreadable(location: JournalLocation, reason: str) -> JournalRecovery:
    """日志本身读不了：不能自动回滚，按对不上的项保留供管理员核对。"""
    item = MismatchItem(
        job_id=location.job_id,
        step_index=0,
        path=f"nav-journal/{location.job_id}",
        expected_before="日志可读",
        expected_after="日志可读",
        actual=reason,
    )
    return JournalRecovery(location.job_id, JournalFate.MISMATCH, 0, (item,))


def _already_committed(dependencies: RecoveryDependencies, journal: Journal) -> bool:
    """变更记录已存在且是已提交：写完了，崩在删日志之前。"""
    if not change_record_path(dependencies.paths, journal.job_id).exists():
        return False
    try:
        record = read_change_record(dependencies.paths, journal.job_id)
    except InputError:
        return False
    return record.outcome is ChangeOutcome.COMMITTED


def _audit_event(
    dependencies: RecoveryDependencies, result: JournalRecovery, now: datetime
) -> OperationEvent:
    """每份日志一条 rollback_navigation_write 操作日志，系统身份。"""
    failed = result.fate is JournalFate.MISMATCH
    has_record = change_record_path(dependencies.paths, result.job_id).exists()
    files = links = 0
    if has_record and not failed:
        # 摘要里的计数是这份日志涉及的文件数和链接数（含本来就等于前像、没有动的步骤）。
        steps = read_change_record(dependencies.paths, result.job_id).steps
        files = sum(step.op == "write_file" for step in steps)
        links = sum(step.op == "set_link" for step in steps)
    return navigation_operation_event(
        NavigationAuditFacts(
            operation=OperationType.ROLLBACK_NAVIGATION_WRITE,
            job_id=result.job_id,
            actor=SYSTEM_ACTOR,
            context=OPS_AUDIT_CONTEXT,
            occurred_at=now,
            result=OperationResult.FAILURE if failed else OperationResult.SUCCESS,
            failure_category=DiagnosticCategory.CONFLICT if failed else None,
            dataset_ids=(),
            dataset_count=0,
            file_count=files,
            link_count=links,
            change_record_id=str(result.job_id) if has_record and not failed else None,
            reverts_job_id=None,
        )
    )
