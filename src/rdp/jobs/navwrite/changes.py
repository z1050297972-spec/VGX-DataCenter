"""变更记录 `nav-changes/<作业编号>.json.gz` 与撤回（领域层，M1-07，ADR 0009 L16）。

每个写导航层的作业——成功的、失败回滚的、被中断回滚的、人工确认的——都留一份，永久保留，
操作日志过了保留期（30 天）清掉以后撤回照样可用。只读写状态目录，不碰导航层；
唯一读导航层的函数是 plan_revert，它只比对、不写。

磁盘格式：gzip 压缩的 UTF-8 JSON，内容是 ChangeRecord。步骤里的文件前后像：
正文不超过 CHANGE_INLINE_MAX_BYTES（1 MiB）的存全文（`content`）；更大的只存 sha256 和大小，
正文放进旁路文件 `nav-changes/<作业编号>.blobs/<sha256>.gz`（相对"1 MiB 以下存全文"的扩展，待负责人确认：
没有它，14 MB 的子任务.json 改过之后就撤回不了）。
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from rdp.infra.state import StatePaths
from rdp.jobs.navwrite.journal import Journal
from rdp.jobs.navwrite.models import MismatchItem, NavOperation, NavWritePlan, PlanReport

_FROZEN = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)


class ChangeOutcome(StrEnum):
    """变更记录的结局。

    Attributes:
        COMMITTED: committed，全部步骤写成，改动生效；只有这种记录可以被撤回。
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


@dataclass(frozen=True)
class ImageDifference:
    """撤回前核对时，当前状态与 #N 后像的一处差异。

    Attributes:
        path: 相对 nav_root 的路径。
        expected: #N 的后像描述（哈希前缀或链接目标或"不存在"），非空。
        actual: 现在的样子，非空。
        changed_by_job_id: 之后改过它的最近一个作业编号，查得到时有值（来自更晚的变更记录），否则 None。
    """

    path: str
    expected: str
    actual: str
    changed_by_job_id: int | None


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
    raise NotImplementedError


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
    raise NotImplementedError


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
        同步读取，不依赖操作日志是否仍保留；40 天后的撤回走这条路径（场景三）。
    """
    raise NotImplementedError


def diff_against_after_images(
    nav_root: Path, paths: StatePaths, record: ChangeRecord
) -> tuple[ImageDifference, ...]:
    """比对导航层当前状态与某次作业的后像，列出哪些地方之后又变了。

    Args:
        nav_root: 导航层根目录绝对路径，必须等于 record.nav_root。
        paths: 已初始化的状态布局，用来查更晚的变更记录以回答"谁改的"。
        record: 被撤回作业的变更记录，outcome 必须是 COMMITTED。

    Returns:
        差异元组，按路径升序；为空表示当前状态完全等于 #N 的后像，可以撤回。

    Raises:
        InputError: record 的结局不是 COMMITTED（回滚过的记录没有后像可撤回）。
        ExternalError: 读导航层失败，或枚举 nav-changes 失败。

    Side Effects:
        无（只读导航层和状态目录）。

    Time Semantics:
        撤回的预览阶段不持锁调用一次，写入作业持写锁时由 verify_preview_state 以撤回计划的预览状态再核对；
        本函数本身不读墙钟。
    """
    raise NotImplementedError


def plan_revert(
    nav_root: Path,
    paths: StatePaths,
    record: ChangeRecord,
    *,
    checkpoint: Callable[[], None],
) -> tuple[NavWritePlan, PlanReport]:
    """由变更记录生成反向计划（只读），当前状态必须等于 #N 的后像。

    Args:
        nav_root: 导航层根目录绝对路径。
        paths: 已初始化的状态布局，用来读旁路 blob。
        record: 被撤回作业的变更记录，outcome 必须是 COMMITTED。
        checkpoint: 必填的有界检查点。

    Returns:
        (反向计划, 报告)。反向计划的步骤是原步骤的逆序反演：write_file 写回前像全文（前像不存在则改成 remove_path）、set_link 改回前像目标
        （前像不存在则改成 remove_path）、make_dir 改成 remove_path(directory)、remove_path 改成按前像重建、
        move_path 挪回。计划的 operation 为 REVERT_CHANGE，reverts_job_id 为 record.job_id，
        预览状态按撤回当时的现状记录。

    Raises:
        ConflictError: 当前状态不等于 #N 的后像；诊断列出每一处差异（路径、预期、实际、之后改过它的作业）。
        InputError: record 结局不是 COMMITTED，或某步的前像正文既未内联也找不到旁路 blob（无法还原）。
        ExternalError: 读导航层或状态目录失败。
        JobCancelledError: 非保护段的 checkpoint 检出人为取消。
        WorkerStoppingError: 非保护段的 checkpoint 检出 worker 停止。

    Side Effects:
        无（只读）。

    Time Semantics:
        撤回预览作业调用，不持写锁；撤回本身是一次写导航层的作业，也有自己的写入日志和变更记录，
        执行时照常在写锁下核对预览状态，所以预览之后又被改动同样以冲突失败。
    """
    raise NotImplementedError
