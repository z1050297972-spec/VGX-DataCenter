"""每日定时作业的日期、提交和去重测试；只使用临时数据库及注入时钟。"""

import sqlite3
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest
from jobs_schedules_support import scheduled_case
from sqlalchemy import event

from rdp.infra.db.connection import session_scope
from rdp.infra.diagnostics import ConflictError
from rdp.jobs import policy
from rdp.jobs.registry import production_registry
from rdp.jobs.schedules import ScheduleRegistry
from rdp.jobs.scheduling_types import ScheduledJob


def test_at_time(tmp_path: Path) -> None:
    """验收6：可控时钟从02:59:59到03:00时只提交一次；提交人SYSTEM_ACTOR，操作日志操作人系统。"""
    from datetime import UTC, datetime, timedelta

    from jobs_schedules_support import scheduled_case
    from sqlalchemy import select

    from rdp.audit.models import OperationLogRow
    from rdp.infra.actors import SYSTEM_ACTOR
    from rdp.infra.db.connection import session_scope
    from rdp.jobs.records import find_job

    now = datetime(2026, 10, 27, 2, 59, 59, tzinfo=UTC)
    with scheduled_case(tmp_path, now) as case:
        previous = now.replace(hour=3, minute=0, second=0) - timedelta(days=1)
        case.service.submit_scheduled(case.definition, previous.date(), now=previous)
        assert case.scheduler.tick_schedules() == ()
        case.clock.wall = now + timedelta(seconds=1)
        submitted = case.scheduler.tick_schedules()
        assert len(submitted) == 1 and case.scheduler.tick_schedules() == ()
        with session_scope(case.dependencies.engine, read_only=True) as session:
            record = find_job(session, submitted[0])
            assert record.submitted_by == SYSTEM_ACTOR and record.submitted_at == case.clock.wall
            audit = session.scalar(
                select(OperationLogRow).where(OperationLogRow.object_id == str(record.job_id))
            )
            assert audit is not None and audit.actor_id is None and audit.actor_name == "系统"
            assert (
                audit.operation == "submit_job"
                and audit.request_id is None
                and audit.source_ip is None
            )


def test_same_day(tmp_path: Path) -> None:
    """验收6：同一本地日期多轮轮询/worker重启仍一个作业和一条系统提交日志。"""
    from datetime import UTC, datetime

    from jobs_schedules_support import scheduled_case
    from sqlalchemy import func, select

    from rdp.audit.models import OperationLogRow
    from rdp.infra.db.connection import session_scope
    from rdp.jobs.models import JobRow
    from rdp.jobs.scheduling_models import ScheduleSubmissionRow

    with scheduled_case(tmp_path, datetime(2026, 10, 27, 4, tzinfo=UTC)) as case:
        assert len(case.scheduler.tick_schedules()) == 1
        for hour in (5, 6, 10, 23):
            case.clock.wall = case.clock.wall.replace(hour=hour)
            assert case.scheduler.tick_schedules() == ()
            case.restart()
            assert case.scheduler.tick_schedules() == ()
        with session_scope(case.dependencies.engine, read_only=True) as session:
            for table in (JobRow, OperationLogRow, ScheduleSubmissionRow):
                assert session.scalar(select(func.count()).select_from(table)) == 1


def test_first_start(tmp_path: Path) -> None:
    """K2：从未提交的规则启动立即补一次，03:00前补过当天不再次按点提交。"""
    from datetime import UTC, datetime

    from jobs_schedules_support import scheduled_case

    from rdp.infra.db.connection import session_scope
    from rdp.jobs.schedule_records import latest_submission

    with scheduled_case(tmp_path, datetime(2026, 10, 27, 1, tzinfo=UTC)) as case:
        first = case.scheduler.tick_schedules()
        assert len(first) == 1
        case.clock.wall = case.clock.wall.replace(hour=3)
        assert case.scheduler.tick_schedules() == ()
        case.restart()
        assert case.scheduler.tick_schedules() == ()
        with session_scope(case.dependencies.engine, read_only=True) as session:
            saved = latest_submission(session, case.definition.name)
            assert saved is not None and saved.job_id == first[0] and saved.submitted_at.hour == 1


