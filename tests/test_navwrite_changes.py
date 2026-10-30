"""变更记录与撤回的契约测试（M1-07，L15、L16，验收 3）。

场景三用可控时钟让操作日志过期被清除，nav-changes 不受影响。全部在 pytest 临时目录里。
"""

import gzip
import os
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from nav_manifest import FakeNavigation
from navwrite_pipeline_support import harness, run_apply, save_preview, two_file_plan
from navwrite_support import (
    archive_again,
    archive_request_without_plan,
    commit_keep_journal,
    dataset_id_of,
    file_image,
    noop,
    plan_for,
    run_committed,
    sha,
    simple_nav,
    tree_state,
    write_step,
)

from rdp.audit.service import AuditMaintenance
from rdp.audit.types import AuditContext, OperationResult, OperationType
from rdp.infra.actors import SYSTEM_ACTOR
from rdp.infra.config import PlatformConfig
from rdp.infra.db.connection import create_database_engine
from rdp.infra.db.migration import migrate
from rdp.infra.diagnostics import ConflictError, ExternalError, InputError
from rdp.infra.state import StatePaths, initialize_state, state_paths
from rdp.jobs.navwrite.atomic import apply_plan
from rdp.jobs.navwrite.audit import (
    NavigationAuditFacts,
    append_navigation_audit,
    navigation_operation_event,
)
from rdp.jobs.navwrite.changes import (
    ChangeOutcome,
    ChangeRecord,
    change_record_path,
    diff_against_after_images,
    plan_revert,
    read_change_record,
)
from rdp.jobs.navwrite.journal import Journal
from rdp.jobs.navwrite.models import (
    MakeDirStep,
    NavOperation,
    NavWritePlan,
    RemovePathStep,
    SetLinkStep,
    WriteFileStep,
)
from rdp.jobs.navwrite.policy import CHANGE_INLINE_MAX_BYTES
from rdp.jobs.navwrite.preview_state import capture_preview_state, verify_preview_state

OLD_A = b'{"v": 1}\n'
NEW_A = b'{"v": 11}\n'


def _case(tmp_path: Path) -> tuple[StatePaths, Path, ChangeRecord]:
    """提交一个五步作业 #7，返回状态目录、导航树和它的变更记录。"""
    paths = state_paths(PlatformConfig(state_dir=tmp_path / "state"), ())
    initialize_state(paths)
    nav, steps = simple_nav(tmp_path)
    run_committed(paths, nav, plan_for(nav, steps, ids=()), 7)
    return paths, nav, read_change_record(paths, 7)


def _kept(tmp_path: Path) -> tuple[StatePaths, NavWritePlan, Journal, Path]:
    """提交作业 #7 但保留写入日志，供重复归档。"""
    paths = state_paths(PlatformConfig(state_dir=tmp_path / "state"), ())
    initialize_state(paths)
    nav, steps = simple_nav(tmp_path)
    plan = plan_for(nav, steps, ids=())
    journal, directory = commit_keep_journal(paths, nav, plan, 7)
    return paths, plan, journal, directory


def test_archive_committed_record_contents(tmp_path: Path) -> None:
    """L16：COMMITTED 记录含计划、每步前像和后像、提交人、起止时刻、受影响数据集。"""
    paths, nav, record = _case(tmp_path)
    assert (record.job_id, record.operation, record.outcome) == (
        7,
        NavOperation.REPOINT_DATASET,
        ChangeOutcome.COMMITTED,
    )
    assert (record.actor_id, record.actor_name) == (1, "管理员")
    assert record.nav_root == str(nav) and record.mismatches == ()
    assert record.started_at <= record.finished_at and record.dataset_ids == ()
    assert [(s.index, s.op, s.path) for s in record.steps] == [
        (0, "make_dir", "newdir"),
        (1, "write_file", "a.json"),
        (2, "write_file", "b.json"),
        (3, "write_file", "newdir/c.json"),
        (4, "set_link", "L"),
    ]
    a = record.steps[1]
    assert a.before.content == OLD_A.decode() and a.before.sha256 == sha(OLD_A)
    assert a.after is not None and a.after.content == NEW_A.decode()
    assert a.after.sha256 == sha(NEW_A) and a.after.size_bytes == len(NEW_A)
    assert record.steps[3].before.exists is False and record.steps[0].before.exists is False
    link = record.steps[4]
    assert link.before.link_target == "/old-target"
    assert link.after is not None and link.after.link_target == "/new-target"
    assert change_record_path(paths, 7) == paths.nav_changes / "7.json.gz"
    with pytest.raises(InputError):
        change_record_path(paths, 0)


