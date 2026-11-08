"""只读工具登记（领域层，M4-01、decisions 1/2），不执行程序或访问数据集。

TOML、SHA-256、lru_cache 和文件访问复用标准库；工具状态和五段诊断是本票业务规则。
ADR 0006 的 Web 例外仅限登记包与工具程序：禁止据此读取其他存储根内容。
工具库位于本地系统盘；只接受普通文件，分块读取设总预算，不创建线程或子进程。
"""

import hashlib
import os
import stat
import time
import tomllib
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import ValidationError

from rdp.infra.diagnostics import Diagnostic, DiagnosticCategory, DiagnosticLevel, DiagnosticObject
from rdp.tools.manifest import ToolManifest

# 1 MiB 分块限制哈希内存；十秒沿用平台本地只读访问默认预算，使用单调时钟。
_HASH_CHUNK_BYTES = 1024 * 1024
_HASH_TIMEOUT_S = 10.0
# 工具只有几个；保留最近 128 份文件身份，避免重新登记后旧指纹无限积累。
_FINGERPRINT_CACHE_LIMIT = 128


@dataclass(frozen=True)
class _ProgramFile:
    """缓存只比较四项文件身份；路径不影响硬链接之间的缓存复用。

    Attributes:
        identity: st_dev、st_ino、字节大小、纳秒修改时间的四元组，来自本次 stat。
        path: 已核对边界的程序绝对路径，仅缓存未命中时用于打开文件。
    """

    identity: tuple[int, int, int, int]
    path: Path = field(compare=False)


type ToolStatus = Literal["可用", "程序找不到", "指纹不符", "清单无效"]


@dataclass(frozen=True)
class ToolConfiguration:
    """登记包内一份型号配置的读取快照。

    Attributes:
        robot_model: 数据集使用的型号字符串。
        filename: 相对登记包的配置路径。
        content: 完整 UTF-8 配置文本，保留换行。
        sha256: 配置原始字节的完整 SHA-256，64 位小写十六进制。
    """

    robot_model: str
    filename: str
    content: str
    sha256: str


@dataclass(frozen=True)
class RegisteredTool:
    """单个登记包的状态快照，坏清单仍保留目录身份供列表展示。

    Attributes:
        name: 登记包目录名。
        manifest: 已校验清单；清单无效时为 None。
        status: 可用、程序找不到、指纹不符、清单无效之一。
        diagnostics: 按发现顺序的五段诊断元组；可用时为空。
        program_path: 工具程序绝对路径；清单无效时为 None。
        configurations: 型号配置快照，按清单顺序；清单无效时为空。
    """

    name: str
    manifest: ToolManifest | None
    status: ToolStatus
    diagnostics: tuple[Diagnostic, ...]
    program_path: Path | None
    configurations: tuple[ToolConfiguration, ...]


@dataclass(frozen=True)
class ToolRegistry:
    """本次读取的工具登记快照，不写数据库索引。

    Attributes:
        items: 按登记包目录名排序的工具元组；目录内没有登记包时为空。
    """

    items: tuple[RegisteredTool, ...]


def load_tool_registry(registry_dir: Path, library_root: Path) -> ToolRegistry:
    """读取登记包与配置，逐个核对工具程序指纹。

    Args:
        registry_dir: 平台登记包根目录，绝对路径；每个直接子目录是一份登记。
        library_root: 本地工具库根目录，绝对路径；只读登记的程序文件，不扫描其他内容。

    Returns:
        按目录名排序的快照；坏清单仅标记该工具无效，不阻止其他登记。
        程序不存在或无法读取为程序找不到，大小或 SHA-256 不匹配为指纹不符。

    Raises:
        OSError: 无法列举登记目录；不把部署读取故障当成空工具库。
        ValueError: 任一根目录不是绝对路径。

    Side Effects:
        无磁盘写入；只读登记包和程序。程序以 O_RDONLY | O_NOATIME 打开，失败不退回普通读取。
        进程内缓存文件身份对应的 SHA-256，最多保留 128 项；不启动线程或子进程。

    Time Semantics:
        每次读取清单和配置；指纹按 (st_dev, st_ino, st_size, st_mtime_ns) 复用。
        本地普通文件同步读取，哈希分块间检查十秒单调时间预算，无重试；不使用墙钟。
    """
    if not registry_dir.is_absolute() or not library_root.is_absolute():
        raise ValueError("登记包与工具库必须使用绝对路径")
    return ToolRegistry(
        tuple(
            _load_tool(package, registry_dir, library_root)
            for package in sorted(registry_dir.iterdir())
            if package.is_dir()
        )
    )


def _contained_path(root: Path, relative: str) -> Path:
    """解析软链接后限制到指定根内，禁止清单路径借软链接读到其他数据。"""
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError(f"路径越出登记边界：{relative}")
    return path


