"""0009升级边界测试；旧版本包和数据库全部复制到临时目录，不改历史迁移。"""

import shutil
from pathlib import Path

import pytest
from audit_support import operation_event
from ops_support import NOW, runtime_inputs
from sqlalchemy import delete, text

from rdp.audit.models import OperationLogRow
from rdp.audit.records import append_operation, query_operations
from rdp.audit.types import LogQuery, OperationQuery
from rdp.infra.config import load_config
from rdp.infra.db.connection import create_database_engine, session_scope
from rdp.infra.db.migration import migrate, migration_config
from rdp.infra.state import state_paths


@pytest.mark.parametrize("empty", [False, True])
def test_upgrade_preserves_audit_history_and_sequence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, empty: bool
) -> None:
    """验证新增迁移：历史字段原样保留，最大记录已删除或删空后也不复用已发编号。"""
    source = migration_config().get_main_option("script_location")
    assert source is not None
    historical = tmp_path / "old-package/migrations"
    shutil.copytree(source, historical)
    for script in (historical / "versions").glob("v*.py"):
        if script.name >= "v0009":
            script.unlink()
    with monkeypatch.context() as patch:
        patch.setattr("rdp.infra.db.migration.__file__", str(historical.parent / "migration.py"))
        inputs = runtime_inputs(tmp_path / "runtime")
    paths = state_paths(load_config(environ=inputs.environ, home=inputs.home).config, ())
    engine = create_database_engine(paths.database)
    try:
        with session_scope(engine) as session:
            append_operation(session, operation_event())
            if empty:
                session.execute(delete(OperationLogRow))
            session.execute(text("UPDATE sqlite_sequence SET seq=100 WHERE name='operation_logs'"))
        with session_scope(engine, read_only=True) as session:
            before = query_operations(
                session, OperationQuery(LogQuery()), lambda _s, _ids: frozenset()
            )
        result = migrate(paths, now=NOW)
        assert result.previous_revision == "0008_dataset_layout"
        # 历史包仅保留到 0008，真实升级入口走完后续迁移；0009 的对象种类扩展与历史行保留由此覆盖。
        assert result.current_revision == "0021_dataset_lineage"
        assert result.backup is not None
        with session_scope(engine, read_only=True) as session:
            assert (
                query_operations(session, OperationQuery(LogQuery()), lambda _s, _ids: frozenset())
                == before
            )
        with session_scope(engine) as session:
            assert append_operation(session, operation_event()) == 101
    finally:
        engine.dispose()
