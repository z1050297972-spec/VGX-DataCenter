"""原子写与回滚（worker 写入侧，领域层，M1-07，ADR 0009 L13/L14）。

这是整个平台唯一真正改动导航层的地方。只写 nav_root，不写存储根、不改链接目标里的任何东西（规则 1）。
标准库 os.replace / os.symlink / os.fsync 够用（ADR 0009 Considered Options），不依赖 renameat2。
本模块没有决策逻辑：改什么由 NavWritePlan 决定，什么时候回滚由 pipeline 和 recovery 决定（规范 2.1）。
回滚和中断恢复共用同一个 rollback_journal，所以"中途失败"和"断电之后"的退回行为完全一致。
"""

import fnmatch
import hashlib
import os
import stat
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path, PurePosixPath

from rdp.infra.diagnostics import DefectError
from rdp.jobs.navwrite.errors import (
    Advice,
    nav_conflict_error,
    nav_external_error,
    nav_input_error,
)
from rdp.jobs.navwrite.journal import Journal, JournalStep, read_before_image
from rdp.jobs.navwrite.models import (
    FileImage,
    MakeDirStep,
    MismatchItem,
    MovePathStep,
    NavWritePlan,
    RemovePathStep,
    SetLinkStep,
    Step,
    WriteFileStep,
)
from rdp.jobs.navwrite.policy import TEMP_NAME_TEMPLATE

