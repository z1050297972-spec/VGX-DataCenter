"""写入日志 `nav-journal/<作业编号>/`（领域层，M1-07，ADR 0009 L13）。

只读写状态目录，不碰导航层。磁盘格式：

    nav-journal/<作业编号>/
        journal.json            # 完整的计划（Journal 的 JSON），先写 journal.json.tmp、fsync，再 rename
        images/<步骤序号>.before # 被覆盖的文件的前像原字节（链接、目录的前像直接记在 journal.json 里）

journal.json 一出现就是完整的；没有它（只有 .tmp 或空目录）说明日志没落完整，导航层一处都还没动。
日志不抄后像正文，只记后像哈希；正文在预览文件里。作业收尾时由 changes.archive_journal 归档后删除。
"""

import hashlib
import os
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from rdp.infra.state import StatePaths
from rdp.jobs.navwrite.errors import nav_conflict_error, nav_external_error, nav_input_error
from rdp.jobs.navwrite.models import (
    FileImage,
    MakeDirStep,
    MovePathStep,
    NavOperation,
    NavWritePlan,
    RemovePathStep,
    SetLinkStep,
    WriteFileStep,
)
from rdp.jobs.navwrite.policy import (
    JOURNAL_FILENAME,
    JOURNAL_FORMAT_VERSION,
    JOURNAL_IMAGES_DIRNAME,
    NAV_JOURNAL_DIRNAME,
)

_FROZEN = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)


class JournalStep(BaseModel):
    """写入日志里的一步：路径、前像、后像哈希；四种步骤共用一个平面结构。

    Attributes:
        model_config: 冻结，拒绝未知字段。
        index: 步骤序号，从 0 起，与计划里的顺序一致；回滚按序号从大到小。
        op: write_file、set_link、make_dir、move_path、remove_path 之一。
        path: 相对 nav_root 的 POSIX 路径。
        to_path: 仅 move_path 有值。
        entry_kind: 仅 move_path 与 remove_path 有值：directory、symlink、file。
        before_file: 仅 write_file 与 remove_path(file)：前像（存在与否、哈希、大小）。
        after_file: 仅 write_file：后像的哈希与大小。
        before_target: 仅 set_link 与 remove_path(symlink)：前像，os.readlink 的原样字符串；set_link 原来不存在为 None。
        after_target: 仅 set_link：后像目标。
        before_blob: 仅 write_file 或 remove_path(file) 且前像存在：前像原字节在日志目录里的相对路径 `images/<index>.before`。
    """

    model_config = _FROZEN
    index: int = Field(ge=0)
    op: Literal["write_file", "set_link", "make_dir", "move_path", "remove_path"]
    path: str = Field(min_length=1)
    to_path: str | None = None
    entry_kind: Literal["directory", "symlink", "file"] | None = None
    before_file: FileImage | None = None
    after_file: FileImage | None = None
    before_target: str | None = None
    after_target: str | None = None
    before_blob: str | None = None


class Journal(BaseModel):
    """一份完整的写入日志（journal.json 的内容）。

    Attributes:
        model_config: 冻结，拒绝未知字段。
        format_version: 固定 JOURNAL_FORMAT_VERSION。
        job_id: 写入作业编号，≥ 1，等于目录名与变更记录编号。
        operation: 操作种类。
        nav_root: 写入所针对的导航根绝对路径文本；恢复时核对与当前配置相同，不同则拒绝处理并列出。
        created_at: 落日志的 UTC 时刻（带时区）。
        dataset_ids: 受影响的永久编号。
        reverts_job_id: 撤回作业才有值。
        steps: 全部步骤，按执行顺序。
    """

    model_config = _FROZEN
    format_version: Literal[1] = 1
    job_id: int = Field(ge=1)
    operation: NavOperation
    nav_root: str = Field(min_length=1)
    created_at: datetime
    dataset_ids: tuple[str, ...]
    reverts_job_id: int | None = Field(default=None, ge=1)
    steps: tuple[JournalStep, ...]


@dataclass(frozen=True)
class JournalLocation:
    """状态目录里发现的一份写入日志目录。

    Attributes:
        job_id: 目录名解析出的作业编号，≥ 1。
        directory: 日志目录的绝对路径。
        complete: journal.json 是否存在；False 表示日志没落完整，导航层一处都还没动，可直接删除。
    """

    job_id: int
    directory: Path
    complete: bool


