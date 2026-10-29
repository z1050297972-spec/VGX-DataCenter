"""09 调度迁移的真实SQLite契约测试；所有数据库和备份均使用临时目录。"""

from datetime import UTC, date, datetime, timedelta, timezone
from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from scheduling_migration_support import JOB_SQL, OPERATION_SQL, schema_objects, version_four
from sqlalchemy import Engine, event, inspect, text
from sqlalchemy.exc import IntegrityError

from rdp.accounts.models import AccountRow
from rdp.audit.models import OperationLogRow
from rdp.infra.db.connection import create_database_engine, session_scope
from rdp.infra.db.migration import migrate, migration_config
from rdp.infra.db.models import metadata
from rdp.infra.diagnostics import ConflictError, DefectError
from rdp.jobs.models import JobRow
from rdp.jobs.scheduling_models import ScheduleSubmissionRow, WorkerGpuCheckRow


def test_isolated() -> None:
    """历史契约：0005承接0004且只有一份活动脚本，资源列共享MetaData。"""
    config = migration_config()
    revision = ScriptDirectory.from_config(config).get_revision("0005_job_scheduling")
    assert revision is not None and revision.down_revision == "0004_jobs_worker"
    location = config.get_main_option("script_location")
    assert location is not None
    assert not (Path(location) / "pending" / "v0005_job_scheduling.py").exists()
    assert JobRow.__table__.c.submitter_id.nullable
    assert {"gpu_index", "wait_reason", "holds_navigation_lock"} <= set(JobRow.__table__.c.keys())
    for model in (ScheduleSubmissionRow, WorkerGpuCheckRow):
        assert model.__table__ is metadata.tables[model.__tablename__]
        assert "__abstract__" not in model.__dict__


def test_upgrade_preserves(tmp_path: Path) -> None:
    """契约：0004升级当前版本保留0005引入的作业/操作日志全部旧记录与索引，默认资源列为空/False。"""
    assert AccountRow.metadata is OperationLogRow.metadata is metadata
    with version_four(tmp_path / "state") as (engine, paths):
        with engine.connect() as connection:
            jobs_before = connection.execute(text("SELECT * FROM jobs")).mappings().all()
            audit_before = connection.execute(text("SELECT * FROM operation_logs")).mappings().all()
            indexes = {
                name: inspect(connection).get_indexes(name) for name in ("jobs", "operation_logs")
            }
        result = migrate(paths, now=datetime(2026, 10, 27, tzinfo=UTC))
        assert (
            result.previous_revision == "0004_jobs_worker"
            and result.current_revision
            == ScriptDirectory.from_config(migration_config()).get_current_head()
        )
        assert result.backup is not None and result.backup.is_file()
        with engine.connect() as connection:
            after = connection.execute(text("SELECT * FROM jobs")).mappings().all()
            assert [{key: row[key] for key in jobs_before[0]} for row in after] == jobs_before
            assert [
                (row["gpu_index"], row["wait_reason"], row["holds_navigation_lock"])
                for row in after
            ] == [(None, None, 0)]
            assert (
                connection.execute(text("SELECT * FROM operation_logs")).mappings().all()
                == audit_before
            )
            assert {name: inspect(connection).get_indexes(name) for name in indexes} == indexes
            assert (
                compare_metadata(
                    MigrationContext.configure(connection, opts={"compare_type": True}), metadata
                )
                == []
            )
        model_engine = create_database_engine(tmp_path / "models.sqlite3")
        try:
            metadata.create_all(model_engine)
            with engine.connect() as actual, model_engine.connect() as expected:
                for name in ("jobs", "operation_logs", "schedule_submissions", "worker_gpu_checks"):
                    query = text("SELECT sql FROM sqlite_master WHERE type='table' AND name=:name")
                    assert " ".join(
                        actual.execute(query, {"name": name}).scalar_one().split()
                    ) == " ".join(expected.execute(query, {"name": name}).scalar_one().split())
        finally:
            model_engine.dispose()


