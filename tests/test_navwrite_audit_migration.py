"""操作日志扩展与 0010 迁移的契约测试（M1-07，L15）。

旧版本包和数据库全部复制到临时目录，不改历史迁移。
"""

import shutil
import tomllib
from datetime import UTC, datetime
from pathlib import Path

import pytest
from audit_support import operation_event
from ops_support import NOW, runtime_inputs
from pydantic import ValidationError
from sqlalchemy import delete, text
from sqlalchemy.schema import CreateTable

from rdp.api.audit_schemas import ObjectResponse
from rdp.audit import _validation as validate
from rdp.audit.errors import AuditInputError
from rdp.audit.models import OperationLogRow
from rdp.audit.records import append_operation, query_operations
from rdp.audit.types import (
    OPERATION_DETAIL_FIELDS,
    AuditContext,
    AuditValues,
    LogQuery,
    ObjectRef,
    OperationDetails,
    OperationEvent,
    OperationQuery,
    OperationResult,
    OperationType,
)
from rdp.infra.actors import ActorRef
from rdp.infra.config import PlatformConfig, load_config
from rdp.infra.db.connection import create_database_engine, session_scope
from rdp.infra.db.migration import migrate, migration_config
from rdp.infra.db.migrations.versions import v0010_nav_write_foundation
from rdp.infra.db.models import metadata
from rdp.infra.diagnostics import ConflictError, InputError
from rdp.infra.state import StatePaths, initialize_state, state_paths
from rdp.jobs.navwrite.rows import NavRecoveryFailureRow

ROOT = Path(__file__).resolve().parent.parent
NAV_CODES = {
    "create_link",
    "create_dataset",
    "repoint_dataset",
    "set_data_origin",
    "revert_change",
    "rollback_navigation_write",
    "confirm_navigation_recovery",
}
OLD_CODES = {
    "create_account": "create_account",
    "create_first_admin": "create_first_admin",
    "delete_account": "delete_account",
    "set_role": "set_role",
    "disable_account": "disable_account",
    "enable_account": "enable_account",
    "reset_password": "reset_password",
    "reset_password_from_ops": "reset_password_from_ops",
    "change_password": "change_password",
    "set_retention": "set_retention",
    "submit_job": "submit_job",
    "cancel_job": "cancel_job",
    "rebuild_index": "rebuild_index",
}


def _navigation_event(
    object_id: str | None = "12",
    name: str = "写导航层 #12",
    operation: OperationType = OperationType.CREATE_LINK,
) -> OperationEvent:
    """写导航层的成功事件。"""
    return OperationEvent(
        NOW,
        ActorRef(7, "管理员甲"),
        operation,
        ObjectRef("navigation_write", object_id, name),
        OperationResult.SUCCESS,
        None,
        AuditContext(source_ip=None, request_id=None),
        OperationDetails(
            before=AuditValues(),
            after=AuditValues(
                dataset_ids=("dataset-1",),
                dataset_count=1,
                file_count=2,
                link_count=1,
                change_record_id="12",
            ),
        ),
    )


def test_new_operation_codes_are_stable_strings() -> None:
    """L15：七个新操作码的字符串值固定，旧值含义不变。"""
    new = {member.value for member in OperationType} - set(OLD_CODES)
    assert new == NAV_CODES
    for name, value in OLD_CODES.items():
        assert OperationType(value).name == name.upper()
    assert OperationType.REVERT_CHANGE.value == "revert_change"


def test_audit_values_new_fields_whitelisted() -> None:
    """L15：dataset_ids、dataset_count、file_count、link_count、change_record_id、reverts_job_id 在白名单里，超过 20 个编号被拒绝。"""
    twenty = tuple(f"dataset-{n:02d}" for n in range(20))
    assert AuditValues(dataset_ids=twenty).dataset_ids == twenty
    with pytest.raises(ValidationError):
        AuditValues(dataset_ids=(*twenty, "dataset-20"))
    with pytest.raises(ValidationError):
        AuditValues(file_count=-1)
    with pytest.raises(ValidationError):
        AuditValues(change_record_id="012")
    with pytest.raises(ValidationError):
        AuditValues.model_validate({"before_content": "全文"})  # 前后像全文不进数据库
    # 其它操作码的白名单里没有这些字段：同一个 details 换成账号操作码被拒绝。
    event = _navigation_event()
    wrong = OperationEvent(
        NOW,
        event.actor,
        OperationType.SET_ROLE,
        ObjectRef("account", "5", "乙"),
        event.result,
        None,
        event.context,
        event.details,
    )
    with pytest.raises(AuditInputError):
        validate.operation(wrong)
    validate.operation(event)