def test_catchup_over_day(tmp_path: Path) -> None:
    """K2：最近提交超过86400秒启动补一次，停机多日不逐日补，记录今天日期。"""
    from datetime import UTC, datetime, timedelta

    from jobs_schedules_support import scheduled_case
    from sqlalchemy import func, select

    from rdp.infra.db.connection import session_scope
    from rdp.jobs.models import JobRow
    from rdp.jobs.schedule_records import latest_submission

    now = datetime(2026, 10, 27, 1, tzinfo=UTC)
    with scheduled_case(tmp_path, now) as case:
        old = now - timedelta(days=7)
        case.service.submit_scheduled(case.definition, old.date(), now=old)
        ids = case.scheduler.tick_schedules()
        assert len(ids) == 1 and case.scheduler.tick_schedules() == ()
        with session_scope(case.dependencies.engine, read_only=True) as session:
            latest = latest_submission(session, case.definition.name)
            assert (
                latest is not None
                and latest.local_date == now.date()
                and latest.submitted_at == now
            )
            assert session.scalar(select(func.count()).select_from(JobRow)) == 2


def test_exact_day() -> None:
    """K2：恰好86400秒不补跑；再过一微秒符合补跑；普通到点资格独立判断。"""
    from datetime import UTC, date, datetime, time, timedelta
    from zoneinfo import ZoneInfo

    from rdp.jobs.schedules import schedule_due
    from rdp.jobs.scheduling_types import ScheduleSubmission

    definition = ScheduledJob(
        "清除", "purge_errors", {}, time(23, 59), description="删除超过保留期的程序报错记录"
    )
    previous = ScheduleSubmission(
        "清除", date(2026, 10, 26), 71, datetime(2026, 10, 26, 12, tzinfo=UTC)
    )
    now = datetime(2026, 10, 27, 12, tzinfo=UTC)
    assert schedule_due(definition, previous, now=now, zone=ZoneInfo("UTC"), startup=True) is None
    assert schedule_due(
        definition,
        previous,
        now=now + timedelta(microseconds=1),
        zone=ZoneInfo("UTC"),
        startup=True,
    ) == date(2026, 10, 27)
    assert (
        schedule_due(
            definition,
            previous,
            now=now + timedelta(seconds=1),
            zone=ZoneInfo("UTC"),
            startup=False,
        )
        is None
    )
    assert schedule_due(
        definition,
        previous,
        now=now.replace(hour=23, minute=59),
        zone=ZoneInfo("UTC"),
        startup=False,
    ) == date(2026, 10, 27)


def test_submitted_not_finished(tmp_path: Path) -> None:
    """契约：24小时依据最近提交时刻，不用执行开始/完成时刻；上个作业仍运行也允许新日期提交排队。"""
    from datetime import UTC, datetime, timedelta

    from jobs_schedules_support import scheduled_case

    from rdp.infra.db.connection import session_scope
    from rdp.jobs.records import claim_job, find_job
    from rdp.jobs.types import JobState

    now = datetime(2026, 10, 27, 1, tzinfo=UTC)
    with scheduled_case(tmp_path, now) as case:
        old = now - timedelta(hours=25)
        previous = case.service.submit_scheduled(case.definition, old.date(), now=old)
        assert previous is not None
        with session_scope(case.dependencies.engine) as session:
            claim_job(
                session, previous.job_id, now=now, paths=case.dependencies.paths, gpu_index=None
            )
        ids = case.scheduler.tick_schedules()
        assert len(ids) == 1 and ids[0] != previous.job_id
        with session_scope(case.dependencies.engine, read_only=True) as session:
            assert find_job(session, previous.job_id).state is JobState.RUNNING
            assert find_job(session, ids[0]).state is JobState.QUEUED