def test_sequence_preserved(tmp_path: Path) -> None:
    """契约：迁移保留两表AUTOINCREMENT高水位，包括删除最高编号及空表，后续插入不复用。"""
    for empty in (False, True):
        with version_four(tmp_path / str(empty)) as (engine, paths):
            with engine.begin() as connection:
                connection.execute(text(JOB_SQL), {"id": 9999})
                connection.execute(text(OPERATION_SQL), {"id": 8888})
                connection.execute(
                    text("DELETE FROM jobs" if empty else "DELETE FROM jobs WHERE job_id=9999")
                )
                connection.execute(
                    text(
                        "DELETE FROM operation_logs"
                        if empty
                        else "DELETE FROM operation_logs WHERE log_id=8888"
                    )
                )
            migrate(paths, now=datetime(2026, 10, 27, tzinfo=UTC))
            with engine.begin() as connection:
                assert connection.execute(text(JOB_SQL), {"id": None}).lastrowid == 10000
                assert connection.execute(text(OPERATION_SQL), {"id": None}).lastrowid == 8889


def test_system_identity(tmp_path: Path) -> None:
    """契约：jobs空编号只允许名字系统，None运维/任意名及非正编号拒绝；正编号且名字系统的账号合法。"""
    with version_four(tmp_path) as (engine, paths):
        migrate(paths, now=datetime(2026, 10, 27, tzinfo=UTC))
        for identifier, name in ((None, "系统"), (7, "系统"), (8, "正常账号")):
            with engine.begin() as connection:
                connection.execute(
                    text("UPDATE jobs SET submitter_id=:id,submitter_name=:name"),
                    {"id": identifier, "name": name},
                )
                assert tuple(
                    connection.execute(text("SELECT submitter_id,submitter_name FROM jobs")).one()
                ) == (identifier, name)
        for identifier, name in ((None, "运维"), (None, "任意名字"), (0, "系统"), (-1, "账号")):
            with pytest.raises(IntegrityError), engine.begin() as connection:
                connection.execute(
                    text("UPDATE jobs SET submitter_id=:id,submitter_name=:name"),
                    {"id": identifier, "name": name},
                )


def test_reserved_name_history(tmp_path: Path) -> None:
    """契约：旧账号作业名字为系统时正常升级，原编号/名字保持不变，不因单向身份约束拒绝历史。"""
    with version_four(tmp_path) as (engine, paths):
        with engine.begin() as connection:
            connection.execute(text("UPDATE jobs SET submitter_name='系统'"))
        migrate(paths, now=datetime(2026, 10, 27, tzinfo=UTC))
        with engine.connect() as connection:
            assert tuple(
                connection.execute(
                    text("SELECT job_id,submitter_id,submitter_name FROM jobs")
                ).one()
            ) == (71, 7, "系统")


def test_audit_system(tmp_path: Path) -> None:
    """契约：操作日志空actor_id只允许运维/系统，其他固定身份拒绝；原账号日志规则不变。"""
    with version_four(tmp_path) as (engine, paths):
        migrate(paths, now=datetime(2026, 10, 27, tzinfo=UTC))
        for identifier, name in ((None, "系统"), (None, "运维"), (7, "系统"), (8, "其他账号")):
            with engine.begin() as connection:
                connection.execute(
                    text("UPDATE operation_logs SET actor_id=:id,actor_name=:name"),
                    {"id": identifier, "name": name},
                )
                assert tuple(
                    connection.execute(text("SELECT actor_id,actor_name FROM operation_logs")).one()
                ) == (identifier, name)
        with pytest.raises(IntegrityError), engine.begin() as connection:
            connection.execute(
                text("UPDATE operation_logs SET actor_id=NULL,actor_name='冒充身份'")
            )


