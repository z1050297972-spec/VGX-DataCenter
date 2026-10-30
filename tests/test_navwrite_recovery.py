"""中断恢复与恢复失败标记的契约测试（M1-07，L14，验收 1 的恢复部分、验收 4）。

用假导航层和临时状态目录，不起真实 worker；kill -9 演练见 test_navwrite_atomic.py。
"""

import time
from collections.abc import Callable, Generator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path

import pytest
from jobs_loop_support import running_loop, wait_for
from jobs_scheduling_execution_support import scheduling_case
from jobs_storage_support import job_database, job_row
from navwrite_support import (
    audit_details,
    commit_keep_journal,
    noop,
    plan_for,
    simple_nav,
    tree_state,
)
from sqlalchemy import Engine, select

from rdp.audit.models import OperationLogRow
from rdp.infra.db.connection import session_scope
from rdp.infra.diagnostics import InputError
from rdp.infra.state import StatePaths
from rdp.jobs.example import execute_count
from rdp.jobs.execution import ExecutionContext
from rdp.jobs.models import JobRow
from rdp.jobs.navwrite import recovery as recovery_module
from rdp.jobs.navwrite.atomic import apply_plan, capture_before_images
from rdp.jobs.navwrite.changes import ArchiveRequest, ChangeOutcome, read_change_record
from rdp.jobs.navwrite.journal import (
    Journal,
    journal_directory,
    list_journals,
    write_journal,
)
from rdp.jobs.navwrite.marker import (
    is_navigation_write_blocked,
    read_recovery_block,
)
from rdp.jobs.navwrite.models import NavWritePlan
from rdp.jobs.navwrite.recovery import (
    JournalFate,
    RecoveryDependencies,
    recover_journal,
    recover_navigation_writes,
)
from rdp.jobs.navwrite.wiring import build_navigation_callbacks
from rdp.jobs.types import JobClock, JobState

WHEN = datetime(2026, 10, 29, 12, tzinfo=UTC)
JOB = 5


@dataclass(frozen=True)
class Case:
    """一个恢复用例：库、状态目录、导航树、依赖和计划。"""

    engine: Engine
    paths: StatePaths
    nav: Path
    plan: NavWritePlan
    dependencies: RecoveryDependencies


@contextmanager
def _case(tmp_path: Path) -> Generator[Case]:
    """带标记表和操作日志表的临时库，加一棵最小导航树。"""
    with job_database(tmp_path) as (engine, paths):
        nav, steps = simple_nav(tmp_path)
        plan = plan_for(nav, steps, ids=())
        clock = JobClock(lambda: WHEN, time.monotonic)
        yield Case(engine, paths, nav, plan, RecoveryDependencies(engine, paths, nav, clock))


def _crash(case: Case, job_id: int = JOB, *, applied: int | None = None) -> None:
    """模拟写到一半断电：日志已落盘，导航层已写了前 applied 步（None 为全部）。"""
    images = capture_before_images(case.nav, case.plan)
    write_journal(case.paths, case.plan, images, job_id, WHEN)
    steps = case.plan.steps if applied is None else case.plan.steps[:applied]
    apply_plan(case.nav, case.plan.model_copy(update={"steps": steps}), job_id, checkpoint=noop)


def _recover(case: Case, job_id: int = JOB) -> recovery_module.JournalRecovery:
    """恢复指定作业的那份日志。"""
    (location,) = (item for item in list_journals(case.paths) if item.job_id == job_id)
    return recover_journal(case.dependencies, location, checkpoint=noop)


def _marker_blocked(case: Case) -> bool:
    """只读事务里看标记。"""
    with session_scope(case.engine, read_only=True) as session:
        return is_navigation_write_blocked(session)


