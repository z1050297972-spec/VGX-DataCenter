"""原子写与回滚（worker 写入侧，领域层，M1-07，ADR 0009 L13/L14）。

这是整个平台唯一真正改动导航层的地方。只写 nav_root，不写存储根、不改链接目标里的任何东西（规则 1）。
标准库 os.replace / os.symlink / os.fsync 够用（ADR 0009 Considered Options），不依赖 renameat2。
本模块没有决策逻辑：改什么由 NavWritePlan 决定，什么时候回滚由 pipeline 和 recovery 决定（规范 2.1）。
回滚和中断恢复共用同一个 rollback_journal，所以"中途失败"和"断电之后"的退回行为完全一致。
"""

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from rdp.jobs.navwrite.journal import Journal, JournalStep
from rdp.jobs.navwrite.models import MismatchItem, NavWritePlan


class StepDisk(StrEnum):
    """一步在磁盘上的现状，相对该步的前像和后像而言。

    Attributes:
        BEFORE: before，等于前像（包括前后像相同的空操作步骤）：不用动。
        AFTER: after，等于后像：需要退回前像。
        NEITHER: neither，两者都不是（多半是有人在终端里改过）：不敢动，要列出。
    """

    BEFORE = "before"
    AFTER = "after"
    NEITHER = "neither"


@dataclass(frozen=True)
class StepObservation:
    """对一步的磁盘现状的观察结果。

    Attributes:
        disk: 现状属于前像、后像还是都不是。
        actual: 现状的文字描述（哈希前缀、链接目标、"不存在"、"读取失败：原因"），非空，不含正文。
    """

    disk: StepDisk
    actual: str


@dataclass(frozen=True)
class RollbackOutcome:
    """一份写入日志回滚的结果。

    Attributes:
        restored_steps: 已退回前像的步骤序号，按退回顺序（从大到小）。
        untouched_steps: 本来就等于前像、没动的步骤序号。
        mismatches: 两者都不是、因此没有动的项；为空表示完全退回。
        failed_steps: 判定为后像、但退回动作本身失败的步骤序号（例如权限错误）；这些项也带在 mismatches 里。
    """

    restored_steps: tuple[int, ...]
    untouched_steps: tuple[int, ...]
    mismatches: tuple[MismatchItem, ...]
    failed_steps: tuple[int, ...]


def capture_before_images(nav_root: Path, plan: NavWritePlan) -> dict[int, bytes]:
    """读出计划里每个"前像存在的 write_file 或 remove_path(file)"步骤现在的原字节，供落日志。

    Args:
        nav_root: 导航层根目录绝对路径。
        plan: 要执行的计划，且预览状态已在写锁下核对通过。

    Returns:
        步骤序号到原字节的映射；只含需要前像文件的步骤。

    Raises:
        ConflictError: 某文件现在的哈希与计划里的前像哈希不同（核对与读取之间被改，或手工修改）；一行都没写。
        ExternalError: 读取失败。

    Side Effects:
        无（只读导航层，用 O_NOFOLLOW 打开，不跟随软链接）。

    Time Semantics:
        调用方必须已持有导航层写锁，并在 verify_preview_state 之后、write_journal 之前调用。
    """
    raise NotImplementedError