def test_resource_checks(tmp_path: Path) -> None:
    """契约：负GPU、非法等待原因、终态持锁/等待、持锁且等待和不合法状态组合被CHECK拒绝。"""
    cases = (
        ("UPDATE jobs SET gpu_index=-1", "ck_jobs_gpu_index"),
        ("UPDATE jobs SET wait_reason='other'", "ck_jobs_wait_reason"),
        ("UPDATE jobs SET holds_navigation_lock=2", "ck_jobs_navigation_boolean"),
        ("UPDATE jobs SET holds_navigation_lock=1", "ck_jobs_navigation_holder_state"),
        ("UPDATE jobs SET wait_reason='navigation_lock'", "ck_jobs_navigation_wait_state"),
        ("UPDATE jobs SET wait_reason='gpu',gpu_index=0", "ck_jobs_gpu_wait_state"),
        (
            "UPDATE jobs SET state='cancelled',ended_at=submitted_at,summary='{}',wait_reason='gpu'",
            "ck_jobs_terminal_resources",
        ),
        (
            "UPDATE jobs SET state='running',log_path='logs/示例/1.log',holds_navigation_lock=1,wait_reason='navigation_lock'",
            "ck_jobs_navigation_holder_state",
        ),
    )
    with version_four(tmp_path) as (engine, paths):
        migrate(paths, now=datetime(2026, 10, 27, tzinfo=UTC))
        for statement, constraint in cases:
            with pytest.raises(IntegrityError) as caught, engine.begin() as connection:
                connection.execute(text(statement))
            assert constraint in str(caught.value.orig)
        with engine.begin() as connection:
            connection.execute(text("UPDATE jobs SET wait_reason='gpu'"))
            connection.execute(
                text(
                    "UPDATE jobs SET state='running',log_path='logs/示例/1.log',wait_reason='navigation_lock'"
                )
            )
            connection.execute(text("UPDATE jobs SET wait_reason=NULL,holds_navigation_lock=1"))
            assert (
                connection.execute(text("SELECT holds_navigation_lock FROM jobs")).scalar_one() == 1
            )


def test_daily_uniqueness(tmp_path: Path) -> None:
    """契约：真实数据库对name/date复合键和job_id唯一性拒绝重复，不只在Python查重。"""
    statement = text(
        "INSERT INTO schedule_submissions(schedule_name,local_date,job_id,submitted_at) VALUES (:name,:day,:id,'2026-10-27T03:00:00.000000Z')"
    )
    with version_four(tmp_path) as (engine, paths):
        migrate(paths, now=datetime(2026, 10, 27, tzinfo=UTC))
        with engine.begin() as connection:
            connection.execute(statement, {"name": "清除", "day": "2026-10-27", "id": 71})
        for name, day, identifier in (("清除", "2026-10-27", 72), ("其他", "2026-10-28", 71)):
            with pytest.raises(IntegrityError), engine.begin() as connection:
                connection.execute(statement, {"name": name, "day": day, "id": identifier})
        with engine.begin() as connection:
            connection.execute(statement, {"name": "清除", "day": "2026-10-28", "id": 72})
            assert (
                connection.execute(text("SELECT count(*) FROM schedule_submissions")).scalar_one()
                == 2
            )


def test_upgrade_atomic(tmp_path: Path) -> None:
    """契约：重建中途失败全部回滚，旧表/序列/索引完整，不留下混合版本。"""

    def fail(*args: object) -> None:
        statement = args[2]
        if isinstance(statement, str) and "CREATE TABLE worker_gpu_checks" in statement:
            raise RuntimeError("模拟DDL中断")

    with version_four(tmp_path) as (engine, paths):
        with engine.connect() as connection:
            before = schema_objects(connection)
            sequences = connection.execute(
                text("SELECT name,seq FROM sqlite_sequence ORDER BY name")
            ).all()
        event.listen(Engine, "before_cursor_execute", fail)
        try:
            with pytest.raises(DefectError):
                migrate(paths, now=datetime(2026, 10, 27, tzinfo=UTC))
        finally:
            event.remove(Engine, "before_cursor_execute", fail)
        with engine.connect() as connection:
            assert schema_objects(connection) == before
            assert (
                connection.execute(text("SELECT name,seq FROM sqlite_sequence ORDER BY name")).all()
                == sequences
            )
            assert (
                connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
                == "0004_jobs_worker"
            )
            assert (
                connection.execute(text("SELECT submitter_name FROM jobs")).scalar_one()
                == "历史提交人"
            )
            assert connection.execute(text("SELECT log_id FROM operation_logs")).scalar_one() == 51


