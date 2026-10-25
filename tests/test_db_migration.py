"""工单 05 契约测试；只在 tmp_path 的假状态目录验证。"""

import importlib
import logging
import multiprocessing
import re
import shutil
import sqlite3
import textwrap
import time
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from db_support import reap_processes as _reap
from db_support import sqlite_connection
from sqlalchemy import Engine, event, inspect
from sqlalchemy.exc import SQLAlchemyError

from rdp.infra.config import PlatformConfig
from rdp.infra.db.connection import create_database_engine
from rdp.infra.db.migration import (
    BACKUP_FILENAME_PATTERN,
    check_database_version,
    migrate,
    migration_config,
)
from rdp.infra.db.migrations.versions import v0001_error_reports
from rdp.infra.db.models import metadata
from rdp.infra.diagnostics import ConflictError, DefectError, ExternalError, InputError
from rdp.infra.state import StatePaths, initialize_state, state_paths


def _paths(root: Path) -> StatePaths:
    """只初始化 pytest 临时状态目录；测试从不探测真实 home。"""
    paths = state_paths(PlatformConfig(state_dir=root), ())
    initialize_state(paths)
    return paths


def _migrate_child(root: str, ready: Any, release: Any, result: Any, hold: bool) -> None:
    """让真实 migrate 在 SQLite 备份边界等待，父进程可观察目录锁是否覆盖整个升级。"""
    original = sqlite3.connect

    class HeldBackup(sqlite3.Connection):
        """只在测试子进程延长备份操作，不修改平台内部函数。"""

        def backup(self, *args: Any, **kwargs: Any) -> None:
            """持有 migrate 锁时发送就绪信号，最多等待 10 秒。"""
            ready.set()
            if not release.wait(10):
                raise TimeoutError("测试释放超时")
            super().backup(*args, **kwargs)

    def connect(*args: Any, **kwargs: Any) -> sqlite3.Connection:
        return original(*args, **kwargs, factory=HeldBackup)

    try:
        if hold:
            sqlite3.connect = connect
        migrate(_paths(Path(root)), now=datetime(2026, 10, 24, tzinfo=UTC))
        result.put("ok")
    except ConflictError:
        result.put("conflict")
    finally:
        sqlite3.connect = original


def _future_package(root: Path, patch: pytest.MonkeyPatch, body: str) -> None:
    """在临时包中加入下一版脚本，按包文件边界验证升级，不 mock 平台的迁移函数。"""
    directory = root / "package" / "migrations"
    source = migration_config().get_main_option("script_location")
    assert source is not None
    shutil.copytree(source, directory)
    script = (
        "from alembic import op\nimport sqlalchemy as sa\nrevision = '0003_test'\ndown_revision = '0002_accounts_sessions'\n\ndef upgrade():\n"
        + textwrap.indent(body, "    ")
        + "\n"
    )
    (directory / "versions" / "v0003_test.py").write_text(script)
    patch.setattr("rdp.infra.db.migration.__file__", str(directory.parent / "migration.py"))


def test_config(tmp_path: Path) -> None:
    """验证契约：migration_config 返回独立编程 Config，包内绝对 script_location，复用指定 connection。"""
    engine = create_database_engine(tmp_path / "db")
    try:
        with engine.connect() as connection:
            config = migration_config(connection)
            assert config.attributes["connection"] is connection
            location = config.get_main_option("script_location")
            assert location is not None and Path(location).is_absolute()
            assert (
                ScriptDirectory.from_config(config).get_current_head() == "0002_accounts_sessions"
            )
    finally:
        engine.dispose()


