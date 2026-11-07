"""变更记录 `nav-changes/<作业编号>.json.gz`（领域层，M1-07，ADR 0009 L16）。

每个写导航层的作业——成功的、失败回滚的、被中断回滚的、人工确认的——都留一份，永久保留，
操作日志过了保留期（30 天）清掉以后仍保留改动历史。只读写状态目录，不碰导航层。

磁盘格式：gzip 压缩的 UTF-8 JSON，内容是 ChangeRecord。步骤里的文件前后像：
正文不超过 CHANGE_INLINE_MAX_BYTES（1 MiB）的存全文（`content`）；更大的只存 sha256 和大小，
正文放进旁路文件 `nav-changes/<作业编号>.blobs/<sha256>.gz`，保证大文件也保留完整改动历史。
"""

import gzip
import hashlib
import logging
import os
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from rdp.infra.state import StatePaths
from rdp.jobs.navwrite.errors import (
    nav_external_error,
    nav_input_error,
)
from rdp.jobs.navwrite.journal import Journal, JournalStep, read_before_image
from rdp.jobs.navwrite.models import (
    MakeDirStep,
    MismatchItem,
    MovePathStep,
    NavOperation,
    NavWritePlan,
    PlanReport,
    RemovePathStep,
    SetLinkStep,
    Step,
    WriteFileStep,
)
from rdp.jobs.navwrite.policy import CHANGE_FORMAT_VERSION, CHANGE_INLINE_MAX_BYTES

logger = logging.getLogger(__name__)
_RULE = "NAV_CHANGES"
_BLOBS_SUFFIX = ".blobs"

_FROZEN = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)


class ChangeOutcome(StrEnum):
    """变更记录的结局。

    Attributes:
        COMMITTED: committed，全部步骤写成，改动生效。
        ROLLED_BACK: rolled_back，作业运行中途失败，已在同一次持锁里按前像退回。
        ROLLED_BACK_BY_RECOVERY: rolled_back_by_recovery，worker 中断，重启后恢复流程退回。
        MANUALLY_CONFIRMED: manually_confirmed，恢复失败后管理员人工核对并确认；导航层现状以人工处理为准。
    """

    COMMITTED = "committed"
    ROLLED_BACK = "rolled_back"
    ROLLED_BACK_BY_RECOVERY = "rolled_back_by_recovery"
    MANUALLY_CONFIRMED = "manually_confirmed"


class ImageRecord(BaseModel):
    """变更记录里一个文件或链接的前像或后像。

    Attributes:
        model_config: 冻结，拒绝未知字段。
        exists: 文件（或链接）是否存在。
        sha256: 文件存在时的 64 位小写摘要；链接或不存在为 None。
        size_bytes: 文件存在时的字节数；其余 None。
        content: 文件正文全文（UTF-8 文本），仅当 size_bytes ≤ CHANGE_INLINE_MAX_BYTES 时有；否则 None。
        blob: 正文超限时旁路文件名 `<sha256>.gz`；正文已内联或不存在时 None。
        link_target: 链接的目标（readlink 原样）；非链接 None。
    """

    model_config = _FROZEN
    exists: bool
    sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    size_bytes: int | None = Field(default=None, ge=0)
    content: str | None = None
    blob: str | None = None
    link_target: str | None = None


class ChangeStep(BaseModel):
    """变更记录里的一步。

    Attributes:
        model_config: 冻结，拒绝未知字段。
        index: 与写入日志相同的步骤序号，从 0 起。
        op: write_file、set_link、make_dir、move_path、remove_path 之一。
        path: 相对 nav_root 的路径。
        to_path: 仅 move_path。
        before: 前像；make_dir 的前像是"不存在"。
        after: 后像；仅 COMMITTED 与 MANUALLY_CONFIRMED 之外的结局可能为 None（回滚后没有后像）。
    """

    model_config = _FROZEN
    index: int = Field(ge=0)
    op: Literal["write_file", "set_link", "make_dir", "move_path", "remove_path"]
    path: str = Field(min_length=1)
    to_path: str | None = None
    before: ImageRecord
    after: ImageRecord | None


class ChangeRecord(BaseModel):
    """一份变更记录的完整内容（压缩前的 JSON 对象）。

    Attributes:
        model_config: 冻结，拒绝未知字段。
        format_version: 固定 CHANGE_FORMAT_VERSION。
        job_id: 写入作业编号，≥ 1，即变更记录编号（文件名）。
        operation: 操作种类。
        outcome: 结局。
        actor_id: 提交人内部编号；系统或运维为 None。
        actor_name: 提交人名字快照，1-64 码点。
        preview_job_id: 依据的预览作业编号；恢复路径可能为 None。
        reverts_job_id: 撤回作业才有值：被撤回的作业编号。
        started_at: 作业开始写入的 UTC 时刻。
        finished_at: 作业收尾的 UTC 时刻，不早于 started_at（时钟回拨时取同值）。
        nav_root: 导航根绝对路径文本。
        dataset_ids: 受影响的永久编号。
        steps: 全部步骤，按序号升序。
        mismatches: 仅 MANUALLY_CONFIRMED：确认时仍对不上的项，其余为空元组。
        report: 预览报告副本，供事后查看"当时预览说了什么"；恢复路径没有预览时为 None。
    """

    model_config = _FROZEN
    format_version: Literal[1] = 1
    job_id: int = Field(ge=1)
    operation: NavOperation
    outcome: ChangeOutcome
    actor_id: int | None = Field(ge=1)
    actor_name: str = Field(min_length=1, max_length=64)
    preview_job_id: int | None = Field(ge=1)
    reverts_job_id: int | None = Field(ge=1)
    started_at: datetime
    finished_at: datetime
    nav_root: str = Field(min_length=1)
    dataset_ids: tuple[str, ...]
    steps: tuple[ChangeStep, ...]
    mismatches: tuple[MismatchItem, ...]
    report: PlanReport | None


