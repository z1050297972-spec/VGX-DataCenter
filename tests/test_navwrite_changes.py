"""变更记录的契约测试（M1-07，L15、L16，验收 3）。

验证归档、原子写、文件内容和回滚结局。全部在 pytest 临时目录里。
"""

import gzip
import os
import time
from pathlib import Path

import pytest
from nav_manifest import FakeNavigation
from navwrite_pipeline_support import harness, run_apply, save_preview, two_file_plan
from navwrite_support import (
    archive_again,
    archive_request_without_plan,
    commit_keep_journal,
    plan_for,
    run_committed,
    sha,
    simple_nav,
    write_step,
)

from rdp.infra.config import PlatformConfig
from rdp.infra.diagnostics import ConflictError, ExternalError, InputError
from rdp.infra.state import StatePaths, initialize_state, state_paths
from rdp.jobs.navwrite.changes import (
    ChangeOutcome,
    ChangeRecord,
    change_record_path,
    read_change_record,
)
from rdp.jobs.navwrite.journal import Journal
from rdp.jobs.navwrite.models import (
    NavOperation,
    NavWritePlan,
)
from rdp.jobs.navwrite.policy import CHANGE_INLINE_MAX_BYTES

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
    """Comments (3)：rolled_back、rolled_back_by_recovery 的记录没有后像。"""
    paths = state_paths(PlatformConfig(state_dir=tmp_path / "state"), ())
    initialize_state(paths)
    nav, steps = simple_nav(tmp_path)
    run_committed(paths, nav, plan_for(nav, steps, ids=()), 5, outcome=outcome)
    record = read_change_record(paths, 5)
    assert record.outcome is outcome
    assert all(step.after is None for step in record.steps)
    assert all(step.before.exists or step.op in ("make_dir", "write_file") for step in record.steps)


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
