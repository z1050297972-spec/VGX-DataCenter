"""基础层向前迁移和版本闸门（05 F1/F2），不启动服务、不改日志、不自动恢复备份。

用 Alembic 的 Config/ScriptDirectory/MigrationContext 解析版本图和执行升级，
sqlite3.Connection.backup 复制一致快照，fcntl.flock 串行化同状态目录的迁移。
备份目录在此处从 StatePaths.root 计算，避免扩大第 03 张 StatePaths/initialize_state 的职责。
"""

import fcntl
import heapq
import os
import re
import sqlite3
import tempfile
import time
from collections.abc import Generator, Iterator
from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import cast
from uuid import uuid4

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import Connection

from rdp.infra.db._constants import BACKUP_FILENAME_PATTERN as BACKUP_FILENAME_PATTERN
from rdp.infra.db._constants import BACKUPS_DIRECTORY_NAME as BACKUPS_DIRECTORY_NAME
from rdp.infra.db._permissions import secure_database_files
from rdp.infra.db.connection import (
    BUSY_TIMEOUT_MS,
    create_database_engine,
    session_scope,
    translate_database_error,
)
from rdp.infra.db.utc import format_utc_text
from rdp.infra.db.validation import invalid_field
from rdp.infra.diagnostics import (
    ConflictError,
    DefectError,
    Diagnostic,
    DiagnosticCategory,
    DiagnosticLevel,
    DiagnosticObject,
    ExternalError,
    InputError,
)
from rdp.infra.state import DATABASE_FILENAME, STATE_DIRECTORY_MODE, StatePaths
from rdp.infra.timeutil import ensure_utc

# F1：只留最新 5 份平台自动升级备份，单位份；不清理人工备份和不完整产物。
MIGRATION_BACKUP_LIMIT = 5
# 备份 progress 回调以 monotonic 检查预算，防止 backup 在繁忙源库上无限等待；单位秒。
BACKUP_TIMEOUT_S = 5.0
# 本票的备份预算：分批页数限制 progress 检查间隔，单位 SQLite 页，不改变页大小。
BACKUP_BATCH_PAGES = 256
# sqlite3.backup 对 BUSY/LOCKED 的内建等待间隔，单位秒；由总预算限制，不无限重试。
BACKUP_RETRY_SLEEP_S = 0.05


@dataclass(frozen=True)
class MigrationResult:
    """一次运维升级的不可变结果，不表示备份可被自动恢复。

    Attributes:
        previous_revision: 升级前唯一 Alembic revision，无单位；可空，None 表示未迁移；无默认。
        current_revision: 包内唯一 head，无单位、非空、不可空、无默认。
        changed: 是否执行迁移，无单位、布尔、不可空、无默认；无待执行版本时 False。
        backup: 本次升级前完整备份的绝对 Path，无单位、无默认；可空，未升级或源文件不存在为 None。
    """

    previous_revision: str | None
    current_revision: str
    changed: bool
    backup: Path | None


def migration_config(connection: Connection | None = None) -> Config:
    """构造仅依赖已安装包内容的 Alembic 配置。

    Args:
        connection: migrate 已持有事务的连接，无单位；默认 None，仅供读取脚本图或开发工具使用。

    Returns:
        新 Config，不读取 ini/pyproject；script_location 为本包 migrations 的绝对目录，
        connection 非空时放入 attributes，env.py 复用它而不再建引擎；版本图要求单 head。
        包内文件通过模块位置定位，运行时不依赖 cwd 或仓库文件，默认不提供离线升级模式。

    Raises:
        DefectError: 包内迁移目录缺失、脚本图损坏或多个 head；提示修复安装，禁止猜版本。

    Side Effects:
        无（只读包文件）；不创建数据库、不配置 logger，不导入并执行业务入口。

    Time Semantics:
        同步构造，无时钟或重试。
    """
    config = Config()
    config.set_main_option(
        "script_location", str(Path(__file__).parent / "migrations").replace("%", "%%")
    )
    if connection is not None:
        config.attributes["connection"] = connection
    try:
        script = ScriptDirectory.from_config(config)
        if len(script.get_heads()) != 1:
            failure = ValueError("包内迁移必须恰好有一个 head")
            raise failure
        tuple(script.walk_revisions())
    except Exception as error:
        raise DefectError() from error
    return config


