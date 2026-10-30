"""来源枚举迁移：只用临时旧版数据库，验证既有索引行和外键完整保留。"""

import shutil
from pathlib import Path

import pytest
from dataset_api_support import seed_historical_index
from datasets_execution_support import dataset_case
from jobs_storage_support import NOW
from nav_manifest import FakeNavigation
from sqlalchemy import Text, literal_column, select, text
from sqlalchemy import table as sql_table

from rdp.infra.db.connection import session_scope
from rdp.infra.db.migration import migrate, migration_config
from rdp.infra.diagnostics import ConflictError


def test_migration_preserves_populated_index_and_expands_origins(
    tmp_path: Path, fake_nav: FakeNavigation, monkeypatch: pytest.MonkeyPatch
) -> None:
    """契约：0011 放宽来源 CHECK，保留八张索引表全部旧行与外键，仍拒绝未知编码；重复迁移无副作用。"""
    source = migration_config().get_main_option("script_location")
    assert source is not None
    historical = tmp_path / "old/migrations"
    shutil.copytree(source, historical, ignore=shutil.ignore_patterns("v0011*", "v0012*"))
    with monkeypatch.context() as patch:
        patch.setattr("rdp.infra.db.migration.__file__", str(historical.parent / "migration.py"))
        with dataset_case(tmp_path / "state", fake_nav) as case:
            seed_historical_index(case.engine, fake_nav, tmp_path / "current", monkeypatch)
            with session_scope(case.engine, read_only=True) as session:
                tables = tuple(
                    session.scalars(
                        text(
                            "SELECT name FROM sqlite_master WHERE type='table' AND (name='datasets' OR name LIKE 'dataset_%') ORDER BY name"
                        )
                    )
                )
                before = {
                    table: session.execute(
                        select(literal_column("*", type_=Text))
                        .select_from(sql_table(table))
                        .order_by(text("1,2"))
                    ).all()
                    for table in tables
                }
            paths, engine = case.paths, case.engine
            # 保持夹具引擎存活，退出历史包路径的覆盖后升级同一份真实旧库。
            with monkeypatch.context() as restore:
                restore.setattr(
                    "rdp.infra.db.migration.__file__",
                    str(Path(__file__).parents[1] / "src/rdp/infra/db/migration.py"),
                )
                result = migrate(paths, now=NOW)
                assert result.changed and result.current_revision == "0012_scene_task_index"
                with session_scope(engine, read_only=True) as session:
                    after = {
                        table: session.execute(
                            select(literal_column("*", type_=Text))
                            .select_from(sql_table(table))
                            .order_by(text("1,2"))
                        ).all()
                        for table in tables
                    }
                    assert {
                        key: [tuple(row[:-3]) for row in rows] if key == "datasets" else rows
                        for key, rows in after.items()
                    } == before
                    assert all(tuple(row[-3:]) == (None, "[]", None) for row in after["datasets"])
                    assert session.execute(text("PRAGMA foreign_key_check")).all() == []
                for origin in ("real", "umi", "ego", "simulation", "open_source", "unknown"):
                    with session_scope(engine) as session:
                        session.execute(
                            text("UPDATE datasets SET data_origin=:origin"), {"origin": origin}
                        )
                with pytest.raises(ConflictError), session_scope(engine) as session:
                    session.execute(text("UPDATE datasets SET data_origin='invented'"))
                assert not migrate(paths, now=NOW).changed
