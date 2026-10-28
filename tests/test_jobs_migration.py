"""M0/08 公共契约测试；数据库与文件只使用临时目录，不依赖真实数据或默认状态目录。"""

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from db_support import sqlite_connection
from jobs_storage_support import job_row
from sqlalchemy import Engine, event, inspect
from sqlalchemy.exc import SQLAlchemyError

from rdp.accounts.models import AccountRow
from rdp.api.job_schemas import JobResponse
from rdp.audit.models import OperationLogRow
from rdp.infra.config import PlatformConfig
from rdp.infra.db.connection import create_database_engine, session_scope
from rdp.infra.db.migration import migrate, migration_config
from rdp.infra.db.migrations.versions import v0004_jobs_worker
from rdp.infra.db.models import metadata
from rdp.infra.diagnostics import DefectError, InputError
from rdp.infra.state import StatePaths, initialize_state, state_paths
from rdp.jobs.models import JobRow, WorkerHeartbeatRow
from rdp.jobs.records import find_job
from rdp.jobs.service import JobService
from rdp.jobs.types import JobState


def test_active_declarations() -> None:
    """迁移激活：作业/心跳共用 MetaData，0006 为唯一 head，版本链保留全部历史版本。"""
    for row in (JobRow, WorkerHeartbeatRow):
        assert "__abstract__" not in row.__dict__
        assert row.metadata is metadata
        assert row.__table__ is metadata.tables[row.__tablename__]
    config = migration_config()
    assert ScriptDirectory.from_config(config).get_current_head() == "0006_platform_version"
    directory = config.get_main_option("script_location")
    assert directory is not None
    assert {item.revision for item in ScriptDirectory.from_config(config).walk_revisions()} == {
        "0001_error_reports",
        "0002_accounts_sessions",
        "0003_audit_login_logs",
        "0004_jobs_worker",
        "0005_job_scheduling",
        "0006_platform_version",
    }


def test_schema_v4(tmp_path: Path) -> None:
    """0004引入的作业/心跳字段在当前版本仍与独立metadata建库一致，覆盖审计CHECK、索引、UTC和无账号外键。"""
    assert AccountRow.metadata is OperationLogRow.metadata is metadata
    paths = state_paths(PlatformConfig(state_dir=tmp_path / "state"), ())
    initialize_state(paths)
    result = migrate(paths, now=datetime(2026, 10, 26, tzinfo=UTC))
    assert result.current_revision == "0006_platform_version"
    engine = create_database_engine(paths.database)
    try:
        with engine.connect() as connection:
            assert (
                compare_metadata(
                    MigrationContext.configure(connection, opts={"compare_type": True}), metadata
                )
                == []
            )
            inspector = inspect(connection)
            assert inspector.get_foreign_keys("jobs") == []
            assert inspector.get_foreign_keys("operation_logs") == []
            assert {tuple(index["column_names"]) for index in inspector.get_indexes("jobs")} == {
                ("state", "job_id")
            }
    finally:
        engine.dispose()
    model_path = tmp_path / "models.sqlite3"
    model_engine = create_database_engine(model_path)
    try:
        metadata.create_all(model_engine)
    finally:
        model_engine.dispose()
    with sqlite_connection(paths.database) as actual, sqlite_connection(model_path) as expected:
        for table in ("jobs", "worker_heartbeat", "operation_logs"):
            statement = "SELECT sql FROM sqlite_master WHERE type='table' AND name=?"
            actual_sql = actual.execute(statement, (table,)).fetchone()[0]
            expected_sql = expected.execute(statement, (table,)).fetchone()[0]
            assert " ".join(actual_sql.split()) == " ".join(expected_sql.split())
        job_sql = actual.execute("SELECT sql FROM sqlite_master WHERE name='jobs'").fetchone()[0]
        assert "PRIMARY KEY AUTOINCREMENT" in job_sql
        assert "started_at TEXT" in job_sql and "progress_at TEXT" in job_sql
        audit_sql = actual.execute(
            "SELECT sql FROM sqlite_master WHERE name='operation_logs'"
        ).fetchone()[0]
        assert "'account','audit_settings','job'" in audit_sql


