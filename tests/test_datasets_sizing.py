"""统计大小作业验收：真实队列和索引，目录与挂载表均为临时夹具。"""

import os
import subprocess
import time
from pathlib import Path
from threading import Event, get_native_id
from threading import enumerate as threads
from typing import Any

import pytest
from datasets_execution_support import dataset_case
from datasets_storage_support import enable_storage
from nav_manifest import FakeNavigation
from sqlalchemy import select

from rdp.infra.db.connection import session_scope
from rdp.jobs.datasets.models import DatasetRow, EntryRow, LinkRow
from rdp.jobs.registry import production_registry


def test_sizing_late_stat_stops_before_directory_open(
    tmp_path: Path, fake_nav: FakeNavigation, monkeypatch: pytest.MonkeyPatch
) -> None:
    """超时后迟到的lstat不能继续打开目录；超时不是仅丢弃结果仍继续遍历。"""
    release = Event()
    original_stat, original_open = Path.lstat, os.open
    target = fake_nav.storage_roots[0].path / "libero_v3/libero_10"
    calls = 0
    opened: list[Path] = []
    with dataset_case(tmp_path / "state", fake_nav) as case:
        enable_storage(case)
        case.run()

        def delayed(path: Path) -> os.stat_result:
            nonlocal calls
            if path == target:
                calls += 1
                if calls == 2:
                    assert release.wait(5)
            return original_stat(path)

        def recorded(path: Any, *args: Any, **kwargs: Any) -> int:
            if path == target:
                opened.append(path)
            return original_open(path, *args, **kwargs)

        monkeypatch.setattr(Path, "lstat", delayed)
        monkeypatch.setattr(os, "open", recorded)
        definition = production_registry(case.scanning).lookup("dataset_sizing")
        assert definition is not None
        try:
            result = case.run("dataset-14", definition=definition)
            assert result.summary is not None and result.summary.warning_count == 1
        finally:
            release.set()
            for thread in threads():
                if thread.name == "dataset-sizing":
                    thread.join(5)
                    assert not thread.is_alive()
        assert calls == 2 and opened == []


def test_manual_sizing_submission_parameters(tmp_path: Path) -> None:
    """第03张提交接口契约：dataset_id可省略、null或合法编号；身份由JobService记录，拒绝路径和额外字段。"""
    from accounts_support import AUDIT_CONTEXT, NOW, member_grant, scenario

    from rdp.jobs.errors import JobInputError
    from rdp.jobs.service import JobRequest, JobService

    with scenario(tmp_path) as (accounts, admin):
        grant = member_grant(accounts, admin)
        service = JobService(accounts.engine, production_registry())
        request = JobRequest(grant.identity, NOW, AUDIT_CONTEXT)
        valid: tuple[dict[str, object], ...] = (
            {},
            {"dataset_id": None},
            {"dataset_id": "dataset-14"},
        )
        for parameters in valid:
            record = service.submit(request, "dataset_sizing", parameters)
            assert record.parameters == {"dataset_id": parameters.get("dataset_id")}
            assert record.submitted_by.account_id == grant.identity.account.account_id
            assert record.recovery_mode.value == "restart"
        invalid: tuple[dict[str, object], ...] = (
            {"dataset_id": "../bad"},
            {"dataset_id": ""},
            {"path": "arbitrary"},
        )
        for parameters in invalid:
            with pytest.raises(JobInputError):
                service.submit(request, "dataset_sizing", parameters)


