"""worker 只读采集磁盘和 GPU，数据库只保存容量快照，不访问数据内容。"""

import shutil
import subprocess
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.engine import Engine

from rdp.infra.diagnostics import ExternalError
from rdp.infra.storage import StorageAccessChecker
from rdp.jobs.policy import GPU_PROBE_TIMEOUT_S

_MIB = 1024 * 1024


class DiskSpace(BaseModel):
    """磁盘容量快照，无法读取时为 None。

    Attributes:
        total_bytes: 总容量字节数。
        free_bytes: 对当前用户可用字节数。
    """

    total_bytes: int | None
    free_bytes: int | None


class StorageSpace(DiskSpace):
    """已登记可写根的容量快照。

    Attributes:
        name: 存储根的配置名称，不包含路径。
    """

    name: str


class GpuUsage(BaseModel):
    """一个 GPU 的利用率和显存快照。

    Attributes:
        index: GPU 序号。
        utilization_percent: GPU 利用率百分比。
        memory_used_bytes: 显存已使用字节。
        memory_total_bytes: 显存总字节。
    """

    index: int
    utilization_percent: float
    memory_used_bytes: int
    memory_total_bytes: int


class WorkerResourceSnapshot(BaseModel):
    """worker 最后一次资源观察。

    Attributes:
        checked_at: 采集结束时的带时区时间。
        system: 系统盘容量。
        storage: 可写存储根容量；未知容量为 None。
        gpu: GPU 信息；无法查询时为 None，空列表表示无 GPU。
    """

    checked_at: datetime
    system: DiskSpace
    storage: list[StorageSpace]
    gpu: list[GpuUsage] | None


def _usage(path: Path) -> DiskSpace:
    """使用标准库查询文件系统容量，不读取目录内容。"""
    try:
        usage = shutil.disk_usage(path)
    except OSError:
        return DiskSpace(total_bytes=None, free_bytes=None)
    return DiskSpace(total_bytes=usage.total, free_bytes=usage.free)


def _storage_space(
    checker: StorageAccessChecker, name: str, checkpoint: Callable[[], None]
) -> StorageSpace:
    """容量查询复用挂载身份与有界访问线程，不在 Web 访问存储根。"""
    observed: list[DiskSpace] = []

    def access(path: Path) -> None:
        checker.access(path)
        observed.append(_usage(path))

    bounded = StorageAccessChecker(checker.mounts, checker.options, access)
    try:
        status = bounded.check(name, checkpoint=checkpoint)
    except ExternalError:
        return StorageSpace(name=name, total_bytes=None, free_bytes=None)
    if not status.online or not observed:
        return StorageSpace(name=name, total_bytes=None, free_bytes=None)
    return StorageSpace(
        name=name, total_bytes=observed[0].total_bytes, free_bytes=observed[0].free_bytes
    )


def _gpu_usage() -> list[GpuUsage] | None:
    """只运行本机 nvidia-smi，缺失或执行失败时返回未知。"""
    command = shutil.which("nvidia-smi")
    if command is None:
        return None
    try:
        result = subprocess.run(  # noqa: S603  # 理由：只执行系统查找的固定 nvidia-smi，不拼用户输入。
            [
                command,
                "--query-gpu=index,utilization.gpu,memory.used,memory.total",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=GPU_PROBE_TIMEOUT_S,
            check=True,
        )
        values = [line.split(",") for line in result.stdout.splitlines() if line.strip()]
        return [
            GpuUsage(
                index=int(row[0]),
                utilization_percent=float(row[1]),
                memory_used_bytes=int(row[2]) * _MIB,
                memory_total_bytes=int(row[3]) * _MIB,
            )
            for row in values
        ]
    except (OSError, subprocess.SubprocessError, ValueError, IndexError):
        return None


def collect_resources(
    engine: Engine,
    checker: StorageAccessChecker | None,
    *,
    now: Callable[[], datetime],
    checkpoint: Callable[[], None],
) -> WorkerResourceSnapshot:
    """只在 worker 读取系统盘、可写根和 GPU，并持久化快照。

    Args:
        engine: 已迁移数据库。
        checker: worker 的挂载和有界访问检查器；None 表示没有可写根。
        now: 返回带时区时刻的时钟。
        checkpoint: 取消及停止检查。

    Returns:
        已提交的资源快照；单项失败时对应字段为空。

    Raises:
        SQLAlchemyError: 持久化失败。
        Exception: checkpoint 的取消或停止异常。

    Side Effects:
        只读系统盘和已登记可写根容量，启动有界 GPU 查询进程，覆盖数据库快照。

    Time Semantics:
        每个存储根遵循 checker 的访问预算，GPU 查询最多 GPU_PROBE_TIMEOUT_S 秒。
    """
    checkpoint()
    system = _usage(Path("/"))
    storage = (
        []
        if checker is None
        else [
            _storage_space(checker, root.name, checkpoint)
            for root in checker.mounts.roots
            if root.writable
        ]
    )
    gpu = _gpu_usage()
    snapshot = WorkerResourceSnapshot(checked_at=now(), system=system, storage=storage, gpu=gpu)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO monitoring_resources (id, snapshot) VALUES (1, :snapshot) ON CONFLICT(id) DO UPDATE SET snapshot=excluded.snapshot"
            ),
            {"snapshot": snapshot.model_dump_json()},
        )
    return snapshot


def latest_resources(engine: Engine) -> WorkerResourceSnapshot | None:
    """只读数据库中的最近一次 worker 资源快照。

    Args:
        engine: 已迁移数据库。

    Returns:
        最近快照；没有采集过为 None。

    Raises:
        SQLAlchemyError: 数据库读取失败。
        ValidationError: 保存的快照格式损坏。

    Side Effects:
        仅读取数据库，不访问系统盘、存储根或 GPU。

    Time Semantics:
        返回已提交的最近一次观察，不代表实时状态。
    """
    with engine.connect() as connection:
        value = connection.execute(
            text("SELECT snapshot FROM monitoring_resources WHERE id=1")
        ).scalar_one_or_none()
    return WorkerResourceSnapshot.model_validate_json(value) if value is not None else None