def test_audit_check_extension(tmp_path: Path) -> None:
    """批准扩展：operation_logs只增加job对象，旧account/audit_settings行、列、CHECK和两个索引保留。"""
    paths = _version_three(tmp_path)
    with sqlite_connection(paths.database) as connection:
        connection.executemany(_INSERT_OPERATION, [{"identifier": 1}, {"identifier": 2}])
        connection.execute(
            "UPDATE operation_logs SET object_kind='audit_settings',object_id='retention',object_name='日志保留期',operation='set_retention' WHERE log_id=2"
        )
        before = connection.execute("SELECT * FROM operation_logs ORDER BY log_id").fetchall()
        columns = connection.execute("PRAGMA table_info(operation_logs)").fetchall()
        old_sql = connection.execute(
            "SELECT sql FROM sqlite_master WHERE name='operation_logs'"
        ).fetchone()[0]
        indexes = connection.execute(
            "SELECT name,sql FROM sqlite_master WHERE type='index' AND tbl_name='operation_logs' ORDER BY name"
        ).fetchall()
    engine = create_database_engine(paths.database)
    try:
        with engine.begin() as connection:
            command.upgrade(migration_config(connection), "0004_jobs_worker")
    finally:
        engine.dispose()
    with sqlite_connection(paths.database) as connection:
        assert (
            connection.execute("SELECT * FROM operation_logs ORDER BY log_id").fetchall() == before
        )
        assert connection.execute("PRAGMA table_info(operation_logs)").fetchall() == columns
        assert (
            connection.execute(
                "SELECT name,sql FROM sqlite_master WHERE type='index' AND tbl_name='operation_logs' ORDER BY name"
            ).fetchall()
            == indexes
        )
        new_sql = connection.execute(
            "SELECT sql FROM sqlite_master WHERE name='operation_logs'"
        ).fetchone()[0]
        expected_sql = old_sql.replace(
            "('account','audit_settings')", "('account','audit_settings','job')"
        )
        assert " ".join(new_sql.split()) == " ".join(expected_sql.split())
        connection.execute(_INSERT_OPERATION, {"identifier": 3})
        connection.execute(
            "UPDATE operation_logs SET object_kind='job',object_name='示例：数数 #11',operation='submit_job' WHERE log_id=3"
        )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("UPDATE operation_logs SET object_kind='unknown' WHERE log_id=3")


def test_audit_sequence_highwater(tmp_path: Path) -> None:
    """编号不复用：先发编号100再清掉最高若干条，重建后sqlite_sequence>=100，新日志编号>100而非MAX现存+1。"""
    paths = _version_three(tmp_path)
    with sqlite_connection(paths.database) as connection:
        connection.executemany(_INSERT_OPERATION, [{"identifier": 1}, {"identifier": 100}])
        connection.execute("DELETE FROM operation_logs WHERE log_id=100")
        assert connection.execute(
            "SELECT seq FROM sqlite_sequence WHERE name='operation_logs'"
        ).fetchone() == (100,)
    migrate(paths, now=datetime(2026, 10, 26, tzinfo=UTC))
    with sqlite_connection(paths.database) as connection:
        assert connection.execute(
            "SELECT seq FROM sqlite_sequence WHERE name='operation_logs'"
        ).fetchone() == (100,)
        assert connection.execute("SELECT log_id FROM operation_logs").fetchall() == [(1,)]
        connection.execute(_INSERT_OPERATION, {"identifier": None})
        assert connection.execute("SELECT MAX(log_id) FROM operation_logs").fetchone() == (101,)