def _load_tool(package: Path, registry_dir: Path, library_root: Path) -> RegisteredTool:
    """隔离单份登记包的输入和文件读取错误，不吞掉程序缺陷。"""
    try:
        return _load_valid_tool(package, registry_dir, library_root)
    except (OSError, ValueError) as error:
        actual = (
            "；".join(
                f"{'.'.join(map(str, detail['loc'])) or 'tool.toml'}：{detail['msg']}"
                for detail in error.errors(include_input=False, include_url=False)
            )
            if isinstance(error, ValidationError)
            else str(error)
        )
        diagnostic = Diagnostic(
            level=DiagnosticLevel.ERROR,
            category=DiagnosticCategory.INPUT,
            stage="工具登记",
            source="平台",
            objects=(
                DiagnosticObject(key="tool", value=package.name),
                DiagnosticObject(key="manifest", value=str(package / "tool.toml")),
            ),
            rule="tools.manifest",
            actual=actual,
            expected="符合 schema_version=1 且配置文件位于登记包内的清单",
            consequence="不能用于转换",
            next_step="请执行线修正登记包并重新检查",
        )
        return RegisteredTool(package.name, None, "清单无效", (diagnostic,), None, ())


def _load_valid_tool(package: Path, registry_dir: Path, library_root: Path) -> RegisteredTool:
    """读取一份完整有效的登记及配置，再核对程序，保持两类故障的状态区别。"""
    safe_package = _contained_path(registry_dir, package.name)
    manifest_file = _contained_path(safe_package, "tool.toml")
    manifest = ToolManifest.model_validate(
        tomllib.loads(manifest_file.read_text(encoding="utf-8")),
        context={"package_dir": package},
    )
    configurations = tuple(
        _read_configuration(safe_package, model, filename)
        for model, filename in manifest.models.items()
    )
    directory = _contained_path(library_root, manifest.tool.directory)
    program = _contained_path(directory, manifest.program.path)
    status, diagnostics = _program_status(manifest, program)
    return RegisteredTool(package.name, manifest, status, diagnostics, program, configurations)


def _read_configuration(package: Path, model: str, filename: str) -> ToolConfiguration:
    """从同一份原始字节生成配置全文和哈希，避免两次读到不同版本。"""
    data = _contained_path(package, filename).read_bytes()
    return ToolConfiguration(
        model, filename, data.decode("utf-8"), hashlib.sha256(data).hexdigest()
    )


def _program_status(
    manifest: ToolManifest, program: Path
) -> tuple[ToolStatus, tuple[Diagnostic, ...]]:
    """大小不同立即拒绝，否则读取或复用指纹；文件读取错误归入不可用状态。"""
    expected = f"sha256 {manifest.program.sha256[:12]}，{manifest.program.size} 字节"
    try:
        metadata = program.stat()
        if not stat.S_ISREG(metadata.st_mode):
            raise OSError("工具程序不是普通文件")
        if metadata.st_size != manifest.program.size:
            actual = f"sha256 未计算（大小不同），{metadata.st_size} 字节"
        else:
            digest = _fingerprint(_ProgramFile(_file_identity(metadata), program))
            if digest == manifest.program.sha256:
                return "可用", ()
            actual = f"sha256 {digest[:12]}，{metadata.st_size} 字节"
    except OSError as error:
        return "程序找不到", (
            _diagnostic(
                manifest.tool.name,
                program,
                actual=f"程序不存在或无法读取（{type(error).__name__}）",
                expected=expected,
                status="程序找不到",
            ),
        )
    return "指纹不符", (
        _diagnostic(
            manifest.tool.name, program, actual=actual, expected=expected, status="指纹不符"
        ),
    )


@lru_cache(maxsize=_FINGERPRINT_CACHE_LIMIT)
def _fingerprint(program: _ProgramFile) -> str:
    """仅缓存完整且读取期间未变化的普通文件，以文件身份复用而不是以路径复用。"""
    deadline = time.monotonic() + _HASH_TIMEOUT_S
    # 非阻塞打开避免意外的 FIFO 等待；NOFOLLOW 防止解析后末级路径被换成链接。
    descriptor = os.open(program.path, os.O_RDONLY | os.O_NOATIME | os.O_NONBLOCK | os.O_NOFOLLOW)
    with os.fdopen(descriptor, "rb") as stream:
        if _file_identity(os.fstat(stream.fileno())) != program.identity:
            raise OSError("程序在读取前变化")
        digest = hashlib.sha256()
        for chunk in iter(lambda: stream.read(_HASH_CHUNK_BYTES), b""):
            if time.monotonic() >= deadline:
                raise TimeoutError("程序指纹读取超时")
            digest.update(chunk)
        if _file_identity(os.fstat(stream.fileno())) != program.identity:
            raise OSError("程序在读取期间变化")
    return digest.hexdigest()


def _file_identity(metadata: os.stat_result) -> tuple[int, int, int, int]:
    """集中指纹缓存的文件身份，修改时间使用文件系统的纳秒整数而非浮点秒。"""
    return metadata.st_dev, metadata.st_ino, metadata.st_size, metadata.st_mtime_ns


def _diagnostic(
    name: str, program: Path, *, actual: str, expected: str, status: ToolStatus
) -> Diagnostic:
    """给不可用工具保留程序身份和修复指引，沿用平台的五段诊断。"""
    return Diagnostic(
        level=DiagnosticLevel.ERROR,
        category=DiagnosticCategory.INPUT,
        stage="工具登记",
        source="平台",
        objects=(
            DiagnosticObject(key="tool", value=name),
            DiagnosticObject(key="program", value=str(program)),
        ),
        rule="tools.fingerprint" if status == "指纹不符" else "tools.program_missing",
        actual=actual,
        expected=expected,
        consequence="不能用于转换",
        next_step="工具程序已变化，需要执行线重新登记"
        if status == "指纹不符"
        else "请执行线检查工具程序路径与读取权限",
    )