def test_downgrade_guard(tmp_path: Path) -> None:
    """契约：存在系统身份、定时提交或非默认资源历史时拒绝降级且不删数据；空新字段可安全回0004。"""
    cases = (
        "UPDATE jobs SET submitter_id=NULL,submitter_name='系统'",
        "UPDATE operation_logs SET actor_id=NULL,actor_name='系统'",
        "UPDATE jobs SET gpu_index=1",
        "UPDATE jobs SET wait_reason='gpu'",
        "UPDATE jobs SET state='running',log_path='logs/示例/1.log',holds_navigation_lock=1",
        "INSERT INTO schedule_submissions VALUES ('清除','2026-10-27',71,'2026-10-27T03:00:00.000000Z')",
        "INSERT INTO worker_gpu_checks VALUES (0,'00000000000040008000000000000001',1,'[]','2026-10-27T03:00:00.000000Z')",
    )
    for index, statement in enumerate(cases):
        with version_four(tmp_path / str(index)) as (engine, _paths):
            with engine.begin() as connection:
                command.upgrade(migration_config(connection), "0005_job_scheduling")
            with engine.begin() as connection:
                connection.execute(text(statement))
                before = schema_objects(connection)
            with pytest.raises(ConflictError), engine.begin() as connection:
                command.downgrade(migration_config(connection), "0004_jobs_worker")
            with engine.connect() as connection:
                assert schema_objects(connection) == before
                assert (
                    connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
                    == "0005_job_scheduling"
                )
    with version_four(tmp_path / "safe") as (engine, _paths):
        with engine.connect() as connection:
            before = schema_objects(connection)
        with engine.begin() as connection:
            command.upgrade(migration_config(connection), "0005_job_scheduling")
        with engine.begin() as connection:
            connection.execute(text("UPDATE sqlite_sequence SET seq=9000 WHERE name='jobs'"))
            connection.execute(
                text("UPDATE sqlite_sequence SET seq=8000 WHERE name='operation_logs'")
            )
            command.downgrade(migration_config(connection), "0004_jobs_worker")
        with engine.begin() as connection:
            assert schema_objects(connection) == before
            assert connection.execute(text(JOB_SQL), {"id": None}).lastrowid == 9001
            assert connection.execute(text(OPERATION_SQL), {"id": None}).lastrowid == 8001


def test_gpu_check_table_isolated_and_roundtrips(tmp_path: Path) -> None:
    """激活契约：核卡和每日表注册共用MetaData，实例/可用性/诊断/UTC时刻与本地日期往返，升级不伪造核对结果。"""
    moment = datetime(2026, 10, 27, 9, 12, 13, 123456, tzinfo=timezone(timedelta(hours=8)))
    with version_four(tmp_path) as (engine, paths):
        migrate(paths, now=datetime(2026, 10, 27, tzinfo=UTC))
        with engine.connect() as connection:
            assert (
                connection.execute(text("SELECT count(*) FROM worker_gpu_checks")).scalar_one() == 0
            )
        with session_scope(engine) as session:
            session.add(
                WorkerGpuCheckRow(
                    gpu_index=2,
                    instance_id="00000000000040008000000000000001",
                    available=True,
                    diagnostics=[],
                    checked_at=moment,
                )
            )
            session.add(
                ScheduleSubmissionRow(
                    schedule_name="清除",
                    local_date=date(2026, 10, 27),
                    job_id=71,
                    submitted_at=moment,
                )
            )
        with session_scope(engine, read_only=True) as session:
            gpu = session.get(WorkerGpuCheckRow, 2)
            submission = session.get(ScheduleSubmissionRow, ("清除", date(2026, 10, 27)))
            assert gpu is not None and submission is not None
            assert gpu.instance_id == "00000000000040008000000000000001"
            assert gpu.available is True and gpu.diagnostics == []
            assert gpu.checked_at == datetime(2026, 10, 27, 1, 12, 13, 123456, tzinfo=UTC)
            assert gpu.checked_at.tzinfo is UTC
            assert submission.local_date == date(2026, 10, 27)
            assert submission.submitted_at == gpu.checked_at
