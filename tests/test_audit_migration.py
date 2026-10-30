"""0003迁移及表约束验证（07）；所有迁移样例仅在tmp_path，不触碰真实平台数据库。"""

import re
import shutil
import sqlite3
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from accounts_support import AUDIT_CONTEXT, NOW, model_database
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from audit_support import operation_event
from sqlalchemy import CheckConstraint, Engine, event, inspect, text
from sqlalchemy.exc import SQLAlchemyError

from rdp.accounts.models import AccountRow
from rdp.audit.models import AuditSettingsRow, LoginLogRow, OperationLogRow
from rdp.audit.records import append_login, append_operation
from rdp.audit.types import LoginEvent, LoginKind, LoginResult
from rdp.infra.actors import ActorRef
from rdp.infra.config import PlatformConfig
from rdp.infra.db.connection import create_database_engine, session_scope
from rdp.infra.db.migration import migrate, migration_config
from rdp.infra.db.migrations.versions import v0003_audit_login_logs
from rdp.infra.db.models import metadata
from rdp.infra.diagnostics import ConflictError, DefectError, InputError
from rdp.infra.state import StatePaths, initialize_state, state_paths


@pytest.fixture(autouse=True)
def historical_audit_schema(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """固定验证历史0003包及其表视图，完整0004由test_jobs_migration独立验证，退出恢复共享元数据。"""
    location = migration_config().get_main_option("script_location")
    assert location is not None
    source = Path(location)
    directory = tmp_path / "historical-package" / "migrations"
    (directory / "versions").mkdir(parents=True)
    shutil.copyfile(source / "env.py", directory / "env.py")
    for filename in (
        "v0001_error_reports.py",
        "v0002_accounts_sessions.py",
        "v0003_audit_login_logs.py",
    ):
        shutil.copyfile(source / "versions" / filename, directory / "versions" / filename)
    monkeypatch.setattr("rdp.infra.db.migration.__file__", str(directory.parent / "migration.py"))
    tables = {
        name: table
        for name, table in metadata.tables.items()
        if name
        not in {
            "jobs",
            "worker_heartbeat",
            "schedule_submissions",
            "worker_gpu_checks",
            "nav_recovery_failure",
        }
        and not name.startswith("dataset")
    }
    monkeypatch.setattr(metadata, "tables", tables)
    # 唯一新增的历史CHECK值由0004负责；旧票仍核对0003的完整SQL，不改成最新版再冒充历史覆盖。
    for constraint in metadata.tables["operation_logs"].constraints:
        if (
            isinstance(constraint, CheckConstraint)
            and constraint.name == "ck_operation_logs_object_kind"
        ):
            monkeypatch.setattr(
                constraint, "sqltext", text("object_kind IN ('account','audit_settings')")
            )
    for constraint in metadata.tables["operation_logs"].constraints:
        if (
            isinstance(constraint, CheckConstraint)
            and constraint.name == "ck_operation_logs_ops_actor"
        ):
            monkeypatch.setattr(
                constraint, "sqltext", text("actor_id IS NOT NULL OR actor_name = '运维'")
            )
    yield


def test_active_migration() -> None:
    """历史验收1：0003包的唯一head及共享MetaData正确，历史包不包含0004。"""
    config = migration_config()
    assert ScriptDirectory.from_config(config).get_current_head() == "0003_audit_login_logs"
    location = config.get_main_option("script_location")
    assert location is not None
    assert "0004_jobs_worker" not in {
        revision.revision for revision in ScriptDirectory.from_config(config).walk_revisions()
    }
    for row in (OperationLogRow, LoginLogRow, AuditSettingsRow):
        assert "__abstract__" not in row.__dict__
        assert row.metadata is metadata


def test_upgrade_schema(tmp_path: Path) -> None:
    """验收1：真实0003建表与共用MetaData完全一致，日志无账号外键且主键AUTOINCREMENT。"""
    assert AccountRow.metadata is metadata
    paths = state_paths(PlatformConfig(state_dir=tmp_path), ())
    initialize_state(paths)
    result = migrate(paths, now=datetime(2026, 10, 26, tzinfo=UTC))
    assert result.current_revision == "0003_audit_login_logs"
    engine = create_database_engine(paths.database)
    try:
        with engine.connect() as connection:
            assert set(inspect(connection).get_table_names()) == {
                "alembic_version",
                "error_reports",
                "accounts",
                "account_sessions",
                "operation_logs",
                "login_logs",
                "audit_settings",
            }
            assert (
                compare_metadata(
                    MigrationContext.configure(connection, opts={"compare_type": True}), metadata
                )
                == []
            )
            for table in ("operation_logs", "login_logs"):
                assert inspect(connection).get_foreign_keys(table) == []
                sql = connection.exec_driver_sql(
                    "SELECT sql FROM sqlite_master WHERE name=?", (table,)
                ).scalar_one()
                assert "AUTOINCREMENT" in sql
    finally:
        engine.dispose()


def test_upgrade_preserves(tmp_path: Path) -> None:
    """验收1/7：升级前备份可读，原账号会话报错不变，不补历史日志或设置行。"""
    paths = _version_two(tmp_path)
    result = migrate(paths, now=datetime(2026, 10, 26, tzinfo=UTC))
    assert result.previous_revision == "0002_accounts_sessions" and result.backup is not None
    with sqlite3.connect(result.backup) as backup, sqlite3.connect(paths.database) as current:
        for sql in (
            "SELECT * FROM accounts",
            "SELECT * FROM account_sessions",
            "SELECT * FROM error_reports",
        ):
            assert current.execute(sql).fetchall() == backup.execute(sql).fetchall()
        assert current.execute("SELECT COUNT(*) FROM audit_settings").fetchone() == (0,)
        assert current.execute("SELECT COUNT(*) FROM operation_logs").fetchone() == (0,)
        assert current.execute("SELECT COUNT(*) FROM login_logs").fetchone() == (0,)


def test_upgrade_rollback(tmp_path: Path) -> None:
    """规范7.1：第三表DDL失败全回滚到0002，无半张表，升级前备份仍在。"""
    paths = _version_two(tmp_path)

    def fail(_connection: Any, _cursor: Any, statement: str, *_args: Any) -> None:
        if "CREATE TABLE audit_settings" in statement:
            raise SQLAlchemyError("测试第三张表创建失败")

    event.listen(Engine, "before_cursor_execute", fail)
    try:
        with pytest.raises(DefectError):
            migrate(paths, now=datetime(2026, 10, 26, tzinfo=UTC))
    finally:
        event.remove(Engine, "before_cursor_execute", fail)
    with sqlite3.connect(paths.database) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (
            "0002_accounts_sessions",
        )
        assert (
            connection.execute(
                "SELECT name FROM sqlite_master WHERE name IN ('operation_logs','login_logs','audit_settings')"
            ).fetchall()
            == []
        )
    assert len(tuple((tmp_path / "backups").glob("*.sqlite3"))) == 1


def test_downgrade_rejected() -> None:
    """验收1：降级在执行SQL前抛InputError，不删除日志。"""
    with pytest.raises(InputError):
        v0003_audit_login_logs.downgrade()


@pytest.mark.parametrize(
    "case",
    [
        "operation_category",
        "missing_login_identity",
        "deletion_result",
        "retention_range",
        "singleton",
    ],
)
def test_database_constraints(case: str, tmp_path: Path) -> None:
    """验收1/4/5：绕过领域的SQL仍受身份组合、结果类别及设置范围/单行约束保护。"""
    with model_database(tmp_path) as engine:
        with session_scope(engine) as session:
            append_operation(session, operation_event())
            append_login(
                session,
                LoginEvent(
                    NOW,
                    ActorRef(7, "管理员甲"),
                    "admin",
                    LoginKind.LOGIN,
                    LoginResult.SUCCESS,
                    AUDIT_CONTEXT,
                ),
            )
            session.execute(text("INSERT INTO audit_settings VALUES (1,7)"))
        sql = {
            "operation_category": "UPDATE operation_logs SET failure_category='external'",
            "missing_login_identity": "UPDATE login_logs SET result='account_missing'",
            "deletion_result": "UPDATE login_logs SET kind='logout',result='wrong_password'",
            "retention_range": "UPDATE audit_settings SET retention_days=6",
            "singleton": "INSERT INTO audit_settings VALUES (2,30)",
        }[case]
        with pytest.raises(ConflictError), session_scope(engine) as session:
            session.execute(text(sql))


def _version_two(root: Path) -> StatePaths:
    """通过Alembic公共接口准备真实0002库和独立已知报错样本，不调用新版本业务服务。"""
    paths = state_paths(PlatformConfig(state_dir=root), ())
    initialize_state(paths)
    engine = create_database_engine(paths.database)
    try:
        with engine.begin() as connection:
            command.upgrade(migration_config(connection), "0002_accounts_sessions")
            connection.exec_driver_sql(
                "INSERT INTO error_reports VALUES ('1','2026-10-25T00:00:00.000000Z','defect','保留摘要','保留报告','job')"
            )
    finally:
        engine.dispose()
    return paths


def test_frozen_sql_matches_models(tmp_path: Path) -> None:
    """验收1：冻结DDL的列约束与模型SQLite建表文本一致，比较独立创建的两份数据库。"""
    paths = _version_two(tmp_path / "migrated")
    migrate(paths, now=datetime(2026, 10, 26, tzinfo=UTC))
    model_path = tmp_path / "models.sqlite3"
    engine = create_database_engine(model_path)
    try:
        metadata.create_all(engine)
    finally:
        engine.dispose()
    with sqlite3.connect(paths.database) as actual, sqlite3.connect(model_path) as expected:
        for table in ("operation_logs", "login_logs", "audit_settings"):
            sql = "SELECT sql FROM sqlite_master WHERE name=?"
            actual_sql = actual.execute(sql, (table,)).fetchone()[0]
            expected_sql = expected.execute(sql, (table,)).fetchone()[0]
            assert re.sub(r"\s+", " ", actual_sql) == re.sub(r"\s+", " ", expected_sql)