def test_clock_backwards(tmp_path: Path) -> None:
    """契约：墙钟回拨的负间隔按零，历史日期唯一行仍阻止回拨后重复；不以最近一行推断旧日期未提交。"""
    from datetime import UTC, datetime, timedelta

    from jobs_schedules_support import scheduled_case
    from sqlalchemy import func, select

    from rdp.infra.db.connection import session_scope
    from rdp.jobs.models import JobRow

    now = datetime(2026, 10, 27, 12, tzinfo=UTC)
    with scheduled_case(tmp_path, now) as case:
        first = case.scheduler.tick_schedules()
        case.clock.wall = now + timedelta(days=1)
        assert len(case.scheduler.tick_schedules()) == 1
        case.clock.wall = now
        case.restart()
        assert case.scheduler.tick_schedules() == ()
        case.clock.wall = (now - timedelta(days=1)).replace(hour=1)
        case.restart()
        assert case.scheduler.tick_schedules() == ()
        case.clock.wall = case.clock.wall.replace(hour=3)
        assert len(case.scheduler.tick_schedules()) == 1
        with session_scope(case.dependencies.engine, read_only=True) as session:
            assert session.scalar(select(func.count()).select_from(JobRow)) == 3
            assert session.get(JobRow, first[0]) is not None


def test_utc_local_dates(tmp_path: Path) -> None:
    """契约：UTC同一天可跨两个本地日、UTC跨日可同一本地日，去重严格按注入时区。"""
    from datetime import UTC, date, datetime
    from zoneinfo import ZoneInfo

    from jobs_schedules_support import scheduled_case

    from rdp.infra.db.connection import session_scope
    from rdp.jobs.schedule_records import latest_submission

    with scheduled_case(
        tmp_path / "two_dates",
        datetime(2026, 10, 27, 1, tzinfo=UTC),
        zone=ZoneInfo("America/Cambridge_Bay"),
    ) as case:
        assert len(case.scheduler.tick_schedules()) == 1
        case.clock.wall = datetime(2026, 10, 27, 10, tzinfo=UTC)
        assert len(case.scheduler.tick_schedules()) == 1
        with session_scope(case.dependencies.engine, read_only=True) as session:
            latest = latest_submission(session, case.definition.name)
            assert latest is not None and latest.local_date == date(2026, 10, 27)
    with scheduled_case(
        tmp_path / "same_date",
        datetime(2026, 10, 27, 23, tzinfo=UTC),
        zone=ZoneInfo("America/Cambridge_Bay"),
    ) as case:
        assert len(case.scheduler.tick_schedules()) == 1
        case.clock.wall = datetime(2026, 10, 28, 1, tzinfo=UTC)
        case.restart()
        assert case.scheduler.tick_schedules() == ()


def test_spring_gap(tmp_path: Path) -> None:
    """契约：固定America/Cambridge_Bay的2026-03-08 02:30不存在，03:00当地首次达到时提交一次。"""
    from datetime import UTC, date, datetime, time
    from zoneinfo import ZoneInfo

    from jobs_schedules_support import scheduled_case

    from rdp.jobs.schedules import daily_deadline

    zone = ZoneInfo("America/Cambridge_Bay")
    assert daily_deadline(date(2026, 3, 8), time(2, 30), zone) == datetime(
        2026, 3, 8, 9, tzinfo=UTC
    )
    with scheduled_case(
        tmp_path, datetime(2026, 3, 8, 8, 59, 59, tzinfo=UTC), zone=zone, local_time=time(2, 30)
    ) as case:
        case.service.submit_scheduled(
            case.definition, date(2026, 3, 7), now=datetime(2026, 3, 7, 9, 30, tzinfo=UTC)
        )
        assert case.scheduler.tick_schedules() == ()
        case.clock.wall = datetime(2026, 3, 8, 9, tzinfo=UTC)
        assert len(case.scheduler.tick_schedules()) == 1
        case.restart()
        assert case.scheduler.tick_schedules() == ()


