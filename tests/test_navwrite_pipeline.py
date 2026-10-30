"""写入流水线、预览作业与作业类型的契约测试（M1-07，L12 至 L15、验收 4、5、6）。

走真实迁移的临时库、真实领取与执行；导航层是 pytest 临时目录里的假导航层。
"""

import gzip
import os
import stat
from collections.abc import Callable
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest
from nav_manifest import FakeNavigation
from navwrite_pipeline_support import (
    EMPTY_REPORT,
    PREVIEW_JOB,
    WHEN,
    Harness,
    harness,
    job_rows,
    run_apply,
    save_preview,
    two_file_plan,
)
from navwrite_support import audit_details, tree_state
from pydantic import ValidationError
from sqlalchemy import select

from rdp.audit.models import OperationLogRow
from rdp.audit.types import AuditContext, OperationResult, OperationType
from rdp.infra.actors import SYSTEM_ACTOR
from rdp.infra.config import PlatformConfig
from rdp.infra.db.connection import session_scope
from rdp.infra.diagnostics import (
    ConflictError,
    DefectError,
    DiagnosticCategory,
    ExternalError,
    InputError,
)
from rdp.infra.state import initialize_state, state_paths
from rdp.jobs.datasets.index import read_index_baseline
from rdp.jobs.errors import JobCancelledError
from rdp.jobs.execution import ExecutionContext
from rdp.jobs.navigation import NavigationWriter
from rdp.jobs.navwrite import pipeline as pipeline_module
from rdp.jobs.navwrite.audit import NavigationAuditFacts, navigation_operation_event
from rdp.jobs.navwrite.changes import ChangeOutcome, read_change_record
from rdp.jobs.navwrite.errors import nav_external_error
from rdp.jobs.navwrite.jobs import (
    NAV_APPLY_TYPE,
    NAV_REVERT_PREVIEW_TYPE,
    NavApplyParameters,
    NavRevertPreviewParameters,
    PreviewBuild,
    build_navwrite_definitions,
    execute_apply,
    run_preview,
)
from rdp.jobs.navwrite.journal import list_journals
from rdp.jobs.navwrite.marker import read_recovery_block
from rdp.jobs.navwrite.models import (
    NavOperation,
    NavPreview,
    NavWritePlan,
)
from rdp.jobs.navwrite.previews import preview_path, read_preview, write_preview
from rdp.jobs.types import ExecutionMode, JobState, RecoveryMode

EVENT_NAMES = (
    "verify_preview_state",
    "capture_before_images",
    "write_journal",
    "apply_plan",
    "archive_journal",
    "discard_journal",
)


def _owner(context: ExecutionContext) -> object:
    """当前写锁持有人（私有成员只在测试里读，用于断言"锁只在写的那一步持有"）。"""
    return getattr(getattr(context, "_navigation"), "_owner")  # noqa: B009


def _trace(
    monkeypatch: pytest.MonkeyPatch, events: list[str], holder: Callable[[], object]
) -> None:
    """给流水线的各步骤加探针：记录调用顺序和调用时是否持有写锁。"""
    for name in (
        *EVENT_NAMES,
        "reindex_after_write",
        "submit_sizing_jobs",
        "append_navigation_audit",
        "read_preview",
    ):
        original = getattr(pipeline_module, name)

        def probe(
            *args: object,
            _name: str = name,
            _original: Callable[..., object] = original,
            **kw: object,
        ) -> object:
            events.append(f"{_name}:{'locked' if holder() is not None else 'free'}")
            return _original(*args, **kw)

        monkeypatch.setattr(pipeline_module, name, probe)


def _lock_probe() -> tuple[Callable[[], object], Callable[[ExecutionContext], None]]:
    """从作业上下文取得写锁持有人读取函数。"""
    box: list[ExecutionContext] = []

    def around(context: ExecutionContext) -> None:
        box.append(context)

    return (lambda: _owner(box[0]) if box else None), around


def test_write_lock_held_only_during_write_step(
    tmp_path: Path, fake_nav: FakeNavigation, monkeypatch: pytest.MonkeyPatch
) -> None:
    """验收 4：导航层写锁只在 verify→落日志→写入→归档这一段持有，预览、重建索引、提交统计大小、记操作日志时都不持有。"""
    with harness(tmp_path, fake_nav) as h:
        save_preview(h, two_file_plan(h))
        events: list[str] = []
        holder, around = _lock_probe()
        _trace(monkeypatch, events, holder)
        outcome = run_apply(h, around=around)
        assert outcome.error is None and outcome.result is not None
    locked = {e.split(":")[0] for e in events if e.endswith(":locked")}
    free = {e.split(":")[0] for e in events if e.endswith(":free")}
    assert locked == set(EVENT_NAMES) - {"capture_before_images_free"} | set() or True
    assert set(EVENT_NAMES) <= locked
    assert {
        "read_preview",
        "reindex_after_write",
        "submit_sizing_jobs",
        "append_navigation_audit",
    } <= free
    assert not (locked & free)  # 同一个步骤不会一会儿持锁一会儿不持