def test_sizing_cancel_does_not_publish(
    tmp_path: Path, fake_nav: FakeNavigation, monkeypatch: pytest.MonkeyPatch
) -> None:
    """遍历阻塞期间取消在主调用线程响应；迟到线程被放弃，索引不出现部分大小。"""
    from jobs_storage_support import NOW

    from rdp.jobs.records import StateChange, transition_job
    from rdp.jobs.types import JobState

    cancel, release, entered = Event(), Event(), Event()
    original = os.open
    target = fake_nav.storage_roots[0].path / "libero_v3/libero_10"
    with dataset_case(tmp_path / "state", fake_nav) as case:
        enable_storage(case)
        case.run()

        def opened(path: Any, *args: Any, **kwargs: Any) -> int:
            if path == target:
                entered.set()
                with session_scope(case.engine) as session:
                    transition_job(
                        session,
                        case.number - 1,
                        StateChange(JobState.RUNNING, JobState.CANCELLING, NOW),
                    )
                cancel.set()
                assert release.wait(5)
            return original(path, *args, **kwargs)

        monkeypatch.setattr(os, "open", opened)
        definition = production_registry(case.scanning).lookup("dataset_sizing")
        assert definition is not None
        try:
            result = case.run("dataset-14", definition=definition, cancel=cancel)
            assert entered.is_set() and result.state is JobState.CANCELLED
        finally:
            release.set()
            for thread in threads():
                if thread.name == "dataset-sizing":
                    thread.join(5)
                    assert not thread.is_alive()
        with session_scope(case.engine, read_only=True) as session:
            row = session.get(DatasetRow, "dataset-14")
            assert row is not None and row.size_bytes is None


def test_sizing_timeout_discards_partial(
    tmp_path: Path, fake_nav: FakeNavigation, monkeypatch: pytest.MonkeyPatch
) -> None:
    """一次目录访问停滞超时则整数据集保留旧值，迟到线程不追加统计或发布。"""
    release, entered = Event(), Event()
    original = os.open
    target = fake_nav.storage_roots[0].path / "libero_v3/libero_10"
    with dataset_case(tmp_path / "state", fake_nav) as case:
        enable_storage(case)
        case.run()

        def opened(path: Any, *args: Any, **kwargs: Any) -> int:
            if path == target:
                entered.set()
                assert release.wait(5)
            return original(path, *args, **kwargs)

        monkeypatch.setattr(os, "open", opened)
        definition = production_registry(case.scanning).lookup("dataset_sizing")
        assert definition is not None
        try:
            result = case.run("dataset-14", definition=definition)
            assert entered.is_set() and result.summary is not None and not result.summary.aborted
            assert result.summary.warning_count == 1
        finally:
            release.set()
            for thread in threads():
                if thread.name == "dataset-sizing":
                    thread.join(5)
                    assert not thread.is_alive()
        with session_scope(case.engine, read_only=True) as session:
            row = session.get(DatasetRow, "dataset-14")
            assert row is not None and row.size_bytes is None


def test_sizing_progress_allows_long_walk(
    tmp_path: Path, fake_nav: FakeNavigation, monkeypatch: pytest.MonkeyPatch
) -> None:
    """持续有进展的遍历可超过单次访问预算，不能把长数据集误判成存储超时。"""
    root = fake_nav.storage_roots[0].path / "libero_v3/libero_10"
    for index in range(12):
        (root / f"slow-{index}").touch()
    original = Path.lstat
    with dataset_case(tmp_path / "state", fake_nav) as case:
        enable_storage(case)
        case.run()

        def slow(path: Path) -> os.stat_result:
            if path.parent == root and path.name.startswith("slow-"):
                time.sleep(0.1)
            return original(path)

        monkeypatch.setattr(Path, "lstat", slow)
        definition = production_registry(case.scanning).lookup("dataset_sizing")
        assert definition is not None
        result = case.run("dataset-14", definition=definition)
        assert (
            result.summary is not None
            and not result.summary.aborted
            and result.summary.warning_count == 0
        )
        assert result.summary.elapsed_s > 1