def _big_case(tmp_path: Path, size: int) -> tuple[StatePaths, Path]:
    """一个把 size 字节的文件改成小内容的作业 #3。"""
    paths = state_paths(PlatformConfig(state_dir=tmp_path / "state"), ())
    initialize_state(paths)
    nav = tmp_path / "nav"
    nav.mkdir()
    old = b"x" * size
    (nav / "big.json").write_bytes(old)
    run_committed(paths, nav, plan_for(nav, (write_step("big.json", old, b"{}\n"),), ids=()), 3)
    return paths, nav


def test_archive_inline_threshold_boundary(tmp_path: Path) -> None:
    """Comments (9)：文件正好 CHANGE_INLINE_MAX_BYTES 时存全文，多 1 字节时只存 sha256 和大小。"""
    paths, _nav = _big_case(tmp_path / "exact", CHANGE_INLINE_MAX_BYTES)
    before = read_change_record(paths, 3).steps[0].before
    assert before.content == "x" * CHANGE_INLINE_MAX_BYTES and before.blob is None
    paths, _nav = _big_case(tmp_path / "over", CHANGE_INLINE_MAX_BYTES + 1)
    before = read_change_record(paths, 3).steps[0].before
    assert before.content is None and before.blob is not None
    assert before.size_bytes == CHANGE_INLINE_MAX_BYTES + 1
    assert before.sha256 == sha(b"x" * (CHANGE_INLINE_MAX_BYTES + 1))


def test_archive_large_file_goes_to_sidecar_blob(tmp_path: Path) -> None:
    """待确认扩展：超限文件的正文放进旁路 blob（按 sha256 命名的 .gz），记录里有 blob 引用。"""
    size = CHANGE_INLINE_MAX_BYTES + 5
    paths, _nav = _big_case(tmp_path, size)
    before = read_change_record(paths, 3).steps[0].before
    assert before.blob == f"{sha(b'x' * size)}.gz"
    assert before.blob is not None
    blob = paths.nav_changes / "3.blobs" / before.blob
    assert gzip.decompress(blob.read_bytes()) == b"x" * size
    assert read_change_record(paths, 3).steps[0].after is not None


def test_archive_requires_plan_for_committed(tmp_path: Path) -> None:
    """契约 archive_journal：outcome 为 COMMITTED 却没给 plan 时报 InputError。"""
    paths = state_paths(PlatformConfig(state_dir=tmp_path / "state"), ())
    initialize_state(paths)
    nav, steps = simple_nav(tmp_path)
    with pytest.raises(InputError):
        archive_request_without_plan(paths, nav, plan_for(nav, steps, ids=()), 7)
    assert not change_record_path(paths, 7).exists()


def test_archive_is_idempotent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """契约 archive_journal：同一作业重复归档写入相同内容，已有记录不被破坏。"""
    paths, plan, journal, directory = _kept(tmp_path)
    path = change_record_path(paths, 7)
    first = path.read_bytes()
    record = read_change_record(paths, 7)
    monkeypatch.setattr(
        time, "time", lambda: 1_000_000_000.0
    )  # 压缩头里的时间戳不能让同样的内容变成不同的字节
    archive_again(paths, journal, directory, plan)
    assert path.read_bytes() == first and read_change_record(paths, 7) == record
    assert [p.name for p in paths.nav_changes.iterdir()] == ["7.json.gz"]