def test_fall_fold(tmp_path: Path) -> None:
    """契约：固定America/Cambridge_Bay的2026-11-01 01:30取第一次，第二次及中间重启不重复。"""
    from datetime import UTC, date, datetime, time
    from zoneinfo import ZoneInfo

    from jobs_schedules_support import scheduled_case

    from rdp.jobs.schedules import daily_deadline

    zone = ZoneInfo("America/Cambridge_Bay")
    assert daily_deadline(date(2026, 11, 1), time(1, 30), zone) == datetime(
        2026, 11, 1, 7, 30, tzinfo=UTC
    )
    with scheduled_case(
        tmp_path, datetime(2026, 11, 1, 7, 29, 59, tzinfo=UTC), zone=zone, local_time=time(1, 30)
    ) as case:
        case.service.submit_scheduled(
            case.definition, date(2026, 10, 31), now=datetime(2026, 10, 31, 7, 30, tzinfo=UTC)
        )
        assert case.scheduler.tick_schedules() == ()
        case.clock.wall = datetime(2026, 11, 1, 7, 30, tzinfo=UTC)
        assert len(case.scheduler.tick_schedules()) == 1
        case.clock.wall = datetime(2026, 11, 1, 8, 30, tzinfo=UTC)
        case.restart()
        assert case.scheduler.tick_schedules() == ()


def test_no_system_tz() -> None:
    """契约：注入不同ZoneInfo得到各自UTC截止，测试不改全局TZ、不依赖本机当前时区。"""
    import os
    from datetime import UTC, date, datetime, time
    from zoneinfo import ZoneInfo

    from rdp.jobs.schedules import daily_deadline

    original = os.environ.get("TZ")
    assert daily_deadline(date(2026, 10, 27), time(3), ZoneInfo("UTC")) == datetime(
        2026, 10, 27, 3, tzinfo=UTC
    )
    assert daily_deadline(
        date(2026, 10, 27), time(3), ZoneInfo("America/Cambridge_Bay")
    ) == datetime(2026, 10, 27, 9, tzinfo=UTC)
    assert daily_deadline(date(2026, 10, 27), time(3), ZoneInfo("Asia/Kathmandu")) == datetime(
        2026, 10, 26, 21, 15, tzinfo=UTC
    )
    assert os.environ.get("TZ") == original


def test_invalid_clock(tmp_path: Path) -> None:
    """契约：naive、非法返回值、UTC换算溢出属于DefectError，不提交作业或报输入错误。"""
    from datetime import UTC, date, datetime, time, timedelta, timezone
    from typing import cast
    from zoneinfo import ZoneInfo

    from jobs_schedules_support import scheduled_case
    from sqlalchemy import func, select

    from rdp.infra.db.connection import session_scope
    from rdp.infra.diagnostics import DefectError
    from rdp.jobs.models import JobRow
    from rdp.jobs.schedules import daily_deadline

    valid = datetime(2026, 10, 27, tzinfo=UTC)
    bad = (
        valid.replace(tzinfo=None),
        None,
        "2026-10-27",
        datetime.max.replace(tzinfo=timezone(-timedelta(hours=23))),
    )
    with scheduled_case(tmp_path, valid) as case:
        for value in bad:
            case.clock.wall = cast(datetime, value)
            with pytest.raises(DefectError):
                case.scheduler.tick_schedules()
        with session_scope(case.dependencies.engine, read_only=True) as session:
            assert session.scalar(select(func.count()).select_from(JobRow)) == 0
    with pytest.raises(DefectError):
        daily_deadline(date.max, time(23, 59), ZoneInfo("America/Los_Angeles"))


def test_localtime_file(tmp_path: Path) -> None:
    """契约：从临时tzfile读取完整夏令时规则，不读/etc/timezone或固定当前offset；坏文件ExternalError。"""
    from datetime import UTC, datetime
    from zoneinfo import TZPATH

    from rdp.infra.diagnostics import DefectError, ExternalError
    from rdp.jobs.schedules import local_timezone

    source = next(
        Path(root) / "America/Cambridge_Bay"
        for root in TZPATH
        if (Path(root) / "America/Cambridge_Bay").is_file()
    )
    copied = tmp_path / "localtime"
    copied.write_bytes(source.read_bytes())
    zone = local_timezone(copied)
    winter = datetime(2026, 1, 1, 12, tzinfo=UTC).astimezone(zone)
    summer = datetime(2026, 7, 1, 12, tzinfo=UTC).astimezone(zone)
    assert winter.hour == 5 and summer.hour == 6
    copied.write_bytes(b"broken tzfile")
    with pytest.raises(ExternalError) as caught:
        local_timezone(copied)
    assert str(copied) in str(caught.value.diagnostics[0].objects)
    assert caught.value.diagnostics[0].next_step
    copied.unlink()
    with pytest.raises(ExternalError):
        local_timezone(copied)
    with pytest.raises(DefectError):
        local_timezone(Path("relative"))