def journal_directory(paths: StatePaths, job_id: int) -> Path:
    """计算某个作业的写入日志目录，只计算、不创建。

    Args:
        paths: 已初始化的状态布局。
        job_id: 作业编号，≥ 1。

    Returns:
        `<状态目录>/nav-journal/<job_id>` 的绝对路径。

    Raises:
        InputError: job_id 不是 ≥ 1 的整数。

    Side Effects:
        无。

    Time Semantics:
        无；纯路径计算。
    """
    _check_job_id(job_id)
    return paths.nav_journal / str(job_id)


def write_journal(
    paths: StatePaths,
    plan: NavWritePlan,
    before_images: dict[int, bytes],
    job_id: int,
    created_at: datetime,
) -> Journal:
    """在改动导航层之前把计划落成写入日志并 fsync。

    Args:
        paths: 已初始化的状态布局。
        plan: 要执行的计划；步骤序号即其下标。
        before_images: 步骤序号到前像原字节的映射，必须覆盖每个"前像存在的 write_file"步骤，
            且字节的哈希等于 plan 里记的前像哈希；remove_path(file) 步骤同样需要；其余步骤不应出现。
        job_id: 写入作业编号，≥ 1；日志目录必须尚不存在。
        created_at: 落日志时刻，带时区，由注入时钟生成。

    Returns:
        已落盘的 Journal，与磁盘上的 journal.json 一致。

    Raises:
        ConflictError: 该作业的日志目录已存在（同一编号不应落两次）。
        InputError: before_images 缺项、多项或哈希与计划不符。
        ExternalError: 写目录、写文件、fsync 或 rename 失败；已落的部分被清掉，导航层未动。

    Side Effects:
        创建 nav-journal/<job_id>/images/*.before，先写 journal.json.tmp 并 fsync，再 rename 为
        journal.json，最后 fsync 目录。失败时删除整个日志目录，什么都不留。不写导航层。

    Time Semantics:
        调用方必须已持有导航层写锁，且已通过预览状态核对。journal.json 的 rename 是"计划生效"的时刻；
        在此之前断电，恢复时只会看到不完整的目录并直接删除。
    """
    _check_job_id(job_id)
    steps = _journal_steps(plan)
    _check_before_images(steps, before_images)
    directory = journal_directory(paths, job_id)
    journal = Journal(
        job_id=job_id,
        operation=plan.operation,
        nav_root=plan.state.nav_root,
        created_at=created_at,
        dataset_ids=plan.dataset_ids,
        reverts_job_id=plan.reverts_job_id,
        steps=steps,
    )
    try:
        directory.mkdir()
    except FileExistsError as error:
        problem = nav_conflict_error(
            "NAV_JOURNAL", "该作业的写入日志已经存在", objects=(("job_id", str(job_id)),)
        )
        raise problem from error
    except OSError as error:
        problem = nav_external_error(
            "NAV_JOURNAL", "无法创建写入日志目录", objects=(("job_id", str(job_id)),)
        )
        raise problem from error
    try:
        (directory / JOURNAL_IMAGES_DIRNAME).mkdir()
        for index, content in before_images.items():
            _write_durable(directory / JOURNAL_IMAGES_DIRNAME / f"{index}.before", content)
        encoded = journal.model_dump_json().encode("utf-8")
        temporary = directory / (JOURNAL_FILENAME + ".tmp")
        _write_durable(temporary, encoded)
        temporary.replace(directory / JOURNAL_FILENAME)
        _fsync_directory(directory)
        _fsync_directory(directory.parent)
    except OSError as error:
        shutil.rmtree(directory, ignore_errors=True)
        problem = nav_external_error(
            "NAV_JOURNAL",
            "写入日志落盘失败，已清理，导航层未动",
            objects=(("job_id", str(job_id)),),
        )
        raise problem from error
    return journal