def test_archive_failure_keeps_existing_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """契约 archive_journal：写入、fsync 或 rename 失败时已有的同名记录不被破坏。"""
    paths, plan, journal, directory = _kept(tmp_path)
    path = change_record_path(paths, 7)
    original = path.read_bytes()
    real_replace = os.replace

    def failing(source: str | os.PathLike[str], target: str | os.PathLike[str]) -> None:
        if str(target).endswith(".json.gz"):
            raise OSError(28, "注入失败")
        real_replace(source, target)

    with monkeypatch.context() as patch:
        patch.setattr(os, "replace", failing)
        with pytest.raises(ExternalError):
            archive_again(paths, journal, directory, plan)
    assert path.read_bytes() == original
    assert [p.name for p in paths.nav_changes.iterdir()] == ["7.json.gz"]  # 临时文件已清掉


@pytest.mark.parametrize(
    "outcome", [ChangeOutcome.ROLLED_BACK, ChangeOutcome.ROLLED_BACK_BY_RECOVERY]
)
def test_archive_rolled_back_outcomes_have_no_after_images(
    tmp_path: Path, outcome: ChangeOutcome
) -> None:
    """Comments (3)：rolled_back、rolled_back_by_recovery 的记录没有后像，且不能被撤回。"""
    paths = state_paths(PlatformConfig(state_dir=tmp_path / "state"), ())
    initialize_state(paths)
    nav, steps = simple_nav(tmp_path)
    run_committed(paths, nav, plan_for(nav, steps, ids=()), 5, outcome=outcome)
    record = read_change_record(paths, 5)
    assert record.outcome is outcome
    assert all(step.after is None for step in record.steps)
    assert all(step.before.exists or step.op in ("make_dir", "write_file") for step in record.steps)
    with pytest.raises(InputError):
        plan_revert(nav, paths, record, checkpoint=noop)
    with pytest.raises(InputError):
        diff_against_after_images(nav, paths, record)