def apply_plan(
    nav_root: Path,
    plan: NavWritePlan,
    job_id: int,
    *,
    checkpoint: Callable[[], None],
) -> None:
    """按计划逐步写入导航层；任何一步失败就停下并抛出，由调用方回滚。

    Args:
        nav_root: 导航层根目录绝对路径。
        plan: 要执行的计划；其写入日志已由 write_journal 落盘。
        job_id: 写入作业编号，用于临时文件命名 `.<名>.rdp-<job_id>-<序号>.tmp`。
        checkpoint: 必填检查点；写锁内由框架延后取消和停止控制异常，所以这里实际只在步骤之间被调用。

    Returns:
        无；全部步骤成功才返回。

    Raises:
        ExternalError: 任一步 I/O 失败（磁盘满、权限、目标父目录不存在）。诊断写明是第几步、哪个路径。
            已完成的步骤保持原样，不在这里回滚。
        InputError: 步骤里的路径逃逸 nav_root 或经过软链接。

    Side Effects:
        write_file：写同目录临时文件、fsync、os.replace、fsync 目录。set_link：先建到临时名，再 os.replace 盖过去。
        make_dir：os.mkdir（父目录必须已存在）。move_path：os.rename，同一文件系统。
        remove_path：先核对前像再 os.unlink / os.rmdir，目录必须已空。
        失败时遗留的临时文件按命名留给 rollback_journal 清理。只写 nav_root 之下，不写存储根。

    Time Semantics:
        调用方持有导航层写锁，整个调用在 worker 30 秒停止预算内完成（每步有界）。
        步骤按计划顺序串行执行，不并行；每步完成后才进入下一步。
    """
    raise NotImplementedError


def observe_step(nav_root: Path, step: JournalStep) -> StepObservation:
    """观察某一步现在在磁盘上是前像、后像还是都不是。

    Args:
        nav_root: 导航层根目录绝对路径。
        step: 写入日志里的一步。

    Returns:
        StepObservation。write_file 比哈希（不存在对应前像"文件不存在"）；set_link 比 readlink 原样字符串；
        make_dir 比"目录存在且为空"与"不存在"；move_path 比来源与目标各自是否存在；
        remove_path 的前像是"对象存在且与记录一致"，后像是"不存在"。
        前后像相同的步骤读作 BEFORE。无法读取（权限等）读作 NEITHER 并在 actual 写原因。

    Raises:
        InputError: step 的路径逃逸 nav_root。

    Side Effects:
        无（只读导航层，不跟随软链接）。

    Time Semantics:
        同步；中断恢复在 worker 启动时调用，运行期回滚在写锁内调用。
    """
    raise NotImplementedError


def rollback_journal(
    nav_root: Path,
    directory: Path,
    journal: Journal,
    *,
    checkpoint: Callable[[], None],
) -> RollbackOutcome:
    """按写入日志逆序退回：等于后像的退回前像，等于前像的不动，两者都不是的列出来。

    Args:
        nav_root: 导航层根目录绝对路径，必须等于 journal.nav_root。
        directory: 该日志的目录，用来读前像原字节。
        journal: 完整的写入日志。
        checkpoint: 必填检查点；回滚不可被取消打断，调用方在 worker 启动阶段或写锁内传入不抛异常的检查点。

    Returns:
        RollbackOutcome。有对不上的项时，能退回的照样退回，退不回的列进 mismatches，不中止后面的步骤（M1-07 工单执行线定的第 4 点）。
        还会清理本作业遗留的 `.rdp-<job_id>-*.tmp` 临时文件。已回滚过的日志再次回滚结果相同（幂等）。

    Raises:
        InputError: nav_root 与 journal.nav_root 不同，或前像文件已损坏（哈希对不上）。
        ExternalError: 无法枚举目录以清理临时文件。单步退回失败不抛，记进 failed_steps 和 mismatches。

    Side Effects:
        write_file 退回：前像存在则原子写回前像字节，不存在则删除该文件。set_link 退回：前像存在则原子改回，
        不存在则删除链接。make_dir 退回：仅目录为空才 rmdir。move_path 退回：改名挪回。remove_path 退回：按前像重建
        （文件从前像原字节原子写回，链接重建，目录 mkdir）。
        不删日志目录，归档和删除由调用方负责。只写 nav_root 之下。

    Time Semantics:
        同步串行，序号从大到小。调用方：写入作业在写锁内（同一次持锁），启动恢复在 worker 单实例锁内、
        作业循环领取之前。
    """
    raise NotImplementedError