def read_journal(directory: Path) -> Journal:
    """读取一份完整的写入日志。

    Args:
        directory: 日志目录的绝对路径，其中必须有 journal.json。

    Returns:
        Journal。

    Raises:
        InputError: journal.json 不存在、不是合法 JSON、format_version 不认识或字段不合格；
            此时不能自动回滚，调用方把它按"恢复失败"处理并保留目录。
        ExternalError: 读取时 I/O 失败。

    Side Effects:
        无（只读状态目录）。

    Time Semantics:
        同步读取；不读墙钟。
    """
    path = directory / JOURNAL_FILENAME
    try:
        content = path.read_bytes()
    except FileNotFoundError as error:
        problem = nav_input_error(
            "NAV_JOURNAL", "写入日志不完整或不存在", objects=(("directory", directory.name),)
        )
        raise problem from error
    except OSError as error:
        problem = nav_external_error(
            "NAV_JOURNAL", "读取写入日志失败", objects=(("directory", directory.name),)
        )
        raise problem from error
    try:
        return Journal.model_validate_json(content)
    except ValidationError as error:
        problem = nav_input_error(
            "NAV_JOURNAL",
            "写入日志损坏或版本不认识",
            expected=f"format_version={JOURNAL_FORMAT_VERSION}",
            objects=(("directory", directory.name),),
        )
        raise problem from error


def read_before_image(directory: Path, step: JournalStep) -> bytes:
    """读出某一步的前像原字节，供回滚和归档使用。

    Args:
        directory: 日志目录的绝对路径。
        step: 一个 write_file 或 remove_path(file) 步骤，其 before_blob 不为 None。

    Returns:
        前像原字节；其 sha256 等于 step.before_file.sha256。

    Raises:
        InputError: step 没有前像文件，或读到的字节哈希与日志记的不符（日志已损坏，不能用来回滚）。
        ExternalError: 读取时 I/O 失败。

    Side Effects:
        无（只读状态目录）。

    Time Semantics:
        同步读取；单个文件可达 14 MB 量级，不分块的一次读取是有意的，回滚需要整份内容。
    """
    if step.before_blob is None or step.before_file is None or step.before_file.sha256 is None:
        problem = nav_input_error(
            "NAV_JOURNAL", "这一步没有前像文件", objects=(("step_index", str(step.index)),)
        )
        raise problem
    path = directory / step.before_blob
    try:
        content = path.read_bytes()
    except FileNotFoundError as error:
        problem = nav_input_error(
            "NAV_JOURNAL", "前像文件丢失", objects=(("step_index", str(step.index)),)
        )
        raise problem from error
    except OSError as error:
        problem = nav_external_error(
            "NAV_JOURNAL", "读取前像文件失败", objects=(("step_index", str(step.index)),)
        )
        raise problem from error
    if hashlib.sha256(content).hexdigest() != step.before_file.sha256:
        problem = nav_input_error(
            "NAV_JOURNAL",
            "前像文件的哈希与日志记录不符，日志已损坏",
            objects=(("step_index", str(step.index)),),
        )
        raise problem
    return content


def list_journals(paths: StatePaths) -> tuple[JournalLocation, ...]:
    """列出状态目录里所有还在的写入日志目录。

    Args:
        paths: 已初始化的状态布局。

    Returns:
        按作业编号升序的 JournalLocation；目录不存在或为空时返回空元组。
        名字不是正整数的子目录被忽略，不删除。

    Raises:
        ExternalError: nav-journal 目录无法枚举。

    Side Effects:
        无（只读状态目录）。

    Time Semantics:
        同步；worker 启动时恢复流程调用一次，运行期间也供页面显示"有没有没收尾的写入"。
    """
    try:
        names = sorted(entry.name for entry in paths.nav_journal.iterdir())
    except FileNotFoundError:
        return ()
    except OSError as error:
        problem = nav_external_error("NAV_JOURNAL", "无法枚举写入日志目录")
        raise problem from error
    found: list[JournalLocation] = []
    for name in names:
        directory = paths.nav_journal / name
        if not (name.isascii() and name.isdecimal() and str(int(name)) == name and int(name) >= 1):
            continue
        if directory.is_symlink() or not directory.is_dir():
            continue
        found.append(
            JournalLocation(int(name), directory, (directory / JOURNAL_FILENAME).is_file())
        )
    return tuple(sorted(found, key=lambda item: item.job_id))