def test_registry_validation() -> None:
    """契约：登记拒绝重复名字、超100条、未知类型、秘密/坏参数、带tzinfo或非整分钟时刻。"""
    from dataclasses import replace
    from datetime import UTC, time

    from rdp.infra.diagnostics import DefectError
    from rdp.jobs.registry import JobRegistry
    from rdp.jobs.types import RecoveryMode

    valid = ScheduledJob("清除", "purge_errors", {}, description="删除超过保留期的程序报错记录")
    cases = (
        (valid, valid),
        tuple(replace(valid, name=str(index)) for index in range(101)),
        (replace(valid, name=" "),),
        (replace(valid, name="x" * 65),),
        (replace(valid, type_name="missing"),),
        (replace(valid, parameters={"password": "不可进入登记"}),),
        (replace(valid, local_time=time(3, 0, tzinfo=UTC)),),
        (replace(valid, local_time=time(3, 0, 1)),),
        (replace(valid, local_time=time(3, 0, 0, 1)),),
    )
    for definitions in cases:
        with pytest.raises(DefectError):
            ScheduleRegistry(definitions, production_registry())
    wrong = JobRegistry()
    definition = production_registry().lookup("purge_errors")
    assert definition is not None
    wrong.register(replace(definition, recovery_mode=RecoveryMode.INTERRUPT))
    with pytest.raises(DefectError):
        ScheduleRegistry((valid,), wrong)


def test_registry_copy() -> None:
    """契约：登记参数深复制、返回副本不改内部数据，按稳定名字排序，空表合法。"""
    parameters: dict[str, object] = {"steps": 3, "interval_ms": 0, "failed_steps": [2]}
    registry = ScheduleRegistry(
        (
            ScheduledJob("b", "example_count", parameters, description="按参数执行数数"),
            ScheduledJob("a", "purge_errors", {}, description="删除超过保留期的程序报错记录"),
        ),
        production_registry(),
    )
    parameters["failed_steps"] = [1]
    values = registry.definitions()
    assert [item.name for item in values] == ["a", "b"]
    assert values[1].parameters["failed_steps"] == [2]
    values[1].parameters["failed_steps"] = [3]
    assert registry.definitions()[1].parameters["failed_steps"] == [2]
    assert ScheduleRegistry((), production_registry()).definitions() == ()


def test_atomic_submit(tmp_path: Path) -> None:
    """验收6：作业、系统提交审计、定时唯一行同事务；三处任一失败全部回滚，不能留未审计作业。"""
    from jobs_storage_support import NOW, job_database
    from sqlalchemy import event, func, select

    from rdp.audit.models import OperationLogRow
    from rdp.infra.db.connection import session_scope
    from rdp.infra.diagnostics import ExternalError
    from rdp.jobs.models import JobRow
    from rdp.jobs.scheduling_models import ScheduleSubmissionRow
    from rdp.jobs.service import JobService

    for table in ("jobs", "operation_logs", "schedule_submissions"):
        with job_database(tmp_path / table) as (engine, _paths):
            service = JobService(engine, production_registry())
            failed: list[str] = []

            def fail(*args: object, target: str = table, seen: list[str] = failed) -> None:
                if (
                    not seen
                    and isinstance(args[2], str)
                    and args[2].startswith("INSERT INTO " + target + " ")
                ):
                    seen.append(target)
                    raise OSError("模拟原子提交失败")

            event.listen(engine, "before_cursor_execute", fail)
            try:
                with pytest.raises(ExternalError):
                    service.submit_scheduled(
                        ScheduledJob(
                            "清除", "purge_errors", {}, description="删除超过保留期的程序报错记录"
                        ),
                        NOW.date(),
                        now=NOW,
                    )
            finally:
                event.remove(engine, "before_cursor_execute", fail)
            assert failed == [table]
            with session_scope(engine, read_only=True) as session:
                assert session.scalar(select(func.count()).select_from(JobRow)) == 0
                assert session.scalar(select(func.count()).select_from(ScheduleSubmissionRow)) == 0
                rows = session.scalars(select(OperationLogRow)).all()
                assert (
                    len(rows) == 1 and rows[0].result == "failure" and rows[0].actor_name == "系统"
                )