@dataclass(frozen=True)
class ArchiveRequest:
    """归档一份写入日志所需的上下文。

    Attributes:
        outcome: 要写入的结局。
        actor_id: 提交人内部编号，系统或运维为 None。
        actor_name: 提交人名字快照。
        preview_job_id: 依据的预览作业编号，未知为 None。
        started_at: 作业开始时刻，aware UTC；恢复路径用日志的 created_at。
        finished_at: 归档时刻，aware UTC，由注入时钟生成。
        plan: 提交成功时传入计划，用来取后像全文；回滚、恢复、确认时传 None（后像没有生效，不记）。
        report: 预览报告副本，可为 None。
        mismatches: 仅人工确认时传入仍对不上的项，其余空元组。
    """

    outcome: ChangeOutcome
    actor_id: int | None
    actor_name: str
    preview_job_id: int | None
    started_at: datetime
    finished_at: datetime
    plan: NavWritePlan | None
    report: PlanReport | None
    mismatches: tuple[MismatchItem, ...]


def change_record_path(paths: StatePaths, job_id: int) -> Path:
    """计算变更记录文件的路径，只计算、不创建。

    Args:
        paths: 已初始化的状态布局。
        job_id: 写入作业编号，≥ 1。

    Returns:
        `<状态目录>/nav-changes/<job_id>.json.gz` 的绝对路径。

    Raises:
        InputError: job_id 不是 ≥ 1 的整数。

    Side Effects:
        无。

    Time Semantics:
        无；纯路径计算。
    """
    if type(job_id) is not int or job_id < 1:
        problem = nav_input_error(_RULE, "作业编号必须是不小于 1 的整数")
        raise problem
    return paths.nav_changes / f"{job_id}.json.gz"


def archive_journal(
    paths: StatePaths, directory: Path, journal: Journal, request: ArchiveRequest
) -> Path:
    """把一份写入日志连同计划和前后像打包成变更记录。

    Args:
        paths: 已初始化的状态布局。
        directory: 写入日志目录，用来读前像原字节。
        journal: 对应的完整写入日志。
        request: 结局和上下文。

    Returns:
        写好的 nav-changes/<job_id>.json.gz 路径。

    Raises:
        InputError: request.plan 与 journal 的步骤对不上，或 outcome 为 COMMITTED 却没给 plan。
        ExternalError: 写入、fsync 或 rename 失败；已有的同名记录不被破坏。

    Side Effects:
        写 nav-changes/<job_id>.json.gz（临时文件 → fsync → os.replace → fsync 目录）和超限文件的旁路 blob。
        同一作业重复归档写入相同内容，幂等。不删日志，删除由 discard_journal 在归档成功之后做。
        只写状态目录，不碰导航层。

    Time Semantics:
        同步；是作业收尾的提交点：COMMITTED 的记录一旦落盘，恢复流程就认为这个作业已提交（不再回滚）。
        因此顺序固定为：先归档，后删日志。
    """
    if request.outcome is ChangeOutcome.COMMITTED and request.plan is None:
        problem = nav_input_error(_RULE, "已提交的作业必须带计划才能归档后像")
        raise problem
    plan_steps = request.plan.steps if request.plan is not None else None
    if plan_steps is not None and not _steps_match(journal, plan_steps):
        problem = nav_input_error(_RULE, "计划与写入日志的步骤对不上", objects=_job(journal))
        raise problem
    blobs = paths.nav_changes / f"{journal.job_id}{_BLOBS_SUFFIX}"
    pending_blobs: dict[str, bytes] = {}
    steps: list[ChangeStep] = []
    for index, step in enumerate(journal.steps):
        planned = plan_steps[index] if plan_steps is not None else None
        before = _before_image(directory, step, pending_blobs)
        after = _after_image(planned, pending_blobs) if planned is not None else None
        steps.append(
            ChangeStep(
                index=step.index,
                op=step.op,
                path=step.path,
                to_path=step.to_path,
                before=before,
                after=after,
            )
        )
    record = ChangeRecord(
        job_id=journal.job_id,
        operation=journal.operation,
        outcome=request.outcome,
        actor_id=request.actor_id,
        actor_name=request.actor_name,
        preview_job_id=request.preview_job_id,
        reverts_job_id=journal.reverts_job_id,
        started_at=request.started_at,
        finished_at=max(request.started_at, request.finished_at),
        nav_root=journal.nav_root,
        dataset_ids=journal.dataset_ids,
        steps=tuple(steps),
        mismatches=request.mismatches,
        report=request.report,
    )
    target = change_record_path(paths, journal.job_id)
    try:
        paths.nav_changes.mkdir(exist_ok=True)
        if pending_blobs:
            blobs.mkdir(exist_ok=True)
            for digest, content in pending_blobs.items():
                _write_atomic(blobs / f"{digest}.gz", _compress(content))
        _write_atomic(target, _compress(record.model_dump_json().encode("utf-8")))
    except OSError as error:
        problem = nav_external_error(
            _RULE, "写变更记录失败，已有的记录没有被破坏", objects=_job(journal)
        )
        raise problem from error
    return target