def discard_journal(directory: Path) -> None:
    """删除一份写入日志目录；只能在归档进变更记录之后，或日志本就不完整时调用。

    Args:
        directory: 日志目录的绝对路径，必须位于 nav-journal 之下。

    Returns:
        无；目录不存在时视为已完成（幂等）。

    Raises:
        InputError: directory 不在 nav-journal 之下。
        ExternalError: 删除失败；留下的残余仍能被 list_journals 看到，不会被误当成已收尾。

    Side Effects:
        递归删除该目录。先删 journal.json 再删其余，使半删状态读作"日志不完整"而不是"完整日志"。

    Time Semantics:
        同步；是作业收尾的提交点之一，崩溃恢复遵守 recovery.recover_journal 对"变更记录与日志并存"的规则。
    """
    if directory.parent.name != NAV_JOURNAL_DIRNAME or not directory.name.isdecimal():
        problem = nav_input_error(
            "NAV_JOURNAL",
            "只能删除 nav-journal 下的写入日志",
            objects=(("directory", directory.name),),
        )
        raise problem
    try:
        (directory / JOURNAL_FILENAME).unlink(missing_ok=True)
        if directory.exists():
            shutil.rmtree(directory)
    except OSError as error:
        problem = nav_external_error(
            "NAV_JOURNAL",
            "删除写入日志失败，残余日志仍会被恢复流程看到",
            objects=(("directory", directory.name),),
        )
        raise problem from error


def _check_job_id(job_id: int) -> None:
    """作业编号必须是 ≥ 1 的整数（拒绝 bool）。"""
    if type(job_id) is not int or job_id < 1:
        problem = nav_input_error("NAV_JOURNAL", "作业编号必须是不小于 1 的整数")
        raise problem


def _write_durable(path: Path, content: bytes) -> None:
    """写文件并 fsync；文件必须尚不存在。"""
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        view = memoryview(content)
        while view:
            written = os.write(descriptor, view)
            view = view[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _fsync_directory(directory: Path) -> None:
    """对目录做 fsync，让里面的新建和改名落盘。"""
    descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _journal_steps(plan: NavWritePlan) -> tuple[JournalStep, ...]:
    """把计划步骤摊平成日志步骤；不抄后像正文。"""
    steps: list[JournalStep] = []
    for index, step in enumerate(plan.steps):
        blob = f"{JOURNAL_IMAGES_DIRNAME}/{index}.before"
        match step:
            case WriteFileStep():
                steps.append(
                    JournalStep(
                        index=index,
                        op="write_file",
                        path=step.path,
                        before_file=step.before,
                        after_file=step.after,
                        before_blob=blob if step.before.exists else None,
                    )
                )
            case SetLinkStep():
                steps.append(
                    JournalStep(
                        index=index,
                        op="set_link",
                        path=step.path,
                        before_target=step.before_target,
                        after_target=step.after_target,
                    )
                )
            case MakeDirStep():
                steps.append(JournalStep(index=index, op="make_dir", path=step.path))
            case MovePathStep():
                steps.append(
                    JournalStep(
                        index=index,
                        op="move_path",
                        path=step.path,
                        to_path=step.to_path,
                        entry_kind=step.entry_kind,
                    )
                )
            case RemovePathStep():
                steps.append(
                    JournalStep(
                        index=index,
                        op="remove_path",
                        path=step.path,
                        entry_kind=step.entry_kind,
                        before_file=step.before_file,
                        before_target=step.before_target,
                        before_blob=blob
                        if step.before_file is not None and step.before_file.exists
                        else None,
                    )
                )
    return tuple(steps)


def _check_before_images(steps: tuple[JournalStep, ...], before_images: dict[int, bytes]) -> None:
    """前像字节必须正好覆盖需要前像文件的步骤，且哈希与计划相符。"""
    needed = {step.index: step for step in steps if step.before_blob is not None}
    if set(before_images) != set(needed):
        problem = nav_input_error(
            "NAV_JOURNAL",
            "前像字节与计划不符：缺项或多项",
            expected="、".join(str(i) for i in sorted(needed)) or "无",
            objects=(("given", "、".join(str(i) for i in sorted(before_images)) or "无"),),
        )
        raise problem
    for index, step in needed.items():
        image = step.before_file
        digest = hashlib.sha256(before_images[index]).hexdigest()
        if image is None or image.sha256 != digest or image.size_bytes != len(before_images[index]):
            problem = nav_input_error(
                "NAV_JOURNAL", "前像字节的哈希与计划不符", objects=(("step_index", str(index)),)
            )
            raise problem