def test_unique_race(tmp_path: Path) -> None:
    """契约：两个独立连接提交同一规则/日期，唯一约束保证只一条作业，败方不留日志或编号引用。"""
    from threading import Barrier, Thread

    from jobs_storage_support import NOW, job_database
    from sqlalchemy import func, select

    from rdp.audit.models import OperationLogRow
    from rdp.infra.db.connection import create_database_engine, session_scope
    from rdp.jobs.models import JobRow
    from rdp.jobs.scheduling_models import ScheduleSubmissionRow
    from rdp.jobs.scheduling_types import ScheduleSubmission
    from rdp.jobs.service import JobService

    with job_database(tmp_path) as (engine, paths):
        other = create_database_engine(paths.database)
        services = (
            JobService(engine, production_registry()),
            JobService(other, production_registry()),
        )
        barrier = Barrier(2)
        results: list[ScheduleSubmission | None] = []
        errors: list[BaseException] = []

        def run(service: JobService) -> None:
            try:
                barrier.wait(timeout=1)
                results.append(
                    service.submit_scheduled(
                        ScheduledJob(
                            "清除", "purge_errors", {}, description="删除超过保留期的程序报错记录"
                        ),
                        NOW.date(),
                        now=NOW,
                    )
                )
            except BaseException as error:
                errors.append(error)

        threads = [Thread(target=run, args=(service,), daemon=True) for service in services]
        try:
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=2)
                assert not thread.is_alive()
            assert errors == [] and len(results) == 2 and sum(item is None for item in results) == 1
            with session_scope(engine, read_only=True) as session:
                for table in (JobRow, OperationLogRow, ScheduleSubmissionRow):
                    assert session.scalar(select(func.count()).select_from(table)) == 1
        finally:
            try:
                barrier.abort()
                for thread in threads:
                    if thread.ident is not None:
                        thread.join(timeout=2)
                        assert not thread.is_alive()
            finally:
                other.dispose()


def test_startup_busy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """契约：启动补跑BEGIN短锁忙不清启动待检查标记，下轮补交，不延长心跳一整个普通锁预算。"""
    monkeypatch.setattr(policy, "PROGRESS_LOCK_TIMEOUT_MS", 10)
    now = datetime(2026, 10, 27, 1, tzinfo=UTC)
    with scheduled_case(tmp_path / "entry", now) as case:
        with session_scope(case.dependencies.engine):
            start = time.monotonic()
            assert case.scheduler.tick_schedules() == ()
            assert time.monotonic() - start < 0.5
        assert len(case.scheduler.tick_schedules()) == 1
    with scheduled_case(tmp_path / "inside", now) as case:
        failed: list[str] = []

        def fail(*args: object) -> None:
            if not failed and isinstance(args[2], str) and args[2].startswith("INSERT INTO jobs "):
                failed.append("inside")
                error = sqlite3.OperationalError("模拟事务内锁竞争")
                error.sqlite_errorcode = sqlite3.SQLITE_BUSY
                raise error

        event.listen(case.dependencies.engine, "before_cursor_execute", fail)
        try:
            with pytest.raises(ConflictError):
                case.scheduler.tick_schedules()
            assert failed == ["inside"]
        finally:
            event.remove(case.dependencies.engine, "before_cursor_execute", fail)