def test_recovery_state_equals_after_is_restored(tmp_path: Path) -> None:
    """L14 样一：磁盘等于后像的项退回前像。"""
    with _case(tmp_path) as case:
        original = tree_state(case.nav)
        _crash(case)
        assert tree_state(case.nav) != original
        result = _recover(case)
        assert result.fate is JournalFate.ROLLED_BACK and result.restored_count == 5
        assert result.mismatches == () and tree_state(case.nav) == original
        assert not journal_directory(case.paths, JOB).exists()
        assert read_change_record(case.paths, JOB).outcome is ChangeOutcome.ROLLED_BACK_BY_RECOVERY
        assert _marker_blocked(case) is False


def test_recovery_state_equals_before_is_untouched(tmp_path: Path) -> None:
    """L14 样二：磁盘等于前像的项不动。"""
    with _case(tmp_path) as case:
        original = tree_state(case.nav)
        _crash(case, applied=0)  # 日志落了，一步都还没写
        result = _recover(case)
        assert result.fate is JournalFate.ROLLED_BACK and result.restored_count == 0
        assert tree_state(case.nav) == original and list_journals(case.paths) == ()
        # 只做了前两步：做了的退回，没做的不动。
        _crash(case, JOB + 1, applied=2)
        assert _recover(case, JOB + 1).restored_count == 2
        assert tree_state(case.nav) == original


def test_recovery_neither_stops_and_lists(tmp_path: Path) -> None:
    """L14 样三：两者都不是的项不动，列出，作业标恢复失败（设标记）。"""
    with _case(tmp_path) as case:
        _crash(case)
        (case.nav / "b.json").write_bytes("有人在终端里改过\n".encode())
        report = recover_navigation_writes(case.dependencies, checkpoint=noop)
        (journal,) = report.journals
        assert journal.fate is JournalFate.MISMATCH and report.blocked is True
        assert [(m.job_id, m.step_index, m.path) for m in journal.mismatches] == [
            (JOB, 2, "b.json")
        ]
        assert (case.nav / "b.json").read_bytes() == "有人在终端里改过\n".encode()
        assert (case.nav / "a.json").read_bytes() == b'{"v": 1}\n'  # 能退回的照样退回
        assert journal.restored_count == 4
        with session_scope(case.engine, read_only=True) as session:
            block = read_recovery_block(session)
        assert block is not None and block.job_ids == (JOB,) and block.total_items == 1


def test_recovery_incomplete_journal_is_discarded(tmp_path: Path) -> None:
    """L13：没有 journal.json 的日志目录说明导航层没动，直接删除，fate 为 INCOMPLETE_DISCARDED。"""
    with _case(tmp_path) as case:
        original = tree_state(case.nav)
        half = journal_directory(case.paths, JOB)
        (half / "images").mkdir(parents=True)
        (half / "journal.json.tmp").write_text("{", encoding="utf-8")
        report = recover_navigation_writes(case.dependencies, checkpoint=noop)
        assert [j.fate for j in report.journals] == [JournalFate.INCOMPLETE_DISCARDED]
        assert not half.exists() and tree_state(case.nav) == original and report.blocked is False


def test_recovery_committed_record_with_leftover_journal_is_not_rolled_back(
    tmp_path: Path,
) -> None:
    """契约 recover_journal：日志与 outcome 为 committed 的变更记录并存时只删日志，不回滚（写完了，崩在删日志之前）。"""
    with _case(tmp_path) as case:
        commit_keep_journal(case.paths, case.nav, case.plan, JOB)  # 提交点已过，日志还在
        written = tree_state(case.nav)
        result = _recover(case)
        assert result.fate is JournalFate.ALREADY_COMMITTED and result.restored_count == 0
        assert tree_state(case.nav) == written  # 没有回滚
        assert not journal_directory(case.paths, JOB).exists()
        assert read_change_record(case.paths, JOB).outcome is ChangeOutcome.COMMITTED