def test_operation_detail_fields_cover_every_operation() -> None:
    """契约：OPERATION_DETAIL_FIELDS 覆盖每一个 OperationType，撤回多一个 reverts_job_id。"""
    assert set(OPERATION_DETAIL_FIELDS) == set(OperationType)
    shared = OPERATION_DETAIL_FIELDS[OperationType.CREATE_LINK]
    assert shared == {
        "dataset_ids",
        "dataset_count",
        "file_count",
        "link_count",
        "change_record_id",
    }
    assert OPERATION_DETAIL_FIELDS[OperationType.REVERT_CHANGE] == shared | {"reverts_job_id"}
    for code in NAV_CODES - {"revert_change"}:
        assert OPERATION_DETAIL_FIELDS[OperationType(code)] == shared


def test_navigation_write_object_ref_validation() -> None:
    """契约 ObjectRef：navigation_write 的对象编号是规范十进制作业编号，名字为“写导航层 #编号”。"""
    validate.operation(_navigation_event())
    for bad in (
        _navigation_event("012", "写导航层 #012"),
        _navigation_event("12", "写导航层 #13"),
        _navigation_event("12", "别的名字"),
        _navigation_event(None, "写导航层 #12"),
        _navigation_event("0", "写导航层 #0"),
    ):
        with pytest.raises(AuditInputError):
            validate.operation(bad)
    # 写导航层的操作码必须对应 navigation_write 对象，反过来也一样。
    mismatched = OperationEvent(
        NOW,
        ActorRef(7, "甲"),
        OperationType.CREATE_LINK,
        ObjectRef("job", "12", "作业 #12"),
        OperationResult.SUCCESS,
        None,
        AuditContext(source_ip=None, request_id=None),
        OperationDetails(before=AuditValues(), after=AuditValues(file_count=1)),
    )
    with pytest.raises(AuditInputError):
        validate.operation(mismatched)