def check_database_version(database: Path) -> None:
    """只读比较数据库版本和包内 head，阻止不兼容代码启动。

    Args:
        database: StatePaths.database 的绝对本地文件路径，无单位，不跟随软链接。

    Returns:
        无；仅当数据库恰好有一个版本且等于包内唯一 head 时通过。

    Raises:
        InputError: 文件不存在、无 alembic_version、版本表为空或版本是 head 的祖先；
            诊断含 database、current/head、规则、拒绝启动的后果，下一步明确“先运行 migrate”。
            版本比代码新、未知 revision、多个版本或不在祖先链时同样拒绝，提示
            “先匹配数据库对应的代码版本，再先运行 migrate 检查；禁止降级，必要时人工恢复备份”；
            不按字符串大小猜版本先后，未知版本不能安全分辨更新代码还是其他分支。
            数据损坏也为 InputError，提示先核实库/备份，migrate 不自动修复损坏。
        ConflictError: 读取版本遇到 SQLITE_BUSY/LOCKED。
        ExternalError: 文件权限或 I/O 故障。
        DefectError: 代码迁移图损坏、多 head 或读取版本的 SQL 编程错误。

    Side Effects:
        无（sqlite3 URI mode=ro 读取，不通过会设 WAL 的业务引擎，不创建数据库或版本表，
        不设置 PRAGMA journal_mode、不升级、不写日志）；SQLite 必要时可能建立共享内存协调，
        不改变持久业务数据。调用方不应把这种只读检查当成并发升级的锁。

    Time Semantics:
        启动前同步检查，锁等待最多约 BUSY_TIMEOUT_MS；运维在服务停止时升级，
        检查完成后运行期间不支持外部修改 schema。
    """
    config = migration_config()
    head = cast(str, ScriptDirectory.from_config(config).get_current_head())
    current, _ = _read_revision(database)
    if current != head:
        problem = _version_problem(database, current, head)
        raise problem


def _version_problem(database: Path, current: str | None, head: str) -> InputError:
    """版本不匹配是输入或数据问题；提示先匹配代码再迁移，不把它误报成锁冲突。"""
    return InputError(
        (
            Diagnostic(
                level=DiagnosticLevel.ERROR,
                category=DiagnosticCategory.INPUT,
                stage="数据库版本",
                source="平台",
                objects=(
                    DiagnosticObject(key="database", value=str(database)),
                    DiagnosticObject(key="current", value=current or "base"),
                    DiagnosticObject(key="head", value=head),
                ),
                rule="数据库版本必须与代码版本兼容",
                actual="数据库缺失、未迁移或版本不匹配",
                expected=head,
                consequence="拒绝启动或迁移，未改变业务数据",
                next_step="先运行 migrate；未知或领先版本先匹配对应代码，再先运行 migrate 检查；禁止降级，必要时人工恢复备份",
            ),
        )
    )


def _read_revision(database: Path, *, migration: bool = False) -> tuple[str | None, bool]:
    """只读读取至多两个版本和是否存在业务表，不创建库或更改 journal_mode。"""
    try:
        if database.is_symlink():
            raise OSError("数据库路径不能为软链接")
        if not database.exists():
            return None, False
        has_wal = database.with_name(database.name + "-wal").exists()
        mode = "rw" if migration and has_wal else "ro"
        options = f"?mode={mode}" + ("&immutable=1" if migration and not has_wal else "")
        with closing(
            sqlite3.connect(database.as_uri() + options, uri=True, timeout=BUSY_TIMEOUT_MS / 1000)
        ) as connection:
            if migration and has_wal:
                # 运维已停服务：只执行 SELECT，用独占连接的私有 WAL 索引避免新建 SHM。
                # 禁止关闭时 checkpoint，才能保持无待执行迁移时主库和既有 WAL 的字节不变。
                connection.setconfig(sqlite3.SQLITE_DBCONFIG_NO_CKPT_ON_CLOSE, True)
                connection.execute("PRAGMA locking_mode=EXCLUSIVE")
            has_version = connection.execute(
                "SELECT count(*) FROM sqlite_master WHERE type='table' AND name='alembic_version'"
            ).fetchone()[0]
            business = (
                connection.execute(
                    "SELECT count(*) FROM sqlite_master WHERE type='table' AND name != 'alembic_version' AND name NOT LIKE 'sqlite_%'"
                ).fetchone()[0]
                > 0
            )
            rows = (
                connection.execute("SELECT version_num FROM alembic_version LIMIT 2").fetchall()
                if has_version
                else []
            )
            if len(rows) > 1:
                problem = _version_problem(database, "多个版本", "唯一 head")
                raise problem
            return (rows[0][0] if rows else None), business
    except (sqlite3.Error, OSError) as error:
        problem = translate_database_error(error, database=database, operation="读取版本")
        raise problem from error


