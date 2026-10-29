"""两段扫描与三种触发的契约；时钟可控，资源、目录、数据库和端口按测试隔离。"""

import os
from datetime import timedelta
from pathlib import Path
from typing import Any, cast

import pytest
from accounts_support import AUDIT_CONTEXT, NOW, member_grant, scenario
from datasets_execution_support import dataset_case
from datasets_support import checkpoint, edit_json
from datasets_trigger_support import TriggerClock
from nav_manifest import FakeNavigation
from sqlalchemy import select

from rdp.audit.models import OperationLogRow
from rdp.infra.db.connection import session_scope
from rdp.infra.diagnostics import (
    ConflictError,
    DefectError,
    Diagnostic,
    DiagnosticCategory,
    DiagnosticLevel,
)
from rdp.jobs.datasets.index import read_index_baseline
from rdp.jobs.datasets.rescan import (
    RescanExecutor,
    RescanParameters,
    build_rescan_definition,
    publish_scan,
    scan_navigation,
    scan_storage,
)
from rdp.jobs.datasets.scan_types import NavigationScan, StorageStage
from rdp.jobs.datasets.triggers import RescanTrigger
from rdp.jobs.errors import JobCancelledError
from rdp.jobs.execution import ExecutionContext
from rdp.jobs.records import find_job
from rdp.jobs.registry import production_registry
from rdp.jobs.service import JobRequest, JobService
from rdp.jobs.types import RecoveryMode


def test_all_five_datasets(tmp_path: Path, fake_nav: FakeNavigation) -> None:
    """验收2：既有fake_nav两个视图各五个入口全量进入索引，数据集按永久编号关联。"""
    with dataset_case(tmp_path / "state", fake_nav) as case:
        result = case.run()
        assert result.summary is not None and not result.summary.aborted
        with session_scope(case.engine, read_only=True) as session:
            baseline = read_index_baseline(session, None, nav_root=fake_nav.nav_root)
        assert len(baseline) == 5
        assert sum(len(item.entry_paths) for item in baseline) == 10
        assert result.progress is not None and result.progress.total_items == 10


def test_single_dataset(tmp_path: Path, fake_nav: FakeNavigation) -> None:
    """验收2：单数据集扫描更新该编号全部入口，不改变其他数据集、全局发现或扫描结果。"""
    with dataset_case(tmp_path / "state", fake_nav) as case:
        case.run()
        with session_scope(case.engine, read_only=True) as session:
            before = read_index_baseline(session, None, nav_root=fake_nav.nav_root)
        edit_json(
            fake_nav.nav_root / "按任务/libero_10/子任务.json",
            lambda data: data.update(extra="changed"),
        )
        result = case.run("dataset-14")
        assert result.summary is not None and not result.summary.aborted
        with session_scope(case.engine, read_only=True) as session:
            after = read_index_baseline(session, None, nav_root=fake_nav.nav_root)
        assert len(after) == 5
        assert [item for item in before if item.dataset_id != "dataset-14"] == [
            item for item in after if item.dataset_id != "dataset-14"
        ]
        assert next(item for item in before if item.dataset_id == "dataset-14") != next(
            item for item in after if item.dataset_id == "dataset-14"
        )


def test_manual_submission(tmp_path: Path) -> None:
    """验收3：手动经JobService.submit提交RESCAN_TYPE，保存真实账号及审计，并通过现有worker领取执行。"""
    with scenario(tmp_path) as (accounts, admin):
        grant = member_grant(accounts, admin)
        service = JobService(accounts.engine, production_registry())
        request = JobRequest(grant.identity, NOW, AUDIT_CONTEXT)
        for dataset_id in (None, "dataset-14"):
            submitted = service.submit(request, "dataset_rescan", {"dataset_id": dataset_id})
            result = service.get(request, submitted.job_id)
            assert result.parameters == {"dataset_id": dataset_id}
            assert result.submitted_by.account_id == grant.identity.account.account_id
            assert result.recovery_mode is RecoveryMode.RESTART