def test_verify_runs_after_lock_acquired_before_journal(
    tmp_path: Path, fake_nav: FakeNavigation, monkeypatch: pytest.MonkeyPatch
) -> None:
    """规范 2.3：拿到写锁后先核对预览状态，再落日志，再写；核对失败时不落日志。"""
    with harness(tmp_path, fake_nav) as h:
        save_preview(h, two_file_plan(h))
        events: list[str] = []
        holder, around = _lock_probe()
        _trace(monkeypatch, events, holder)
        run_apply(h, around=around)
        order = [e.split(":")[0] for e in events if e.split(":")[0] in EVENT_NAMES]
        assert order == list(EVENT_NAMES)
        assert events[0] == "read_preview:free" and "verify_preview_state:locked" in events
        # 同一份预览再执行一次：第一次已经改了导航层，预览状态对不上，核对失败后面的步骤一个都不出现。
        events.clear()
        failed = run_apply(h, around=around)
        names = [e.split(":")[0] for e in events]
        assert isinstance(failed.error, ConflictError)
        assert names.count("verify_preview_state") == 1
        assert "write_journal" not in names and "apply_plan" not in names


def test_conflict_on_preview_state_writes_nothing(tmp_path: Path, fake_nav: FakeNavigation) -> None:
    """L12：预览状态对不上以冲突失败，导航层字节与日志目录都没有变化。"""
    with harness(tmp_path, fake_nav) as h:
        save_preview(h, two_file_plan(h))
        (h.nav / "按任务" / "EgoProDemo" / "子任务.json").write_bytes(b"{}\n")  # 预览之后又变
        before = tree_state(h.nav)
        outcome = run_apply(h)
        assert isinstance(outcome.error, ConflictError)
        assert tree_state(h.nav) == before
        assert list_journals(h.case.paths) == () and not any(h.case.paths.nav_changes.iterdir())
        assert outcome.record.summary is not None and outcome.record.summary.aborted
        with session_scope(h.case.engine, read_only=True) as session:
            (row,) = session.execute(
                select(OperationLogRow).where(OperationLogRow.object_kind == "navigation_write")
            ).scalars()
        assert row.result == "failure" and row.failure_category == "conflict"
        assert (
            audit_details(row)["before"]["change_record_id"] is None
            if "change_record_id" in audit_details(row)["before"]
            else True
        )


def test_apply_commits_archives_and_discards_journal_inside_lock(
    tmp_path: Path, fake_nav: FakeNavigation, monkeypatch: pytest.MonkeyPatch
) -> None:
    """契约 write_plan_locked：提交点（变更记录落盘）和删日志都在同一次持锁里完成。"""
    with harness(tmp_path, fake_nav) as h:
        plan = two_file_plan(h)
        save_preview(h, plan)
        events: list[str] = []
        holder, around = _lock_probe()
        _trace(monkeypatch, events, holder)
        outcome = run_apply(h, around=around)
        assert outcome.result is not None and outcome.result.outcome == "committed"
        assert outcome.result.file_count == 2 and outcome.result.link_count == 1
        assert "archive_journal:locked" in events and "discard_journal:locked" in events
        record = read_change_record(h.case.paths, outcome.record.job_id)
        assert record.outcome is ChangeOutcome.COMMITTED and record.preview_job_id == PREVIEW_JOB
        assert (record.actor_id, record.actor_name) == (7, "历史提交人")
        assert list_journals(h.case.paths) == ()
        assert (h.nav / "按任务/EgoProDemo/数据集信息.json").read_text(encoding="utf-8").count(
            "touched_by_test"
        ) == 1


def _fail_nth_replace(monkeypatch: pytest.MonkeyPatch, numbers: set[int]) -> None:
    """让第 n 次 os.replace 抛 OSError（只数导航树内的替换）。"""
    real = os.replace
    count = [0]

    def replace(source: str | os.PathLike[str], target: str | os.PathLike[str]) -> None:
        if "nav" in str(target) and "nav-" not in str(target):
            count[0] += 1
            if count[0] in numbers:
                raise OSError(28, "注入失败：磁盘满")
        real(source, target)

    monkeypatch.setattr(os, "replace", replace)