def read_change_record(paths: StatePaths, job_id: int) -> ChangeRecord:
    """读取一份变更记录。

    Args:
        paths: 已初始化的状态布局。
        job_id: 写入作业编号，≥ 1。

    Returns:
        ChangeRecord。

    Raises:
        InputError: 记录不存在（该作业没有写过导航层，或编号不对）、解压或解析失败、format_version 不认识。
        ExternalError: 读取时 I/O 失败。

    Side Effects:
        无（只读状态目录）。

    Time Semantics:
        同步读取，不依赖操作日志是否仍保留。
    """
    path = change_record_path(paths, job_id)
    try:
        raw = path.read_bytes()
    except FileNotFoundError as error:
        problem = nav_input_error(_RULE, "这个作业没有变更记录", objects=(("job_id", str(job_id)),))
        raise problem from error
    except OSError as error:
        problem = nav_external_error(_RULE, "读取变更记录失败", objects=(("job_id", str(job_id)),))
        raise problem from error
    try:
        return ChangeRecord.model_validate_json(gzip.decompress(raw))
    except (OSError, EOFError, ValueError, ValidationError) as error:
        problem = nav_input_error(
            _RULE,
            "变更记录损坏或版本不认识",
            expected=f"format_version={CHANGE_FORMAT_VERSION}",
            objects=(("job_id", str(job_id)),),
        )
        raise problem from error


def _job(journal: Journal) -> tuple[tuple[str, str], ...]:
    """诊断里的作业编号。"""
    return (("job_id", str(journal.job_id)),)


def _steps_match(journal: Journal, steps: tuple[Step, ...]) -> bool:
    """计划步骤与写入日志逐步同类同路径。"""
    return len(steps) == len(journal.steps) and all(
        planned.op == logged.op and planned.path == logged.path
        for planned, logged in zip(steps, journal.steps, strict=True)
    )


def _compress(content: bytes) -> bytes:
    """确定性压缩（mtime 固定为 0），同样内容得到同样字节，重复归档幂等。"""
    return gzip.compress(content, mtime=0)


def _write_atomic(target: Path, content: bytes) -> None:
    """临时文件 → fsync → os.replace → fsync 目录；失败不留临时文件，已有同名文件不被破坏。"""
    temporary = target.with_name(f".{target.name}.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        try:
            view = memoryview(content)
            while view:
                view = view[os.write(descriptor, view) :]
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        temporary.replace(target)
    except OSError:
        temporary.unlink(missing_ok=True)
        raise
    directory = os.open(target.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def _file_record(content: bytes, pending: dict[str, bytes]) -> ImageRecord:
    """文件正文的记录：不超过上限内联全文，更大的只存哈希和大小，正文放旁路 blob。"""
    digest = hashlib.sha256(content).hexdigest()
    base = {"exists": True, "sha256": digest, "size_bytes": len(content)}
    if len(content) <= CHANGE_INLINE_MAX_BYTES:
        try:
            return ImageRecord.model_validate({**base, "content": content.decode("utf-8")})
        except UnicodeDecodeError:
            pass
    pending[digest] = content
    return ImageRecord.model_validate({**base, "blob": f"{digest}.gz"})


def _before_image(directory: Path, step: JournalStep, pending: dict[str, bytes]) -> ImageRecord:
    """一步的前像记录。"""
    if step.before_blob is not None:
        return _file_record(read_before_image(directory, step), pending)
    if step.op == "set_link" or (step.op == "remove_path" and step.entry_kind == "symlink"):
        return ImageRecord(exists=step.before_target is not None, link_target=step.before_target)
    if step.op in ("move_path", "remove_path"):
        return ImageRecord(exists=True)
    return ImageRecord(exists=False)


def _after_image(planned: Step, pending: dict[str, bytes]) -> ImageRecord:
    """一步的后像记录，只在提交成功时由计划得到。"""
    match planned:
        case WriteFileStep():
            return _file_record(planned.after_content.encode("utf-8"), pending)
        case SetLinkStep():
            return ImageRecord(exists=True, link_target=planned.after_target)
        case MakeDirStep() | MovePathStep():
            return ImageRecord(exists=True)
        case RemovePathStep():
            return ImageRecord(exists=False)