def test_failed_and_rolled_back_jobs_also_get_records(
    tmp_path: Path, fake_nav: FakeNavigation, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Comments 更正：失败和回滚的作业也要写变更记录，以 L16 为准。"""
    with harness(tmp_path, fake_nav) as h:
        save_preview(h, two_file_plan(h))
        real = os.replace
        count = [0]

        def second_write_fails(
            source: str | os.PathLike[str], target: str | os.PathLike[str]
        ) -> None:
            if str(target).startswith(str(h.nav)):
                count[0] += 1
                if count[0] == 2:
                    raise OSError(28, "注入失败")
            real(source, target)

        with monkeypatch.context() as patch:
            patch.setattr(os, "replace", second_write_fails)
            outcome = run_apply(h)
        assert isinstance(outcome.error, ExternalError)
        record = read_change_record(h.case.paths, outcome.record.job_id)
        assert record.outcome is ChangeOutcome.ROLLED_BACK
        assert record.operation is NavOperation.REPOINT_DATASET and record.dataset_ids == (
            h.dataset,
        )
        assert [step.path for step in record.steps][:2] == [
            "按任务/EgoProDemo/数据集信息.json",
            "按任务/EgoProDemo/子任务.json",
        ]
        assert all(step.after is None for step in record.steps)  # 回滚的记录没有后像
        # 冲突失败（一行都没写）不产生变更记录，因为没有任何改动可记。
        (h.nav / "按任务" / "EgoProDemo" / "多出来.txt").write_text("x", encoding="utf-8")
        again = run_apply(h)
        assert isinstance(again.error, ConflictError)
        assert not change_record_path(h.case.paths, again.record.job_id).exists()


def test_read_change_record_roundtrip(tmp_path: Path) -> None:
    """契约 read_change_record：写出再读回得到相同的 ChangeRecord。"""
    paths, _nav, record = _case(tmp_path)
    raw = gzip.decompress(change_record_path(paths, 7).read_bytes())
    assert ChangeRecord.model_validate_json(raw) == record
    assert record.model_dump_json().encode() == raw


def test_read_change_record_missing_or_unknown_version(tmp_path: Path) -> None:
    """契约 read_change_record：记录不存在、损坏或 format_version 不认识时报 InputError。"""
    paths, _nav, _record = _case(tmp_path)
    with pytest.raises(InputError):
        read_change_record(paths, 99)
    path = change_record_path(paths, 7)
    good = gzip.decompress(path.read_bytes())
    for broken in (
        "不是gzip".encode(),
        gzip.compress("{坏".encode()),
        gzip.compress(good.replace(b'"format_version":1', b'"format_version":2')),
        gzip.compress(b"[]"),
    ):
        path.write_bytes(broken)
        with pytest.raises(InputError):
            read_change_record(paths, 7)


def test_plan_revert_inverts_steps_in_reverse_order(tmp_path: Path) -> None:
    """L16 验收：反向计划是原步骤逆序反演，write_file 写回前像全文，set_link 改回前像目标。"""
    paths, nav, record = _case(tmp_path)
    plan, report = plan_revert(nav, paths, record, checkpoint=noop)
    assert plan.operation is NavOperation.REVERT_CHANGE and plan.reverts_job_id == 7
    kinds = [(type(step).__name__, step.path) for step in plan.steps]
    assert kinds == [
        ("SetLinkStep", "L"),
        ("RemovePathStep", "newdir/c.json"),
        ("WriteFileStep", "b.json"),
        ("WriteFileStep", "a.json"),
        ("RemovePathStep", "newdir"),
    ]
    link, _removed, b, a, _dir = plan.steps
    assert isinstance(link, SetLinkStep)
    assert (link.before_target, link.after_target) == ("/new-target", "/old-target")
    assert isinstance(a, WriteFileStep) and isinstance(b, WriteFileStep)
    assert a.after_content == OLD_A.decode() and a.after == file_image(OLD_A)
    assert a.before == file_image(NEW_A)
    assert (report.file_count, report.link_count, report.directory_count) == (3, 1, 0)
    assert plan.state.nav_root == str(nav)
    # 照反向计划写一遍，导航层回到 #7 之前。
    original_after = tree_state(nav)
    apply_plan(nav, plan, 8, checkpoint=noop)
    assert (nav / "a.json").read_bytes() == OLD_A and not (nav / "newdir").exists()
    assert str(Path(nav / "L").readlink()) == "/old-target" and tree_state(nav) != original_after


def test_plan_revert_of_created_objects_removes_them(tmp_path: Path) -> None:
    """L16：撤回新建类操作时，新建的文件、链接、空目录用 remove_path 删掉，目录在最后。"""
    paths = state_paths(PlatformConfig(state_dir=tmp_path / "state"), ())
    initialize_state(paths)
    nav = tmp_path / "nav"
    nav.mkdir()
    steps = (
        MakeDirStep(path="d"),
        write_step("d/new.json", None, b"{}\n"),
        SetLinkStep(path="d/link", before_target=None, after_target="/t"),
    )
    run_committed(paths, nav, plan_for(nav, steps, ids=()), 4)
    plan, _report = plan_revert(nav, paths, read_change_record(paths, 4), checkpoint=noop)
    assert all(isinstance(step, RemovePathStep) for step in plan.steps)
    assert [(s.path, s.entry_kind) for s in plan.steps if isinstance(s, RemovePathStep)] == [
        ("d/link", "symlink"),
        ("d/new.json", "file"),
        ("d", "directory"),
    ]
    apply_plan(nav, plan, 5, checkpoint=noop)
    assert tree_state(nav) == {}


def test_plan_revert_requires_current_state_equals_after_images(tmp_path: Path) -> None:
    """L16：当前状态等于 #N 的后像才生成反向计划。"""
    paths, nav, record = _case(tmp_path)
    assert diff_against_after_images(nav, paths, record) == ()
    (nav / "a.json").write_bytes(b"{}\n")
    with pytest.raises(ConflictError):
        plan_revert(nav, paths, record, checkpoint=noop)
    (nav / "a.json").write_bytes(NEW_A)
    plan_revert(nav, paths, record, checkpoint=noop)
    with pytest.raises(InputError):
        diff_against_after_images(tmp_path / "别的树", paths, record)


def test_plan_revert_conflict_lists_differences(tmp_path: Path) -> None:
    """L16 验收：中间又被改过时以冲突失败，列出每一处差异（路径、预期、实际、之后改过它的作业）。"""
    paths, nav, record = _case(tmp_path)
    run_committed(
        paths, nav, plan_for(nav, (write_step("a.json", NEW_A, b'{"v": 111}\n'),), ids=()), 8
    )
    (nav / "L").unlink()
    (nav / "L").symlink_to("/第三处")
    before = tree_state(nav)
    with pytest.raises(ConflictError) as caught:
        plan_revert(nav, paths, record, checkpoint=noop)
    assert tree_state(nav) == before  # 只读
    rendered = " ".join(f"{o.key}={o.value}" for o in caught.value.diagnostics[0].objects)
    assert "a.json" in rendered and "L" in rendered and "#8" in rendered
    assert "一行都没写" in caught.value.diagnostics[0].consequence


def test_plan_revert_rejects_non_committed_record(tmp_path: Path) -> None:
    """契约 plan_revert：结局不是 COMMITTED 时报 InputError。"""
    paths, nav, record = _case(tmp_path)
    manual = record.model_copy(update={"outcome": ChangeOutcome.MANUALLY_CONFIRMED})
    with pytest.raises(InputError):
        plan_revert(nav, paths, manual, checkpoint=noop)


def test_plan_revert_missing_blob_is_input_error(tmp_path: Path) -> None:
    """契约 plan_revert：前像正文既没内联也找不到旁路 blob 时报 InputError，不生成残缺计划。"""
    size = CHANGE_INLINE_MAX_BYTES + 1
    paths, nav = _big_case(tmp_path, size)
    record = read_change_record(paths, 3)
    plan, _report = plan_revert(nav, paths, record, checkpoint=noop)
    (step,) = plan.steps
    assert isinstance(step, WriteFileStep) and step.after.sha256 == sha(b"x" * size)
    blob = next((paths.nav_changes / "3.blobs").iterdir())
    blob.unlink()
    with pytest.raises(InputError):
        plan_revert(nav, paths, record, checkpoint=noop)


def test_revert_is_itself_a_write_job_with_own_record(tmp_path: Path) -> None:
    """L16：撤回本身也是写导航层的作业，有自己的写入日志和变更记录，reverts_job_id 指向 #N。"""
    paths, nav, record = _case(tmp_path)
    plan, _report = plan_revert(nav, paths, record, checkpoint=noop)
    run_committed(paths, nav, plan, 8)
    own = read_change_record(paths, 8)
    assert own.operation is NavOperation.REVERT_CHANGE and own.reverts_job_id == 7
    assert own.outcome is ChangeOutcome.COMMITTED and own.job_id == 8
    assert list(paths.nav_journal.iterdir()) == []  # 收尾后写入日志已删
    # 撤回的撤回：#8 的记录又能生成反向计划，回到 #7 之后的样子。
    again, _ = plan_revert(nav, paths, own, checkpoint=noop)
    run_committed(paths, nav, again, 9)
    assert (nav / "a.json").read_bytes() == NEW_A and str(
        Path(nav / "L").readlink()
    ) == "/new-target"


def test_revert_after_audit_log_purged_still_works(tmp_path: Path) -> None:
    """验收 3（场景三）：可控时钟走过 30 天、操作日志被清除后，nav-changes 还在，撤回作业照常预览、执行成功。"""
    paths, nav, _record = _case(tmp_path)
    migrate(paths, now=datetime(2026, 10, 29, tzinfo=UTC))
    engine = create_database_engine(paths.database)
    try:
        written = datetime(2026, 10, 29, 12, tzinfo=UTC)
        event = navigation_operation_event(
            NavigationAuditFacts(
                operation=OperationType.REPOINT_DATASET,
                job_id=7,
                actor=SYSTEM_ACTOR,
                context=AuditContext(source_ip=None, request_id=None),
                occurred_at=written,
                result=OperationResult.SUCCESS,
                failure_category=None,
                dataset_ids=(),
                dataset_count=0,
                file_count=3,
                link_count=1,
                change_record_id="7",
                reverts_job_id=None,
            )
        )
        append_navigation_audit(engine, event)
        # 可控时钟：31 天后清除，操作日志里这一条没了。
        purged = AuditMaintenance(engine).purge_expired(written + timedelta(days=31))
        assert purged.operation_count == 1
    finally:
        engine.dispose()
    assert change_record_path(paths, 7).is_file()
    plan, _report = plan_revert(nav, paths, read_change_record(paths, 7), checkpoint=noop)
    run_committed(paths, nav, plan, 8)
    assert (nav / "a.json").read_bytes() == OLD_A and str(
        Path(nav / "L").readlink()
    ) == "/old-target"


def test_revert_conflicts_when_changed_between_preview_and_apply(
    fake_nav: FakeNavigation, tmp_path: Path
) -> None:
    """L16、L12：撤回预览之后现状又变，写入作业在写锁下核对时以冲突失败，一行都没写。"""
    paths = state_paths(PlatformConfig(state_dir=tmp_path / "state"), ())
    initialize_state(paths)
    nav = fake_nav.nav_root
    dataset = dataset_id_of(fake_nav, "EgoProDemo")
    path = nav / "按任务" / "EgoProDemo" / "数据集信息.json"
    old = path.read_bytes()
    state = capture_preview_state(nav, (dataset,), None, checkpoint=noop)
    plan = plan_for(
        nav, (write_step("按任务/EgoProDemo/数据集信息.json", old, b"{}\n"),), ids=(dataset,)
    )
    run_committed(paths, nav, plan.model_copy(update={"state": state}), 7)
    plan_back, _report = plan_revert(nav, paths, read_change_record(paths, 7), checkpoint=noop)
    verify_preview_state(nav, plan_back.state, checkpoint=noop)  # 预览当时是对的
    (nav / "按任务" / "EgoProDemo" / "子任务.json").write_bytes(b"{}\n")  # 预览之后又变
    before = tree_state(nav)
    with pytest.raises(ConflictError):
        verify_preview_state(nav, plan_back.state, checkpoint=noop)
    assert tree_state(nav) == before and path.read_bytes() == b"{}\n"


def test_diff_against_after_images_names_later_job(tmp_path: Path) -> None:
    """契约 diff_against_after_images：能从更晚的变更记录查到改过它的作业编号时填 changed_by_job_id。"""
    paths, nav, record = _case(tmp_path)
    (nav / "b.json").write_bytes("手改\n".encode())  # 没有任何作业记录改过 b.json
    run_committed(
        paths, nav, plan_for(nav, (write_step("a.json", NEW_A, b'{"v": 0}\n'),), ids=()), 8
    )
    run_committed(
        paths, nav, plan_for(nav, (write_step("a.json", b'{"v": 0}\n', b'{"v": 9}\n'),), ids=()), 9
    )
    differences = {d.path: d for d in diff_against_after_images(nav, paths, record)}
    assert set(differences) == {"a.json", "b.json"}
    assert differences["a.json"].changed_by_job_id == 9  # 最近一个改过它的作业
    assert differences["b.json"].changed_by_job_id is None
    assert differences["a.json"].expected != differences["a.json"].actual
    assert sha(NEW_A)[:12] in differences["a.json"].expected