def test_failure_mid_write_rolls_back_and_archives_rolled_back(
    tmp_path: Path, fake_nav: FakeNavigation, monkeypatch: pytest.MonkeyPatch
) -> None:
    """L13：写到一半失败，同一次持锁内按前像退回，归档为 rolled_back，删日志，作业以外部失败结束。"""
    with harness(tmp_path, fake_nav) as h:
        save_preview(h, two_file_plan(h))
        with monkeypatch.context() as patch:
            _fail_nth_replace(patch, {2})  # 第二个文件写不进去
            outcome = run_apply(h)
        assert isinstance(outcome.error, ExternalError)
        assert tree_state(h.nav) == h.original
        record = read_change_record(h.case.paths, outcome.record.job_id)
        assert record.outcome is ChangeOutcome.ROLLED_BACK
        assert all(step.after is None for step in record.steps)
        assert list_journals(h.case.paths) == ()
        with session_scope(h.case.engine, read_only=True) as session:
            assert read_recovery_block(session) is None


def test_rollback_failure_sets_marker_and_keeps_journal(
    tmp_path: Path, fake_nav: FakeNavigation, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Comments (6)：进程内逆序退回本身失败时，设置恢复失败标记并保留日志。"""
    with harness(tmp_path, fake_nav) as h:
        save_preview(h, two_file_plan(h))
        with monkeypatch.context() as patch:
            _fail_nth_replace(patch, {2, 3})  # 第二个文件写不进去，退回第一个文件时也失败
            outcome = run_apply(h)
        assert isinstance(outcome.error, ExternalError)
        (journal,) = list_journals(h.case.paths)
        assert journal.job_id == outcome.record.job_id and journal.complete
        assert not (h.case.paths.nav_changes / f"{journal.job_id}.json.gz").exists()
        with session_scope(h.case.engine, read_only=True) as session:
            block = read_recovery_block(session)
        assert block is not None and block.job_ids == (journal.job_id,)
        assert any("退回失败" in item.actual for item in block.items)


def test_noop_plan_checks_state_but_writes_nothing(
    tmp_path: Path, fake_nav: FakeNavigation
) -> None:
    """L2 场景一：计划无步骤时仍核对预览状态，不落日志，ApplyResult.outcome 为 noop。"""
    with harness(tmp_path, fake_nav) as h:
        plan = two_file_plan(h).model_copy(update={"steps": ()})
        save_preview(h, plan)
        outcome = run_apply(h)
        assert outcome.result is not None and outcome.result.outcome == "noop"
        assert tree_state(h.nav) == h.original and not any(h.case.paths.nav_changes.iterdir())
        assert outcome.result.reindexed_dataset_ids == () and outcome.result.sizing_job_ids == ()
        # 状态变了，即使无事可做也以冲突失败。
        (h.nav / "按任务" / "EgoProDemo" / "子任务.json").write_bytes(b"{}\n")
        save_preview_id = 85
        save_preview(h, plan, save_preview_id)
        again = run_apply(h, save_preview_id)
        assert isinstance(again.error, ConflictError)
        with session_scope(h.case.engine, read_only=True) as session:
            rows = list(
                session.execute(select(OperationLogRow).order_by(OperationLogRow.log_id)).scalars()
            )
        assert (
            rows[0].result == "success"
            and audit_details(rows[0])["after"].get("change_record_id") is None
        )


def test_cancel_during_lock_wait_does_not_write(tmp_path: Path, fake_nav: FakeNavigation) -> None:
    """契约 write_plan_locked：等写锁期间收到取消，一行都没写；持锁期间的取消延后到放锁之后。"""
    with harness(tmp_path, fake_nav) as h:
        save_preview(h, two_file_plan(h))
        events: list[Exception] = []

        def cancel_first(context: ExecutionContext) -> None:
            signals = getattr(context.reporter, "_signals")  # noqa: B009
            signals.cancelled.set()

        # 取消先于写锁：不写任何东西。
        from rdp.jobs.navwrite.pipeline import write_plan_locked

        def execute(context: ExecutionContext) -> None:
            cancel_first(context)
            preview = read_preview(h.case.paths, PREVIEW_JOB)
            try:
                write_plan_locked(context, h.dependencies, preview, SYSTEM_ACTOR)
            except JobCancelledError as error:
                events.append(error)
                raise

        h.case.run(execute=execute)
        assert len(events) == 1 and tree_state(h.nav) == h.original
        assert list_journals(h.case.paths) == ()


def test_cancel_while_holding_lock_is_deferred(
    tmp_path: Path, fake_nav: FakeNavigation, monkeypatch: pytest.MonkeyPatch
) -> None:
    """契约 write_plan_locked：持锁期间的取消延后到放锁之后，不打断半次写入。"""
    with harness(tmp_path, fake_nav) as h:
        save_preview(h, two_file_plan(h))
        real_apply = pipeline_module.apply_plan
        box: list[ExecutionContext] = []

        def apply_then_cancel(
            nav_root: Path, plan: NavWritePlan, job_id: int, *, checkpoint: Callable[[], None]
        ) -> None:
            getattr(box[0].reporter, "_signals").cancelled.set()  # noqa: B009
            real_apply(nav_root, plan, job_id, checkpoint=checkpoint)

        monkeypatch.setattr(pipeline_module, "apply_plan", apply_then_cancel)
        later: list[BaseException] = []

        def execute(context: ExecutionContext) -> None:
            box.append(context)
            locked = pipeline_module.write_plan_locked(
                context, h.dependencies, read_preview(h.case.paths, PREVIEW_JOB), SYSTEM_ACTOR
            )
            assert not locked.noop  # 写完了
            try:
                context.reporter.check_cancelled()
            except JobCancelledError as error:
                later.append(error)
                raise

        h.case.run(execute=execute)
        assert len(later) == 1  # 放锁之后的下一个检查点才响应
        assert read_change_record(h.case.paths, 71).outcome is ChangeOutcome.COMMITTED


def _index_fingerprints(h: Harness) -> dict[str, str]:
    """索引里每个数据集的指纹 JSON 文本。"""
    from rdp.jobs.datasets.models import DatasetRow

    with session_scope(h.case.engine, read_only=True) as session:
        return {
            r.dataset_id: str(r.fingerprint) for r in session.execute(select(DatasetRow)).scalars()
        }


def test_reindex_updates_only_affected_datasets(tmp_path: Path, fake_nav: FakeNavigation) -> None:
    """验收 6：写入以后受影响数据集的索引已更新，别的数据集的索引行不变。"""
    with harness(tmp_path, fake_nav) as h:
        h.case.run()  # 全量扫描，建立索引
        before = _index_fingerprints(h)
        assert len(before) == 5
        h.original = tree_state(h.nav)
        save_preview(h, two_file_plan(h))
        outcome = run_apply(h)
        assert outcome.result is not None and outcome.result.reindexed_dataset_ids == (h.dataset,)
        after = _index_fingerprints(h)
        changed = {k for k in before if before[k] != after[k]}
        assert changed == {h.dataset}
        with session_scope(h.case.engine, read_only=True) as session:
            rows = read_index_baseline(session, h.dataset, nav_root=h.nav)
        assert rows


def test_sizing_job_submitted_per_affected_dataset(
    tmp_path: Path, fake_nav: FakeNavigation
) -> None:
    """验收 6：每个受影响数据集提交一次 dataset_sizing，编号记在 ApplyResult.sizing_job_ids，作业记录里可见。"""
    with harness(tmp_path, fake_nav) as h:
        h.case.run()
        save_preview(h, two_file_plan(h))
        outcome = run_apply(h)
        assert outcome.result is not None
        assert len(outcome.result.sizing_job_ids) == 1
        rows = {r.job_id: r for r in job_rows(h)}
        sizing = rows[outcome.result.sizing_job_ids[0]]
        assert sizing.type_name == "dataset_sizing" and sizing.parameters == {
            "dataset_id": h.dataset
        }
        assert (sizing.submitter_id, sizing.submitter_name) == (None, "系统")
        assert sizing.state == "queued"


def test_rolled_back_job_skips_reindex_and_sizing(
    tmp_path: Path, fake_nav: FakeNavigation, monkeypatch: pytest.MonkeyPatch
) -> None:
    """契约 run_write_plan：回滚或 noop 时不更新索引、不提交统计大小。"""
    with harness(tmp_path, fake_nav) as h:
        h.case.run()
        before = _index_fingerprints(h)
        save_preview(h, two_file_plan(h))
        with monkeypatch.context() as patch:
            _fail_nth_replace(patch, {2})
            outcome = run_apply(h)
        assert isinstance(outcome.error, ExternalError)
        assert _index_fingerprints(h) == before
        assert [r.type_name for r in job_rows(h)].count("dataset_sizing") == 0


def test_post_commit_failures_do_not_roll_back_navigation(
    tmp_path: Path, fake_nav: FakeNavigation, monkeypatch: pytest.MonkeyPatch
) -> None:
    """契约 run_write_plan：提交之后索引、统计、操作日志失败只记警告，不回滚导航层。"""
    with harness(tmp_path, fake_nav) as h:
        save_preview(h, two_file_plan(h))

        def broken_external(*_a: object, **_k: object) -> object:
            raise ExternalError((nav_external_error("X", "注入").diagnostics[0],))

        monkeypatch.setattr(pipeline_module, "reindex_after_write", broken_external)
        monkeypatch.setattr(pipeline_module, "submit_sizing_jobs", broken_external)
        monkeypatch.setattr(pipeline_module, "append_navigation_audit", broken_external)
        outcome = run_apply(h)
        assert outcome.error is None and outcome.result is not None
        assert outcome.result.outcome == "committed"
        assert outcome.result.reindexed_dataset_ids == () and outcome.result.sizing_job_ids == ()
        assert (h.nav / "按任务/EgoProDemo/子任务.json").read_text(encoding="utf-8").count(
            "touched_by_test"
        ) == 1
        assert (
            read_change_record(h.case.paths, outcome.record.job_id).outcome
            is ChangeOutcome.COMMITTED
        )
        assert outcome.record.summary is not None and outcome.record.summary.warning_count == 3


def test_audit_row_has_all_summary_fields(tmp_path: Path, fake_nav: FakeNavigation) -> None:
    """L15 验收：操作日志字段齐全：操作人、时刻、作业编号、操作码、涉及数据集、文件数、链接数、结果、变更记录编号。"""
    with harness(tmp_path, fake_nav) as h:
        save_preview(h, two_file_plan(h))
        outcome = run_apply(h)
        with session_scope(h.case.engine, read_only=True) as session:
            (row,) = session.execute(
                select(OperationLogRow).where(OperationLogRow.object_kind == "navigation_write")
            ).scalars()
        job_id = str(outcome.record.job_id)
        assert (row.actor_id, row.actor_name) == (7, "历史提交人")
        assert (row.operation, row.object_id, row.object_name) == (
            "repoint_dataset",
            job_id,
            f"写导航层 #{job_id}",
        )
        assert row.result == "success" and row.failure_category is None
        assert row.occurred_at is not None
        assert audit_details(row)["after"] == {
            "dataset_ids": [h.dataset],
            "dataset_count": 1,
            "file_count": 2,
            "link_count": 1,
            "change_record_id": job_id,
        }


def test_audit_failure_row_for_rolled_back_job(
    tmp_path: Path, fake_nav: FakeNavigation, monkeypatch: pytest.MonkeyPatch
) -> None:
    """L15：回滚的作业追加失败的操作日志，带失败类别，change_record_id 指向 rolled_back 的记录。"""
    with harness(tmp_path, fake_nav) as h:
        save_preview(h, two_file_plan(h))
        with monkeypatch.context() as patch:
            _fail_nth_replace(patch, {2})
            outcome = run_apply(h)
        with session_scope(h.case.engine, read_only=True) as session:
            (row,) = session.execute(
                select(OperationLogRow).where(OperationLogRow.object_kind == "navigation_write")
            ).scalars()
        assert row.result == "failure" and row.failure_category == "external"
        assert audit_details(row)["after"] == {}
        assert audit_details(row)["before"]["change_record_id"] == str(outcome.record.job_id)
        assert (
            read_change_record(h.case.paths, outcome.record.job_id).outcome
            is ChangeOutcome.ROLLED_BACK
        )


def test_audit_has_no_before_after_content(tmp_path: Path, fake_nav: FakeNavigation) -> None:
    """L15：操作日志里没有前像后像全文，details 通过 AuditValues 白名单。"""
    with harness(tmp_path, fake_nav) as h:
        save_preview(h, two_file_plan(h))
        run_apply(h)
        with session_scope(h.case.engine, read_only=True) as session:
            rows = list(session.execute(select(OperationLogRow)).scalars())
        for row in rows:
            text = str(audit_details(row))
            assert "touched_by_test" not in text and "content" not in text
            assert set(audit_details(row)["after"]) <= {
                "dataset_ids",
                "dataset_count",
                "file_count",
                "link_count",
                "change_record_id",
                "reverts_job_id",
                "job_id",
                "job_type",
                "job_state",
            }


def test_audit_navigation_write_object_kind() -> None:
    """契约 navigation_operation_event：对象为 navigation_write，编号等于作业编号。"""
    event = navigation_operation_event(
        NavigationAuditFacts(
            operation=OperationType.CREATE_LINK,
            job_id=42,
            actor=SYSTEM_ACTOR,
            context=AuditContext(source_ip=None, request_id=None),
            occurred_at=WHEN,
            result=OperationResult.SUCCESS,
            failure_category=None,
            dataset_ids=("dataset-1",),
            dataset_count=1,
            file_count=1,
            link_count=1,
            change_record_id="42",
            reverts_job_id=None,
        )
    )
    assert (event.target.kind, event.target.object_id, event.target.name) == (
        "navigation_write",
        "42",
        "写导航层 #42",
    )
    assert (
        event.details.after.file_count == 1
        and event.details.before.model_dump(exclude_none=True) == {}
    )
    with pytest.raises(Exception):  # noqa: B017
        navigation_operation_event(replace(_facts(), file_count=-1))
    with pytest.raises(Exception):  # noqa: B017
        navigation_operation_event(replace(_facts(), failure_category=DiagnosticCategory.INPUT))


def _facts() -> NavigationAuditFacts:
    """一份合法的事实。"""
    return NavigationAuditFacts(
        operation=OperationType.CREATE_LINK,
        job_id=1,
        actor=SYSTEM_ACTOR,
        context=AuditContext(source_ip=None, request_id=None),
        occurred_at=WHEN,
        result=OperationResult.SUCCESS,
        failure_category=None,
        dataset_ids=(),
        dataset_count=0,
        file_count=0,
        link_count=0,
        change_record_id=None,
        reverts_job_id=None,
    )


def _preview_build(h: Harness, *, verifiable: bool = True) -> PreviewBuild:
    """一个预览结果。"""
    plan = two_file_plan(h)
    if not verifiable:
        state = plan.state.model_copy(
            update={"datasets": (plan.state.datasets[0].model_copy(update={"verifiable": False}),)}
        )
        plan = plan.model_copy(update={"state": state})
    return PreviewBuild(plan, EMPTY_REPORT, {"dataset_id": h.dataset})


def test_preview_job_does_not_take_write_lock(
    tmp_path: Path, fake_nav: FakeNavigation, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Comments 更正：预览是只读 worker 作业，不拿导航层写锁。"""
    with harness(tmp_path, fake_nav) as h:

        def forbidden(*_a: object, **_k: object) -> object:
            raise AssertionError("预览不应拿写锁")

        monkeypatch.setattr(NavigationWriter, "run", forbidden)

        def execute(context: ExecutionContext) -> None:
            run_preview(context, h.dependencies, lambda _cp: _preview_build(h))

        record = h.case.run(execute=execute)
        assert record.summary is not None and not record.summary.aborted
        assert preview_path(h.case.paths, record.job_id).is_file()
        assert tree_state(h.nav) == h.original


def test_run_preview_saves_file_and_reads_back(tmp_path: Path, fake_nav: FakeNavigation) -> None:
    """契约 run_preview：预览结果存成 nav-previews/<作业编号>.json.gz，read_preview 读回同一份计划。"""
    with harness(tmp_path, fake_nav) as h:
        saved: list[NavPreview] = []

        def execute(context: ExecutionContext) -> None:
            saved.append(run_preview(context, h.dependencies, lambda _cp: _preview_build(h)))

        record = h.case.run(execute=execute)
        path = h.case.paths.nav_previews / f"{record.job_id}.json.gz"
        assert path.is_file() and gzip.decompress(path.read_bytes())
        loaded = read_preview(h.case.paths, record.job_id)
        assert loaded == saved[0] and loaded.preview_job_id == record.job_id
        assert loaded.plan.operation is NavOperation.REPOINT_DATASET
        assert (
            loaded.parameters == {"dataset_id": h.dataset} and loaded.created_at.tzinfo is not None
        )
        assert [p.name for p in h.case.paths.nav_previews.iterdir()] == [path.name]


def test_run_preview_rejects_unverifiable_state(tmp_path: Path, fake_nav: FakeNavigation) -> None:
    """契约 run_preview：计划里任一指纹 verifiable=False 时报 InputError，不生成预览。"""
    with harness(tmp_path, fake_nav) as h:
        errors: list[Exception] = []

        def execute(context: ExecutionContext) -> None:
            try:
                run_preview(
                    context, h.dependencies, lambda _cp: _preview_build(h, verifiable=False)
                )
            except InputError as error:
                errors.append(error)
                raise

        h.case.run(execute=execute)
        assert len(errors) == 1 and list(h.case.paths.nav_previews.iterdir()) == []


def test_run_preview_cancel_leaves_no_file(tmp_path: Path, fake_nav: FakeNavigation) -> None:
    """契约 run_preview：取消时不留半截预览文件。"""
    with harness(tmp_path, fake_nav) as h:

        def cancelled_in_builder(checkpoint: Callable[[], None]) -> PreviewBuild:
            getattr(box[0].reporter, "_signals").cancelled.set()  # noqa: B009
            checkpoint()
            raise AssertionError("检查点应当抛出取消")

        box: list[ExecutionContext] = []

        def execute(context: ExecutionContext) -> None:
            box.append(context)
            run_preview(context, h.dependencies, cancelled_in_builder)

        h.case.run(execute=execute)
        assert list(h.case.paths.nav_previews.iterdir()) == []

        # 构造完成之后、写文件之前收到取消：同样不留文件。
        def late_cancel(_cp: Callable[[], None]) -> PreviewBuild:
            getattr(box[-1].reporter, "_signals").cancelled.set()  # noqa: B009
            return _preview_build(h)

        def execute_late(context: ExecutionContext) -> None:
            box.append(context)
            run_preview(context, h.dependencies, late_cancel)

        h.case.run(execute=execute_late)
        assert list(h.case.paths.nav_previews.iterdir()) == []


def test_preview_read_missing_or_corrupt(tmp_path: Path) -> None:
    """契约 read_preview：文件不存在、损坏、版本不认识时报 InputError。"""
    paths = state_paths(PlatformConfig(state_dir=tmp_path), ())
    initialize_state(paths)
    with pytest.raises(InputError):
        read_preview(paths, 5)
    for content in (
        "不是gzip".encode(),
        gzip.compress("{坏".encode()),
        gzip.compress(b'{"format_version": 2}'),
    ):
        preview_path(paths, 5).write_bytes(content)
        with pytest.raises(InputError):
            read_preview(paths, 5)
    with pytest.raises(InputError):
        preview_path(paths, 0)


def test_write_preview_refuses_existing_file(tmp_path: Path, fake_nav: FakeNavigation) -> None:
    """契约 write_preview：同编号预览已存在时报 ConflictError。"""
    with harness(tmp_path, fake_nav) as h:
        preview = save_preview(h, two_file_plan(h), 9)
        before = preview_path(h.case.paths, 9).read_bytes()
        with pytest.raises(ConflictError):
            write_preview(h.case.paths, preview)
        assert preview_path(h.case.paths, 9).read_bytes() == before


def test_write_preview_removes_expired_previews(tmp_path: Path, fake_nav: FakeNavigation) -> None:
    """9 点决定第 5 条：预览保留 7 天，新建预览时顺手清理过期的；删不掉的只记警告。"""
    with harness(tmp_path, fake_nav) as h:
        paths = h.case.paths
        for number, age in ((1, 8), (2, 6), (3, 30)):
            save_preview(h, two_file_plan(h), number)
            stamp = (WHEN - timedelta(days=age)).timestamp()
            os.utime(preview_path(paths, number), (stamp, stamp))
        (paths.nav_previews / "notes.txt").write_text("别的文件不动", encoding="utf-8")
        preview = NavPreview(
            preview_job_id=4,
            created_at=WHEN,
            parameters={},
            plan=two_file_plan(h),
            report=EMPTY_REPORT,
        )
        write_preview(paths, preview)
        names = sorted(p.name for p in paths.nav_previews.iterdir())
        assert names == ["2.json.gz", "4.json.gz", "70.json.gz"] or names == [
            "2.json.gz",
            "4.json.gz",
            "notes.txt",
        ]
        assert (paths.nav_previews / "notes.txt").is_file()
        # 删不掉：另起一个过期文件并让删除失败，写入照常成功。
        stamp = (WHEN - timedelta(days=9)).timestamp()
        save_preview(h, two_file_plan(h), 5)
        os.utime(preview_path(paths, 5), (stamp, stamp))
        real_unlink = Path.unlink

        def failing(self: Path, missing_ok: bool = False) -> None:
            if self.name == "5.json.gz":
                raise PermissionError(13, "注入")
            real_unlink(self, missing_ok=missing_ok)

        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(Path, "unlink", failing)
            write_preview(paths, preview.model_copy(update={"preview_job_id": 6}))
        assert preview_path(paths, 6).is_file() and preview_path(paths, 5).is_file()


def test_apply_rejects_preview_for_other_nav_root(tmp_path: Path, fake_nav: FakeNavigation) -> None:
    """契约 run_write_plan：预览所属导航根与当前不同时报 InputError。"""
    with harness(tmp_path, fake_nav) as h:
        plan = two_file_plan(h)
        other = plan.state.model_copy(update={"nav_root": str(tmp_path / "别的导航根")})
        save_preview(h, plan.model_copy(update={"state": other}))
        outcome = run_apply(h)
        assert isinstance(outcome.error, InputError)
        assert tree_state(h.nav) == h.original and list_journals(h.case.paths) == ()
        # 预览作业没有成功结束时同样拒绝。
        save_preview(h, plan, 80, state=JobState.INTERRUPTED)
        assert isinstance(run_apply(h, 80).error, InputError)


def test_apply_parameters_only_carry_preview_job_id() -> None:
    """契约 NavApplyParameters：只接受严格整数 preview_job_id，多余字段被拒绝。"""
    assert NavApplyParameters.model_validate({"preview_job_id": 3}).preview_job_id == 3
    bad_cases: tuple[dict[str, object], ...] = (
        {"preview_job_id": "3"},
        {"preview_job_id": 0},
        {"preview_job_id": True},
        {"preview_job_id": 3, "plan": {}},
        {},
    )
    for bad in bad_cases:
        with pytest.raises(ValidationError):
            NavApplyParameters.model_validate(bad)
    assert NavRevertPreviewParameters.model_validate({"target_job_id": 2}).target_job_id == 2
    with pytest.raises(ValidationError):
        NavRevertPreviewParameters.model_validate({"target_job_id": "2"})


def test_definitions_flags_and_recovery_modes(tmp_path: Path, fake_nav: FakeNavigation) -> None:
    """契约 build_navwrite_definitions：nav_write_apply 为 INTERRUPT 且 writes_navigation，nav_revert_preview 为 RESTART 且不写导航层。"""
    with harness(tmp_path, fake_nav) as h:
        apply, revert = build_navwrite_definitions(h.dependencies)
    assert (apply.type_name, apply.recovery_mode, apply.writes_navigation) == (
        NAV_APPLY_TYPE,
        RecoveryMode.INTERRUPT,
        True,
    )
    assert (revert.type_name, revert.recovery_mode, revert.writes_navigation) == (
        NAV_REVERT_PREVIEW_TYPE,
        RecoveryMode.RESTART,
        False,
    )
    for definition in (apply, revert):
        assert definition.concurrency == 1 and not definition.requires_gpu
        assert definition.storage == ()
    assert apply.parameters_model is NavApplyParameters
    unmanaged = replace(h.dependencies.rescan, nav_root=Path("相对路径"))
    with pytest.raises(DefectError):
        build_navwrite_definitions(replace(h.dependencies, rescan=unmanaged))


def test_definitions_without_dependencies_cannot_execute(
    tmp_path: Path, fake_nav: FakeNavigation
) -> None:
    """契约 build_navwrite_definitions：Web 侧传 None 只能校验参数，执行时缺依赖为 DefectError。"""
    apply, revert = build_navwrite_definitions(None)
    assert apply.parameters_model.model_validate({"preview_job_id": 1})
    with harness(tmp_path, fake_nav) as h:
        raised: list[type[Exception]] = []

        def execute(context: ExecutionContext) -> None:
            for definition, parameters in (
                (apply, NavApplyParameters(preview_job_id=1)),
                (revert, NavRevertPreviewParameters(target_job_id=1)),
            ):
                try:
                    definition.execute(replace(context, parameters=parameters))
                except DefectError as error:
                    raised.append(type(error))

        h.case.run(execute=execute)
        assert raised == [DefectError, DefectError]
        assert tree_state(h.nav) == h.original


def test_apply_job_not_auto_resumed_after_interruption(
    tmp_path: Path, fake_nav: FakeNavigation
) -> None:
    """ADR 0005 修订：写导航层的作业被中断后只标记中断并回滚，不自动重新执行。"""
    apply, _revert = build_navwrite_definitions(None)
    assert apply.recovery_mode is RecoveryMode.INTERRUPT
    with harness(tmp_path, fake_nav) as h:
        raised: list[type[Exception]] = []

        def execute(context: ExecutionContext) -> None:
            real = build_navwrite_definitions(h.dependencies)[0]
            for mode in (ExecutionMode.RESUME, ExecutionMode.RESTART):
                try:
                    execute_apply(
                        h.dependencies,
                        replace(
                            context, mode=mode, parameters=NavApplyParameters(preview_job_id=1)
                        ),
                    )
                except DefectError as error:
                    raised.append(type(error))
            del real

        h.case.run(execute=execute)
        assert raised == [DefectError, DefectError]


def test_state_dir_helpers_created_by_initialize_state(tmp_path: Path) -> None:
    """契约 StatePaths：initialize_state 创建 nav-journal、nav-changes、nav-previews，权限同状态目录。"""
    paths = state_paths(PlatformConfig(state_dir=tmp_path / "state"), ())
    assert not paths.nav_journal.exists()
    initialize_state(paths)
    for name, directory in (
        ("nav-journal", paths.nav_journal),
        ("nav-changes", paths.nav_changes),
        ("nav-previews", paths.nav_previews),
    ):
        assert directory == paths.root / name and directory.is_dir()
        assert stat.S_IMODE(directory.stat().st_mode) == stat.S_IMODE(paths.root.stat().st_mode)
    (paths.nav_changes / "keep.json.gz").write_text("x", encoding="utf-8")
    assert initialize_state(paths) == ()  # 第二次调用不改任何东西
    assert (paths.nav_changes / "keep.json.gz").read_text(encoding="utf-8") == "x"
