"""Lichtblick 离线安装（运维入口层，M5-04/10），只写平台状态目录，不接触机器人。

摘要、tar 过滤、字节正则和临时目录使用标准库；原子发布避免 Web 读到半成品。
"""

import hashlib
import re
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

# M5-10：工作站软件解码实测中位 28.7、P90 41.8、最长 54 毫秒；100 毫秒留出余量。
H264_FRAME_WAIT_MS = 100
# M5-10 核对的 1.30.0 表达式；只替换 H.264 分支，不依赖压缩变量名或改动其定义。
_FRAME_WAIT_PATTERN = re.compile(rb'codec\.startsWith\("hvc1"\)===!0\?2e3:[A-Za-z_$][\w$]*')
# M5-10：锁定发布包的两个解码 chunk 各有一处；不满足就不能确认补丁仍适用。
_EXPECTED_FRAME_WAIT_MATCHES = 2


def install_lichtblick(package: Path, *, state_dir: Path) -> Path:
    """校验本地发布包、修正 H.264 等待并原子安装 Lichtblick 网页。

    Args:
        package: 本地 lichtblick-web.tar.gz 路径，不接受 URL；相对路径以命令工作目录解析。
        state_dir: 配置解析后的本地状态根绝对路径，不可指向数据盘。

    Returns:
        完整安装目录；同补丁版本已有普通 index.html 时直接返回，不读取包、不覆盖文件。

    Raises:
        InputError: sha256 不匹配、tar 损坏、条目不安全、缺少根 index.html 或目标路径越界。
            H.264 等待表达式在全包中不是恰好两处时也拒绝安装。
        ExternalError: 本地包或状态目录 I/O 失败。

    Side Effects:
        先只读原始包并校验，成功后在版本父目录的临时子目录解包、丢弃 .map、打补丁，再重命名发布。
        包校验失败不写磁盘；解包或补丁失败清理临时产物，可能保留空父目录；已有版本不变。

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
                    _patch_h264_wait(Path(temporary))
                    Path(temporary).rename(destination)
        return destination
    except (tarfile.TarError, EOFError) as error:
        raise InputError((_diagnostic("archive", "发布包不是完整的安全 tar.gz"),)) from error
    except OSError as error:
        raise ExternalError((_diagnostic("io", type(error).__name__),)) from error


def _patch_h264_wait(directory: Path) -> None:
    """在临时安装目录按字节修改 H.264 等待，保留换行和其他代码原文。"""
    # 先核对全包再写回，避免只修补一部分却把不适用的发布包当作成功。
    matches = sum(
        len(_FRAME_WAIT_PATTERN.findall(path.read_bytes())) for path in directory.rglob("*.js")
    )
    if matches != _EXPECTED_FRAME_WAIT_MATCHES:
        raise InputError(
            (
                _diagnostic(
                    "h264_wait",
                    f"Lichtblick 包内容和预期不同，H.264 等待补丁没法打（匹配 {matches} 处）",
                    expected=f"H.264 等待表达式在全包中恰好 {_EXPECTED_FRAME_WAIT_MATCHES} 处",
                ),
            )
        )
    replacement = f'codec.startsWith("hvc1")===!0?2e3:{H264_FRAME_WAIT_MS}'.encode("ascii")
    for path in directory.rglob("*.js"):
        original = path.read_bytes()
        patched, count = _FRAME_WAIT_PATTERN.subn(replacement, original)
        if count:
            path.write_bytes(patched)


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


def _diagnostic(
    rule: str,
    actual: str,
    *,
    expected: str = "锁定 sha256 的 lichtblick-web.tar.gz，且只含根内普通文件和目录",
) -> Diagnostic:
    """只报告锁定包身份及安全原因，不回显不可信条目内容。"""
    return Diagnostic(
        level=DiagnosticLevel.ERROR,
        category=DiagnosticCategory.EXTERNAL if rule == "io" else DiagnosticCategory.INPUT,
        stage="安装 Lichtblick",
        source="平台",
        objects=(DiagnosticObject(key="version", value=lichtblick.LICHTBLICK_VERSION),),
        rule=f"lichtblick.{rule}",
        actual=actual,
        expected=expected,
        consequence="未发布新的 Lichtblick 网页",
        next_step="核对本地发布包后运行 rdp install-lichtblick /本地路径/lichtblick-web.tar.gz",
    )