def migrate(paths: StatePaths, *, now: datetime) -> MigrationResult:
    """在安全备份后把状态数据库升级到包内最新版本。

    Args:
        paths: 第 03 张 state_paths 的布局；root 已初始化、可读写且可信，database 在 root 内，
            本地磁盘，不访问导航层或 NAS；运维调用前必须停止 Web/worker，禁止服务中改 schema。
        now: 注入的 aware 墙钟时刻，内部 ensure_utc，微秒精度；测试固定，不能为 naive。

    Returns:
        MigrationResult；相同 head 返回 changed=False、backup=None，除收紧文件权限外不改数据库/目录/备份。
        无数据库文件属于有待执行迁移，建新库但不备份不存在的空库；已有空文件/无版本库
        先备份，previous_revision=None，备份版本标签 base；绝不对已有未知表执行 stamp。
        有合法祖先版本时升级全部待执行脚本；第一版只建 error_reports 和 Alembic 版本表。

    Raises:
        InputError: now 非法、布局非法、数据库版本未知/领先/分叉、多版本、损坏或非空无版本库；
            后者只允许完全无业务表的空库初始化，不覆盖既有表。诊断给出拒绝和修复步骤。
        ConflictError: root 目录 fd 上的 flock(LOCK_EX|LOCK_NB) 被另一个 migrate 持有，
            立即拒绝；或数据库锁等待 BUSY_TIMEOUT_MS（5000 毫秒）超时。目录锁不创建锁文件，不删除锁 inode。
        ExternalError: 备份、权限、磁盘、I/O 或清理旧备份失败；backup progress 超过
            BACKUP_TIMEOUT_S 也拒绝升级。保留可定位的阶段及路径，避免输出 SQL/报告内容。
        DefectError: 迁移图错误、升级脚本或其他程序错误；拒绝降级。

    Side Effects:
        先锁 root，再只读核对版本；先收紧已有数据库、WAL/SHM及平台完整备份到0600；无待执行脚本立即释放锁，不改文件内容。
        待升级时创建 root/backups（新目录精确 STATE_DIRECTORY_MODE=0700），
        已有 backups 不能为软链接且权限必须为 0700，否则 ExternalError 拒绝，不擅自 chmod。
        已有数据库先用 sqlite3.Connection.backup 分批复制到同目录 0600 临时文件，
        关闭并确认成功后原子发布为 rdp-before-YYYYMMDDTHHMMSSffffffZ-<revision>-<uuid4hex>.sqlite3；
        revision 只允许 ASCII 字母、数字、下划线，base 表示无版本；随机后缀防时钟重复覆盖。
        临时文件创建时就用 .partial 后缀，文件名不从任意数据库内容拼接；完成后才去掉后缀。
        备份失败不开始迁移，删除本次临时文件；清理失败留下 .partial 后缀并在诊断标明路径。
        用同一个显式 BEGIN IMMEDIATE 事务执行所有升级及版本表更新，SQLite DDL 可回滚；
        失败保留已完成备份，回滚 schema/数据，首次创建失败可留下无业务表的空库及 WAL/SHM。
        回滚本身失败标明数据库结果未知，要求人工恢复，绝不自动用备份覆盖。
        成功后按备份文件名中的 UTC 时间升序、同时间按完整文件名排序，只保留最新 5 份；
        只删本平台完整命名且非软链接的普通文件，不按 mtime，不碰人工文件或 .partial。
        目录用 scandir 迭代、heapq 保持最多 5 个候选再二次扫描删除，不全量加载文件名列表。
        清理失败时升级已提交、备份可能多于 5 份，ExternalError 明确“升级成功，保留清理失败”，
        不谎称迁移回滚。最终关闭所有连接/自有引擎并释放锁，不配置全局日志。

    Time Semantics:
        文件名用注入 UTC，保留排序不依赖本地 -06:00；备份预算用 monotonic，
        每批 BACKUP_BATCH_PAGES 页、busy sleep BACKUP_RETRY_SLEEP_S 秒，
        progress 检查 BACKUP_TIMEOUT_S 预算，无无限重试。
        SQLite/磁盘单次系统调用不可强制打断，预算非硬实时保证；服务停止约束保证备份后无业务写入。
    """
    if (
        not paths.root.is_absolute()
        or ".." in paths.root.parts
        or "\x00" in str(paths.root)
        or paths.database != paths.root / DATABASE_FILENAME
        or paths.root.is_symlink()
        or paths.database.is_symlink()
    ):
        problem = invalid_field("state_paths", "可信的绝对状态目录与其 rdp.sqlite3 文件")
        raise problem
    try:
        now = ensure_utc(now)
    except (ValueError, OverflowError) as error:
        problem = invalid_field("now", "可表示的有时区 UTC 时刻")
        raise problem from error
    with _migration_lock(paths):
        return _migrate_locked(paths, now)