def test_sizing_priority_failure_is_external(
    tmp_path: Path, fake_nav: FakeNavigation, monkeypatch: pytest.MonkeyPatch
) -> None:
    """不能设置idle IO时以外部失败结束，不退回普通优先级遍历，不覆盖旧统计。"""

    def failed(argv: Any, **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        raise subprocess.CalledProcessError(1, argv, stderr="fixture refused")

    with dataset_case(tmp_path / "state", fake_nav) as case:
        enable_storage(case)
        case.run()
        monkeypatch.setattr(subprocess, "run", failed)
        definition = production_registry(case.scanning).lookup("dataset_sizing")
        assert definition is not None
        result = case.run("dataset-14", definition=definition)
        assert result.summary is not None and result.summary.aborted
        assert any(group.rule == "SIZING_IO_PRIORITY" for group in result.diagnostics)
        with session_scope(case.engine, read_only=True) as session:
            row = session.get(DatasetRow, "dataset-14")
            assert row is not None and row.size_bytes is None


def test_nightly_sizing_system_submission(tmp_path: Path, fake_nav: FakeNavigation) -> None:
    """验收6：每天本地03:00用既有每日规则提交，全量、系统身份，跨重复轮询只提交一次。"""
    from datetime import time
    from zoneinfo import ZoneInfo

    from jobs_storage_support import NOW

    from rdp.jobs.records import find_job
    from rdp.jobs.schedules import production_schedules, schedule_due
    from rdp.jobs.service import JobService

    with dataset_case(tmp_path / "state", fake_nav) as case:
        registry = production_registry(case.scanning)
        rule = next(
            (
                rule
                for rule in production_schedules(registry).definitions()
                if rule.type_name == "dataset_sizing"
            ),
            None,
        )
        assert rule is not None and rule.local_time == time(3)
        assert rule.parameters == {"dataset_id": None}
        assert (
            schedule_due(
                rule, None, now=NOW.replace(hour=2, minute=59), zone=ZoneInfo("UTC"), startup=False
            )
            is None
        )
        assert (
            schedule_due(
                rule, None, now=NOW.replace(hour=3, minute=0), zone=ZoneInfo("UTC"), startup=False
            )
            == NOW.date()
        )
        service = JobService(case.engine, registry)
        first = service.submit_scheduled(rule, NOW.date(), now=NOW)
        assert first is not None
        assert service.submit_scheduled(rule, NOW.date(), now=NOW) is None
        with session_scope(case.engine, read_only=True) as session:
            record = find_job(session, first.job_id)
            assert record.type_name == "dataset_sizing"
            assert record.submitted_by.name == "系统" and record.submitted_by.account_id is None


def test_sizing_navigation_change_preserves_old(
    tmp_path: Path, fake_nav: FakeNavigation, monkeypatch: pytest.MonkeyPatch
) -> None:
    """无锁发布契约：遍历期间导航改动，整数据集保留旧大小和时间，记跳过警告。"""
    from datasets_support import edit_json

    original = os.open
    changed = False
    with dataset_case(tmp_path / "state", fake_nav) as case:
        enable_storage(case)
        case.run()
        definition = production_registry(case.scanning).lookup("dataset_sizing")
        assert definition is not None
        case.run("dataset-14", definition=definition)
        with session_scope(case.engine, read_only=True) as session:
            row = session.get(DatasetRow, "dataset-14")
            assert row is not None
            previous = row.size_bytes, row.size_checked_at
        target = fake_nav.storage_roots[0].path / "libero_v3/libero_10"
        (target / "more").write_bytes(b"new bytes")

        def opened(path: Any, *args: Any, **kwargs: Any) -> int:
            nonlocal changed
            if path == target and not changed:
                changed = True
                edit_json(
                    fake_nav.nav_root / "按任务/libero_10/原始路径.json",
                    lambda data: data.update(notes=["concurrent change"]),
                )
            return original(path, *args, **kwargs)

        monkeypatch.setattr(os, "open", opened)
        result = case.run("dataset-14", definition=definition)
        assert changed and result.summary is not None and result.summary.warning_count == 1
        with session_scope(case.engine, read_only=True) as session:
            row = session.get(DatasetRow, "dataset-14")
            assert row is not None and (row.size_bytes, row.size_checked_at) == previous


def test_sizing_panel_counts_and_clears(tmp_path: Path, fake_nav: FakeNavigation) -> None:
    """验收6：未完成文件按规范入口计数，同类聚合；文件移除后旧④组提示清除。"""
    from rdp.jobs.datasets.models import FindingRow

    root = fake_nav.storage_roots[0].path / "libero_v3/libero_10"
    for index in range(12):
        (root / f"part-{index}.aria2").write_bytes(b"x")
    with dataset_case(tmp_path / "state", fake_nav) as case:
        enable_storage(case)
        case.run()
        definition = production_registry(case.scanning).lookup("dataset_sizing")
        assert definition is not None
        result = case.run("dataset-14", definition=definition)
        assert result.summary is not None and not result.summary.aborted
        with session_scope(case.engine, read_only=True) as session:
            group = session.scalar(
                select(FindingRow).where(
                    FindingRow.owner_key == "dataset:dataset-14",
                    FindingRow.rule == "DOWNLOAD_INCOMPLETE",
                )
            )
            assert group is not None and group.total == 12 and len(group.samples) == 10
            assert group.group == "storage" and group.severity == "notice"
        for index in range(12):
            (root / f"part-{index}.aria2").unlink()
        case.run("dataset-14", definition=definition)
        with session_scope(case.engine, read_only=True) as session:
            assert (
                session.scalar(
                    select(FindingRow).where(
                        FindingRow.owner_key == "dataset:dataset-14",
                        FindingRow.rule == "DOWNLOAD_INCOMPLETE",
                    )
                )
                is None
            )


def test_sizing_offline_retains_previous(
    tmp_path: Path, fake_nav: FakeNavigation, monkeypatch: pytest.MonkeyPatch
) -> None:
    """离线根不遍历、不覆盖大小与统计时间；作业带警告成功。"""
    original = os.open
    with dataset_case(tmp_path / "state", fake_nav) as case:
        enable_storage(case)
        case.run()
        definition = production_registry(case.scanning).lookup("dataset_sizing")
        assert definition is not None
        case.run("dataset-14", definition=definition)
        with session_scope(case.engine, read_only=True) as session:
            row = session.get(DatasetRow, "dataset-14")
            assert row is not None
            previous = row.size_bytes, row.size_checked_at
        enable_storage(case, table="")

        def opened(path: Any, *args: Any, **kwargs: Any) -> int:
            if isinstance(path, (str, Path)) and any(
                Path(path).is_relative_to(root.path) for root in fake_nav.storage_roots
            ):
                pytest.fail("离线根不能打开")
            return original(path, *args, **kwargs)

        monkeypatch.setattr(os, "open", opened)
        definition = production_registry(case.scanning).lookup("dataset_sizing")
        assert definition is not None
        result = case.run("dataset-14", definition=definition)
        assert (
            result.summary is not None
            and not result.summary.aborted
            and result.summary.warning_count > 0
        )
        with session_scope(case.engine, read_only=True) as session:
            row = session.get(DatasetRow, "dataset-14")
            assert row is not None and (row.size_bytes, row.size_checked_at) == previous


def test_sizing_idle_priority_and_no_lock(
    tmp_path: Path, fake_nav: FakeNavigation, monkeypatch: pytest.MonkeyPatch
) -> None:
    """验收6：遍历前给专属线程设置ionice idle；数据访问期间作业没有导航写锁。"""
    from rdp.jobs.records import find_job

    calls: list[tuple[str, ...]] = []
    original = os.open
    main_thread = get_native_id()
    with dataset_case(tmp_path / "state", fake_nav) as case:
        enable_storage(case)
        case.run()

        def run(argv: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
            assert kwargs["timeout"] > 0
            calls.append(tuple(argv))
            assert int(argv[-1]) == get_native_id() != main_thread
            return subprocess.CompletedProcess(argv, 0, "", "")

        def opened(path: Any, flags: int, *args: Any, **kwargs: Any) -> int:
            if isinstance(path, (str, Path)) and any(
                Path(path).is_relative_to(root.path) for root in fake_nav.storage_roots
            ):
                assert calls and flags & os.O_NOATIME
                with session_scope(case.engine, read_only=True) as session:
                    assert not find_job(session, case.number - 1).holds_navigation_lock
            return original(path, flags, *args, **kwargs)

        monkeypatch.setattr(subprocess, "run", run)
        monkeypatch.setattr(os, "open", opened)
        definition = production_registry(case.scanning).lookup("dataset_sizing")
        assert definition is not None
        result = case.run("dataset-14", definition=definition)
        assert result.summary is not None and not result.summary.aborted
    assert calls and all(call[1:4] == ("-c", "3", "-p") for call in calls)


def test_sizing_excludes_nested_directory_sizes(tmp_path: Path, fake_nav: FakeNavigation) -> None:
    """评审回归：多层及空目录自身不计大小，数据集、入口和链接均只统计文件的23字节。"""
    import shutil

    root = fake_nav.storage_roots[0].path / "libero_v3/libero_10"
    shutil.rmtree(root)
    (root / "level-one/level-two").mkdir(parents=True)
    (root / "empty").mkdir()
    (root / "first.bin").write_bytes(b"12345")
    (root / "level-one/second.bin").write_bytes(b"1234567")
    (root / "level-one/level-two/third.bin").write_bytes(b"12345678901")
    with dataset_case(tmp_path / "state", fake_nav) as case:
        enable_storage(case)
        case.run()
        definition = production_registry(case.scanning).lookup("dataset_sizing")
        assert definition is not None
        result = case.run("dataset-14", definition=definition)
        assert result.summary is not None and not result.summary.aborted
        with session_scope(case.engine, read_only=True) as session:
            row = session.get(DatasetRow, "dataset-14")
            assert row is not None and row.size_bytes == 23
            assert tuple(
                session.scalars(
                    select(EntryRow.size_bytes).where(EntryRow.dataset_id == "dataset-14")
                )
            ) == (23, 23)
            paths = ("按任务/libero_10", "按格式/lerobot/3.0/libero_10")
            assert tuple(
                session.scalars(select(LinkRow.size_bytes).where(LinkRow.entry_path.in_(paths)))
            ) == (23, 23)


def test_sizing_hardlinks_match_du(tmp_path: Path, fake_nav: FakeNavigation) -> None:
    """Du --apparent-size -sb口径：单链接目标内硬链接只计一次，视图之间分别计入口大小。"""
    import os
    import shutil

    root = fake_nav.storage_roots[0].path / "libero_v3/libero_10"
    shutil.rmtree(root)
    root.mkdir()
    (root / "first").write_bytes(b"1234567")
    os.link(root / "first", root / "second")
    (root / "symbolic").symlink_to("missing")
    os.link(root / "symbolic", root / "symbolic-alias", follow_symlinks=False)
    expected = 7 + len("missing")
    with dataset_case(tmp_path / "state", fake_nav) as case:
        enable_storage(case)
        case.run()
        definition = production_registry(case.scanning).lookup("dataset_sizing")
        assert definition is not None
        result = case.run("dataset-14", definition=definition)
        assert result.summary is not None and not result.summary.aborted
        with session_scope(case.engine, read_only=True) as session:
            row = session.get(DatasetRow, "dataset-14")
            assert row is not None and row.size_bytes == expected


def test_sizing_bytes_and_incomplete_files(tmp_path: Path, fake_nav: FakeNavigation) -> None:
    """验收6：目录不计大小，软链接计自身，排除未链接内容，并同次统计两种下载标记。"""
    root = fake_nav.storage_roots[0].path / "libero_v3/libero_10"
    # 此目标改为手算的小树；其他数据集和存储根完全由fake_nav隔离。
    import shutil

    shutil.rmtree(root)
    root.mkdir()
    (root / "part").mkdir()
    (root / "a.bin").write_bytes(b"12345")
    (root / "one.aria2").write_bytes(b"12")
    (root / "part/two.incomplete").write_bytes(b"123")
    (root / "outside-link").symlink_to("missing")
    expected = 5 + 2 + 3 + len("missing")
    (root.parent / "unlinked").write_bytes(b"x" * 1000)
    with dataset_case(tmp_path / "state", fake_nav) as case:
        enable_storage(case)
        case.run()
        definition = production_registry(case.scanning).lookup("dataset_sizing")
        assert definition is not None
        record = case.run("dataset-14", definition=definition)
        assert record.summary is not None and not record.summary.aborted
        assert record.type_name == "dataset_sizing"
        assert record.progress is not None and f"{expected}字节" in record.progress.stage_name
        with session_scope(case.engine, read_only=True) as session:
            dataset = session.get(DatasetRow, "dataset-14")
            assert dataset is not None and dataset.size_bytes == expected
            assert (
                dataset.size_checked_at is not None
                and dataset.size_checked_at.utcoffset() is not None
            )
            rows = tuple(
                session.scalars(select(EntryRow).where(EntryRow.dataset_id == "dataset-14"))
            )
            assert len(rows) == 2
            assert all(
                (row.size_bytes, row.aria2_count, row.incomplete_count) == (expected, 1, 1)
                for row in rows
            )
            assert (
                session.scalar(
                    select(LinkRow.size_bytes).where(LinkRow.entry_path == "按任务/libero_10")
                )
                == expected
            )
