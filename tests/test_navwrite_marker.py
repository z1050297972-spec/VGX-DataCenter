"""全局标记"导航层恢复失败"的契约测试（M1-07，ADR 0005 修订）。

用真实 SQLite 临时库（表由 rdp.jobs.navwrite.rows 的声明建出，迁移 v0010 的冻结 DDL 另有测试对齐）。
"""

import subprocess
import sys
from collections.abc import Generator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from jobs_storage_support import job_database
from navwrite_support import audit_details, plan_for, simple_nav
from sqlalchemy import Engine, select, text

from rdp.audit.models import OperationLogRow
from rdp.audit.types import AuditContext
from rdp.infra.actors import OPS_ACTOR, ActorRef
from rdp.infra.db.connection import session_scope
from rdp.infra.diagnostics import ConflictError, InputError
from rdp.infra.state import StatePaths
from rdp.jobs.navwrite import marker as marker_module
from rdp.jobs.navwrite.atomic import apply_plan, capture_before_images
from rdp.jobs.navwrite.changes import ArchiveRequest, ChangeOutcome, read_change_record
from rdp.jobs.navwrite.journal import Journal, journal_directory, list_journals, write_journal
from rdp.jobs.navwrite.marker import (
    AcknowledgeRequest,
    acknowledge_recovery_block,
    is_navigation_write_blocked,
    read_recovery_block,
    record_recovery_block,
)
from rdp.jobs.navwrite.models import MismatchItem
from rdp.jobs.navwrite.policy import MARKER_ITEM_SAMPLE_LIMIT

NOW = datetime(2026, 10, 29, 12, tzinfo=UTC)
ADMIN = ActorRef(2, "管理员")
REQUEST_ID = uuid4().hex
CONTEXT = AuditContext(source_ip="127.0.0.1", request_id=REQUEST_ID)


def _item(job_id: int, step: int, path: str = "a.json") -> MismatchItem:
    """一项对不上的步骤。"""
    return MismatchItem(
        job_id=job_id,
        step_index=step,
        path=path,
        expected_before="sha256 aaaaaaaaaaaa",
        expected_after="sha256 bbbbbbbbbbbb",
        actual="sha256 cccccccccccc",
    )


@contextmanager
def _database(tmp_path: Path) -> Generator[tuple[Engine, StatePaths]]:
    """带标记表的临时库和状态目录。"""
    with job_database(tmp_path) as (engine, paths):
        yield engine, paths


def _set_block(engine: Engine, items: tuple[MismatchItem, ...], now: datetime = NOW) -> None:
    """在写事务里设置标记。"""
    with session_scope(engine) as session:
        record_recovery_block(session, items, now=now)


def _blocked(engine: Engine) -> bool:
    """只读事务里看是否被挡住。"""
    with session_scope(engine, read_only=True) as session:
        return is_navigation_write_blocked(session)


def test_read_block_none_when_absent(tmp_path: Path) -> None:
    """契约 read_recovery_block：没有标记行时返回 None，is_navigation_write_blocked 为 False。"""
    with _database(tmp_path) as (engine, _paths):
        with session_scope(engine, read_only=True) as session:
            assert read_recovery_block(session) is None
        assert _blocked(engine) is False


def test_record_block_creates_single_row(tmp_path: Path) -> None:
    """契约 record_recovery_block：首次设置建一行，set_at 取注入的时刻。"""
    with _database(tmp_path) as (engine, _paths):
        with session_scope(engine) as session:
            block = record_recovery_block(session, (_item(3, 1), _item(3, 0)), now=NOW)
        assert block.set_at == NOW and block.job_ids == (3,) and block.total_items == 2
        assert [i.step_index for i in block.items] == [0, 1]  # 按作业编号、步骤序号升序
        with session_scope(engine, read_only=True) as session:
            assert read_recovery_block(session) == block
            count = session.execute(text("SELECT count(*) FROM nav_recovery_failure")).scalar()
        assert count == 1 and _blocked(engine) is True


