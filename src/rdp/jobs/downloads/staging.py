"""worker 只读扫描下载暂存目录并保存数据库快照；不删除、不写存储根。

使用标准库 dir_fd/O_NOFOLLOW 防止目录遍历跟随软链接；沿用存储检查器的有界等待。
"""

import os
import re
import stat
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from threading import Event
from typing import Literal

from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.engine import Engine

from rdp.infra.config import StorageRootConfig
from rdp.infra.db.connection import create_database_engine, session_scope
from rdp.infra.db.validation import invalid_field
from rdp.infra.diagnostics import DefectError
from rdp.infra.state import state_paths
from rdp.jobs.downloads.job import DownloadDependencies
from rdp.jobs.execution import ExecutionContext
from rdp.jobs.models import DownloadStagingSnapshotRow, JobRow
from rdp.jobs.registry import StorageUse
from rdp.jobs.storage import check_storage_before_job
from rdp.jobs.types import JobProgress

# 仓库和提交短码遵循 staging_path 的路径格式；只接受平台会生成的目录。
_PART = re.compile(r"[A-Za-z0-9._-]+")
_LEAF = re.compile(r"([A-Za-z0-9._-]+)@([0-9a-f]{12})")
_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC


class ScanParameters(BaseModel):
    """扫描所有已登记可写根，客户端不指定任意路径。"""

    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)


class StagingEntry(BaseModel):
    """一个不含绝对路径的暂存目录观察。"""

    storage_root: str
    repo_type: Literal["dataset", "model"]
    repo_id: str
    commit_prefix: str
    size_bytes: int
    modified_at: datetime
    in_use: bool = False


class StagingSnapshot(BaseModel):
    """扫描时刻与条目；使用标志是该时刻的保守观察，不是删除许可。"""

    created_at: datetime
    items: tuple[StagingEntry, ...]


@dataclass(frozen=True)
class StagingScanner:
    """worker 的下载边界；Web 登记时没有目录访问能力。

    Attributes:
        dependencies: 已装配的下载边界；Web 为 None。
    """

    dependencies: DownloadDependencies | None

    def execute(self, context: ExecutionContext) -> None:
        """只读扫描可写根并将快照发布到数据库。

        Args:
            context: 只含 ScanParameters 的扫描作业上下文。

        Returns:
            无。

        Raises:
            DefectError: 依赖或参数不匹配。
            ExternalError: 根离线、超时或数据库不可用。

        Side Effects:
            只读登记为可写的存储根；仅写状态数据库和作业进度。

        Time Semantics:
            各根依次以存储检查器总预算访问；占用状态在发布事务中观察。
        """
        if self.dependencies is None or not isinstance(context.parameters, ScanParameters):
            raise DefectError()
        plan = self.dependencies.plan
        entries: list[StagingEntry] = []
        for root in plan.config.storage_roots:
            if root.writable:
                entries.extend(_check_and_scan(root, plan.checker, context))
        context.reporter.check_cancelled()
        engine = create_database_engine(state_paths(plan.config, ()).database)
        try:
            _save(engine, context.job_id, context.clock.now(), entries)
        finally:
            engine.dispose()
        context.reporter.report(
            JobProgress(
                stage_index=1,
                stage_count=1,
                stage_name="扫描下载暂存",
                done=1,
                total=1,
                unit="快照",
                total_items=1,
                failed_items=0,
                warning_count=0,
            )
        )


def _check_and_scan(
    root: StorageRootConfig, checker: object, context: ExecutionContext
) -> list[StagingEntry]:
    """把枚举放在受管存储检查的有界线程，超时后阻止迟到线程继续遍历。"""
    from rdp.infra.storage import StorageAccessChecker

    if not isinstance(checker, StorageAccessChecker):
        raise DefectError()
    abandoned = Event()
    result: list[StagingEntry] = []

    def access(path: Path) -> None:
        checker.access(path)
        if not abandoned.is_set():
            result.extend(_scan_root(root, abandoned))

    try:
        check_storage_before_job(
            (StorageUse(root.name, write=True),),
            checker=replace(checker, access=access),
            checkpoint=context.reporter.check_cancelled,
        )
    finally:
        abandoned.set()
    return result


def _open_child(parent: int, name: str) -> int | None:
    """不存在的层级视作空目录；绝不跟随软链接。"""
    try:
        return os.open(name, _FLAGS, dir_fd=parent)
    except FileNotFoundError:
        return None


