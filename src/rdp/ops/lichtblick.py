"""Lichtblick 离线安装（运维入口层，M5-04），只写平台状态目录，不接触机器人。

摘要、tar 过滤和临时目录使用标准库；先全包校验再解包，原子发布避免 Web 读到半成品。
"""

import hashlib
import tarfile
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory

from rdp.infra import lichtblick
from rdp.infra.diagnostics import (
    Diagnostic,
    DiagnosticCategory,
    DiagnosticLevel,
    DiagnosticObject,
    ExternalError,
    InputError,
)
from rdp.infra.state import STATE_DIRECTORY_MODE


def install_lichtblick(package: Path, *, state_dir: Path) -> Path:
    """校验本地发布包并原子安装锁定版本的 Lichtblick 网页。

    Args:
        package: 本地 lichtblick-web.tar.gz 路径，不接受 URL；相对路径以命令工作目录解析。
        state_dir: 配置解析后的本地状态根绝对路径，不可指向数据盘。

    Returns:
        完整安装目录；同版本已有普通 index.html 时直接返回，不读取包、不覆盖文件。

    Raises:
        InputError: sha256 不匹配、tar 损坏、条目不安全、缺少根 index.html 或目标路径越界。
        ExternalError: 本地包或状态目录 I/O 失败。

    Side Effects:
        先只读包并校验，成功后创建版本父目录、在其临时子目录解包，丢弃 .map，最后重命名发布。
        校验失败不写磁盘；解包失败清理临时产物，可能保留空父目录；已有版本不变。

    Time Semantics:
        同步本地磁盘操作，不联网、不重试；部署方应串行安装，并保持状态根由平台账号独占。
    """
    destination = lichtblick.lichtblick_directory(state_dir)
    try:
        if not destination.resolve().is_relative_to(state_dir.resolve()):
            raise InputError((_diagnostic("path", "安装路径越出状态根"),))
        if (destination / "index.html").is_file():
            return destination
        with package.open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != lichtblick.LICHTBLICK_SHA256:
                raise InputError((_diagnostic("checksum", "发布包 sha256 不匹配"),))
            stream.seek(0)
            with tarfile.open(fileobj=stream, mode="r:gz") as archive:
                members = archive.getmembers()
                _validate_members(members)
                # 安装可先于数据库初始化，仍沿用状态根仅属主可访问的权限。
                state_dir.mkdir(parents=True, exist_ok=True, mode=STATE_DIRECTORY_MODE)
                destination.parent.mkdir(exist_ok=True, mode=STATE_DIRECTORY_MODE)
                with TemporaryDirectory(prefix=".install-", dir=destination.parent) as temporary:
                    # data 过滤器还负责剥离危险权限；自定义预检额外拒绝所有链接，而非只拒绝越界链接。
                    archive.extractall(
                        temporary,
                        members=[member for member in members if not member.name.endswith(".map")],
                        filter="data",
                    )
                    Path(temporary).rename(destination)
        return destination
    except (tarfile.TarError, EOFError) as error:
        raise InputError((_diagnostic("archive", "发布包不是完整的安全 tar.gz"),)) from error
    except OSError as error:
        raise ExternalError((_diagnostic("io", type(error).__name__),)) from error


def _validate_members(members: list[tarfile.TarInfo]) -> None:
    """只允许根内普通文件和目录，先拒绝整包，避免发现坏条目时已经写入文件。"""
    for member in members:
        path = PurePosixPath(member.name)
        if path.is_absolute() or ".." in path.parts or not (member.isfile() or member.isdir()):
            raise InputError((_diagnostic("entry", "包内含越界路径、链接或特殊文件"),))
    if not any(
        PurePosixPath(item.name) == PurePosixPath("index.html") and item.isfile()
        for item in members
    ):
        raise InputError((_diagnostic("index", "发布包根目录缺少 index.html"),))


def _diagnostic(rule: str, actual: str) -> Diagnostic:
    """只报告锁定包身份及安全原因，不回显不可信条目内容。"""
    return Diagnostic(
        level=DiagnosticLevel.ERROR,
        category=DiagnosticCategory.EXTERNAL if rule == "io" else DiagnosticCategory.INPUT,
        stage="安装 Lichtblick",
        source="平台",
        objects=(DiagnosticObject(key="version", value=lichtblick.LICHTBLICK_VERSION),),
        rule=f"lichtblick.{rule}",
        actual=actual,
        expected="锁定 sha256 的 lichtblick-web.tar.gz，且只含根内普通文件和目录",
        consequence="未发布新的 Lichtblick 网页",
        next_step="核对本地发布包后运行 rdp install-lichtblick /本地路径/lichtblick-web.tar.gz",
    )