def test_record_block_merges_and_keeps_first_set_at(tmp_path: Path) -> None:
    """契约 record_recovery_block：再次设置时 job_ids 取并集、items 去重，set_at 不变。"""
    with _database(tmp_path) as (engine, _paths):
        _set_block(engine, (_item(5, 0), _item(3, 2)))
        later = NOW + timedelta(hours=1)
        with session_scope(engine) as session:
            block = record_recovery_block(session, (_item(3, 2), _item(7, 1)), now=later)
        assert block.set_at == NOW  # 第一次设置的时刻
        assert block.job_ids == (3, 5, 7)
        assert [(i.job_id, i.step_index) for i in block.items] == [(3, 2), (5, 0), (7, 1)]
        assert block.total_items == 3


def test_record_block_caps_items_but_keeps_total(tmp_path: Path) -> None:
    """规范 6.6：items 至多 MARKER_ITEM_SAMPLE_LIMIT 条，total_items 完整。"""
    with _database(tmp_path) as (engine, _paths):
        many = tuple(_item(3, n, f"f{n}.json") for n in range(MARKER_ITEM_SAMPLE_LIMIT + 50))
        _set_block(engine, many)
        with session_scope(engine, read_only=True) as session:
            block = read_recovery_block(session)
        assert block is not None
        assert len(block.items) == MARKER_ITEM_SAMPLE_LIMIT
        assert block.total_items == MARKER_ITEM_SAMPLE_LIMIT + 50
        assert [i.step_index for i in block.items] == list(range(MARKER_ITEM_SAMPLE_LIMIT))


def test_record_block_rejects_empty_items(tmp_path: Path) -> None:
    """契约 record_recovery_block：items 为空报 InputError。"""
    with _database(tmp_path) as (engine, _paths):
        with pytest.raises(InputError), session_scope(engine) as session:
            record_recovery_block(session, (), now=NOW)
        assert _blocked(engine) is False


def test_block_row_is_singleton_by_check(tmp_path: Path) -> None:
    """迁移 v0010：singleton_id 只能为 1，第二行被 CHECK 拒绝。"""
    with _database(tmp_path) as (engine, _paths):
        _set_block(engine, (_item(3, 0),))
        with pytest.raises(ConflictError), session_scope(engine) as session:
            session.execute(
                text(
                    "INSERT INTO nav_recovery_failure VALUES (2, '2026-10-29 12:00:00.000000', '[1]', '[]', 1)"
                )
            )


def _stuck_journal(paths: StatePaths, job_id: int) -> tuple[Path, Path]:
    """造一份写到一半的日志（已写入导航层），返回 (导航树, 日志目录)。"""
    root = paths.root / f"fake-nav-{job_id}"
    root.mkdir()
    nav, steps = simple_nav(root)
    plan = plan_for(nav, steps, ids=())
    write_journal(paths, plan, capture_before_images(nav, plan), job_id, NOW)
    apply_plan(nav, plan, job_id, checkpoint=lambda: None)
    return nav, journal_directory(paths, job_id)


def _admin_request() -> AcknowledgeRequest:
    """管理员的确认请求。"""
    return AcknowledgeRequest(actor=ADMIN, context=CONTEXT, now=NOW + timedelta(days=1))


def test_acknowledge_requires_existing_block(tmp_path: Path) -> None:
    """契约 acknowledge_recovery_block：没有标记时报 ConflictError。"""
    with _database(tmp_path) as (engine, paths), pytest.raises(ConflictError):
        acknowledge_recovery_block(engine, paths, _admin_request())


def test_acknowledge_requires_account_admin(tmp_path: Path) -> None:
    """契约 acknowledge_recovery_block：actor.account_id 为 None（运维）时报 InputError。"""
    with _database(tmp_path) as (engine, paths):
        _set_block(engine, (_item(3, 0),))
        request = AcknowledgeRequest(actor=OPS_ACTOR, context=CONTEXT, now=NOW)
        with pytest.raises(InputError):
            acknowledge_recovery_block(engine, paths, request)
        assert _blocked(engine) is True