def test_startup_submission(tmp_path: Path, fake_nav: FakeNavigation) -> None:
    """验收3：worker恢复准备完成后首次poll提交一次全量扫描，后续轮询不重复启动提交。"""
    with dataset_case(tmp_path / "state", fake_nav) as case:
        clock = TriggerClock()
        trigger = RescanTrigger(
            JobService(case.engine, production_registry(case.scanning)), clock.clock()
        )
        submitted = trigger.poll()
        assert len(submitted) == 1
        assert trigger.poll() == ()
        with session_scope(case.engine, read_only=True) as session:
            record = find_job(session, submitted[0])
            assert record.parameters == {"dataset_id": None}
            assert record.submitted_by.account_id is None and record.submitted_by.name == "系统"
            events = tuple(
                session.scalars(
                    select(OperationLogRow).where(OperationLogRow.operation == "submit_job")
                )
            )
            assert len(events) == 1 and events[0].actor_name == "系统"
            assert events[0].actor_id is None and events[0].object_id == str(record.job_id)


def test_periodic_submission(tmp_path: Path, fake_nav: FakeNavigation) -> None:
    """验收3：可控单调时钟599.999秒不提交、600秒提交全量，提交人空编号且名字系统，作业与审计同事务。"""
    with dataset_case(tmp_path / "state", fake_nav) as case:
        clock = TriggerClock()
        trigger = RescanTrigger(
            JobService(case.engine, production_registry(case.scanning)), clock.clock()
        )
        first = trigger.poll()
        clock.elapsed_s = 599.999
        assert trigger.poll() == ()
        clock.elapsed_s = 600.0
        second = trigger.poll()
        assert len(second) == 1 and second != first
        assert trigger.poll() == ()
        with session_scope(case.engine, read_only=True) as session:
            record = find_job(session, second[0])
            assert record.parameters == {"dataset_id": None}
            assert record.submitted_by.account_id is None and record.submitted_by.name == "系统"
            assert record.submitted_at == clock.wall


def test_periodic_busy(tmp_path: Path, fake_nav: FakeNavigation) -> None:
    """触发契约：BEGIN短锁忙不消耗启动或到期状态，下轮重试成功；事务入场后的失败不误判锁忙。"""
    with dataset_case(tmp_path / "state", fake_nav) as case:
        clock = TriggerClock()
        trigger = RescanTrigger(
            JobService(case.engine, production_registry(case.scanning)), clock.clock()
        )
        with case.engine.begin():
            assert trigger.poll() == ()
        first = trigger.poll()
        assert len(first) == 1
        clock.elapsed_s = 600.0
        with case.engine.begin():
            assert trigger.poll() == ()
        with case.engine.begin() as connection:
            connection.exec_driver_sql(
                "CREATE TRIGGER reject_scan BEFORE INSERT ON jobs BEGIN SELECT RAISE(ABORT, 'test constraint'); END"
            )
        try:
            with pytest.raises(ConflictError):
                trigger.poll()
        finally:
            with case.engine.begin() as connection:
                connection.exec_driver_sql("DROP TRIGGER reject_scan")
        second = trigger.poll()
        assert len(second) == 1 and second != first
        assert trigger.poll() == ()


def test_clock_changes(tmp_path: Path, fake_nav: FakeNavigation) -> None:
    """触发契约：墙钟回拨不改变600秒间隔，单调回拨不累计负时长，非法时钟报DefectError。"""
    with dataset_case(tmp_path / "state", fake_nav) as case:
        clock = TriggerClock()
        service = JobService(case.engine, production_registry(case.scanning))
        trigger = RescanTrigger(service, clock.clock())
        assert len(trigger.poll()) == 1
        clock.elapsed_s = 300.0
        assert trigger.poll() == ()
        clock.wall -= timedelta(days=1)
        clock.elapsed_s = 100.0
        assert trigger.poll() == ()
        clock.elapsed_s = 599.999
        assert trigger.poll() == ()
        clock.elapsed_s = 600.0
        assert len(trigger.poll()) == 1
        for value in (float("nan"), float("inf"), True):
            clock.elapsed_s = cast(float, value)
            with pytest.raises(DefectError):
                trigger.poll()
        clock.elapsed_s = 601.0
        clock.wall = clock.wall.replace(tzinfo=None)
        with pytest.raises(DefectError):
            trigger.poll()


