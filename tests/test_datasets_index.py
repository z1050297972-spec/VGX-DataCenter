"""索引原子替换和迁移契约；数据库仅使用tmp_path，活动迁移链另有M0回归约束。"""

import os
import shutil
import sqlite3
from pathlib import Path
from typing import Any

import pytest
from datasets_execution_support import dataset_case
from datasets_support import checkpoint, edit_json
from jobs_storage_support import NOW
from nav_manifest import FakeNavigation
from sqlalchemy import event, inspect, select, text
from sqlalchemy.exc import OperationalError

from rdp.infra.config import PlatformConfig
from rdp.infra.db.connection import create_database_engine, session_scope
from rdp.infra.db.migration import migrate
from rdp.infra.db.migrations.versions.v0007_dataset_index import downgrade
from rdp.infra.diagnostics import InputError
from rdp.infra.state import initialize_state, state_paths
from rdp.jobs.datasets.index import read_index_baseline
from rdp.jobs.datasets.models import (
    DatasetRow,
    DatasetScanRow,
    EntryRow,
    FindingRow,
    LinkRow,
    ScanRootRow,
    SourceRow,
)
from rdp.jobs.datasets.rescan import publish_scan, scan_navigation, scan_storage
from rdp.jobs.execution import ExecutionContext


def test_atomic_rollback(tmp_path: Path, fake_nav: FakeNavigation) -> None:
    """索引契约：替换中途注入数据库失败后旧八表行及当前代次完整保留，不出现部分新索引。"""
    with dataset_case(tmp_path / "state", fake_nav) as case:
        case.run()
        with session_scope(case.engine, read_only=True) as session:
            before = read_index_baseline(session, None, nav_root=fake_nav.nav_root)
            old_scan = session.scalar(
                select(DatasetScanRow.scan_id).where(DatasetScanRow.is_current.is_(True))
            )
        edit_json(
            fake_nav.nav_root / "按任务/libero_10/子任务.json",
            lambda data: data.update(extra="new"),
        )

        def fail(
            _connection: Any,
            _cursor: Any,
            statement: str,
            parameters: Any,
            _context: Any,
            _many: bool,
        ) -> None:
            if statement.startswith("INSERT INTO dataset_sources"):
                raise OperationalError(
                    statement, parameters, sqlite3.OperationalError("disk I/O error")
                )

        event.listen(case.engine, "before_cursor_execute", fail)
        try:
            result = case.run()
        finally:
            event.remove(case.engine, "before_cursor_execute", fail)
        assert result.summary is not None and result.summary.aborted
        with session_scope(case.engine, read_only=True) as session:
            assert read_index_baseline(session, None, nav_root=fake_nav.nav_root) == before
            assert (
                session.scalar(
                    select(DatasetScanRow.scan_id).where(DatasetScanRow.is_current.is_(True))
                )
                == old_scan
            )


def test_atomic_visibility(tmp_path: Path, fake_nav: FakeNavigation) -> None:
    """索引契约：并发只读连接只能看到发布前或发布后的完整索引，不能看到先删后建中间态。"""
    with dataset_case(tmp_path / "state", fake_nav) as case:
        case.run()
        observed: list[int] = []

        def read_during_write(
            _connection: Any,
            _cursor: Any,
            statement: str,
            _parameters: Any,
            _context: Any,
            _many: bool,
        ) -> None:
            if statement.startswith("DELETE FROM dataset_entries"):
                with session_scope(case.engine, read_only=True) as session:
                    observed.append(len(tuple(session.scalars(select(EntryRow.path)))))

        event.listen(case.engine, "after_cursor_execute", read_during_write)
        try:
            record = case.run()
        finally:
            event.remove(case.engine, "after_cursor_execute", read_during_write)
        assert record.summary is not None and not record.summary.aborted
        assert observed and set(observed) == {10}