def test_schedule_commit_conflict(tmp_path: Path) -> None:
    """定时提交的COMMIT发生BUSY必须传播，不能冒充BEGIN忙并静默重试。"""
    now = datetime(2026, 10, 27, 1, tzinfo=UTC)
    with scheduled_case(tmp_path / "commit", now) as case:
        from sqlalchemy import Connection

        committed: list[bool] = []

        def fail_commit(connection: Connection) -> None:
            if (
                not committed
                and connection.exec_driver_sql("SELECT COUNT(*) FROM jobs").scalar_one() > 0
            ):
                committed.append(True)
                error = sqlite3.OperationalError("模拟提交时锁竞争")
                error.sqlite_errorcode = sqlite3.SQLITE_BUSY
                raise error

        event.listen(case.dependencies.engine, "commit", fail_commit)
        try:
            with pytest.raises(ConflictError):
                case.scheduler.tick_schedules()
            assert committed == [True]
        finally:
            event.remove(case.dependencies.engine, "commit", fail_commit)


def test_ordinary_day_after_catchup(tmp_path: Path) -> None:
    """K2：今天补跑一次后，明天03:00正常按点；不随补跑时刻把每天计划滑动。"""
    from datetime import UTC, datetime

    from jobs_schedules_support import scheduled_case

    with scheduled_case(tmp_path, datetime(2026, 10, 27, 12, tzinfo=UTC)) as case:
        assert len(case.scheduler.tick_schedules()) == 1
        case.clock.wall = datetime(2026, 10, 28, 2, 59, 59, tzinfo=UTC)
        assert case.scheduler.tick_schedules() == ()
        case.clock.wall = datetime(2026, 10, 28, 3, tzinfo=UTC)
        assert len(case.scheduler.tick_schedules()) == 1
        assert case.scheduler.tick_schedules() == ()


def test_latest_by_id(tmp_path: Path) -> None:
    """契约：提交墙钟回拨后仍按job_id选最近提交；历史记录不被覆盖。"""
    from datetime import timedelta

    from jobs_storage_support import NOW, job_database

    from rdp.infra.db.connection import session_scope
    from rdp.jobs.schedule_records import latest_submission
    from rdp.jobs.service import JobService

    definition = ScheduledJob(
        "清除", "purge_errors", {}, description="删除超过保留期的程序报错记录"
    )
    with job_database(tmp_path) as (engine, _paths):
        service = JobService(engine, production_registry())
        with session_scope(engine, read_only=True) as session:
            assert latest_submission(session, "清除") is None
        first = service.submit_scheduled(definition, NOW.date(), now=NOW)
        earlier = NOW - timedelta(days=1)
        second = service.submit_scheduled(definition, earlier.date(), now=earlier)
        assert first is not None and second is not None and second.job_id > first.job_id
        with session_scope(engine, read_only=True) as session:
            assert latest_submission(session, "清除") == second
        assert service.submit_scheduled(definition, NOW.date(), now=NOW) is None


def test_next_deadline() -> None:
    """契约：今天未提交且已到点返回今天到期时间，今天已提交则下一可用日；有界日期集覆盖回拨历史。"""
    from datetime import UTC, date, datetime
    from zoneinfo import ZoneInfo

    from rdp.jobs.schedules import next_run_at

    definition = ScheduledJob(
        "清除", "purge_errors", {}, description="删除超过保留期的程序报错记录"
    )
    now = datetime(2026, 10, 27, 12, tzinfo=UTC)
    assert next_run_at(definition, frozenset(), now=now, zone=ZoneInfo("UTC")) == datetime(
        2026, 10, 27, 3, tzinfo=UTC
    )
    assert next_run_at(
        definition, frozenset({date(2026, 10, 27)}), now=now, zone=ZoneInfo("UTC")
    ) == datetime(2026, 10, 28, 3, tzinfo=UTC)
    assert next_run_at(
        definition,
        frozenset({date(2026, 10, 27), date(2026, 10, 28)}),
        now=now,
        zone=ZoneInfo("UTC"),
    ) == datetime(2026, 10, 29, 3, tzinfo=UTC)