_RULE = "NAV_ATOMIC"
# _link_target 对"存在但不是软链接"返回的哨兵文本，不会和真实 readlink 结果混淆（含不可见字符）。
_NOT_A_LINK = "\x00not-a-link"
# 新建文件的权限；已有文件替换时沿用原文件的权限。
_NEW_FILE_MODE = 0o644
_READ_CHUNK = 1024 * 1024


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
        ConflictError: 某文件现在的哈希与计划里的前像哈希不同（核对与读取之间被改，或手工修改），
            或计划要新建的文件已经存在；一行都没写。
        ExternalError: 读取失败。

    Side Effects:
        无（只读导航层，用 O_NOFOLLOW 打开，不跟随软链接）。

    Time Semantics:
        调用方必须已持有导航层写锁，并在 verify_preview_state 之后、write_journal 之前调用。
    """
    images: dict[int, bytes] = {}
    for index, step in enumerate(plan.steps):
        match step:
            case WriteFileStep():
                path = _locate(nav_root, step.path)
                if step.before.exists:
                    images[index] = _read_checked(path, step.before, index, step.path)
                elif path.exists() or path.is_symlink():
                    problem = nav_conflict_error(
                        _RULE,
                        "计划要新建的文件已经存在",
                        objects=(("step_index", str(index)), ("path", step.path)),
                    )
                    raise problem
            case RemovePathStep() if step.entry_kind == "file" and step.before_file is not None:
                path = _locate(nav_root, step.path)
                if step.before_file.exists:
                    images[index] = _read_checked(path, step.before_file, index, step.path)
            case _:
                _locate(nav_root, step.path)
    return images


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
    for step in plan.steps:
        _locate(nav_root, step.path)
        if isinstance(step, MovePathStep):
            _locate(nav_root, step.to_path)
    for index, step in enumerate(plan.steps):
        checkpoint()
        try:
            _apply_step(nav_root, step, job_id, index)
        except OSError as error:
            problem = nav_external_error(
                _RULE,
                f"第 {index} 步写入失败：{type(error).__name__}",
                objects=(("step_index", str(index)), ("path", step.path)),
                advice=Advice(
                    "已完成的步骤保持原样，由调用方按写入日志退回", "检查导航层所在磁盘后重试"
                ),
            )
            raise problem from error


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
    path = _locate(nav_root, step.path)
    match step.op:
        case "write_file":
            return _observe_write(path, step)
        case "set_link":
            return _observe_link(path, step)
        case "make_dir":
            return _observe_dir(path)
        case "move_path":
            return _observe_move(path, _locate(nav_root, _required(step.to_path)))
        case "remove_path":
            if not path.exists() and not path.is_symlink():
                return StepObservation(StepDisk.AFTER, "不存在")
            return _observe_removed(path, step)


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
    if str(nav_root) != journal.nav_root:
        problem = nav_input_error(
            _RULE,
            "写入日志属于另一个导航根，不能用它回滚这棵树",
            objects=(("journal_nav_root", journal.nav_root), ("nav_root", str(nav_root))),
        )
        raise problem
    images = {
        step.index: read_before_image(directory, step)
        for step in journal.steps
        if step.before_blob is not None
    }
    # 临时文件从不是权威内容：先清掉，免得它们让 make_dir 的"目录为空"判断误判。
    _remove_temp_files(nav_root, journal)
    restored: list[int] = []
    untouched: list[int] = []
    failed: list[int] = []
    mismatches: list[MismatchItem] = []
    for step in sorted(journal.steps, key=lambda item: item.index, reverse=True):
        checkpoint()
        observation = observe_step(nav_root, step)
        if observation.disk is StepDisk.BEFORE:
            untouched.append(step.index)
            continue
        if observation.disk is StepDisk.AFTER:
            try:
                _restore(nav_root, step, images.get(step.index), journal.job_id)
            except OSError as error:
                failed.append(step.index)
                mismatches.append(_mismatch(journal, step, f"退回失败：{type(error).__name__}"))
            else:
                restored.append(step.index)
            continue
        mismatches.append(_mismatch(journal, step, observation.actual))
    _remove_temp_files(nav_root, journal)
    return RollbackOutcome(tuple(restored), tuple(untouched), tuple(mismatches), tuple(failed))


def _locate(nav_root: Path, relative: str) -> Path:
    """把步骤里的相对路径解析成 nav_root 下的绝对路径；逃逸或经过软链接就拒绝。"""
    pure = PurePosixPath(relative)
    if (
        not relative
        or pure.is_absolute()
        or ".." in pure.parts
        or "." in pure.parts
        or "\x00" in relative
    ):
        problem = nav_input_error(
            _RULE, "步骤路径必须是 nav_root 之下的相对路径", objects=(("path", relative),)
        )
        raise problem
    current = nav_root
    for part in pure.parts[:-1]:
        current = current / part
        try:
            mode = os.lstat(current).st_mode
        except FileNotFoundError:
            continue  # 目录尚不存在：由写入步骤自己报错，或由前面的 make_dir 创建
        except OSError as error:
            problem = nav_external_error(_RULE, "无法检查路径分量", objects=(("path", relative),))
            raise problem from error
        if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
            problem = nav_input_error(
                _RULE, "路径经过软链接或非目录，拒绝写入", objects=(("path", relative),)
            )
            raise problem
    return nav_root / relative


def _read_checked(path: Path, image: FileImage, index: int, relative: str) -> bytes:
    """读出文件原字节并核对前像哈希；不跟随软链接。"""
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError as error:
        problem = nav_conflict_error(
            _RULE,
            "前像文件现在读不了或不存在",
            objects=(("step_index", str(index)), ("path", relative)),
        )
        raise problem from error
    try:
        chunks: list[bytes] = []
        while block := os.read(descriptor, _READ_CHUNK):
            chunks.append(block)
    except OSError as error:
        problem = nav_external_error(
            _RULE, "读取前像文件失败", objects=(("step_index", str(index)), ("path", relative))
        )
        raise problem from error
    finally:
        os.close(descriptor)
    content = b"".join(chunks)
    if hashlib.sha256(content).hexdigest() != image.sha256 or len(content) != image.size_bytes:
        problem = nav_conflict_error(
            _RULE,
            "文件现在的内容与计划里的前像不同",
            objects=(("step_index", str(index)), ("path", relative)),
        )
        raise problem
    return content


def _fsync_directory(directory: Path) -> None:
    """对目录做 fsync，使新建、改名、删除落盘。"""
    descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _temp_name(path: Path, job_id: int, index: int) -> Path:
    """同目录、按命名认得出的临时路径。"""
    return path.with_name(TEMP_NAME_TEMPLATE.format(name=path.name, job_id=job_id, index=index))


def _atomic_write(path: Path, content: bytes, job_id: int, index: int) -> None:
    """同目录临时文件 → fsync → os.replace → fsync 目录；已有文件沿用其权限。"""
    if path.is_symlink() or path.is_dir():
        raise OSError(21, "目标不是普通文件")
    try:
        mode = stat.S_IMODE(path.stat().st_mode)
    except FileNotFoundError:
        mode = _NEW_FILE_MODE
    temporary = _temp_name(path, job_id, index)
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, mode)
    try:
        view = memoryview(content)
        while view:
            view = view[os.write(descriptor, view) :]
        os.fchmod(descriptor, mode)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    temporary.replace(path)
    _fsync_directory(path.parent)


def _atomic_link(path: Path, target: str, job_id: int, index: int) -> None:
    """链接先建到临时名，再 rename 盖过去。"""
    temporary = _temp_name(path, job_id, index)
    temporary.unlink(missing_ok=True)
    temporary.symlink_to(target)
    temporary.replace(path)
    _fsync_directory(path.parent)


def _remove(nav_root: Path, step: RemovePathStep, index: int) -> None:
    """核对前像后删除；目录必须已空，从不递归。"""
    path = _locate(nav_root, step.path)
    problem = nav_conflict_error(
        _RULE,
        "要删除的对象与计划里的前像不同",
        objects=(("step_index", str(index)), ("path", step.path)),
    )
    if step.entry_kind == "file":
        digest, _text = _file_digest(path)
        if step.before_file is None or not _matches_image(digest, step.before_file):
            raise problem
        path.unlink()
    elif step.entry_kind == "symlink":
        if _link_target(path) != step.before_target:
            raise problem
        path.unlink()
    else:
        if path.is_symlink() or not path.is_dir():
            raise problem
        path.rmdir()
    _fsync_directory(path.parent)


def _file_digest(path: Path) -> tuple[str | None, str]:
    """现状的文件摘要和描述；不存在返回 (None, "文件不存在")，不可读或不是普通文件给出原因。"""
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return None, "文件不存在"
    except OSError as error:
        return "<unreadable>", f"读取失败：{type(error).__name__}"
    if not stat.S_ISREG(info.st_mode):
        return "<not-regular>", "存在但不是普通文件"
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError as error:
        return "<unreadable>", f"读取失败：{type(error).__name__}"
    digest = hashlib.sha256()
    try:
        while block := os.read(descriptor, _READ_CHUNK):
            digest.update(block)
    except OSError as error:
        return "<unreadable>", f"读取失败：{type(error).__name__}"
    finally:
        os.close(descriptor)
    value = digest.hexdigest()
    return value, f"sha256 {value[:12]}"


def _matches_image(actual: str | None, image: FileImage) -> bool:
    """现状摘要是否等于一个文件像；不存在对应 exists=False。"""
    if actual is None:
        return not image.exists
    return image.exists and actual == image.sha256


def _link_target(path: Path) -> str | None:
    """软链接目标原样；不存在为 None；存在但不是链接给哨兵文本。"""
    try:
        return str(path.readlink())
    except FileNotFoundError:
        return None
    except OSError:
        return _NOT_A_LINK


def _observe_removed(path: Path, step: JournalStep) -> StepObservation:
    """remove_path 的对象还在：与记录一致读作 BEFORE，否则 NEITHER。"""
    if step.entry_kind == "file":
        actual, text = _file_digest(path)
        before = step.before_file
        if before is not None and _matches_image(actual, before):
            return StepObservation(StepDisk.BEFORE, text)
        return StepObservation(StepDisk.NEITHER, text)
    if step.entry_kind == "symlink":
        current = _link_target(path)
        text = "存在但不是软链接" if current == _NOT_A_LINK else f"指向 {current}"
        disk = StepDisk.BEFORE if current == step.before_target else StepDisk.NEITHER
        return StepObservation(disk, text)
    if path.is_dir() and not path.is_symlink():
        return StepObservation(StepDisk.BEFORE, "目录存在")
    return StepObservation(StepDisk.NEITHER, "存在但不是目录")


def _restore(nav_root: Path, step: JournalStep, image: bytes | None, job_id: int) -> None:
    """把判定为后像的一步退回前像。"""
    path = _locate(nav_root, step.path)
    match step.op:
        case "write_file":
            if image is None:
                path.unlink()
                _fsync_directory(path.parent)
            else:
                _atomic_write(path, image, job_id, step.index)
        case "set_link":
            if step.before_target is None:
                path.unlink()
                _fsync_directory(path.parent)
            else:
                _atomic_link(path, step.before_target, job_id, step.index)
        case "make_dir":
            path.rmdir()
            _fsync_directory(path.parent)
        case "move_path":
            target = _locate(nav_root, _required(step.to_path))
            target.rename(path)
            _fsync_directory(path.parent)
            _fsync_directory(target.parent)
        case "remove_path":
            if step.entry_kind == "file":
                image = _required(image)
                _atomic_write(path, image, job_id, step.index)
            elif step.entry_kind == "symlink":
                _atomic_link(path, _required(step.before_target), job_id, step.index)
            else:
                path.mkdir()
                _fsync_directory(path.parent)


def _describe_before(step: JournalStep) -> str:
    """前像的文字描述，不含正文。"""
    match step.op:
        case "write_file":
            image = step.before_file
            return f"sha256 {image.sha256[:12]}" if image and image.sha256 else "文件不存在"
        case "set_link":
            return f"指向 {step.before_target}" if step.before_target else "不存在"
        case "make_dir":
            return "不存在"
        case "move_path":
            return "来源在，目标不在"
        case "remove_path":
            return "对象存在且与记录一致"


def _describe_after(step: JournalStep) -> str:
    """后像的文字描述，不含正文。"""
    match step.op:
        case "write_file":
            image = step.after_file
            return f"sha256 {image.sha256[:12]}" if image and image.sha256 else "文件不存在"
        case "set_link":
            return f"指向 {step.after_target}"
        case "make_dir":
            return "空目录"
        case "move_path":
            return "目标在，来源不在"
        case "remove_path":
            return "不存在"


def _mismatch(journal: Journal, step: JournalStep, actual: str) -> MismatchItem:
    """一项对不上或退不回的步骤。"""
    return MismatchItem(
        job_id=journal.job_id,
        step_index=step.index,
        path=step.path,
        expected_before=_describe_before(step),
        expected_after=_describe_after(step),
        actual=actual,
    )


def _remove_temp_files(nav_root: Path, journal: Journal) -> None:
    """清理本作业遗留的 .rdp-<job_id>-*.tmp 临时文件。"""
    pattern = f".*.rdp-{journal.job_id}-*.tmp"
    directories: set[Path] = set()
    for step in journal.steps:
        for relative in (step.path, step.to_path):
            if relative is not None:
                directories.add(_locate(nav_root, relative).parent)
    for directory in sorted(directories):
        try:
            names = [entry.name for entry in directory.iterdir()]
        except FileNotFoundError:
            continue
        except OSError as error:
            problem = nav_external_error(
                _RULE, "无法枚举目录以清理临时文件", objects=(("directory", directory.name),)
            )
            raise problem from error
        for name in fnmatch.filter(names, pattern):
            try:
                (directory / name).unlink()
            except OSError as error:
                problem = nav_external_error(_RULE, "无法删除临时文件", objects=(("file", name),))
                raise problem from error


def _apply_step(nav_root: Path, step: Step, job_id: int, index: int) -> None:
    """执行计划里的一步；OSError 由调用方统一包装。"""
    match step:
        case WriteFileStep():
            _atomic_write(
                _locate(nav_root, step.path), step.after_content.encode("utf-8"), job_id, index
            )
        case SetLinkStep():
            _atomic_link(_locate(nav_root, step.path), step.after_target, job_id, index)
        case MakeDirStep():
            path = _locate(nav_root, step.path)
            path.mkdir()
            _fsync_directory(path.parent)
        case MovePathStep():
            source, target = _locate(nav_root, step.path), _locate(nav_root, step.to_path)
            if target.exists() or target.is_symlink():
                raise FileExistsError(17, "目标已存在，不覆盖")
            source.rename(target)
            _fsync_directory(source.parent)
            _fsync_directory(target.parent)
        case RemovePathStep():
            _remove(nav_root, step, index)


def _observe_write(path: Path, step: JournalStep) -> StepObservation:
    """write_file：比哈希；前后像相同读作 BEFORE。"""
    actual, text = _file_digest(path)
    if step.before_file is not None and _matches_image(actual, step.before_file):
        return StepObservation(StepDisk.BEFORE, text)
    if step.after_file is not None and _matches_image(actual, step.after_file):
        return StepObservation(StepDisk.AFTER, text)
    return StepObservation(StepDisk.NEITHER, text)


def _observe_link(path: Path, step: JournalStep) -> StepObservation:
    """set_link：比 readlink 原样字符串。"""
    current = _link_target(path)
    if current == _NOT_A_LINK:
        return StepObservation(StepDisk.NEITHER, "存在但不是软链接")
    text = f"指向 {current}" if current is not None else "不存在"
    if current == step.before_target:
        return StepObservation(StepDisk.BEFORE, text)
    if current == step.after_target:
        return StepObservation(StepDisk.AFTER, text)
    return StepObservation(StepDisk.NEITHER, text)


def _observe_dir(path: Path) -> StepObservation:
    """make_dir：不存在为前像，空目录为后像，非空或不是目录都不是。"""
    if not path.exists() and not path.is_symlink():
        return StepObservation(StepDisk.BEFORE, "不存在")
    if path.is_symlink() or not path.is_dir():
        return StepObservation(StepDisk.NEITHER, "存在但不是目录")
    try:
        empty = not any(path.iterdir())
    except OSError as error:
        return StepObservation(StepDisk.NEITHER, f"读取失败：{type(error).__name__}")
    if empty:
        return StepObservation(StepDisk.AFTER, "空目录")
    return StepObservation(StepDisk.NEITHER, "目录非空")


def _observe_move(source: Path, target: Path) -> StepObservation:
    """move_path：来源与目标各自是否存在。"""
    source_exists = source.exists() or source.is_symlink()
    target_exists = target.exists() or target.is_symlink()
    text = f"来源{'在' if source_exists else '不在'}，目标{'在' if target_exists else '不在'}"
    if source_exists and not target_exists:
        return StepObservation(StepDisk.BEFORE, text)
    if target_exists and not source_exists:
        return StepObservation(StepDisk.AFTER, text)
    return StepObservation(StepDisk.NEITHER, text)


def _required[T](value: T | None) -> T:
    """日志里本步骤类型必然有的字段；缺失说明日志被改坏，属于程序缺陷。"""
    if value is None:
        raise DefectError
    return value