def _historical_database(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> StatePaths:
    """只含到 0009 的迁移包和数据库，升级时由真实迁移入口走 0010。"""
    source = migration_config().get_main_option("script_location")
    assert source is not None
    historical = tmp_path / "old-package/migrations"
    shutil.copytree(source, historical)
    (historical / "versions/v0010_nav_write_foundation.py").unlink()
    with monkeypatch.context() as patch:
        patch.setattr("rdp.infra.db.migration.__file__", str(historical.parent / "migration.py"))
        inputs = runtime_inputs(tmp_path / "runtime")
        paths = state_paths(load_config(environ=inputs.environ, home=inputs.home).config, ())
        migrate(paths, now=NOW)
    return paths


def test_old_rows_unchanged_by_0010(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """迁移 v0010：升级后 operation_logs 全部旧行、索引和发号高水位不变。"""
    for empty in (False, True):
        root = tmp_path / f"case-{empty}"
        root.mkdir()
        paths = _historical_database(root, monkeypatch)
        engine = create_database_engine(paths.database)
        try:
            with session_scope(engine) as session:
                append_operation(session, operation_event())
                if empty:
                    session.execute(delete(OperationLogRow))
                session.execute(
                    text("UPDATE sqlite_sequence SET seq=100 WHERE name='operation_logs'")
                )
            with session_scope(engine, read_only=True) as session:
                before = query_operations(
                    session, OperationQuery(LogQuery()), lambda _s, _i: frozenset()
                )
                indexes = {
                    row[0]
                    for row in session.execute(
                        text(
                            "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='operation_logs'"
                        )
                    )
                }
            result = migrate(paths, now=NOW)
            assert result.previous_revision == "0009_rebuild_index_audit"
            assert result.current_revision == "0010_nav_write_foundation"
            with session_scope(engine, read_only=True) as session:
                after = query_operations(
                    session, OperationQuery(LogQuery()), lambda _s, _i: frozenset()
                )
                kept = {
                    row[0]
                    for row in session.execute(
                        text(
                            "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='operation_logs'"
                        )
                    )
                }
            assert after == before and kept == indexes
            with session_scope(engine) as session:
                assert append_operation(session, operation_event()) == 101
        finally:
            engine.dispose()


def _migrated(tmp_path: Path) -> StatePaths:
    """真实迁移到最新版本的状态目录。"""
    paths = state_paths(PlatformConfig(state_dir=tmp_path), ())
    initialize_state(paths)
    migrate(paths, now=datetime(2026, 10, 29, tzinfo=UTC))
    return paths


def test_0010_accepts_navigation_write_kind(tmp_path: Path) -> None:
    """迁移 v0010：升级后 object_kind 可写 navigation_write，旧值仍可写，未知值被 CHECK 拒绝。"""
    paths = _migrated(tmp_path)
    engine = create_database_engine(paths.database)
    try:
        with session_scope(engine) as session:
            append_operation(session, _navigation_event())
            append_operation(session, operation_event())
        with pytest.raises(ConflictError), session_scope(engine) as session:
            session.execute(
                text(
                    "INSERT INTO operation_logs (occurred_at, actor_name, operation, object_kind, object_name, result, details) "
                    "VALUES ('2026-10-29 00:00:00.000000', '运维', 'x', 'bogus', 'n', 'success', '{}')"
                )
            )
        with session_scope(engine, read_only=True) as session:
            kinds = {
                row[0] for row in session.execute(text("SELECT object_kind FROM operation_logs"))
            }
        assert kinds == {"navigation_write", "account"}
    finally:
        engine.dispose()


def _table_sql(database: Path, table: str) -> str:
    """sqlite_master 里的建表语句。"""
    import sqlite3

    with sqlite3.connect(database) as connection:
        (sql,) = connection.execute(
            "SELECT sql FROM sqlite_master WHERE name=?", (table,)
        ).fetchone()
    return str(sql)


def test_0010_creates_marker_table(tmp_path: Path) -> None:
    """迁移 v0010：创建单行表 nav_recovery_failure，约束与冻结 DDL 一致。"""
    paths = _migrated(tmp_path)
    import sqlite3

    assert _table_sql(paths.database, "nav_recovery_failure").split() == (
        v0010_nav_write_foundation.MARKER_SQL.strip().rstrip(";").split()
    )
    with sqlite3.connect(paths.database) as connection:
        columns = {
            row[1]: (row[2], bool(row[3]), row[5])
            for row in connection.execute("PRAGMA table_info(nav_recovery_failure)")
        }
        assert connection.execute("SELECT count(*) FROM nav_recovery_failure").fetchone() == (0,)
    assert columns == {
        "singleton_id": ("INTEGER", True, 1),
        "set_at": ("TEXT", True, 0),
        "job_ids": ("JSON", True, 0),
        "items": ("JSON", True, 0),
        "total_items": ("INTEGER", True, 0),
    }


def test_0010_downgrade_refused(tmp_path: Path) -> None:
    """迁移 v0010：降级被拒绝，保留当前结构和数据。"""
    paths = _migrated(tmp_path)
    before = _table_sql(paths.database, "nav_recovery_failure")
    with pytest.raises(InputError):
        v0010_nav_write_foundation.downgrade()
    assert _table_sql(paths.database, "nav_recovery_failure") == before


def test_0010_matches_orm_after_activation(tmp_path: Path) -> None:
    """迁移 v0010：移入 versions 后 compare_metadata 对 ORM 无差异。"""
    assert not (ROOT / "src/rdp/infra/db/migrations/pending").exists()
    script = Path(__file__).resolve().parent.parent / "src/rdp/infra/db/migrations/versions"
    assert (script / "v0010_nav_write_foundation.py").is_file()
    paths = _migrated(tmp_path / "migrated")
    model = tmp_path / "model.sqlite3"
    engine = create_database_engine(model)
    try:
        tables = [metadata.tables["nav_recovery_failure"], metadata.tables["operation_logs"]]
        metadata.create_all(engine, tables=tables)
    finally:
        engine.dispose()
    for table in ("nav_recovery_failure", "operation_logs"):
        assert _table_sql(paths.database, table).split() == _table_sql(model, table).split()
    assert metadata.tables["nav_recovery_failure"] is NavRecoveryFailureRow.__table__
    assert str(CreateTable(metadata.tables["nav_recovery_failure"])).split()


def test_import_boundary_contract_present() -> None:
    """规范 1.4：pyproject 的 import-linter 合约禁止 rdp.api、rdp.ops 直接 import atomic、recovery、pipeline、jobs。"""
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    contracts = config["tool"]["importlinter"]["contracts"]
    (contract,) = (c for c in contracts if "worker 一侧" in c["name"])
    assert contract["type"] == "forbidden"
    assert set(contract["source_modules"]) == {"rdp.api", "rdp.ops"}
    assert set(contract["forbidden_modules"]) == {
        "rdp.jobs.navwrite.atomic",
        "rdp.jobs.navwrite.recovery",
        "rdp.jobs.navwrite.pipeline",
        "rdp.jobs.navwrite.jobs",
    }
    # 直接依赖：api、ops 的源文件里没有任何一行 import 这四个模块（合约本身由 make check 的 lint-imports 执行）。
    for package in ("api", "ops"):
        for source in (ROOT / "src/rdp" / package).rglob("*.py"):
            content = source.read_text(encoding="utf-8")
            for module in ("atomic", "recovery", "pipeline", "jobs"):
                assert f"rdp.jobs.navwrite.{module}" not in content, source
                assert f"from rdp.jobs.navwrite import {module}" not in content, source


def test_api_audit_schema_accepts_navigation_write_kind() -> None:
    """契约：操作日志接口的对象种类包含 navigation_write，OpenAPI 与生成类型保持同步。"""
    response = ObjectResponse(
        kind="navigation_write", object_id="12", name="写导航层 #12", deleted=False
    )
    assert response.kind == "navigation_write"
    with pytest.raises(ValidationError):
        ObjectResponse(kind="bogus", object_id="1", name="x", deleted=False)  # pyright: ignore[reportArgumentType]
    openapi = (ROOT / "src/web/src/api/openapi.json").read_text(encoding="utf-8")
    generated = (ROOT / "src/web/src/api/schema.d.ts").read_text(encoding="utf-8")
    assert '"navigation_write"' in openapi and '"navigation_write"' in generated