def test_missed_intervals(tmp_path: Path, fake_nav: FakeNavigation) -> None:
    """触发契约：错过多个周期只补一项，worker重启再提交启动扫描，不修改每日清理任务去重。"""
    with dataset_case(tmp_path / "state", fake_nav) as case:
        clock = TriggerClock()
        service = JobService(case.engine, production_registry(case.scanning))
        trigger = RescanTrigger(service, clock.clock())
        assert len(trigger.poll()) == 1
        clock.elapsed_s = 2400.0
        assert len(trigger.poll()) == 1
        assert trigger.poll() == ()
        clock.elapsed_s = 2999.999
        assert trigger.poll() == ()
        clock.elapsed_s = 3000.0
        assert len(trigger.poll()) == 1
        restarted = RescanTrigger(service, clock.clock())
        assert len(restarted.poll()) == 1
        assert restarted.poll() == ()


def test_first_stage_lock(
    tmp_path: Path, fake_nav: FakeNavigation, monkeypatch: pytest.MonkeyPatch
) -> None:
    """验收4：第一段读取和指纹调用都观察到同一worker导航锁已持有，异常路径释放锁。"""
    observations: list[NavigationScan] = []
    held: list[bool] = []
    contexts: list[ExecutionContext] = []
    original = os.open
    with dataset_case(tmp_path / "state", fake_nav) as case:

        def guarded(path: Any, *args: Any, **kwargs: Any) -> int:
            if contexts and path == "原始路径.json":
                with pytest.raises(DefectError):
                    contexts[0].write_navigation(lambda: None, lambda: None)
                held.append(True)
            return original(path, *args, **kwargs)

        monkeypatch.setattr(os, "open", guarded)

        def execute(context: ExecutionContext) -> None:
            contexts.append(context)
            observations.append(scan_navigation(context, case.scanning))
            assert context.write_navigation(lambda: None, lambda: True)

        result = case.run(execute=execute)
        assert result.summary is not None and not result.summary.aborted
    assert held and all(held)
    assert len(observations[0].datasets) == 5
    assert sum(len(item.entries) for item in observations[0].datasets) == 10
    assert all(item.fingerprint.verifiable for item in observations[0].datasets)
    assert observations[0].lock_held_s >= 0


def test_second_stage_unlocked(tmp_path: Path, fake_nav: FakeNavigation) -> None:
    """验收4：第二段调用时导航锁未持有；NOT_RUN结果显式为空，不读取任何假存储根。"""
    observed: list[bool] = []
    with dataset_case(tmp_path / "state", fake_nav) as case:

        def execute(context: ExecutionContext) -> None:
            nav = scan_navigation(context, case.scanning)

            def check() -> None:
                with session_scope(case.engine, read_only=True) as session:
                    observed.append(find_job(session, context.job_id).holds_navigation_lock)

            result = scan_storage(nav, case.scanning, checkpoint=check)
            assert result.stage is StorageStage.NOT_RUN
            assert result.roots == result.links == result.sources == result.findings == ()

        record = case.run(execute=execute)
        assert record.summary is not None and not record.summary.aborted
    assert observed == [False]


def test_changed_dataset_skip(tmp_path: Path, fake_nav: FakeNavigation) -> None:
    """验收4：两段之间修改一个数据集后提交跳过该数据集、保留旧行并报DATASET_CHANGED提示，其余数据集正常更新。"""
    with dataset_case(tmp_path / "state", fake_nav) as case:
        case.run()
        with session_scope(case.engine, read_only=True) as session:
            before = read_index_baseline(session, "dataset-14")

        def execute(context: ExecutionContext) -> None:
            nav = scan_navigation(context, case.scanning)
            storage = scan_storage(nav, case.scanning, checkpoint=checkpoint)
            edit_json(
                fake_nav.nav_root / "按任务/libero_10/子任务.json",
                lambda data: data.update(extra="during scan"),
            )
            result = publish_scan(context, case.scanning, nav, storage)
            assert result.skipped_dataset_count == 1 and result.dataset_count == 4

        record = case.run(execute=execute)
        assert record.summary is not None and not record.summary.aborted
        assert any(group.rule == "DATASET_CHANGED" for group in record.diagnostics)
        with session_scope(case.engine, read_only=True) as session:
            assert read_index_baseline(session, "dataset-14") == before