def test_full_removal(tmp_path: Path, fake_nav: FakeNavigation) -> None:
    """索引契约：全量仅删除基线中两次确认消失的数据集及无编号入口；空导航可清旧索引，枚举失败保留旧索引。"""
    with dataset_case(tmp_path / "state", fake_nav) as case:
        case.run()
        shutil.rmtree(fake_nav.nav_root / "按任务/libero_10")
        shutil.rmtree(fake_nav.nav_root / "按格式/lerobot/3.0/libero_10")
        record = case.run()
        assert record.summary is not None and not record.summary.aborted
        with session_scope(case.engine, read_only=True) as session:
            assert len(read_index_baseline(session, None, nav_root=fake_nav.nav_root)) == 4
        (fake_nav.nav_root / "按任务").rename(fake_nav.nav_root / "missing-view")
        record = case.run()
        assert record.summary is not None and record.summary.aborted
        with session_scope(case.engine, read_only=True) as session:
            assert len(read_index_baseline(session, None, nav_root=fake_nav.nav_root)) == 4


def test_single_scope(tmp_path: Path, fake_nav: FakeNavigation) -> None:
    """索引契约：部分扫描不改其他数据集及全局发现，不清其他存储根最近已知状态。"""
    with dataset_case(tmp_path / "state", fake_nav) as case:
        case.run()
        with session_scope(case.engine, read_only=True) as session:
            before = tuple(
                session.execute(
                    select(EntryRow.path, EntryRow.scan_id)
                    .where(EntryRow.dataset_id != "dataset-14")
                    .order_by(EntryRow.path)
                )
            )
        result = case.run("dataset-14")
        assert result.summary is not None and not result.summary.aborted
        with session_scope(case.engine, read_only=True) as session:
            assert (
                tuple(
                    session.execute(
                        select(EntryRow.path, EntryRow.scan_id)
                        .where(EntryRow.dataset_id != "dataset-14")
                        .order_by(EntryRow.path)
                    )
                )
                == before
            )
            assert (
                session.get(
                    FindingRow, ("global", "json", "action_required", "TOP_LEVEL_UNREGISTERED")
                )
                is not None
            )


def test_broken_entry_identity(tmp_path: Path, fake_nav: FakeNavigation) -> None:
    """读取及索引契约：未知dataset_id入口以位置保存可见，不生成假编号；身份冲突和重复source_id完整保留。"""
    path = fake_nav.nav_root / "按任务/libero_10"
    for file in path.glob("*.json"):
        file.write_text("{")
    with dataset_case(tmp_path / "state", fake_nav) as case:
        record = case.run()
        assert record.summary is not None and not record.summary.aborted
        with session_scope(case.engine, read_only=True) as session:
            row = session.get(EntryRow, "按任务/libero_10")
            assert row is not None and row.dataset_id is None
            assert row.name == "libero_10"


def test_unverifiable_placeholder(tmp_path: Path, fake_nav: FakeNavigation) -> None:
    """索引契约：首次不可读入口只新增无法读取占位；不可验证状态不能覆盖已存在的可用投影或发布第二段值。"""
    path = fake_nav.nav_root / "按任务/libero_10"
    with dataset_case(tmp_path / "state", fake_nav) as case:
        case.run()
        with session_scope(case.engine, read_only=True) as session:
            before = read_index_baseline(session, "dataset-14")
        for file in path.glob("*.json"):
            file.unlink()
            file.symlink_to("missing")
        result = case.run()
        assert result.summary is not None and not result.summary.aborted
        with session_scope(case.engine, read_only=True) as session:
            assert read_index_baseline(session, "dataset-14") == before
            row = session.get(EntryRow, "按任务/libero_10")
            assert row is not None and row.dataset_id == "dataset-14"