def test_acknowledge_archives_deletes_journal_then_clears_marker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Comments (5)：确认时先归档日志（manually_confirmed，带仍对不上的项）、删日志，最后清标记，顺序可断言。"""
    with _database(tmp_path) as (engine, paths):
        _nav, directory = _stuck_journal(paths, 3)
        _set_block(engine, (_item(3, 2, "b.json"),))
        events: list[str] = []
        real_archive, real_discard = marker_module.archive_journal, marker_module.discard_journal

        def archive(
            state: StatePaths, journal_dir: Path, journal: Journal, request: ArchiveRequest
        ) -> Path:
            assert _blocked(engine) and directory.exists()
            events.append("archive")
            return real_archive(state, journal_dir, journal, request)

        def discard(target: Path) -> None:
            assert _blocked(engine) and (paths.nav_changes / "3.json.gz").is_file()
            events.append("discard")
            real_discard(target)

        monkeypatch.setattr(marker_module, "archive_journal", archive)
        monkeypatch.setattr(marker_module, "discard_journal", discard)
        result = acknowledge_recovery_block(engine, paths, _admin_request())
        assert events == ["archive", "discard"] and result.cleared_job_ids == (3,)
        assert _blocked(engine) is False and not directory.exists()
        record = read_change_record(paths, 3)
        assert record.outcome is ChangeOutcome.MANUALLY_CONFIRMED
        assert [m.path for m in record.mismatches] == ["b.json"]
        assert record.actor_id == 2 and record.actor_name == "管理员"
        assert all(step.after is None for step in record.steps)
        assert list_journals(paths) == ()


def test_acknowledge_appends_audit(tmp_path: Path) -> None:
    """Comments (5)：确认追加一条 confirm_navigation_recovery 操作日志，操作人是管理员账号。"""
    with _database(tmp_path) as (engine, paths):
        _stuck_journal(paths, 3)
        _set_block(engine, (_item(3, 2),))
        result = acknowledge_recovery_block(engine, paths, _admin_request())
        with session_scope(engine, read_only=True) as session:
            rows = session.execute(select(OperationLogRow)).scalars().all()
        (row,) = rows
        assert row.log_id == result.audit_log_id
        assert (row.operation, row.object_kind, row.object_id) == (
            "confirm_navigation_recovery",
            "navigation_write",
            "3",
        )
        assert (row.actor_id, row.actor_name, row.result) == (2, "管理员", "success")
        assert row.request_id == REQUEST_ID and row.source_ip == "127.0.0.1"
        assert dict(audit_details(row)["after"])["change_record_id"] == "3"


def test_acknowledge_crash_before_clearing_keeps_block(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """契约 acknowledge_recovery_block：崩在清标记之前，标记保留、写操作继续被挡住；再确认一次幂等。"""
    with _database(tmp_path) as (engine, paths):
        _stuck_journal(paths, 3)
        _set_block(engine, (_item(3, 2),))

        def crash(*_args: object, **_kwargs: object) -> int:
            raise RuntimeError("崩在清标记之前")

        with monkeypatch.context() as patch:
            patch.setattr(marker_module, "append_operation", crash)
            with pytest.raises(RuntimeError):
                acknowledge_recovery_block(engine, paths, _admin_request())
        assert _blocked(engine) is True  # 宁可多挡
        assert not journal_directory(paths, 3).exists()  # 日志已归档并删掉
        first = (paths.nav_changes / "3.json.gz").read_bytes()
        result = acknowledge_recovery_block(engine, paths, _admin_request())
        assert result.cleared_job_ids == (3,) and _blocked(engine) is False
        assert (paths.nav_changes / "3.json.gz").read_bytes() == first  # 记录没有被重写成别的


def test_acknowledge_unblocks_next_poll(tmp_path: Path) -> None:
    """验收（演示）：确认以后下一轮领取即放行排队的写作业，不需要重启 worker。"""
    with _database(tmp_path) as (engine, paths):
        _set_block(engine, (_item(3, 0),))
        assert _blocked(engine) is True  # 领取前每轮读到的就是这个结果
        acknowledge_recovery_block(engine, paths, _admin_request())
        assert _blocked(engine) is False  # 同一个 engine、没有重建任何东西


def test_marker_module_does_not_import_writer_modules() -> None:
    """规范 1.4：marker 模块不 import atomic、recovery、pipeline、jobs，Web 可以依赖它。"""
    code = (
        "import sys, rdp.jobs.navwrite.marker;"
        "bad=[m for m in ('atomic','recovery','pipeline','jobs') "
        "if 'rdp.jobs.navwrite.'+m in sys.modules];"
        "sys.exit(1 if bad else 0)"
    )
    done = subprocess.run(  # noqa: S603  # 理由：固定解释器加固定的检查脚本。
        [sys.executable, "-I", "-c", code], timeout=60, check=False
    )
    assert done.returncode == 0
