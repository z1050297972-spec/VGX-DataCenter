"""M5-09 离线 wheel 安装入口；标准库校验、临时文件及原子替换，不访问网络。"""

import hashlib
import shutil
from pathlib import Path
from tempfile import TemporaryDirectory

from rdp.infra import viz_relay
from rdp.infra.diagnostics import (
    Diagnostic,
    DiagnosticCategory,
    DiagnosticLevel,
    DiagnosticObject,
    ExternalError,
    InputError,
)
from rdp.infra.state import STATE_DIRECTORY_MODE


def install_viz_relay_wheel(package: Path, *, state_dir: Path) -> Path:
    """校验固定 wheel 的文件名和摘要后原子存入平台状态目录。

    Args:
        package: 本地 whl 文件路径，名称必须等于锁定文件名；不接受 URL。
        state_dir: 已解析的本地状态根绝对路径，不可指向数据盘。

    Returns:
        viz_relay/wheels 下的已校验文件路径；同摘要文件已存在时不重复写入。

    Raises:
        InputError: 文件名或 sha256 与锁定值不符。
        ExternalError: 本地读取或写入失败。

    Side Effects:
        校验通过才创建父目录并原子发布；失败清理临时文件，可能留下空父目录。
        文件名或摘要错误不写任何文件；不初始化数据库。

    Time Semantics:
        同步本地文件操作，不联网、不重试。
    """
    destination = state_dir / "viz_relay" / "wheels" / viz_relay.WHEEL_FILENAME
    try:
        if package.name != viz_relay.WHEEL_FILENAME:
            raise InputError((_diagnostic("filename", "wheel 文件名不匹配"),))
        with package.open("rb") as source:
            if hashlib.file_digest(source, "sha256").hexdigest() != viz_relay.WHEEL_SHA256:
                raise InputError((_diagnostic("checksum", "wheel sha256 不匹配"),))
            if destination.is_file():
                with destination.open("rb") as existing:
                    if (
                        hashlib.file_digest(existing, "sha256").hexdigest()
                        == viz_relay.WHEEL_SHA256
                    ):
                        return destination
            source.seek(0)
            destination.parent.mkdir(parents=True, exist_ok=True, mode=STATE_DIRECTORY_MODE)
            with TemporaryDirectory(prefix=".install-", dir=destination.parent) as temporary:
                staged = Path(temporary) / package.name
                with staged.open("wb") as output:
                    shutil.copyfileobj(source, output)
                staged.replace(destination)
        return destination
    except OSError as error:
        raise ExternalError((_diagnostic("io", "本地 wheel 读取或发布失败"),)) from error


def _diagnostic(rule: str, actual: str) -> Diagnostic:
    """仅报告锁定身份和分类，不回显本地文件内容。"""
    return Diagnostic(
        level=DiagnosticLevel.ERROR,
        category=DiagnosticCategory.EXTERNAL if rule == "io" else DiagnosticCategory.INPUT,
        stage="安装预览 wheel",
        source="平台",
        objects=(DiagnosticObject(key="version", value=viz_relay.SDK_VERSION),),
        rule=f"viz_relay.{rule}",
        actual=actual,
        expected="固定文件名且 sha256 匹配的机器人 wheel",
        consequence="没有发布新的 wheel",
        next_step=f"rdp install-viz-relay-wheel /本地路径/{viz_relay.WHEEL_FILENAME}",
    )