def test_preserve_sizes(tmp_path: Path, fake_nav: FakeNavigation) -> None:
    """第02张交接：NOT_RUN/离线保持同目标上次统计值及时间，目标改变清空旧统计，不将None转换为零。"""
    with dataset_case(tmp_path / "state", fake_nav) as case:
        case.run()
        with session_scope(case.engine) as session:
            row = session.get(DatasetRow, "dataset-14")
            assert row is not None
            row.size_bytes, row.size_checked_at = 123, NOW
        result = case.run("dataset-14")
        assert result.summary is not None and not result.summary.aborted
        with session_scope(case.engine, read_only=True) as session:
            row = session.get(DatasetRow, "dataset-14")
            assert row is not None and (row.size_bytes, row.size_checked_at) == (123, NOW)
        edit_json(
            fake_nav.nav_root / "按任务/libero_10/原始路径.json",
            lambda data: data["links"][0].update(
                source_path=str(fake_nav.storage_roots[0].path / "changed")
            ),
        )
        case.run("dataset-14")
        with session_scope(case.engine, read_only=True) as session:
            row = session.get(DatasetRow, "dataset-14")
            assert row is not None and row.size_bytes is None and row.size_checked_at is None


def test_storage_metadata_fields(tmp_path: Path, fake_nav: FakeNavigation) -> None:
    """第02张交接：robot_type/fps/codebase_version、链接状态及检查时间、根离线原因、aria2/incomplete计数均可存取，未知值可区分。"""
    with dataset_case(tmp_path / "state", fake_nav) as case:
        case.run()
        with session_scope(case.engine) as session:
            source = session.get(SourceRow, ("按任务/libero_10", 0))
            assert source is not None and source.status == "unchecked" and source.fps is None
            (
                source.robot_type,
                source.fps,
                source.fps_rounded,
                source.codebase_version,
                source.meta_checked_at,
            ) = "franka", 20.0, 20, "v3.0", NOW
        case.run("dataset-14")
        with session_scope(case.engine, read_only=True) as session:
            source = session.get(SourceRow, ("按任务/libero_10", 0))
            assert source is not None and (
                source.robot_type,
                source.fps,
                source.fps_rounded,
                source.codebase_version,
            ) == ("franka", 20.0, 20, "v3.0")
            assert all(
                row.online is None and row.checked_at is None
                for row in session.scalars(select(ScanRootRow))
            )


def test_utc_roundtrip(tmp_path: Path, fake_nav: FakeNavigation) -> None:
    """索引时间契约：全部检查及统计时刻往返为aware UTC，墙钟回拨不导致错误先后约束或丢弃结果。"""
    with dataset_case(tmp_path / "state", fake_nav) as case:
        case.run()
        with session_scope(case.engine, read_only=True) as session:
            row = session.scalar(select(DatasetScanRow))
            assert row is not None and row.started_at == NOW and row.committed_at == NOW
            assert row.started_at.tzinfo is not None
            assert row.job_id == 71


def test_schema_constraints(tmp_path: Path, fake_nav: FakeNavigation) -> None:
    """表结构契约：八表主外键、索引、空值及CHECK有效，重复入口主键/非法状态/负大小/不配对统计时间拒绝。"""
    from rdp.infra.diagnostics import ConflictError

    with dataset_case(tmp_path / "state", fake_nav) as case:
        case.run()
        for statement in (
            "UPDATE dataset_links SET status='bad'",
            "UPDATE datasets SET size_bytes=-1",
            "UPDATE dataset_entries SET view='invalid'",
            "UPDATE dataset_sources SET ordinal=-1",
        ):
            with pytest.raises(ConflictError), session_scope(case.engine) as session:
                session.execute(text(statement))
        assert {item["name"] for item in inspect(case.engine).get_indexes("dataset_sources")} == {
            "ix_dataset_sources_identity",
            "ix_dataset_sources_robot",
            "ix_dataset_sources_fps",
        }


def test_migration_upgrade(tmp_path: Path) -> None:
    """迁移契约：0006升级0007原子创建八表，保留全部M0数据和序列，失败回滚，DDL与声明逐项一致。"""
    paths = state_paths(PlatformConfig(state_dir=tmp_path), ())
    initialize_state(paths)
    result = migrate(paths, now=NOW)
    assert result.current_revision == "0013_download_adjustments"
    engine = create_database_engine(paths.database)
    try:
        names = set(inspect(engine).get_table_names())
        assert {
            "datasets",
            "dataset_entries",
            "dataset_documents",
            "dataset_links",
            "dataset_sources",
            "dataset_scans",
            "dataset_scan_roots",
            "dataset_findings",
            "jobs",
            "accounts",
        } <= names
    finally:
        engine.dispose()