def test_recovery_archives_then_deletes_journal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Comments (3)：回滚完成后，先归档进变更记录（rolled_back_by_recovery），再删日志，顺序可断言。"""
    with _case(tmp_path) as case:
        _crash(case)
        events: list[str] = []
        real_archive, real_discard = (
            recovery_module.archive_journal,
            recovery_module.discard_journal,
        )

        def archive(
            state: StatePaths, journal_dir: Path, journal: Journal, request: ArchiveRequest
        ) -> Path:
            assert journal_directory(case.paths, JOB).exists()
            events.append("archive")
            return real_archive(state, journal_dir, journal, request)

        def discard(directory: Path) -> None:
            assert (case.paths.nav_changes / f"{JOB}.json.gz").is_file()  # 归档已落盘
            events.append("discard")
            real_discard(directory)

        monkeypatch.setattr(recovery_module, "archive_journal", archive)
        monkeypatch.setattr(recovery_module, "discard_journal", discard)
        _recover(case)
        assert events == ["archive", "discard"]


def test_recovery_failure_keeps_journal_for_admin(tmp_path: Path) -> None:
    """Comments (4)：MISMATCH 时日志保留，供管理员核对。"""
    with _case(tmp_path) as case:
        _crash(case)
        (case.nav / "a.json").write_bytes(b"{}\n")
        result = _recover(case)
        assert result.fate is JournalFate.MISMATCH
        assert journal_directory(
            case.paths,
            JOB,
        ).is_dir()
        assert [item.job_id for item in list_journals(case.paths)] == [JOB]
        assert not (case.paths.nav_changes / f"{JOB}.json.gz").exists()  # 没有收尾，不写记录


def test_recovery_is_idempotent_after_crash_at_any_step(tmp_path: Path) -> None:
    """契约 recover_journal：在回滚中途再次崩溃后重新运行，结论相同。"""
    for crash_at in range(1, 6):  # 五步计划，回滚在每一步之前各调用一次检查点
        with _case(tmp_path / f"c{crash_at}") as case:
            (tmp_path / f"c{crash_at}").mkdir(exist_ok=True)
            original = tree_state(case.nav)
            _crash(case)
            dying = _dying_after(crash_at)

            (location,) = list_journals(case.paths)
            with pytest.raises(RuntimeError):
                recover_journal(case.dependencies, location, checkpoint=dying)
            again = _recover(case)
            assert again.fate is JournalFate.ROLLED_BACK
            assert tree_state(case.nav) == original and list_journals(case.paths) == ()


def _dying_after(crash_at: int) -> Callable[[], None]:
    """第 crash_at 次被调用时抛出，模拟恢复到一半又断电。"""
    calls = [0]

    def checkpoint() -> None:
        calls[0] += 1
        if calls[0] == crash_at:
            raise RuntimeError("恢复到一半又断电")

    return checkpoint


def test_recovery_runs_before_any_write_job_claim(tmp_path: Path) -> None:
    """验收 4：恢复流程跑完以前，别的写作业不开始；用 ExecutorDependencies.recover_navigation 的调用顺序断言。"""
    events: list[str] = []

    def execute(context: ExecutionContext) -> None:
        events.append("execute")
        execute_count(context)

    def recover() -> None:
        events.append("recover-start")
        time.sleep(0.05)  # 恢复期间 worker 不得领取任何作业
        events.append("recover-end")

    with scheduling_case(tmp_path, execute=execute, writes_navigation=frozenset({"a"})) as case:
        case.add(71, "a")
        dependencies = replace(case.dependencies, recover_navigation=recover)
        with running_loop(dependencies):
            wait_for(lambda: case.get(71).state is JobState.COMPLETED)
    assert events == ["recover-start", "recover-end", "execute"]


def test_recovery_failure_marker_survives_worker_restart(tmp_path: Path) -> None:
    """ADR 0005 修订：重启 worker 不清除标记，写作业继续被挡住。"""
    with _case(tmp_path) as case:
        _crash(case)
        (case.nav / "b.json").write_bytes(b"{}\n")
        recover_navigation_writes(case.dependencies, checkpoint=noop)
        restarted = replace(case.dependencies, engine=case.engine)
        report = recover_navigation_writes(restarted, checkpoint=noop)  # 重启后再跑一遍
        assert report.blocked is True and _marker_blocked(case) is True
        assert [j.job_id for j in report.journals] == [JOB]  # 日志还在，仍然对不上


def test_blocked_write_jobs_stay_queued_others_run(tmp_path: Path) -> None:
    """Comments (1)、(7)：标记在时 writes_navigation 的作业留在排队中，其他类型（含重新扫描）照常运行。"""
    with scheduling_case(tmp_path, writes_navigation=frozenset({"a"})) as case:
        case.add(71, "a")
        case.add(72, "a")
        case.add(73, "b")
        blocked = [True]
        from rdp.jobs.scheduling import Scheduler

        scheduler = Scheduler(
            replace(case.dependencies, navigation_blocked=lambda: blocked[0]),
            case.resources,
            recovered=(),
        )
        work = scheduler.claim_next()
        assert work is not None and work.record.job_id == 73  # 不写导航层的类型照常领取
        assert scheduler.claim_next() is None
        assert case.get(71).state is JobState.QUEUED and case.get(72).state is JobState.QUEUED
        blocked[0] = False  # 管理员确认之后下一轮即放行
        released = scheduler.claim_next()
        assert released is not None and released.record.job_id == 71
        for item in (work, released):
            assert item.claim is not None
            case.resources.pool.release(item.claim)


def test_recovery_failure_job_stays_interrupted(tmp_path: Path) -> None:
    """Comments (1)：作业状态仍是已中断，没有新增状态，也没有作业结果。"""
    assert {state.value for state in JobState} == {
        "queued",
        "running",
        "cancelling",
        "completed",
        "cancelled",
        "interrupted",
    }
    with _case(tmp_path) as case:
        with session_scope(case.engine) as session:
            session.add(job_row(JobState.INTERRUPTED, job_id=JOB))
        _crash(case)
        (case.nav / "b.json").write_bytes(b"{}\n")
        recover_navigation_writes(case.dependencies, checkpoint=noop)
        with session_scope(case.engine, read_only=True) as session:
            row = session.get(JobRow, JOB)
        assert row is not None and row.state == "interrupted"
        assert row.summary is not None and row.summary["outcome"] is None  # 没有作业结果


def test_recovery_appends_audit_per_journal(tmp_path: Path) -> None:
    """L15：每份日志追加一条 rollback_navigation_write 操作日志，系统身份，失败的带 conflict 类别。"""
    with _case(tmp_path) as case:
        _crash(case)  # JOB：回滚成功
        stuck = journal_directory(case.paths, JOB + 1)
        (stuck / "images").mkdir(parents=True)  # JOB+1：不完整，直接删除
        (stuck / "journal.json.tmp").write_text("{", encoding="utf-8")
        recover_navigation_writes(case.dependencies, checkpoint=noop)
        with session_scope(case.engine, read_only=True) as session:
            rows = (
                session.execute(select(OperationLogRow).order_by(OperationLogRow.log_id))
                .scalars()
                .all()
            )
        assert [r.object_id for r in rows] == [str(JOB), str(JOB + 1)]
        assert {r.operation for r in rows} == {"rollback_navigation_write"}
        assert {(r.actor_id, r.actor_name, r.object_kind) for r in rows} == {
            (None, "系统", "navigation_write")
        }
        assert rows[0].result == "success" and audit_details(rows[0])["after"]["file_count"] == 3
        assert audit_details(rows[0])["after"]["change_record_id"] == str(JOB)
    with _case(tmp_path / "mismatch") as case:
        (tmp_path / "mismatch").mkdir(exist_ok=True)
        _crash(case)
        (case.nav / "a.json").write_bytes(b"{}\n")
        recover_navigation_writes(case.dependencies, checkpoint=noop)
        with session_scope(case.engine, read_only=True) as session:
            (row,) = session.execute(select(OperationLogRow)).scalars().all()
        assert row.result == "failure" and row.failure_category == "conflict"
        assert audit_details(row)["after"] == {}  # 失败事件的 after 按 M0 约定为空


def test_recovery_rejects_journal_for_other_nav_root(tmp_path: Path) -> None:
    """契约 recover_navigation_writes：日志的 nav_root 与当前配置不同时报 InputError，不回滚。"""
    with _case(tmp_path) as case:
        _crash(case)
        written = tree_state(case.nav)
        other = tmp_path / "other-root"
        other.mkdir()
        wrong = replace(case.dependencies, nav_root=other)
        with pytest.raises(InputError):
            recover_navigation_writes(wrong, checkpoint=noop)
        assert tree_state(case.nav) == written and tree_state(other) == {}
        assert list_journals(case.paths) != ()


def test_recovery_corrupt_journal_is_mismatch_not_crash(tmp_path: Path) -> None:
    """契约 recover_navigation_writes：journal.json 损坏时按 MISMATCH 保留，不抛，不删。"""
    with _case(tmp_path) as case:
        broken = journal_directory(case.paths, JOB)
        broken.mkdir(parents=True)
        (broken / "journal.json").write_text("{坏", encoding="utf-8")
        report = recover_navigation_writes(case.dependencies, checkpoint=noop)
        (journal,) = report.journals
        assert journal.fate is JournalFate.MISMATCH and len(journal.mismatches) == 1
        assert (broken / "journal.json").is_file() and report.blocked is True
        assert _marker_blocked(case) is True


def test_recovery_merges_new_items_into_existing_marker(tmp_path: Path) -> None:
    """契约 recover_navigation_writes：已有标记时仍处理新日志，对不上的并入标记，不清除。"""
    with _case(tmp_path) as case:
        _crash(case)
        (case.nav / "b.json").write_bytes(b"{}\n")
        recover_navigation_writes(case.dependencies, checkpoint=noop)
        other = journal_directory(case.paths, JOB + 2)
        other.mkdir()
        (other / "journal.json").write_text("{坏", encoding="utf-8")
        report = recover_navigation_writes(case.dependencies, checkpoint=noop)
        assert report.blocked is True
        with session_scope(case.engine, read_only=True) as session:
            block = read_recovery_block(session)
        assert block is not None and block.job_ids == (JOB, JOB + 2)
        assert {i.job_id for i in block.items} == {JOB, JOB + 2}


def test_recovery_with_no_journals(tmp_path: Path) -> None:
    """契约 recover_navigation_writes：没有日志时 journals 为空，blocked 取决于是否已有标记。"""
    with _case(tmp_path) as case:
        report = recover_navigation_writes(case.dependencies, checkpoint=noop)
        assert report.journals == () and report.blocked is False
        _crash(case)
        (case.nav / "b.json").write_bytes(b"{}\n")
        recover_navigation_writes(case.dependencies, checkpoint=noop)
        # 管理员处理前日志在、标记在；新一轮没有新日志可处理，仍然被挡住。
        for location in list_journals(case.paths):
            assert location.job_id == JOB
        assert is_blocked_after_restart(case) is True


def is_blocked_after_restart(case: Case) -> bool:
    """用全新的恢复调用读标记，确认仍被挡住。"""
    return recover_navigation_writes(case.dependencies, checkpoint=noop).blocked


def test_wiring_callbacks_recover_and_report_block(tmp_path: Path) -> None:
    """Worker 装配：recover_navigation 回调跑启动恢复，navigation_blocked 回调只读标记。"""
    with _case(tmp_path) as case:
        recover, blocked = build_navigation_callbacks(
            case.engine, case.paths, case.nav, case.dependencies.clock
        )
        _crash(case)
        (case.nav / "b.json").write_bytes(b"{}\n")
        assert blocked() is False  # 日志还没处理，标记还没设
        recover()
        assert blocked() is True and _marker_blocked(case) is True