def _migrate_locked(paths: StatePaths, now: datetime) -> MigrationResult:
    """目录锁覆盖版本判断、备份、升级和保留清理，避免两个迁移互相踩踏。"""
    try:
        secure_database_files(paths.database)
    except OSError as error:
        raise _migration_external(paths, "数据库权限", paths.database) from error
    config = migration_config()
    head = cast(str, ScriptDirectory.from_config(config).get_current_head())
    current, business = _read_revision(paths.database, migration=True)
    if current is None and business:
        problem = _version_problem(paths.database, "非空无版本库", head)
        raise problem
    known = {revision.revision for revision in ScriptDirectory.from_config(config).walk_revisions()}
    if current is not None and current not in known:
        problem = _version_problem(paths.database, "未知版本", head)
        raise problem
    if current == head:
        return MigrationResult(current, head, False, None)
    _backup_directory(paths)
    backup = _backup(paths, now, current) if paths.database.exists() else None
    engine = create_database_engine(paths.database)
    try:
        with session_scope(engine) as session:
            config = migration_config(session.connection())
            command.upgrade(config, "head")
        head = cast(str, ScriptDirectory.from_config(config).get_current_head())
        _prune_backups(paths)
        return MigrationResult(current, head, True, backup)
    except (InputError, ConflictError, ExternalError, DefectError):
        raise
    except Exception as error:
        problem = DefectError(
            (
                Diagnostic(
                    level=DiagnosticLevel.ERROR,
                    category=DiagnosticCategory.DEFECT,
                    stage="执行迁移",
                    source="平台",
                    objects=(DiagnosticObject(key="database", value=str(paths.database)),),
                    rule="迁移脚本必须完整执行",
                    actual="迁移脚本发生程序错误",
                    expected="全部脚本与版本更新提交",
                    consequence="迁移失败，已尝试回滚；清理失败时数据库结果未知",
                    next_step="检查异常链和备份；结果未知时停止服务并人工恢复",
                ),
            )
        )
        raise problem from error
    finally:
        engine.dispose()


@contextmanager
def _migration_lock(paths: StatePaths) -> Generator[None, None, None]:
    """锁住目录 inode，不创建锁文件；内核在关闭 fd 或进程退出时释放锁。"""
    try:
        descriptor = os.open(paths.root, os.O_RDONLY | os.O_DIRECTORY)
    except OSError as error:
        raise _migration_external(paths, "迁移锁", paths.root) from error
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise ConflictError(
                (
                    Diagnostic(
                        level=DiagnosticLevel.ERROR,
                        category=DiagnosticCategory.CONFLICT,
                        stage="数据库迁移",
                        source="平台",
                        objects=(DiagnosticObject(key="database", value=str(paths.database)),),
                        rule="同一状态目录只能运行一个 migrate",
                        actual="另一个迁移持有目录锁",
                        expected="立即取得排他目录锁",
                        consequence="本次迁移未开始，无文件改动",
                        next_step="等待另一个 migrate 完成后重试",
                    ),
                )
            ) from error
        yield
    finally:
        os.close(descriptor)