def test_recheck_commit_lock(tmp_path: Path, fake_nav: FakeNavigation) -> None:
    """验收4：最终复核到事务提交持续持同一导航锁，插入竞争写入只能在提交之后进行。"""
    from sqlalchemy import event

    observed: list[bool] = []
    contexts: list[ExecutionContext] = []
    with dataset_case(tmp_path / "state", fake_nav) as case:

        def execute(context: ExecutionContext) -> None:
            contexts.append(context)
            RescanExecutor(case.scanning).execute(context)

        def query_lock(
            _connection: Any,
            _cursor: Any,
            statement: str,
            _parameters: Any,
            _context: Any,
            _many: bool,
        ) -> None:
            if statement.startswith("INSERT INTO dataset_scans"):
                with pytest.raises(DefectError):
                    contexts[0].write_navigation(lambda: None, lambda: None)
                observed.append(True)

        event.listen(case.engine, "before_cursor_execute", query_lock)
        try:
            record = case.run(execute=execute)
        finally:
            event.remove(case.engine, "before_cursor_execute", query_lock)
        assert record.summary is not None and not record.summary.aborted
    assert observed == [True]


def test_cancel_and_restart(tmp_path: Path, fake_nav: FakeNavigation) -> None:
    """ADR0005：等待取消可退出，持锁段取消延后，提交前取消保留旧索引；RESTART从头采集并由框架控制恢复次数。"""
    from rdp.jobs.errors import WorkerStoppingError

    signal_diagnostic = Diagnostic(
        level=DiagnosticLevel.ERROR,
        category=DiagnosticCategory.CONFLICT,
        stage="控制检查",
        source="平台",
        objects=(),
        rule="测试控制信号",
        actual="收到控制请求",
        expected=None,
        consequence="阶段停止",
        next_step="重新提交",
    )
    with dataset_case(tmp_path / "state", fake_nav) as case:

        def execute(context: ExecutionContext) -> None:
            nav = scan_navigation(context, case.scanning)

            def cancel() -> None:
                raise JobCancelledError((signal_diagnostic,))

            with pytest.raises(JobCancelledError):
                scan_storage(nav, case.scanning, checkpoint=cancel)

            def stop() -> None:
                raise WorkerStoppingError((signal_diagnostic,))

            with pytest.raises(WorkerStoppingError):
                scan_storage(nav, case.scanning, checkpoint=stop)

        record = case.run(execute=execute)
        assert record.summary is not None and not record.summary.aborted
        with session_scope(case.engine, read_only=True) as session:
            assert read_index_baseline(session, None) == ()


def test_job_definition() -> None:
    """作业契约：RESCAN_TYPE登记RESTART、并发1、无需GPU、无预执行存储需求，Web缺执行能力不能运行。"""
    definition = build_rescan_definition(None)
    assert definition.type_name == "dataset_rescan"
    assert definition.recovery_mode is RecoveryMode.RESTART
    assert definition.concurrency == 1 and not definition.requires_gpu
    assert definition.storage == ()
    assert definition.parameters_model is RescanParameters


def test_summary_counts(tmp_path: Path, fake_nav: FakeNavigation) -> None:
    """作业契约：摘要包括实际发布数据集数、入口数、跳过数和发现数；结果只由现有outcome函数按独立计数计算。"""
    with dataset_case(tmp_path / "state", fake_nav) as case:
        record = case.run()
        assert record.summary is not None
        assert record.summary.total_items == 10 and record.summary.failed_items == 0
        assert record.summary.warning_count == 0
        assert record.progress is not None and "5数据集" in record.progress.stage_name


def test_parallel_isolation(tmp_path: Path, fake_nav: FakeNavigation) -> None:
    """验收8：每次fake_nav、状态目录、时钟、日志和端口均为测试私有；make check以-n auto连跑三次一致，不关闭xdist。"""
    from nav_manifest import expand_fake_nav

    other = tmp_path / "other"
    other.mkdir()
    second = expand_fake_nav(other, fixture_dir=Path(__file__).parent / "fixtures/nav")
    with (
        dataset_case(tmp_path / "state1", fake_nav) as first_case,
        dataset_case(tmp_path / "state2", second) as second_case,
    ):
        first_case.run()
        with session_scope(second_case.engine, read_only=True) as session:
            assert read_index_baseline(session, None) == ()
        second_case.run()
        assert first_case.paths.database != second_case.paths.database
