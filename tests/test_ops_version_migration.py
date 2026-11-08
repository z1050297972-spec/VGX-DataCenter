"""第 11 张 version_migration 契约清单；只用临时目录和可注入依赖，不触碰真实部署或服务。"""

from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

import pytest
from accounts_support import NOW
from alembic import command
from alembic.script import ScriptDirectory
from scheduling_migration_support import JOB_SQL, schema_objects, version_four
from sqlalchemy import Engine, event, inspect, text
from sqlalchemy.exc import IntegrityError

from rdp.infra.config import PlatformConfig
from rdp.infra.db.connection import create_database_engine
from rdp.infra.db.migration import check_database_version, migrate, migration_config
from rdp.infra.diagnostics import ConflictError, DefectError
from rdp.infra.state import StatePaths, initialize_state, state_paths
from rdp.jobs.models import JobRow


def test_active_head() -> None:
    """验证0008成为唯一活动head，历史0007仍在图中且所有活动迁移来自versions。"""
    config = migration_config()
    assert ScriptDirectory.from_config(config).get_current_head() == "0019_collection_registry"
    location = config.get_main_option("script_location")
    assert location is not None
    # 后续工单可以声明pending；真正的保护是Alembic只加载versions，不提前激活新revision。
    assert all(
        Path(revision.path).parent == Path(location) / "versions"
        for revision in ScriptDirectory.from_config(config).walk_revisions()
    )
    assert "0007_dataset_index" in {
        revision.revision for revision in ScriptDirectory.from_config(config).walk_revisions()
    }
    assert JobRow.__table__.c.platform_version.nullable


def test_upgrade_empty_and_history(tmp_path: Path) -> None:
    """验证契约：0005→0006增加可空platform_version，旧行NULL，不把升级版本伪造成旧执行事实。"""
    for empty in (False, True):
        with _version_five(tmp_path / str(empty)) as (engine, paths):
            with engine.begin() as connection:
                if empty:
                    connection.execute(text("DELETE FROM jobs"))
                before = connection.execute(text("SELECT * FROM jobs")).mappings().all()
            result = migrate(paths, now=NOW)
            assert result.previous_revision == "0005_job_scheduling"
            assert result.current_revision == "0019_collection_registry"
            assert result.backup is not None and result.backup.is_file()
            with engine.connect() as connection:
                after = connection.execute(text("SELECT * FROM jobs")).mappings().all()
                assert [dict(row, platform_version=None) for row in before] == after


def test_fresh_latest(tmp_path: Path) -> None:
    """验证契约：空库迁移至0008具有完整账号、日志、作业、调度和数据集索引结构，版本闸门接受最新head。"""
    paths = state_paths(PlatformConfig(state_dir=tmp_path), ())
    initialize_state(paths)
    result = migrate(paths, now=NOW)
    assert result.current_revision == "0019_collection_registry"
    check_database_version(paths.database)
    engine = create_database_engine(paths.database)
    try:
        assert {
            "accounts",
            "operation_logs",
            "login_logs",
            "jobs",
            "schedule_submissions",
            "worker_gpu_checks",
        } <= set(inspect(engine).get_table_names())
        assert "platform_version" in {
            column["name"] for column in inspect(engine).get_columns("jobs")
        }
    finally:
        engine.dispose()


def test_constraints(tmp_path: Path) -> None:
    """验证契约：版本列允许NULL与1/128码点，拒绝空值和129码点；原jobs约束和索引仍有效。"""
    with _version_five(tmp_path) as (engine, paths):
        migrate(paths, now=NOW)
        for version in (None, "v", "版" * 128):
            with engine.begin() as connection:
                connection.execute(
                    text("UPDATE jobs SET platform_version=:version"), {"version": version}
                )
                assert (
                    connection.execute(text("SELECT platform_version FROM jobs")).scalar_one()
                    == version
                )
        for version in ("", "版" * 129):
            with pytest.raises(IntegrityError), engine.begin() as connection:
                connection.execute(
                    text("UPDATE jobs SET platform_version=:version"), {"version": version}
                )
        with pytest.raises(IntegrityError), engine.begin() as connection:
            connection.execute(text("UPDATE jobs SET gpu_index=-1"))
        assert inspect(engine).get_indexes("jobs")[0]["column_names"] == ["state", "job_id"]


