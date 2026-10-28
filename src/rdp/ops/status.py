"""只读运维状态检查（11），不以心跳推断锁，不把状态查询当作业务执行入口。

单实例探测复用 fcntl.flock；作业查询复用 sqlite3 的 mode=ro 与版本闸门。
探测只回答此刻的状态，不替代执行导航修改时必须持续持有的排他锁。
"""

import errno
import fcntl
import os
import socket
import sqlite3
import stat
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

from rdp.infra.config import WebConfig
from rdp.infra.db.connection import BUSY_TIMEOUT_MS, translate_database_error
from rdp.infra.db.migration import check_database_version
from rdp.infra.diagnostics import (
    ConflictError,
    Diagnostic,
    DiagnosticCategory,
    DiagnosticLevel,
    DiagnosticObject,
    ExternalError,
    InputError,
)


@dataclass(frozen=True)
class WorkerAvailability:
    """本地 worker 锁的瞬时判断，不是执行许可的租约。

    Attributes:
        allowed: 未持锁为 True，持锁为 False。
        diagnostics: 允许时为空；拒绝时一条冲突诊断，含锁路径、影响及停止 worker 的下一步。
    """

    allowed: bool
    diagnostics: tuple[Diagnostic, ...]


def check_worker_stopped(lock_path: Path) -> WorkerAvailability:
    """非阻塞探测 worker 单实例锁，给需要停 worker 的运维动作提供拒绝原因。

    Args:
        lock_path: StatePaths.worker_lock 的绝对路径；不创建或删除该文件。

    Returns:
        锁文件缺失或可以独占加锁时 allowed=True；冲突时 False 并附诊断。
        陈旧文件、其中的 PID 文字、心跳日期均不能代替实际 flock 判断。

    Raises:
        InputError: 路径相对、指向目录或软链接等非普通锁文件。
        ExternalError: 文件权限、打开、加锁或释放失败；不能误报为 worker 已停止。

    Side Effects:
        已有文件用独立描述符执行 LOCK_EX|LOCK_NB，取得后立即释放并关闭；失败也关闭描述符。
        文件缺失直接返回，不新建目录，不删除 worker.lock，不修改文件内容或导航层。

    Time Semantics:
        不等待、不轮询；返回后 worker 可能立即启动，M1 实际写入须重新取得并保持锁。
    """
    if not lock_path.is_absolute():
        raise InputError(
            (_diagnostic(str(lock_path), "锁路径不是绝对路径", DiagnosticCategory.INPUT),)
        )
    try:
        return _probe_lock(lock_path)
    except FileNotFoundError:
        return WorkerAvailability(True, ())
    except OSError as error:
        if error.errno == errno.ELOOP:
            raise InputError(
                (_diagnostic(str(lock_path), "锁路径是软链接", DiagnosticCategory.INPUT),)
            ) from error
        raise ExternalError(
            (_diagnostic(str(lock_path), "无法可靠检查锁状态", DiagnosticCategory.EXTERNAL),)
        ) from error


def _probe_lock(path: Path) -> WorkerAvailability:
    """O_NOFOLLOW与fstat核验实际打开的对象，消除路径检查与打开之间的软链接竞争。"""
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise InputError((_diagnostic(str(path), "锁不是普通文件", DiagnosticCategory.INPUT),))
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return WorkerAvailability(
                False,
                (_diagnostic(str(path), "worker仍持有单实例锁", DiagnosticCategory.CONFLICT),),
            )
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        return WorkerAvailability(True, ())
    finally:
        os.close(descriptor)


def has_active_jobs(database: Path) -> bool:
    """只读判断数据库中是否存在阻止升级的作业。

    Args:
        database: 已有 SQLite 数据库绝对路径；版本须等于当前程序 head。

    Returns:
        存在 running 或 cancelling 为 True；只有 queued 或终态记录、空表为 False。
        心跳是否在线不影响判断；遗留 running 同样拒绝升级，提示先恢复并处理。

    Raises:
        InputError: 数据库缺失、损坏或版本不匹配，提示 rdp migrate，不能当作空闲。
        ConflictError: 版本检查或读取锁等待超预算。
        ExternalError: 数据库权限或读取 I/O 失败。
        DefectError: 固定 SQL、路径类型或迁移图配置错误。

    Side Effects:
        无（mode=ro 连接、query_only，只查询是否存在并 LIMIT 1，finally 关闭连接；
        不建空数据库、不写心跳或作业，不初始化日志、状态目录，不迁移）。

    Time Semantics:
        单次锁等待沿用数据库 5 秒上限；结果是当次快照，升级停服务后必须再查一次以封闭竞态。
    """
    check_database_version(database)
    try:
        with closing(
            sqlite3.connect(
                database.as_uri() + "?mode=ro", uri=True, timeout=BUSY_TIMEOUT_MS / 1000
            )
        ) as connection:
            connection.execute("PRAGMA query_only=ON")
            return (
                connection.execute(
                    "SELECT 1 FROM jobs WHERE state IN ('running','cancelling') LIMIT 1"
                ).fetchone()
                is not None
            )
    except sqlite3.Error as error:
        problem = translate_database_error(error, database=database, operation="检查活跃作业")
        raise problem from error


def check_web_port(settings: WebConfig) -> None:
    """检测配置的监听地址和端口能否在本机使用，供安装脚本启动前拒绝冲突。

    Args:
        settings: load_config 的最终 WebConfig；port 为 1-65535，host 沿用配置约束。

    Returns:
        无，所有候选监听地址均可临时绑定后关闭；不保留端口预约。

    Raises:
        ConflictError: 地址端口已被占用，诊断提示修改配置中的 web.port 后重试。
        ExternalError: 地址解析、权限或 socket 操作失败，不能误报为空闲。

    Side Effects:
        仅对配置监听地址短暂 bind 后关闭 socket，不 listen、不发送数据、不启动服务。
        所有失败路径关闭已创建 socket；不读取数据库或碰 systemd。

    Time Semantics:
        socket 操作超时 1 秒，无自动重试；本机名称解析沿用系统解析器，不承诺 DNS 可中止。
        检查与实际启动之间可能被其他进程占用，最终绑定错误仍由服务入口报告。
    """
    try:
        addresses = socket.getaddrinfo(settings.host, settings.port, type=socket.SOCK_STREAM)
        for family, kind, protocol, _name, address in addresses:
            with socket.socket(family, kind, protocol) as candidate:
                candidate.settimeout(1.0)
                candidate.bind(address)
    except OSError as error:
        category = (
            DiagnosticCategory.CONFLICT
            if error.errno == errno.EADDRINUSE
            else DiagnosticCategory.EXTERNAL
        )
        diagnostic = _diagnostic(f"{settings.host}:{settings.port}", "监听地址不可用", category)
        if category is DiagnosticCategory.CONFLICT:
            raise ConflictError((diagnostic,)) from error
        raise ExternalError((diagnostic,)) from error


def _diagnostic(target: str, actual: str, category: DiagnosticCategory) -> Diagnostic:
    """只读运维预检的统一诊断，拒绝状态明确给出后果及下一步。"""
    return Diagnostic(
        level=DiagnosticLevel.ERROR,
        category=category,
        stage="运维预检",
        source="平台",
        objects=(DiagnosticObject(key="target", value=target),),
        rule="维护前状态必须可确认",
        actual=actual,
        expected="worker已停止且监听端口可用",
        consequence="拒绝本次维护或启动",
        next_step="停止worker后重试；端口冲突时修改配置 web.port",
    )