def test_config_none(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """验证契约：migration_config(None) 可读取脚本图，不打开数据库；从其他 cwd 运行不依赖 ini/pyproject。"""
    monkeypatch.chdir(tmp_path)
    first, second = migration_config(), migration_config()
    assert first is not second
    assert "connection" not in first.attributes
    assert ScriptDirectory.from_config(first).get_current_head() == "0002_accounts_sessions"
    assert not list(tmp_path.iterdir())


def test_config_invalid(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """验证契约：包目录缺失、脚本图损坏、多 head 给 DefectError，不猜版本。"""
    monkeypatch.setattr("rdp.infra.db.migration.__file__", str(tmp_path / "migration.py"))
    with pytest.raises(DefectError):
        migration_config()


def test_version_current(tmp_path: Path) -> None:
    """验证契约：check_database_version 仅恰等于唯一 head 时通过，不写数据、不建版本表。"""
    paths = _paths(tmp_path)
    migrate(paths, now=datetime(2026, 10, 24, tzinfo=UTC))
    before = paths.database.read_bytes()
    assert check_database_version(paths.database) is None
    assert paths.database.read_bytes() == before


def test_version_absent(tmp_path: Path) -> None:
    """验证契约：库文件不存在给 InputError 且不创建文件，诊断含 database/current/head 和先运行 migrate。"""
    path = tmp_path / "absent"
    with pytest.raises(InputError) as caught:
        check_database_version(path)
    assert "先运行 migrate" in caught.value.diagnostics[0].next_step
    assert not path.exists()


def test_version_unversioned(tmp_path: Path) -> None:
    """验证契约：无版本表或空版本表给 InputError，提示先运行 migrate，不自动升级。"""
    path = tmp_path / "db"
    with sqlite_connection(path) as connection:
        connection.execute("CREATE TABLE alembic_version (version_num TEXT)")
    with pytest.raises(InputError):
        check_database_version(path)


def test_version_behind(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """验证契约：祖先版本给 InputError，实际/期望/拒绝启动/先运行 migrate 都在诊断中。"""
    paths = _paths(tmp_path / "state")
    migrate(paths, now=datetime(2026, 10, 24, tzinfo=UTC))
    _future_package(tmp_path, monkeypatch, "pass")
    with pytest.raises(InputError) as caught:
        check_database_version(paths.database)
    assert "先运行 migrate" in caught.value.diagnostics[0].next_step


def test_version_unknown(tmp_path: Path) -> None:
    """验证契约：未知或代码降级后的版本给 InputError，不按字符串排序，提示匹配代码再先运行 migrate。"""
    paths = _paths(tmp_path)
    migrate(paths, now=datetime(2026, 10, 24, tzinfo=UTC))
    with sqlite_connection(paths.database) as connection:
        connection.execute("UPDATE alembic_version SET version_num='9999_future'")
    with pytest.raises(InputError) as caught:
        check_database_version(paths.database)
    assert "匹配" in caught.value.diagnostics[0].next_step


def test_version_multiple(tmp_path: Path) -> None:
    """验证契约：多个版本或分叉版本给 InputError，拒绝自动修复。"""
    path = tmp_path / "db"
    with sqlite_connection(path) as connection:
        connection.execute("CREATE TABLE alembic_version (version_num TEXT)")
        connection.executemany("INSERT INTO alembic_version VALUES (?)", [("a",), ("b",)])
    with pytest.raises(InputError):
        check_database_version(path)


def test_version_corrupt(tmp_path: Path) -> None:
    """验证契约：损坏库给 InputError，提示核实备份，不把 migrate 宣称为修复工具。"""
    path = tmp_path / "db"
    path.write_bytes(b"damaged" * 100)
    with pytest.raises(InputError):
        check_database_version(path)


def test_version_busy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """验证契约：版本读取 BUSY/LOCKED 给 ConflictError。"""
    path = tmp_path / "db"
    path.touch()

    def fail(*args: Any, **kwargs: Any) -> Any:
        error = sqlite3.OperationalError("锁冲突")
        error.sqlite_errorcode = sqlite3.SQLITE_BUSY
        raise error

    monkeypatch.setattr(sqlite3, "connect", fail)
    with pytest.raises(ConflictError):
        check_database_version(path)


def test_version_external(tmp_path: Path) -> None:
    """验证契约：版本读取权限/I/O 给 ExternalError，不改 journal_mode 或持久数据。"""
    target = tmp_path / "target"
    target.touch()
    path = tmp_path / "link"
    path.symlink_to(target)
    with pytest.raises(ExternalError):
        check_database_version(path)
    assert target.read_bytes() == b""


def test_version_defect(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """验证契约：版本读取 SQL 编程错误或脚本图多 head 给 DefectError。"""
    paths = _paths(tmp_path / "state")
    migrate(paths, now=datetime(2026, 10, 24, tzinfo=UTC))
    _future_package(tmp_path, monkeypatch, "pass")
    location = migration_config().get_main_option("script_location")
    assert location is not None
    directory = Path(location)
    (directory / "versions" / "branch.py").write_text("revision='branch'\ndown_revision=None\n")
    with pytest.raises(DefectError):
        check_database_version(paths.database)


def test_migrate_new(tmp_path: Path) -> None:
    """验证契约：验收 5：不存在数据库算待迁移，migrate 建首版报错表和版本表，不备份不存在的空库。"""
    paths = _paths(tmp_path)
    result = migrate(paths, now=datetime(2026, 10, 24, tzinfo=UTC))
    assert result.changed is True
    assert result.previous_revision is None
    assert result.current_revision == "0002_accounts_sessions"
    assert result.backup is None
    with sqlite_connection(paths.database) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (
            "0002_accounts_sessions",
        )
        assert connection.execute("SELECT count(*) FROM error_reports").fetchone() == (0,)


def test_migrate_empty(tmp_path: Path) -> None:
    """验证契约：已有空文件或无业务表空库升级前备份，版本标签 base，previous_revision=None。"""
    paths = _paths(tmp_path)
    paths.database.touch()
    result = migrate(paths, now=datetime(2026, 10, 24, tzinfo=UTC))
    assert result.backup is not None and result.backup.exists()
    assert "-base-" in result.backup.name
    with sqlite_connection(result.backup) as connection:
        assert connection.execute("PRAGMA quick_check").fetchone() == ("ok",)
        assert connection.execute(
            "SELECT count(*) FROM sqlite_master WHERE type='table'"
        ).fetchone() == (0,)


def test_migrate_existing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """验证契约：合法祖先版本升级到 head，changed=True、previous/current/backup 返回正确。"""
    paths = _paths(tmp_path / "state")
    migrate(paths, now=datetime(2026, 10, 24, tzinfo=UTC))
    _future_package(
        tmp_path, monkeypatch, 'op.create_table("upgrade_probe", sa.Column("value", sa.Integer()))'
    )
    result = migrate(paths, now=datetime(2026, 10, 25, tzinfo=UTC))
    assert (
        result.previous_revision == "0002_accounts_sessions"
        and result.current_revision == "0003_test"
    )
    assert result.changed is True and result.backup is not None
    assert check_database_version(paths.database) is None


def test_migrate_noop(tmp_path: Path) -> None:
    """验证契约：验收 5/6：相同 head 二次 migrate changed=False、backup=None，文件内容/mtime/目录清单都不变。"""
    for retained_wal in (False, True):
        paths = _paths(tmp_path / str(retained_wal))
        migrate(paths, now=datetime(2026, 10, 24, tzinfo=UTC))
        if retained_wal:
            with sqlite_connection(paths.database) as connection:
                connection.setconfig(sqlite3.SQLITE_DBCONFIG_NO_CKPT_ON_CLOSE, True)
                connection.execute(
                    "INSERT INTO error_reports VALUES ('7','2026-10-01T00:00:00.000000Z','defect','摘要','安全报告','job')"
                )
        before = {
            str(path.relative_to(paths.root)): (
                path.read_bytes() if path.is_file() else None,
                path.stat().st_mtime_ns,
            )
            for path in paths.root.rglob("*")
        }
        root_mtime = paths.root.stat().st_mtime_ns
        result = migrate(paths, now=datetime(2026, 10, 25, tzinfo=UTC))
        assert result.changed is False and result.backup is None
        after = {
            str(path.relative_to(paths.root)): (
                path.read_bytes() if path.is_file() else None,
                path.stat().st_mtime_ns,
            )
            for path in paths.root.rglob("*")
        }
        assert before == after
        assert paths.root.stat().st_mtime_ns == root_mtime


def test_compare_metadata(tmp_path: Path) -> None:
    """验证契约：验收 5：对迁移后 tmp_path 库用 Alembic compare_metadata 与 models.metadata 比较，差异为空。"""
    paths = _paths(tmp_path)
    migrate(paths, now=datetime(2026, 10, 24, tzinfo=UTC))
    engine = create_database_engine(paths.database)
    try:
        with engine.connect() as connection:
            assert (
                compare_metadata(
                    MigrationContext.configure(connection, opts={"compare_type": True}), metadata
                )
                == []
            )
    finally:
        engine.dispose()


def test_table_sql_matches_metadata(tmp_path: Path) -> None:
    """验证首版迁移与模型的完整建表 SQL 一致，涵盖 compare_metadata 未比较的 CHECK。"""
    paths = _paths(tmp_path / "migrated")
    migrate(paths, now=datetime(2026, 10, 24, tzinfo=UTC))
    model_database = tmp_path / "model.sqlite3"
    engine = create_database_engine(model_database)
    try:
        metadata.create_all(engine)
    finally:
        engine.dispose()
    statements: list[str] = []
    for database in (paths.database, model_database):
        with sqlite_connection(database) as connection:
            row = connection.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name='error_reports'"
            ).fetchone()
        assert row is not None and isinstance(row[0], str)
        statements.append(" ".join(row[0].split()))
    assert statements[0] == statements[1]


def test_backup_contents(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """验证契约：验收 6：备份通过 sqlite3 打开且 quick_check 成功，升级前数据/版本一致，包含已提交 WAL 内容。"""
    paths = _paths(tmp_path / "state")
    migrate(paths, now=datetime(2026, 10, 24, tzinfo=UTC))
    with sqlite_connection(paths.database) as connection:
        connection.setconfig(sqlite3.SQLITE_DBCONFIG_NO_CKPT_ON_CLOSE, True)
        connection.execute(
            "INSERT INTO error_reports VALUES ('1','2026-10-01T00:00:00.123456Z','defect','摘要','TypeError: example','job')"
        )
    assert paths.database.with_name(paths.database.name + "-wal").exists()
    _future_package(
        tmp_path, monkeypatch, 'op.create_table("upgrade_probe", sa.Column("value", sa.Integer()))'
    )
    result = migrate(paths, now=datetime(2026, 10, 25, tzinfo=UTC))
    assert result.backup is not None
    with sqlite_connection(result.backup) as backup:
        assert backup.execute("PRAGMA quick_check").fetchone() == ("ok",)
        assert backup.execute("SELECT report FROM error_reports WHERE error_id='1'").fetchone() == (
            "TypeError: example",
        )
        assert backup.execute("SELECT version_num FROM alembic_version").fetchone() == (
            "0002_accounts_sessions",
        )


def test_backup_before(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """验证契约：备份完成并原子发布后才执行任何升级 SQL；不直接复制 sqlite3/wal/shm 文件。"""
    paths = _paths(tmp_path / "state")
    migrate(paths, now=datetime(2026, 10, 24, tzinfo=UTC))
    body = "from pathlib import Path\nassert list(Path(op.get_bind().engine.url.database).parent.joinpath('backups').glob('*.sqlite3'))\nop.create_table('upgrade_probe', sa.Column('value', sa.Integer()))"
    _future_package(tmp_path, monkeypatch, body)
    assert migrate(paths, now=datetime(2026, 10, 25, tzinfo=UTC)).changed


def test_backup_filename(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """验证契约：注入非 UTC 时刻规范为 UTC 文件名，带升级前 revision；同一 now 的两次备份随机后缀不覆盖。"""
    paths = _paths(tmp_path / "state")
    migrate(paths, now=datetime(2026, 10, 24, tzinfo=UTC))
    # 下一版故意失败，让两次调用面对同一数据库 revision，且两份备份留在同一目录。
    _future_package(tmp_path, monkeypatch, 'raise RuntimeError("保留同一升级前版本")')
    moments = (
        datetime(2026, 10, 24, 10, 30, 40, 123456, tzinfo=timezone(timedelta(hours=8))),
        datetime(2026, 10, 23, 20, 30, 40, 123456, tzinfo=timezone(timedelta(hours=-6))),
    )
    backups: list[Path] = []
    for moment in moments:
        before = set((paths.root / "backups").glob("*.sqlite3"))
        with pytest.raises(DefectError):
            migrate(paths, now=moment)
        added = set((paths.root / "backups").glob("*.sqlite3")) - before
        assert len(added) == 1
        backup = added.pop()
        assert backup.name.startswith("rdp-before-20261024T023040123456Z-0002_accounts_sessions-")
        backups.append(backup)
    assert backups[0] != backups[1]
    assert all(path.is_file() for path in backups)
    assert len(list((paths.root / "backups").glob("*.sqlite3"))) == 2


def test_backup_filename_pattern(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """验证搬移约束：平台生成的备份名匹配，uuid 后缀大写或少一位不匹配。"""
    # 固定含字母的 uuid，避免随机后缀恰好全为数字，使大写拒绝用例失去区分度。
    identifier = UUID("12345678-9abc-4def-8abc-123456789abc")
    monkeypatch.setattr("rdp.infra.db.migration.uuid4", lambda: identifier)
    paths = _paths(tmp_path)
    paths.database.touch()
    result = migrate(paths, now=datetime(2026, 10, 25, tzinfo=UTC))
    assert result.backup is not None
    name = result.backup.name
    assert re.fullmatch(BACKUP_FILENAME_PATTERN, name) is not None
    assert (
        re.fullmatch(BACKUP_FILENAME_PATTERN, name.replace(identifier.hex, identifier.hex.upper()))
        is None
    )
    assert (
        re.fullmatch(BACKUP_FILENAME_PATTERN, name.replace(identifier.hex, identifier.hex[:-1]))
        is None
    )


def test_backup_permissions(tmp_path: Path) -> None:
    """验证契约：新 backups 精确 0700，完整/临时备份 0600，不依赖 umask、不更改已有目录权限。"""
    paths = _paths(tmp_path)
    paths.database.touch()
    result = migrate(paths, now=datetime(2026, 10, 24, tzinfo=UTC))
    assert (tmp_path / "backups").stat().st_mode & 0o777 == 0o700
    assert result.backup is not None and result.backup.stat().st_mode & 0o777 == 0o600


def test_backup_bad_directory(tmp_path: Path) -> None:
    """验证契约：backups 已有软链接、非目录或非 0700 给 ExternalError，拒绝升级、不擅自 chmod。"""
    paths = _paths(tmp_path)
    paths.database.touch()
    backups = tmp_path / "backups"
    backups.mkdir(mode=0o755)
    backups.chmod(0o755)
    with pytest.raises(ExternalError):
        migrate(paths, now=datetime(2026, 10, 24, tzinfo=UTC))
    assert backups.stat().st_mode & 0o777 == 0o755
    assert paths.database.read_bytes() == b""


def test_backup_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """验证契约：备份失败不开始升级，原库数据/版本不变，删除本次临时文件，允许留下新空目录。"""
    paths = _paths(tmp_path)
    paths.database.touch()

    def fail(*args: Any, **kwargs: Any) -> Any:
        raise OSError("磁盘满")

    monkeypatch.setattr("tempfile.mkstemp", fail)
    with pytest.raises(ExternalError):
        migrate(paths, now=datetime(2026, 10, 24, tzinfo=UTC))
    assert paths.database.read_bytes() == b""
    assert list((tmp_path / "backups").iterdir()) == []


def test_backup_partial(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """验证契约：临时文件清理失败留下可识别 .partial，ExternalError 标明阶段及路径，不删其他文件。"""
    paths = _paths(tmp_path)
    paths.database.touch()
    replace = Path.replace
    unlink = Path.unlink

    def fail_replace(self: Path, target: Any) -> Path:
        if self.suffix == ".partial":
            raise OSError("发布失败")
        return replace(self, target)

    def fail_unlink(self: Path, missing_ok: bool = False) -> None:
        if self.suffix == ".partial":
            raise OSError("清理失败")
        unlink(self, missing_ok=missing_ok)

    with monkeypatch.context() as patch:
        patch.setattr(Path, "replace", fail_replace)
        patch.setattr(Path, "unlink", fail_unlink)
        with pytest.raises(ExternalError) as caught:
            migrate(paths, now=datetime(2026, 10, 24, tzinfo=UTC))
    assert caught.value.diagnostics[0].stage == "清理临时备份"
    partials = list((tmp_path / "backups").glob("*.partial"))
    assert len(partials) == 1 and paths.database.read_bytes() == b""


def test_backup_deadline(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """验证契约：backup 分批 256 页，progress 用 monotonic 控制 5 秒预算，busy sleep 0.05 秒；超时 ExternalError 且不升级。"""
    paths = _paths(tmp_path)
    paths.database.touch()
    ticks = iter((0.0, 6.0, 7.0, 8.0))
    monkeypatch.setattr(time, "monotonic", lambda: next(ticks, 10.0))
    with pytest.raises(ExternalError):
        migrate(paths, now=datetime(2026, 10, 24, tzinfo=UTC))
    assert paths.database.read_bytes() == b""
    assert not list((tmp_path / "backups").iterdir())


def test_backup_rotation(tmp_path: Path) -> None:
    """验证契约：升级成功只按文件名 UTC/完整名字保留最新 5 份，不看 mtime；只删平台命名普通文件。"""
    paths = _paths(tmp_path)
    directory = tmp_path / "backups"
    directory.mkdir(mode=0o700)
    for day in range(1, 7):
        (
            directory
            / f"rdp-before-202610{day:02d}T000000000000Z-base-123456789abc4def8abc123456789abc.sqlite3"
        ).touch()
    paths.database.touch()
    migrate(paths, now=datetime(2026, 10, 24, tzinfo=UTC))
    names = sorted(path.name for path in directory.iterdir())
    assert len(names) == 5
    assert not any("20261001T" in name or "20261002T" in name for name in names)


def test_backup_foreign(tmp_path: Path) -> None:
    """验证契约：保留人工备份、未知名字、符号链接及 .partial，不加载所有报告内容。"""
    paths = _paths(tmp_path)
    directory = tmp_path / "backups"
    directory.mkdir(mode=0o700)
    platform: list[Path] = []
    for day in range(1, 7):
        path = (
            directory
            / f"rdp-before-202610{day:02d}T000000000000Z-base-123456789abc4def8abc123456789abc.sqlite3"
        )
        path.write_text(f"平台备份 {day}")
        platform.append(path)
    protected = {
        "manual.sqlite3": "人工备份",
        "incomplete.partial": "未完成",
        "other.txt": "其他文件",
    }
    for name, content in protected.items():
        (directory / name).write_text(content)
    link = (
        directory
        / "rdp-before-20200101T000000000000Z-base-123456789abc4def8abc123456789abc.sqlite3"
    )
    link.symlink_to(directory / "manual.sqlite3")
    paths.database.touch()
    result = migrate(paths, now=datetime(2026, 10, 24, tzinfo=UTC))
    assert result.backup is not None
    assert not platform[0].exists() and not platform[1].exists()
    for day, path in enumerate(platform[2:], start=3):
        assert path.read_text() == f"平台备份 {day}"
    assert link.is_symlink() and link.readlink() == directory / "manual.sqlite3"
    for name, content in protected.items():
        assert (directory / name).read_text() == content
    assert {path.name for path in directory.iterdir()} == {
        *(path.name for path in platform[2:]),
        result.backup.name,
        link.name,
        *protected,
    }


def test_rotation_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """验证契约：清理旧备份失败抛 ExternalError，明确升级已提交且备份可能超过 5 份，不声称回滚。"""
    paths = _paths(tmp_path)
    directory = tmp_path / "backups"
    directory.mkdir(mode=0o700)
    for day in range(1, 7):
        (
            directory
            / f"rdp-before-202610{day:02d}T000000000000Z-base-123456789abc4def8abc123456789abc.sqlite3"
        ).touch()
    paths.database.touch()
    unlink = Path.unlink

    def fail(self: Path, missing_ok: bool = False) -> None:
        if self.suffix == ".sqlite3":
            raise PermissionError("删除被拒绝")
        unlink(self, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", fail)
    with pytest.raises(ExternalError) as caught:
        migrate(paths, now=datetime(2026, 10, 24, tzinfo=UTC))
    assert caught.value.diagnostics[0].consequence == "升级成功，保留清理失败"
    assert check_database_version(paths.database) is None


def test_migrate_invalid_time(tmp_path: Path) -> None:
    """验证契约：naive/UTC 溢出 now 给 InputError，不创建备份或执行迁移。"""
    paths = _paths(tmp_path)
    with pytest.raises(InputError):
        migrate(paths, now=datetime(2026, 10, 24, tzinfo=UTC).replace(tzinfo=None))
    assert not paths.database.exists()


def test_migrate_invalid_layout(tmp_path: Path) -> None:
    """验证契约：非法/不可信布局给 InputError，拒绝写状态目录之外。"""
    paths = _paths(tmp_path / "state")
    wrong = StatePaths(
        paths.root, tmp_path / "outside.sqlite3", paths.logs, paths.job_logs, paths.worker_lock
    )
    with pytest.raises(InputError):
        migrate(wrong, now=datetime(2026, 10, 24, tzinfo=UTC))


def test_migrate_unknown(tmp_path: Path) -> None:
    """验证契约：未知/领先/分叉/多版本/损坏库拒绝升级，不备份或覆盖数据。"""
    paths = _paths(tmp_path)
    migrate(paths, now=datetime(2026, 10, 24, tzinfo=UTC))
    with sqlite_connection(paths.database) as connection:
        connection.execute("UPDATE alembic_version SET version_num='9999_future'")
    before = paths.database.read_bytes()
    with pytest.raises(InputError):
        migrate(paths, now=datetime(2026, 10, 24, tzinfo=UTC))
    assert paths.database.read_bytes() == before


def test_migrate_unversioned_data(tmp_path: Path) -> None:
    """验证契约：无版本但有既有业务表的数据库给 InputError，不 stamp、不覆盖表。"""
    paths = _paths(tmp_path)
    with sqlite_connection(paths.database) as connection:
        connection.execute("CREATE TABLE existing (value INTEGER)")
    before = paths.database.read_bytes()
    with pytest.raises(InputError):
        migrate(paths, now=datetime(2026, 10, 24, tzinfo=UTC))
    assert paths.database.read_bytes() == before


def test_migrate_parallel(tmp_path: Path) -> None:
    """验证契约：两个 spawn migrate 用 root 目录 fd flock 非阻塞排他，第二个立即 ConflictError；不创建/删除锁 inode。"""
    paths = _paths(tmp_path)
    paths.database.touch()
    context = multiprocessing.get_context("spawn")
    ready, release, result = context.Event(), context.Event(), context.Queue()
    first = context.Process(
        target=_migrate_child, args=(str(tmp_path), ready, release, result, True)
    )
    second = context.Process(
        target=_migrate_child, args=(str(tmp_path), ready, release, result, False)
    )
    started: list[Any] = []
    try:
        first.start()
        started.append(first)
        assert ready.wait(5)
        before = time.monotonic()
        second.start()
        started.append(second)
        assert result.get(timeout=3) == "conflict"
        assert time.monotonic() - before < 3
        release.set()
        assert result.get(timeout=5) == "ok"
    finally:
        release.set()
        _reap(started)
        result.close()
        result.join_thread()


def test_migrate_busy(tmp_path: Path) -> None:
    """验证契约：迁移 BEGIN 等写锁约 5 秒后 ConflictError，已发布备份保留，schema 不变。"""
    paths = _paths(tmp_path)
    paths.database.touch()
    holders: list[sqlite3.Connection] = []

    def hold(*args: Any, **kwargs: Any) -> None:
        if args[2] == "BEGIN IMMEDIATE" and not holders:
            connection = sqlite3.connect(paths.database)
            connection.execute("BEGIN IMMEDIATE")
            holders.append(connection)

    event.listen(Engine, "before_cursor_execute", hold)
    try:
        started = time.monotonic()
        with pytest.raises(ConflictError):
            migrate(paths, now=datetime(2026, 10, 24, tzinfo=UTC))
        assert 4 <= time.monotonic() - started <= 10
        assert len(list((paths.root / "backups").glob("*.sqlite3"))) == 1
    finally:
        event.remove(Engine, "before_cursor_execute", hold)
        for connection in holders:
            connection.rollback()
            connection.close()


def test_migrate_upgrade_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """验证契约：升级脚本中途失败回滚全部 DDL/数据/版本，保留升级前完整备份并释放连接和锁。"""
    paths = _paths(tmp_path / "state")
    migrate(paths, now=datetime(2026, 10, 24, tzinfo=UTC))
    _future_package(
        tmp_path,
        monkeypatch,
        'op.create_table("partial", sa.Column("value", sa.Integer()))\nraise RuntimeError("脚本故障")',
    )
    with pytest.raises(DefectError):
        migrate(paths, now=datetime(2026, 10, 25, tzinfo=UTC))
    with sqlite_connection(paths.database) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (
            "0002_accounts_sessions",
        )
        assert connection.execute(
            "SELECT count(*) FROM sqlite_master WHERE name='partial'"
        ).fetchone() == (0,)
    assert len(list((paths.root / "backups").glob("*.sqlite3"))) == 1


def test_migrate_first_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """验证契约：首次升级失败可留无业务表空库及 SQLite 辅助文件，不留假 head。"""
    paths = _paths(tmp_path / "state")
    _future_package(tmp_path, monkeypatch, 'raise RuntimeError("脚本故障")')
    with pytest.raises(DefectError):
        migrate(paths, now=datetime(2026, 10, 24, tzinfo=UTC))
    with sqlite_connection(paths.database) as connection:
        assert connection.execute(
            "SELECT count(*) FROM sqlite_master WHERE type='table'"
        ).fetchone() == (0,)


def test_migrate_rollback_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """验证契约：回滚失败诊断标明数据库结果未知及人工恢复步骤，不自动覆盖原库。"""
    paths = _paths(tmp_path / "state")
    migrate(paths, now=datetime(2026, 10, 24, tzinfo=UTC))
    _future_package(tmp_path, monkeypatch, 'raise RuntimeError("脚本故障")')

    def fail(*args: Any, **kwargs: Any) -> None:
        raise OSError("回滚故障")

    monkeypatch.setattr("sqlalchemy.orm.Session.rollback", fail)
    with pytest.raises(DefectError) as caught:
        migrate(paths, now=datetime(2026, 10, 24, tzinfo=UTC))
    assert "结果未知" in str(getattr(caught.value.__cause__, "__notes__", []))
    assert len(list((paths.root / "backups").glob("*.sqlite3"))) == 1


def test_migrate_io(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """验证契约：升级权限/磁盘满/I/O 为 ExternalError；自有连接和引擎最终关闭。"""
    paths = _paths(tmp_path)

    def fail(*args: Any, **kwargs: Any) -> Any:
        error = sqlite3.OperationalError("磁盘满")
        error.sqlite_errorcode = sqlite3.SQLITE_FULL
        raise error

    monkeypatch.setattr("sqlite3.dbapi2.connect", fail)
    with pytest.raises(ExternalError):
        migrate(paths, now=datetime(2026, 10, 24, tzinfo=UTC))


def test_migrate_defect(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """验证契约：脚本/版本图程序错误给 DefectError，失败无全局日志配置改变。"""
    paths = _paths(tmp_path / "state")
    _future_package(tmp_path, monkeypatch, 'raise ValueError("迁移缺陷")')
    with pytest.raises(DefectError):
        migrate(paths, now=datetime(2026, 10, 24, tzinfo=UTC))


def test_env_connection(tmp_path: Path) -> None:
    """验证契约：env.run_migrations 复用注入连接/共享 metadata，render_as_batch/compare_type/transactional_ddl 均 True。"""
    engine = create_database_engine(tmp_path / "db")
    try:
        with engine.begin() as connection:
            command.upgrade(migration_config(connection), "head")
            assert (
                connection.exec_driver_sql("SELECT version_num FROM alembic_version").scalar_one()
                == "0002_accounts_sessions"
            )
            assert compare_metadata(MigrationContext.configure(connection), metadata) == []
    finally:
        engine.dispose()


def test_env_invalid(tmp_path: Path) -> None:
    """验证契约：env 缺连接或离线模式给 DefectError，不读 ini 或猜 URL。"""
    environment = importlib.import_module("rdp.infra.db.migrations.env")
    with pytest.raises(DefectError):
        environment.run_migrations()
    assert not list(tmp_path.iterdir())


def test_env_propagation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """验证契约：env 的脚本/配置/SQL 异常传到 migrate 分类并回滚，不私自提交。"""
    paths = _paths(tmp_path / "state")
    migrate(paths, now=datetime(2026, 10, 24, tzinfo=UTC))
    _future_package(tmp_path, monkeypatch, 'raise RuntimeError("脚本原始异常")')
    engine = create_database_engine(paths.database)
    try:
        with pytest.raises(RuntimeError, match="脚本原始异常"), engine.begin() as connection:
            command.upgrade(migration_config(connection), "head")
    finally:
        engine.dispose()


def test_env_logging(tmp_path: Path) -> None:
    """验证契约：导入和执行 env 均不调用 logging.config.fileConfig，不安装或改变全局 handler。"""
    root = logging.getLogger()
    before = (tuple(root.handlers), root.level)
    environment = importlib.import_module("rdp.infra.db.migrations.env")
    importlib.reload(environment)
    paths = _paths(tmp_path)
    migrate(paths, now=datetime(2026, 10, 24, tzinfo=UTC))
    assert (tuple(root.handlers), root.level) == before


def test_upgrade(tmp_path: Path) -> None:
    """验证契约：upgrade 只建报错表及命名索引；版本表由 Alembic 管理，不建账号/作业/日志表。"""
    engine = create_database_engine(tmp_path / "db")
    try:
        with engine.begin() as connection:
            with Operations.context(MigrationContext.configure(connection)):
                assert v0001_error_reports.upgrade() is None
            assert inspect(connection).get_table_names() == ["error_reports"]
            assert {item["name"] for item in inspect(connection).get_indexes("error_reports")} == {
                "ix_error_reports_occurred_at"
            }
    finally:
        engine.dispose()


def test_upgrade_failure(tmp_path: Path) -> None:
    """验证契约：upgrade SQLAlchemyError 交 migrate 转换，显式事务保证 DDL 回滚。"""
    engine = create_database_engine(tmp_path / "db")
    try:
        with (
            pytest.raises(SQLAlchemyError),
            engine.begin() as connection,
            Operations.context(MigrationContext.configure(connection)),
        ):
            v0001_error_reports.upgrade()
            v0001_error_reports.upgrade()
        with engine.connect() as connection:
            assert inspect(connection).get_table_names() == []
    finally:
        engine.dispose()


def test_downgrade(tmp_path: Path) -> None:
    """验证契约：downgrade 任意调用立即 InputError，诊断写 F1/未修改/人工恢复，不执行 SQL。"""
    with pytest.raises(InputError) as caught:
        v0001_error_reports.downgrade()
    assert "备份" in caught.value.diagnostics[0].next_step
    assert not list(tmp_path.iterdir())


def test_installed_package(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """验证契约：在临时包布局和其他 cwd 运行迁移，无仓库 pyproject/alembic.ini/script.py.mako 仍可定位脚本。"""
    directory = tmp_path / "installed"
    directory.mkdir()
    _future_package(directory, monkeypatch, "pass")
    monkeypatch.chdir(tmp_path)
    paths = _paths(tmp_path / "state")
    assert migrate(paths, now=datetime(2026, 10, 24, tzinfo=UTC)).current_revision == "0003_test"
    assert not (directory / "pyproject.toml").exists()


def test_bounded_backup_scan(tmp_path: Path) -> None:
    """验证契约：备份目录迭代扫描、最多 5 个候选，不随文件数全量加载，删除范围不扩大。"""
    paths = _paths(tmp_path)
    directory = tmp_path / "backups"
    directory.mkdir(mode=0o700)
    for number in range(100):
        (
            directory
            / f"rdp-before-20261001T000000{number:06d}Z-base-123456789abc4def8abc123456789abc.sqlite3"
        ).touch()
    paths.database.touch()
    migrate(paths, now=datetime(2026, 10, 24, tzinfo=UTC))
    assert len(list(directory.glob("*.sqlite3"))) == 5