def test_audit_sequence_empty(tmp_path: Path) -> None:
    """编号不复用：发过100后清空全部审计行，0004重建仍保留高水位100，下一条编号>100。"""
    paths = _version_three(tmp_path)
    with sqlite_connection(paths.database) as connection:
        connection.execute(_INSERT_OPERATION, {"identifier": 100})
        connection.execute("DELETE FROM operation_logs")
    migrate(paths, now=datetime(2026, 10, 26, tzinfo=UTC))
    with sqlite_connection(paths.database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM operation_logs").fetchone() == (0,)
        assert connection.execute(
            "SELECT seq FROM sqlite_sequence WHERE name='operation_logs'"
        ).fetchone() == (100,)
        connection.execute(_INSERT_OPERATION, {"identifier": None})
        assert connection.execute("SELECT log_id FROM operation_logs").fetchone() == (101,)


@pytest.mark.parametrize(
    "failed_sql",
    [
        "ALTER TABLE operation_logs",
        "INSERT INTO operation_logs",
        "UPDATE sqlite_sequence",
        "CREATE TABLE jobs",
        "CREATE TABLE worker_heartbeat",
        "CREATE INDEX ix_jobs_state_id",
    ],
)
def test_migration_rollback(failed_sql: str, tmp_path: Path) -> None:
    """原子升级：重建表/恢复sqlite_sequence/建索引/建新表任一步失败回滚到0003，旧行、序列、索引原样，备份保留。"""
    paths = _version_three(tmp_path)
    with sqlite_connection(paths.database) as connection:
        connection.execute(_INSERT_OPERATION, {"identifier": 100})
        before = tuple(connection.iterdump())
    attempted: list[str] = []

    def fail(_connection: object, _cursor: object, statement: str, *_rest: object) -> None:
        """只在明确的数据库执行边界注入一次故障，不替换迁移内部函数。"""
        if statement.lstrip().startswith(failed_sql):
            attempted.append(statement)
            raise SQLAlchemyError("测试DDL故障")

    event.listen(Engine, "before_cursor_execute", fail)
    try:
        with pytest.raises(DefectError):
            migrate(paths, now=datetime(2026, 10, 26, tzinfo=UTC))
    finally:
        event.remove(Engine, "before_cursor_execute", fail)
    assert len(attempted) == 1
    with sqlite_connection(paths.database) as connection:
        assert tuple(connection.iterdump()) == before
    backups = tuple((tmp_path / "backups").glob("*.sqlite3"))
    assert len(backups) == 1
    with sqlite_connection(backups[0]) as backup:
        assert tuple(backup.iterdump()) == before


@pytest.mark.parametrize("with_job", [False, True])
def test_downgrade_refused(with_job: bool, tmp_path: Path) -> None:
    """降级策略：有job记录或没有job记录都拒绝自动降级，任何DDL前InputError，提示人工恢复完整备份。"""
    paths = _version_three(tmp_path)
    migrate(paths, now=datetime(2026, 10, 26, tzinfo=UTC))
    with sqlite_connection(paths.database) as connection:
        if with_job:
            connection.execute(_INSERT_OPERATION, {"identifier": 1})
            connection.execute("UPDATE operation_logs SET object_kind='job',operation='submit_job'")
        before = tuple(connection.iterdump())
    with pytest.raises(InputError) as caught:
        v0004_jobs_worker.downgrade()
    assert caught.value.diagnostics
    with sqlite_connection(paths.database) as connection:
        assert tuple(connection.iterdump()) == before


def test_job_foreign_key_absent(tmp_path: Path) -> None:
    """永久记录：删除账号不影响jobs及审计快照，无账号外键；重提自编号保留，不存在删除作业入口。"""
    paths = _version_three(tmp_path)
    migrate(paths, now=datetime(2026, 10, 26, tzinfo=UTC))
    with sqlite_connection(paths.database) as connection:
        assert connection.execute("PRAGMA foreign_key_list(jobs)").fetchall() == []
    engine = create_database_engine(paths.database)
    try:
        from accounts_support import model_row

        from rdp.accounts.models import AccountRow

        with session_scope(engine) as session:
            session.add(model_row(account_id=7))
            session.add(job_row())
        with session_scope(engine) as session:
            account = session.get(AccountRow, 7)
            assert account is not None
            session.delete(account)
        with session_scope(engine, read_only=True) as session:
            record = find_job(session, 71)
            assert (record.submitted_by.account_id, record.submitted_by.name) == (7, "历史提交人")
        assert not hasattr(JobService, "delete")
    finally:
        engine.dispose()


def test_recovery_counter_schema(tmp_path: Path) -> None:
    """第9条：0004的recovery_count默认0且CHECK为0至3，JobRecord/API保留计数，重新提交新作业归零。"""
    paths = _version_three(tmp_path)
    migrate(paths, now=datetime(2026, 10, 26, tzinfo=UTC))
    engine = create_database_engine(paths.database)
    try:
        with session_scope(engine) as session:
            row = job_row(JobState.QUEUED)
            session.add(row)
        with session_scope(engine, read_only=True) as session:
            assert find_job(session, 71).recovery_count == 0
        with sqlite_connection(paths.database) as connection:
            for count in (-1, 4):
                with pytest.raises(sqlite3.IntegrityError):
                    connection.execute("UPDATE jobs SET recovery_count=?", (count,))
            connection.execute("UPDATE jobs SET recovery_count=3")
        with session_scope(engine, read_only=True) as session:
            assert find_job(session, 71).recovery_count == 3
        schema = JobResponse.model_json_schema()["properties"]["recovery_count"]
        assert schema["minimum"] == 0 and schema["maximum"] == 3
    finally:
        engine.dispose()


def test_claimed_log_path_constraint(tmp_path: Path) -> None:
    """第4条：0004的log_path唯一且running等已领取状态非空；queued允许空，领取事务预留与状态原子提交。"""
    paths = _version_three(tmp_path)
    migrate(paths, now=datetime(2026, 10, 26, tzinfo=UTC))
    engine = create_database_engine(paths.database)
    try:
        with session_scope(engine) as session:
            session.add_all([job_row(), job_row(JobState.QUEUED, job_id=72)])
        with sqlite_connection(paths.database) as connection:
            for sql in (
                "UPDATE jobs SET log_path=NULL WHERE job_id=71",
                "UPDATE jobs SET log_path=(SELECT log_path FROM jobs WHERE job_id=71) WHERE job_id=72",
            ):
                with pytest.raises(sqlite3.IntegrityError):
                    connection.execute(sql)
        with session_scope(engine, read_only=True) as session:
            assert find_job(session, 71).state is JobState.RUNNING
            assert find_job(session, 72).log_path is None
    finally:
        engine.dispose()


# 独立的历史行样本；显式给100模拟已分配高水位，后续插入None由SQLite自动分配。
_INSERT_OPERATION = """INSERT INTO operation_logs
    (log_id,occurred_at,actor_id,actor_name,operation,object_kind,object_id,object_name,result,details)
    VALUES (:identifier,'2026-10-26T00:00:00.000000Z',7,'历史操作人','create_account','account','11','历史对象','success','{"version":1,"before":{},"after":{"display_name":"历史对象"}}')"""


def _version_three(root: Path) -> StatePaths:
    """通过Alembic公共入口创建真实0003，不调用新迁移生成历史预期值。"""
    paths = state_paths(PlatformConfig(state_dir=root), ())
    initialize_state(paths)
    engine = create_database_engine(paths.database)
    try:
        with engine.begin() as connection:
            command.upgrade(migration_config(connection), "0003_audit_login_logs")
    finally:
        engine.dispose()
    return paths


@pytest.mark.parametrize("damage", ["text", "negative", "duplicate", "missing"])
def test_corrupt_audit_sequence_is_rejected(damage: str, tmp_path: Path) -> None:
    """序列损坏必须InputError并完整回滚，不能猜高水位后冒险复用已发编号。"""
    paths = _version_three(tmp_path)
    with sqlite_connection(paths.database) as connection:
        connection.execute(_INSERT_OPERATION, {"identifier": 100})
        if damage == "text":
            connection.execute(
                "UPDATE sqlite_sequence SET seq='invalid' WHERE name='operation_logs'"
            )
        elif damage == "negative":
            connection.execute("UPDATE sqlite_sequence SET seq=-1 WHERE name='operation_logs'")
        elif damage == "duplicate":
            connection.execute(
                "INSERT INTO sqlite_sequence(name,seq) VALUES ('operation_logs',100)"
            )
        else:
            connection.execute("DELETE FROM sqlite_sequence WHERE name='operation_logs'")
        before = tuple(connection.iterdump())
    with pytest.raises(InputError) as caught:
        migrate(paths, now=datetime(2026, 10, 26, tzinfo=UTC))
    assert caught.value.diagnostics
    with sqlite_connection(paths.database) as connection:
        assert tuple(connection.iterdump()) == before