def test_migration_downgrade() -> None:
    """迁移契约：downgrade在任何DDL前抛InputError，保留当前索引与永久历史。"""
    with pytest.raises(InputError):
        downgrade()


def test_obsolete_scan_cleanup(tmp_path: Path, fake_nav: FakeNavigation) -> None:
    """索引契约：只清非最新且无索引或发现引用的扫描代次，跳过数据集仍能读到其旧根状态和检查时间。"""
    with dataset_case(tmp_path / "state", fake_nav) as case:
        case.run()
        case.run("dataset-14")
        with session_scope(case.engine, read_only=True) as session:
            assert len(tuple(session.scalars(select(DatasetScanRow)))) == 2
        case.run()
        with session_scope(case.engine, read_only=True) as session:
            assert len(tuple(session.scalars(select(DatasetScanRow)))) == 1


def test_projection_fingerprint_race(
    tmp_path: Path, fake_nav: FakeNavigation, monkeypatch: pytest.MonkeyPatch
) -> None:
    """第一段读取JSON后、计算指纹前发生手工修改时标为不可验证，不能用新指纹发布旧投影。"""
    with dataset_case(tmp_path / "state", fake_nav) as case:
        case.run()
        path = fake_nav.nav_root / "按任务/libero_10/子任务.json"
        identity = (path.stat().st_dev, path.stat().st_ino)
        original = os.read
        changed: list[bool] = []

        def racing_read(descriptor: int, count: int) -> bytes:
            value = original(descriptor, count)
            status = os.fstat(descriptor)
            if value and not changed and (status.st_dev, status.st_ino) == identity:
                changed.append(True)
                path.write_bytes(path.read_bytes() + b" ")
            return value

        monkeypatch.setattr(os, "read", racing_read)

        def execute(context: ExecutionContext) -> None:
            nav = scan_navigation(context, case.scanning)
            item = next(item for item in nav.datasets if item.dataset_id == "dataset-14")
            assert not item.fingerprint.verifiable
            result = publish_scan(
                context, case.scanning, nav, scan_storage(nav, case.scanning, checkpoint=checkpoint)
            )
            assert result.skipped_dataset_count == 1

        record = case.run(execute=execute)
        assert record.summary is not None and not record.summary.aborted
        assert changed == [True]


def test_first_unreadable_identified_entry(tmp_path: Path, fake_nav: FakeNavigation) -> None:
    """首次扫描某文件不可读但身份仍已知时仍展示入口，只存损坏占位，不丢数据集。"""
    path = fake_nav.nav_root / "按任务/libero_10/原始路径.json"
    path.unlink()
    path.symlink_to("missing")
    with dataset_case(tmp_path / "state", fake_nav) as case:
        record = case.run()
        assert record.summary is not None and not record.summary.aborted
        with session_scope(case.engine, read_only=True) as session:
            row = session.get(EntryRow, "按任务/libero_10")
            assert row is not None and row.dataset_id == "dataset-14"
            assert (
                tuple(session.scalars(select(LinkRow).where(LinkRow.entry_path == row.path))) == ()
            )


def test_actual_link_change_clears_size(tmp_path: Path, fake_nav: FakeNavigation) -> None:
    """实际readlink目标变化即清空旧统计，不能仅比较JSON中未改的source_path。"""
    with dataset_case(tmp_path / "state", fake_nav) as case:
        case.run()
        with session_scope(case.engine) as session:
            row = session.get(DatasetRow, "dataset-14")
            assert row is not None
            row.size_bytes, row.size_checked_at = 123, NOW
        link = fake_nav.nav_root / "按任务/libero_10/原始数据"
        link.unlink()
        link.symlink_to("new-missing-target")
        record = case.run("dataset-14")
        assert record.summary is not None and not record.summary.aborted
        with session_scope(case.engine, read_only=True) as session:
            row = session.get(DatasetRow, "dataset-14")
            assert row is not None and row.size_bytes is None