def test_date_window(tmp_path: Path) -> None:
    """契约：日期窗口含起点不含终点，越界/超过370天拒绝，未提交返回空集合。"""
    from datetime import UTC, date, datetime, time, timedelta
    from typing import cast

    from jobs_storage_support import job_database

    from rdp.infra.db.connection import session_scope
    from rdp.infra.diagnostics import DefectError
    from rdp.jobs.schedule_records import submission_dates
    from rdp.jobs.service import JobService

    today = date(2026, 10, 27)
    definition = ScheduledJob(
        "清除", "purge_errors", {}, description="删除超过保留期的程序报错记录"
    )
    with job_database(tmp_path) as (engine, _paths):
        service = JobService(engine, production_registry())
        with session_scope(engine, read_only=True) as session:
            assert (
                submission_dates(session, "清除", today, today + timedelta(days=2)) == frozenset()
            )
        for offset in (-1, 0, 1, 2):
            day = today + timedelta(days=offset)
            service.submit_scheduled(definition, day, now=datetime.combine(day, time(3), UTC))
        with session_scope(engine, read_only=True) as session:
            assert submission_dates(session, "清除", today, today + timedelta(days=2)) == frozenset(
                {today, today + timedelta(days=1)}
            )
            for start, end in (
                (today, today),
                (today, today - timedelta(days=1)),
                (today, today + timedelta(days=371)),
                (cast(date, datetime(2026, 10, 27, tzinfo=UTC)), today + timedelta(days=1)),
            ):
                with pytest.raises(DefectError):
                    submission_dates(session, "清除", start, end)
        with session_scope(engine) as session, pytest.raises(DefectError):
            submission_dates(session, "清除", today, today + timedelta(days=1))


def test_skipped_date() -> None:
    """契约：本地日余下时间全部不存在时daily_deadline为None，下次计划有界搜索，不无限循环。"""
    from datetime import UTC, date, datetime, time, timedelta
    from zoneinfo import ZoneInfo

    from rdp.infra.diagnostics import DefectError
    from rdp.jobs.schedules import daily_deadline, next_run_at

    zone = ZoneInfo("Pacific/Apia")
    assert daily_deadline(date(2011, 12, 30), time(3), zone) is None
    definition = ScheduledJob(
        "清除", "purge_errors", {}, description="删除超过保留期的程序报错记录"
    )
    assert next_run_at(
        definition,
        frozenset({date(2011, 12, 29)}),
        now=datetime(2011, 12, 29, 13, tzinfo=UTC),
        zone=zone,
    ) == datetime(2011, 12, 30, 13, tzinfo=UTC)
    today = date(2026, 10, 27)
    full = frozenset(today + timedelta(days=index) for index in range(370))
    with pytest.raises(DefectError):
        next_run_at(definition, full, now=datetime(2026, 10, 27, tzinfo=UTC), zone=ZoneInfo("UTC"))
    with pytest.raises(DefectError):
        next_run_at(
            definition,
            frozenset({date.max}),
            now=datetime.max.replace(tzinfo=UTC),
            zone=ZoneInfo("UTC"),
        )


def test_resubmit_system(tmp_path: Path) -> None:
    """契约：账号重新提交系统的终态作业，新提交人为当前账号、来源编号正确，不复制系统身份。"""
    from accounts_support import AUDIT_CONTEXT, NOW, member_grant, scenario

    from rdp.infra.actors import SYSTEM_ACTOR
    from rdp.jobs.service import JobRequest, JobService

    with scenario(tmp_path) as (accounts, administrator):
        grant = member_grant(accounts, administrator)
        service = JobService(accounts.engine, production_registry())
        submission = service.submit_scheduled(
            ScheduledJob(
                "系统数数",
                "example_count",
                {"steps": 1, "interval_ms": 0},
                description="按参数执行数数",
            ),
            NOW.date(),
            now=NOW,
        )
        assert submission is not None
        request = JobRequest(grant.identity, NOW, AUDIT_CONTEXT)
        assert service.get(request, submission.job_id).submitted_by == SYSTEM_ACTOR
        service.cancel(request, submission.job_id)
        child = service.resubmit(request, submission.job_id)
        assert child.resubmitted_from == submission.job_id
        assert child.submitted_by.account_id == grant.identity.account.account_id
        assert child.submitted_by != SYSTEM_ACTOR