def _backup(paths: StatePaths, now: datetime, revision: str | None) -> Path:
    """SQLite backup 复制含已提交 WAL 的一致快照，成功后才原子发布。"""
    directory = paths.root / BACKUPS_DIRECTORY_NAME
    stamp = format_utc_text(now).translate(str.maketrans("", "", "-:."))
    destination = directory / f"rdp-before-{stamp}-{revision or 'base'}-{uuid4().hex}.sqlite3"
    partial: Path | None = None
    started = time.monotonic()

    def progress(_status: int, _remaining: int, _total: int) -> None:
        if time.monotonic() - started > BACKUP_TIMEOUT_S:
            raise TimeoutError("数据库备份超过预算")

    try:
        descriptor, name = tempfile.mkstemp(dir=directory, suffix=".partial")
        partial = Path(name)
        os.close(descriptor)
        with (
            closing(
                sqlite3.connect(
                    paths.database.as_uri() + "?mode=ro", uri=True, timeout=BUSY_TIMEOUT_MS / 1000
                )
            ) as source,
            closing(sqlite3.connect(partial, timeout=BUSY_TIMEOUT_MS / 1000)) as target,
        ):
            source.backup(
                target, pages=BACKUP_BATCH_PAGES, sleep=BACKUP_RETRY_SLEEP_S, progress=progress
            )
        partial.replace(destination)
        return destination
    except (OSError, sqlite3.Error) as error:
        raise _migration_external(paths, "备份", partial or directory) from error
    finally:
        if partial is not None:
            try:
                partial.unlink(missing_ok=True)
            except OSError as cleanup:
                raise _migration_external(paths, "清理临时备份", partial) from cleanup


def _backup_directory(paths: StatePaths) -> None:
    """仅纠正本次创建目录的权限，已有宽权限目录拒绝使用，不擅自修改。"""
    directory = paths.root / BACKUPS_DIRECTORY_NAME
    try:
        if directory.is_symlink():
            raise OSError("备份目录不能为软链接")
        if not directory.exists():
            directory.mkdir(mode=STATE_DIRECTORY_MODE)
            directory.chmod(STATE_DIRECTORY_MODE)
        if not directory.is_dir() or directory.stat().st_mode & 0o7777 != STATE_DIRECTORY_MODE:
            raise OSError("备份目录必须为权限 0700 的目录")
    except OSError as error:
        raise _migration_external(paths, "备份目录", directory) from error


def _migration_external(paths: StatePaths, stage: str, target: Path) -> ExternalError:
    """运维失败保留安全阶段和路径，明确升级已提交还是尚未开始。"""
    return ExternalError(
        (
            Diagnostic(
                level=DiagnosticLevel.ERROR,
                category=DiagnosticCategory.EXTERNAL,
                stage=stage,
                source="平台",
                objects=(
                    DiagnosticObject(key="database", value=str(paths.database)),
                    DiagnosticObject(key="path", value=str(target)),
                ),
                rule="迁移必须有完整备份和可用的本地存储",
                actual="本地文件操作失败或超过预算",
                expected="目录权限 0700、备份完整且文件系统可用",
                consequence="升级成功，保留清理失败"
                if stage == "清理旧备份"
                else "未开始升级；可能保留空目录或 .partial 文件",
                next_step="检查路径、权限、空间和备份；清理诊断路径的半成品后再重试",
            ),
        )
    )


def _backup_names(directory: Path) -> Iterator[str]:
    """逐项筛选平台完整备份，不跟随软链接，也不把半成品或人工文件纳入清理。"""
    with os.scandir(directory) as entries:
        for entry in entries:
            if entry.is_file(follow_symlinks=False) and re.fullmatch(
                BACKUP_FILENAME_PATTERN, entry.name
            ):
                yield entry.name


def _prune_backups(paths: StatePaths) -> None:
    """两次扫描加固定大小堆，只保留文件名最新的五份；清理失败不能宣称升级回滚。"""
    directory = paths.root / BACKUPS_DIRECTORY_NAME
    try:
        keep = set(heapq.nlargest(MIGRATION_BACKUP_LIMIT, _backup_names(directory)))
        for name in _backup_names(directory):
            if name not in keep:
                (directory / name).unlink()
    except OSError as error:
        raise _migration_external(paths, "清理旧备份", directory) from error
