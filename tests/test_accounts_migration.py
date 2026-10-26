"""工单06前向迁移测试；只用 tmp_path/临时数据库和固定 aware 时钟。"""

import re
import shutil
import sqlite3
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from sqlalchemy import Engine, event, inspect
from sqlalchemy.exc import SQLAlchemyError

from rdp.accounts.models import AccountRow
from rdp.infra.config import PlatformConfig
from rdp.infra.db.connection import create_database_engine
from rdp.infra.db.migration import check_database_version, migrate, migration_config
from rdp.infra.db.migrations.versions import v0002_accounts_sessions
from rdp.infra.db.models import metadata
from rdp.infra.diagnostics import DefectError, InputError
from rdp.infra.state import StatePaths, initialize_state, state_paths


@pytest.fixture(autouse=True)
def historical_accounts_schema(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """第6张固定验证历史0002包和表；保留所有原断言，0003另由本票完整迁移测试覆盖。"""
    location = migration_config().get_main_option("script_location")
    assert location is not None
    source = Path(location)
    directory = tmp_path / "historical-package" / "migrations"
    (directory / "versions").mkdir(parents=True)
    shutil.copyfile(source / "env.py", directory / "env.py")
    for filename in ("v0001_error_reports.py", "v0002_accounts_sessions.py"):
        shutil.copyfile(source / "versions" / filename, directory / "versions" / filename)
    monkeypatch.setattr("rdp.infra.db.migration.__file__", str(directory.parent / "migration.py"))
    # 只缩小本历史版本的建表/对比视图，不重建Table；fixture结束精确恢复共享登记。
    tables = {
        name: table
        for name, table in metadata.tables.items()
        if name in {"error_reports", "accounts", "account_sessions"}
    }
    monkeypatch.setattr(metadata, "tables", tables)
    yield


def test_upgrade_new(tmp_path: Path) -> None:
    """验证契约：激活0002后空库升级到新head，账号、会话两表和原报错表结构与共用MetaData比较无差异。"""
    paths = state_paths(PlatformConfig(state_dir=tmp_path), ())
    initialize_state(paths)
    result = migrate(paths, now=datetime(2026, 10, 25, tzinfo=UTC))
    assert result.current_revision == "0002_accounts_sessions"
    engine = create_database_engine(paths.database)
    try:
        with engine.connect() as connection:
            assert set(inspect(connection).get_table_names()) == {
                "alembic_version",
                "error_reports",
                "accounts",
                "account_sessions",
            }
            assert (
                compare_metadata(
                    MigrationContext.configure(connection, opts={"compare_type": True}), metadata
                )
                == []
            )
            assert AccountRow.metadata is metadata
    finally:
        engine.dispose()


def test_upgrade_existing(tmp_path: Path) -> None:
    """验证契约：0001升级前先生成可读取备份，已有报错数据不变，不创建默认账号。"""
    paths = _first_version(tmp_path)
    result = migrate(paths, now=datetime(2026, 10, 25, tzinfo=UTC))
    assert result.previous_revision == "0001_error_reports" and result.backup is not None
    with sqlite3.connect(result.backup) as old:
        assert old.execute("SELECT version_num FROM alembic_version").fetchone() == (
            "0001_error_reports",
        )
        assert old.execute("SELECT report FROM error_reports").fetchone() == ("保留报告",)
    with sqlite3.connect(paths.database) as current:
        assert current.execute("SELECT report FROM error_reports").fetchone() == ("保留报告",)
        assert current.execute("SELECT count(*) FROM accounts").fetchone() == (0,)


def test_upgrade_noop(tmp_path: Path) -> None:
    """验证契约：再次migrate不改schema或数据、不新增备份。"""
    paths = _first_version(tmp_path)
    migrate(paths, now=datetime(2026, 10, 25, tzinfo=UTC))
    before = paths.database.read_bytes()
    backups = tuple((tmp_path / "backups").iterdir())
    result = migrate(paths, now=datetime(2026, 10, 25, tzinfo=UTC))
    assert not result.changed and result.backup is None
    assert paths.database.read_bytes() == before
    assert tuple((tmp_path / "backups").iterdir()) == backups


def test_upgrade_failure(tmp_path: Path) -> None:
    """验证契约：DDL中途失败整体回滚，版本仍0001，保留完整升级前备份，无半张表。"""
    paths = _first_version(tmp_path)

    def fail(connection: Any, cursor: Any, statement: str, *args: Any) -> None:
        if "CREATE TABLE account_sessions" in statement:
            raise SQLAlchemyError("测试 DDL 失败")

    event.listen(Engine, "before_cursor_execute", fail)
    try:
        with pytest.raises(DefectError):
            migrate(paths, now=datetime(2026, 10, 25, tzinfo=UTC))
    finally:
        event.remove(Engine, "before_cursor_execute", fail)
    with sqlite3.connect(paths.database) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (
            "0001_error_reports",
        )
        assert (
            connection.execute(
                "SELECT name FROM sqlite_master WHERE name IN ('accounts','account_sessions')"
            ).fetchall()
            == []
        )
    assert len(list((tmp_path / "backups").glob("*.sqlite3"))) == 1


def test_upgrade_utc_checks(tmp_path: Path) -> None:
    """验证契约：迁移的UTC文本列、索引、约束名、AUTOINCREMENT及会话级联外键与模型一致。"""
    paths = _first_version(tmp_path / "migrated")
    migrate(paths, now=datetime(2026, 10, 25, tzinfo=UTC))
    model_path = tmp_path / "model.sqlite3"
    engine = create_database_engine(model_path)
    try:
        metadata.create_all(engine)
    finally:
        engine.dispose()
    with sqlite3.connect(paths.database) as actual, sqlite3.connect(model_path) as expected:
        for table in ("accounts", "account_sessions", "error_reports"):
            actual_sql = actual.execute(
                "SELECT sql FROM sqlite_master WHERE name=?", (table,)
            ).fetchone()[0]
            expected_sql = expected.execute(
                "SELECT sql FROM sqlite_master WHERE name=?", (table,)
            ).fetchone()[0]
            assert re.sub(r"\s+", " ", actual_sql) == re.sub(r"\s+", " ", expected_sql)
        assert (
            actual.execute("PRAGMA foreign_key_list(account_sessions)").fetchone()[6] == "CASCADE"
        )


def test_upgrade_gate(tmp_path: Path) -> None:
    """验证契约：旧版本启动被闸门拒绝，不能自动迁移。"""
    paths = _first_version(tmp_path)
    before = paths.database.read_bytes()
    with pytest.raises(InputError):
        check_database_version(paths.database)
    assert paths.database.read_bytes() == before


def test_downgrade_refused(tmp_path: Path) -> None:
    """验证契约：任何降级在SQL前给InputError，数据库和版本不变，提示停服务人工恢复备份。"""
    with pytest.raises(InputError) as caught:
        v0002_accounts_sessions.downgrade()
    assert "备份" in caught.value.diagnostics[0].next_step


def _first_version(root: Path) -> StatePaths:
    """只在临时状态目录通过 Alembic 公共接口建立真实的历史版本。"""
    paths = state_paths(PlatformConfig(state_dir=root), ())
    initialize_state(paths)
    engine = create_database_engine(paths.database)
    try:
        with engine.begin() as connection:
            command.upgrade(migration_config(connection), "0001_error_reports")
            connection.exec_driver_sql(
                "INSERT INTO error_reports VALUES ('1','2026-10-25T00:00:00.000000Z','defect','保留摘要','保留报告','job')"
            )
    finally:
        engine.dispose()
    return paths
