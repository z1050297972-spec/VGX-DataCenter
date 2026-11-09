"""清洗专用只读边界与输入展开；沿用 datasets._readonly 的 EPERM 回退规则。

这里需要把 O_NOATIME 回退作为报告诊断返回，现有 open_fd 没有该出口，故局部实现打开。
使用标准库 scandir/realpath，路径排序按分量比较以对应 Rust PathBuf。
"""

import errno
import os
from collections.abc import Callable, Generator, Iterator, Sequence
from pathlib import Path

from rdp.infra.diagnostics import (
    Diagnostic,
    DiagnosticCategory,
    DiagnosticLevel,
    DiagnosticObject,
    InputError,
)

# 报告必须能整体序列化；上限是平台内存保护，不是工具的清洗阈值。
MAX_INPUT_FILES = 10_000
MAX_CONFIG_BYTES = 1024 * 1024


def diagnostic(
    rule: str, actual: str, *, path: Path, topic: str | None = None, fatal: bool = True
) -> Diagnostic:
    """构造带文件和可选话题身份的既有诊断对象。"""
    objects = (DiagnosticObject(key="file", value=str(path)),)
    if topic is not None:
        objects += (DiagnosticObject(key="topic", value=topic),)
    return Diagnostic(
        level=DiagnosticLevel.ERROR if fatal else DiagnosticLevel.WARNING,
        category=DiagnosticCategory.INPUT,
        stage="清洗预览",
        source="平台",
        objects=objects,
        rule=rule,
        actual=actual,
        expected="符合登记工具配置及清洗规则",
        consequence="该文件默认剔除，其他文件继续" if fatal else "保留检查结果并提示人工核对",
        next_step=(
            "可把录制拆成更短的文件后重新预览"
            if rule
            in ("cleaning.message_limit", "cleaning.cache_limit", "cleaning.alignment_limit")
            else "核对该文件和话题，修复数据或调整已登记的规则后重新预览"
        ),
    )


def open_readonly(path: Path, warnings: list[Diagnostic], *, directory: bool = False) -> int:
    """只读打开并返回描述符；O_NOATIME 仅因 EPERM 回退且记录后果。"""
    flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NONBLOCK
    if directory:
        flags |= os.O_DIRECTORY | os.O_NOFOLLOW
    try:
        return os.open(path, flags | os.O_NOATIME)
    except OSError as error:
        if error.errno != errno.EPERM:
            raise
        warnings.append(
            diagnostic(
                "cleaning.noatime_fallback",
                "O_NOATIME 权限不足，已退回只读打开；文件系统可能更新访问时间",
                path=path,
                fatal=False,
            )
        )
        return os.open(path, flags)


def read_config_bytes(path: Path) -> bytes:
    """配置最多读取 1 MiB，拒绝异常大小，避免 TOML 全量解析无界。"""
    try:
        with path.open("rb") as stream:
            content = stream.read(MAX_CONFIG_BYTES + 1)
        if len(content) > MAX_CONFIG_BYTES:
            raise ValueError("配置超过 1 MiB")
        return content
    except (OSError, ValueError) as error:
        raise InputError((diagnostic("cleaning.config_read", str(error), path=path),)) from error


def collect_inputs(
    inputs: Sequence[tuple[str, Path]], checkpoint: Callable[[], None]
) -> tuple[list[tuple[str, Path]], list[Diagnostic]]:
    """展开并按 realpath 去重保留首次身份；目录软链接跳过警告，区别于 Rust 跟随。"""
    files: list[tuple[str, Path]] = []
    warnings: list[Diagnostic] = []
    seen: set[str] = set()
    for source_id, original in inputs:
        checkpoint()
        path = original.absolute()
        if path.is_symlink() and path.is_dir():
            warnings.append(_symlink_warning(path))
            continue
        found = _find_mcap(path, warnings, checkpoint) if path.is_dir() else [path]
        for file in found:
            canonical = os.path.realpath(file)
            if canonical not in seen:
                seen.add(canonical)
                files.append((source_id, file))
            _check_file_limit(len(files), path)
    return files, warnings


def _find_mcap(
    root: Path, warnings: list[Diagnostic], checkpoint: Callable[[], None]
) -> list[Path]:
    """迭代 scandir，不跟随目录软链接，检查点放在异常转换范围之外。"""
    found: list[Path] = []
    pending = [root]
    while pending:
        checkpoint()
        directory = pending.pop()
        entries = _directory_entries(directory, warnings)
        try:
            _collect_entries(entries, directory, (pending, found, warnings), checkpoint)
        finally:
            entries.close()
    if not found:
        raise InputError((diagnostic("cleaning.empty_directory", "目录内没有 MCAP", path=root),))
    found.sort(key=lambda item: tuple(os.fsencode(p) for p in item.parts))
    return found


def _collect_entries(
    entries: Iterator[os.DirEntry[str]],
    directory: Path,
    buffers: tuple[list[Path], list[Path], list[Diagnostic]],
    checkpoint: Callable[[], None],
) -> None:
    """每次只保留一个目录条目；显式限制待遍历目录和候选文件数。"""
    pending, found, warnings = buffers
    for entry in entries:
        checkpoint()
        path = directory / entry.name
        if entry.is_symlink() and entry.is_dir():
            warnings.append(_symlink_warning(path))
        elif entry.is_dir(follow_symlinks=False):
            pending.append(path)
        elif path.suffix.lower() == ".mcap":
            found.append(path)
        _check_file_limit(len(pending) + len(found) + len(warnings), directory)


def _directory_entries(path: Path, warnings: list[Diagnostic]) -> Generator[os.DirEntry[str]]:
    """把目录读取异常限制在生成器内，调用方回调异常不会被误记为数据错误。"""
    try:
        descriptor = open_readonly(path, warnings, directory=True)
        try:
            with os.scandir(descriptor) as entries:
                yield from entries
        finally:
            os.close(descriptor)
    except OSError as error:
        raise InputError((diagnostic("cleaning.inputs", str(error), path=path),)) from error


def _check_file_limit(count: int, path: Path) -> None:
    """超出容量时拒绝整次展开，不能悄悄截断用户选择。"""
    if count > MAX_INPUT_FILES:
        raise InputError((diagnostic("cleaning.input_limit", "输入条目超过 10000", path=path),))


def _symlink_warning(path: Path) -> Diagnostic:
    """记录跳过目录软链接，便于调用方解释与工具展开结果的差异。"""
    return diagnostic("cleaning.directory_symlink", "跳过指向目录的软链接", path=path, fatal=False)