def _size(directory: int, abandoned: Event) -> int:
    """逐级打开目录，忽略软链接和特殊文件；递归调用持有父目录描述符。"""
    total = 0
    with os.scandir(directory) as entries:
        for entry in entries:
            if abandoned.is_set():
                break
            info = entry.stat(follow_symlinks=False)
            if stat.S_ISREG(info.st_mode):
                total += info.st_size
            elif stat.S_ISDIR(info.st_mode):
                child = _open_child(directory, entry.name)
                if child is not None:
                    try:
                        total += _size(child, abandoned)
                    finally:
                        os.close(child)
    return total


def _leaves(
    parent: int, root: StorageRootConfig, kind: Literal["dataset", "model"], abandoned: Event
) -> list[StagingEntry]:
    """只扫描规范仓库身份目录；实际文件名仅用于计数，不进入数据库。"""
    result: list[StagingEntry] = []
    with os.scandir(parent) as namespaces:
        for namespace in namespaces:
            if abandoned.is_set():
                break
            if (
                not _PART.fullmatch(namespace.name)
                or namespace.name in (".", "..")
                or not namespace.is_dir(follow_symlinks=False)
            ):
                continue
            org_fd = _open_child(parent, namespace.name)
            if org_fd is None:
                continue
            try:
                with os.scandir(org_fd) as repositories:
                    for repository in repositories:
                        if abandoned.is_set():
                            break
                        match = _LEAF.fullmatch(repository.name)
                        if (
                            match is None
                            or match[1] in (".", "..")
                            or not repository.is_dir(follow_symlinks=False)
                        ):
                            continue
                        fd = _open_child(org_fd, repository.name)
                        if fd is not None:
                            try:
                                modified = datetime.fromtimestamp(os.fstat(fd).st_mtime, UTC)
                                result.append(
                                    StagingEntry(
                                        storage_root=root.name,
                                        repo_type=kind,
                                        repo_id=f"{namespace.name}/{match[1]}",
                                        commit_prefix=match[2],
                                        size_bytes=_size(fd, abandoned),
                                        modified_at=modified,
                                    )
                                )
                            finally:
                                os.close(fd)
            finally:
                os.close(org_fd)
    return result


def _scan_root(root: StorageRootConfig, abandoned: Event) -> list[StagingEntry]:
    """从可信根沿固定目录向下打开，不解析任何可替换的软链接。"""
    root_fd = os.open(root.path, _FLAGS)
    descriptors = [root_fd]
    try:
        parent = root_fd
        for name in ("暂存", "下载"):
            child = _open_child(parent, name)
            if child is None:
                return []
            descriptors.append(child)
            parent = child
        result: list[StagingEntry] = []
        for kind in ("dataset", "model"):
            if abandoned.is_set():
                break
            child = _open_child(parent, kind)
            if child is not None:
                try:
                    result.extend(_leaves(child, root, kind, abandoned))
                finally:
                    os.close(child)
        return result
    finally:
        for fd in reversed(descriptors):
            os.close(fd)


def _save(engine: Engine, job_id: int, now: datetime, entries: list[StagingEntry]) -> None:
    """发布事务同时观察活动下载；不以静态扫描结果作为未来删除的许可。"""
    with session_scope(engine) as session:
        active = session.scalars(
            select(JobRow).where(
                JobRow.type_name == "download",
                JobRow.state.in_(("queued", "running", "cancelling")),
            )
        ).all()
        busy = {
            (
                row.parameters.get("storage_root"),
                row.parameters.get("repo_type"),
                row.parameters.get("repo_id"),
            )
            for row in active
        }
        items = tuple(
            entry.model_copy(
                update={"in_use": (entry.storage_root, entry.repo_type, entry.repo_id) in busy}
            )
            for entry in entries
        )
        result = StagingSnapshot(created_at=now, items=items)
        row = session.get(DownloadStagingSnapshotRow, job_id)
        if row is None:
            session.add(
                DownloadStagingSnapshotRow(job_id=job_id, snapshot=result.model_dump(mode="json"))
            )
        else:
            row.snapshot = result.model_dump(mode="json")


def read_staging_snapshot(engine: Engine, job_id: int) -> StagingSnapshot:
    """读取指定扫描作业发布的数据库快照。

    Args:
        engine: 平台受管数据库引擎。
        job_id: 正整数扫描作业编号。

    Returns:
        生成时刻和条目快照。

    Raises:
        InputError: 快照不存在或损坏。
        ExternalError: 数据库读取失败。

    Side Effects:
        只读数据库，不访问存储根。

    Time Semantics:
        返回上一次提交的快照，不代表当前占用状态。
    """
    with session_scope(engine, read_only=True) as session:
        row = session.get(DownloadStagingSnapshotRow, job_id)
        if row is None:
            problem = invalid_field("job_id", "已完成的暂存扫描")
            raise problem
        return StagingSnapshot.model_validate(row.snapshot)