def test_sequence_preserved(tmp_path: Path) -> None:
    """验证契约：升级/降级保留sqlite_sequence高水位，覆盖已有行及删除全部历史后空表，编号不复用。"""
    for empty in (False, True):
        with _version_five(tmp_path / str(empty)) as (engine, _paths):
            with engine.begin() as connection:
                connection.execute(text(JOB_SQL), {"id": 9000})
                connection.execute(
                    text("DELETE FROM jobs" if empty else "DELETE FROM jobs WHERE job_id=9000")
                )
            with engine.begin() as connection:
                command.upgrade(migration_config(connection), "0006_platform_version")
            with engine.begin() as connection:
                assert connection.execute(text(JOB_SQL), {"id": None}).lastrowid == 9001
                command.downgrade(migration_config(connection), "0005_job_scheduling")
                assert connection.execute(text(JOB_SQL), {"id": None}).lastrowid == 9002


def test_downgrade_refuses_data_loss(tmp_path: Path) -> None:
    """验证契约：任意非NULL版本先拒绝降级，数据、schema和revision全不变；全NULL时可恢复0005。"""
    with _version_five(tmp_path) as (engine, _paths):
        with engine.begin() as connection:
            command.upgrade(migration_config(connection), "0006_platform_version")
        with engine.begin() as connection:
            connection.execute(text("UPDATE jobs SET platform_version='old (1234567)'"))
            before = schema_objects(connection)
        with pytest.raises(ConflictError), engine.begin() as connection:
            command.downgrade(migration_config(connection), "0005_job_scheduling")
        with engine.begin() as connection:
            assert schema_objects(connection) == before
            assert (
                connection.execute(text("SELECT platform_version FROM jobs")).scalar_one()
                == "old (1234567)"
            )
            assert (
                connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
                == "0006_platform_version"
            )
            connection.execute(text("UPDATE jobs SET platform_version=NULL"))
            command.downgrade(migration_config(connection), "0005_job_scheduling")
            assert "platform_version" not in {
                column["name"] for column in inspect(connection).get_columns("jobs")
            }


def test_migration_failure_atomic(tmp_path: Path) -> None:
    """验证契约：DDL/I/O故障整次事务回滚且升级前备份保留；不修改历史迁移文件。"""

    def fail(*args: object) -> None:
        statement = args[2]
        if isinstance(statement, str) and "INSERT INTO jobs (" in statement:
            raise RuntimeError("模拟DDL复制中断")

    with _version_five(tmp_path) as (engine, paths):
        with engine.connect() as connection:
            before = schema_objects(connection)
            rows = connection.execute(text("SELECT * FROM jobs")).all()
            sequences = connection.execute(
                text("SELECT * FROM sqlite_sequence ORDER BY name")
            ).all()
        event.listen(Engine, "before_cursor_execute", fail)
        try:
            with pytest.raises(DefectError):
                migrate(paths, now=NOW)
        finally:
            event.remove(Engine, "before_cursor_execute", fail)
        with engine.connect() as connection:
            assert schema_objects(connection) == before
            assert connection.execute(text("SELECT * FROM jobs")).all() == rows
            assert (
                connection.execute(text("SELECT * FROM sqlite_sequence ORDER BY name")).all()
                == sequences
            )
            assert (
                connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
                == "0005_job_scheduling"
            )
        assert len(list((paths.root / "backups").glob("*.sqlite3"))) == 1


@contextmanager
def _version_five(root: Path) -> Generator[tuple[Engine, StatePaths]]:
    """建立真实0005历史库，使用旧列插入样本，退出回收引擎。"""
    with version_four(root) as (engine, paths):
        with engine.begin() as connection:
            command.upgrade(migration_config(connection), "0005_job_scheduling")
        yield engine, paths
