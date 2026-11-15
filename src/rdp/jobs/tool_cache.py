"""工具缓存的本地文件系统边界（领域层，M4.6-02），不读工具本体或数据集。

使用标准库 dir_fd/O_NOFOLLOW 逐层操作；pathlib.mkdir(parents=True) 会跟随中间链接，
现有下载私有助手也不提供本票的 0700 创建契约，因此在此集中缓存目录和结果文件操作。
"""

import os
import stat
from collections.abc import Generator
from contextlib import contextmanager, suppress
from pathlib import Path

from pydantic import TypeAdapter, ValidationError

from rdp.infra.config import ToolsConfig
from rdp.infra.diagnostics import (
    DefectError,
    Diagnostic,
    DiagnosticCategory,
    DiagnosticLevel,
    DiagnosticObject,
    ExternalError,
)
from rdp.tools.manifest import ToolIdentity

# 清单是名字规则的唯一来源；只复用该字段的类型和约束，不伪造完整的工具身份。
_TOOL_NAME = TypeAdapter[str](ToolIdentity.model_fields["name"].rebuild_annotation())
_DIRECTORY_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC


def tool_cache_dir(settings: ToolsConfig, tool_name: str) -> Path:
    """准备工具专属的私有缓存目录，拒绝路径上的任何符号链接。

    Args:
        settings: 已加载的工具配置；cache_root 为不含 NUL 或 .. 的绝对路径。
        tool_name: 清单规定的输入2输出[-变体] 名称，仅 ASCII 小写字母、数字及变体连字符。

    Returns:
        cache_root/tool_name 的绝对路径，所有分量均为真实目录。

    Raises:
        DefectError: tool_name 不符合清单规则，或 cache_root 不是合法的绝对路径。
        ExternalError: 任一分量是链接、非目录，或创建、打开失败；携带路径的五段诊断。

    Side Effects:
        缺失的目录逐层以 0700 创建，已有目录权限不变；失败时保留已创建的空目录。
        不访问工具程序、导航层或数据集。

    Time Semantics:
        同步访问本机状态盘，无轮询或重试；调用方须把 cache_root 配置在本地磁盘。
    """
    try:
        _TOOL_NAME.validate_python(tool_name, strict=True)
    except ValidationError as error:
        raise DefectError() from error
    path = settings.cache_root / tool_name
    _validate_path(path)
    try:
        with _directory(path, create=True):
            pass
    except OSError as error:
        raise ExternalError(_cache_diagnostics(path, str(error))) from error
    return path


def result_file(cache: Path, job_id: int) -> Path:
    """清除同作业的旧预览结果文件，并返回工具将要新建的结果路径。

    Args:
        cache: tool_cache_dir 返回的已存在缓存目录，绝对路径且不含 NUL 或 ..。
        job_id: 平台作业编号，严格正整数；调用方保证该作业不会并发写同一个结果文件。

    Returns:
        cache/preview-<job_id>.json 的绝对路径；本函数不创建文件。

    Raises:
        DefectError: cache 路径形式非法，或 job_id 不是严格正整数。
        ExternalError: 缓存路径含链接或非目录，结果路径不是普通文件，或读取元信息、删除失败。

    Side Effects:
        若旧结果是普通文件则删除；不跟随符号链接，不删除目录或链接。
        失败时不新建结果文件；已删除的旧结果不恢复。

    Time Semantics:
        在启动工具之前调用，同步访问本地缓存，不等待结果产生，不轮询或重试。
    """
    _validate_path(cache)
    if type(job_id) is not int or job_id <= 0:
        raise DefectError()
    path = cache / f"preview-{job_id}.json"
    try:
        with _directory(cache, create=False) as descriptor:
            try:
                info = os.stat(path.name, dir_fd=descriptor, follow_symlinks=False)
            except FileNotFoundError:
                return path
            if not stat.S_ISREG(info.st_mode):
                raise ExternalError(
                    _cache_diagnostics(path, "已有结果路径不是普通文件（可能是符号链接或目录）")
                )
            # 使用已打开的父目录删除目录项，避免核对以后父路径被换链导致越界删除。
            os.unlink(path.name, dir_fd=descriptor)
    except OSError as error:
        raise ExternalError(_cache_diagnostics(path, str(error))) from error
    return path


def _validate_path(path: Path) -> None:
    """在任何文件系统操作前拒绝路径越界形式，不 resolve 后吞掉链接证据。"""
    if not path.is_absolute() or ".." in path.parts or "\x00" in str(path):
        raise DefectError()


@contextmanager
def _directory(path: Path, *, create: bool) -> Generator[int]:
    """从文件系统根逐层持有目录描述符，创建和打开都相对于已验证的父目录。"""
    descriptor = os.open(path.anchor, _DIRECTORY_FLAGS)
    try:
        for part in path.parts[1:]:
            if create:
                with suppress(FileExistsError):
                    # 0700 是工单规定的工具缓存权限；已有目录不改权限。
                    os.mkdir(part, mode=0o700, dir_fd=descriptor)
            child = os.open(part, _DIRECTORY_FLAGS, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        yield descriptor
    finally:
        os.close(descriptor)


def _cache_diagnostics(path: Path, actual: str) -> tuple[Diagnostic, ...]:
    """缓存外部失败统一携带可定位对象及修复建议，不自行记录日志。"""
    return (
        Diagnostic(
            level=DiagnosticLevel.ERROR,
            category=DiagnosticCategory.EXTERNAL,
            stage="准备工具缓存",
            source="平台",
            objects=(DiagnosticObject(key="path", value=str(path)),),
            rule="tool_cache.path_unavailable",
            actual=actual,
            expected="缓存各层为真实目录，旧结果为普通文件，且平台有创建和删除权限",
            consequence="本次工具执行无法准备缓存或结果文件",
            next_step="检查缓存路径的符号链接、文件类型和目录权限后重试",
        ),
    )
