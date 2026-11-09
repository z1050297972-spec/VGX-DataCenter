"""平台 SSH 公钥查询及手动安装命令；只读本地状态目录，不启动进程或连接机器人。

路径使用 pathlib，公钥格式用标准库 base64/struct 验证，避免把误放的私钥当公钥返回。
私钥生成由 worker 私有模块负责，Web 只能调用这里的读取能力。
"""

import base64
import binascii
import shlex
import struct
from pathlib import Path

from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from rdp.collection.models import RobotRow
from rdp.collection.service import CollectionNotFoundError
from rdp.infra.diagnostics import (
    Diagnostic,
    DiagnosticCategory,
    DiagnosticLevel,
    DiagnosticObject,
    ExternalError,
)
from rdp.infra.state import StatePaths

# OpenSSH ed25519 编码固定为算法名长度+算法名+32 字节公钥；公钥行含注释最多 1 KiB。
_PUBLIC_KEY_MAX_BYTES = 1024


class SshPublicKey(BaseModel):
    """只返回公钥及当前机器人的手动安装命令；未生成或登记不完整时相应字段为 None。"""

    model_config = ConfigDict(extra="forbid", frozen=True)
    public_key: str | None
    copy_command: str | None


def checked_ssh_path(paths: StatePaths, filename: str) -> Path:
    """限定 SSH 状态文件在平台自己的真实目录内。

    Args:
        paths: 由入口初始化的可信状态路径，调用期间不允许其他主体替换目录。
        filename: 固定文件名 id_ed25519、id_ed25519.pub 或 known_hosts，不接受请求输入。

    Returns:
        状态根下 ssh 目录里的绝对路径；允许尚未存在。

    Raises:
        OSError: SSH 目录或文件为软链接、路径越界、目标不是普通文件或文件系统无法检查。
        ValueError: 程序传入不在许可清单内的文件名。

    Side Effects:
        无；仅检查本地路径，不读取任何密钥内容。

    Time Semantics:
        同步本地元数据检查，不重试；状态目录须位于本地磁盘。
    """
    if filename not in {"id_ed25519", "id_ed25519.pub", "known_hosts"}:
        raise ValueError("非法 SSH 状态文件名")
    directory = paths.root / "ssh"
    target = directory / filename
    if (
        directory.is_symlink()
        or target.is_symlink()
        or not target.resolve().is_relative_to(paths.root.resolve())
    ):
        raise OSError("SSH 状态路径不能越界或为软链接")
    # 状态文件只能是普通文件；尤其拒绝 FIFO，避免只读接口被无界 read 挂住。
    if target.exists() and not target.is_file():
        raise OSError("SSH 状态文件必须是普通文件")
    return target


def copy_command(paths: StatePaths, address: str, port: int, user: str) -> str:
    """按当前登记生成负责人手动执行的公钥安装命令。

    Args:
        paths: 平台状态目录布局；公钥固定放在 ssh/id_ed25519.pub。
        address: 已校验的 IP 或主机名，非空。
        port: SSH TCP 端口，1 至 65535。
        user: 已登记的非空 SSH 用户名，不含空白。

    Returns:
        用 shlex.join 转义的一行 ssh-copy-id 命令，包含登记端口。

    Raises:
        OSError: 公钥路径越界或为软链接。

    Side Effects:
        无；只拼接文本，不执行命令或读取用户 SSH 配置。

    Time Semantics:
        命令只反映本次读取的登记快照，地址更改后需重新获取。
    """
    return shlex.join(
        (
            "ssh-copy-id",
            "-i",
            str(checked_ssh_path(paths, "id_ed25519.pub")),
            "-p",
            str(port),
            "--",
            f"{user}@{address}",
        )
    )


def read_public_key(paths: StatePaths, session: Session, robot_id: int) -> SshPublicKey:
    """读取平台公钥并给指定机器人生成手动安装说明。

    Args:
        paths: 已初始化的平台本地状态目录；不会访问用户 ~/.ssh。
        session: 已鉴权的只读业务会话。
        robot_id: 已登记机器人的永久编号，1 至 2^63-1。

    Returns:
        公钥一行与命令；首次 worker 检查前 public_key 为 None，缺少地址或用户时命令为 None。

    Raises:
        CollectionNotFoundError: 机器人编号不存在。
        ExternalError: 公钥文件不可读、格式不是单行 ed25519 公钥或路径不安全。
        SQLAlchemyError: 读取机器人失败，由数据库边界处理。

    Side Effects:
        无；只读公钥和机器人登记，既不读私钥也不生成密钥。

    Time Semantics:
        当前请求快照；不等待 worker 生成密钥，未生成时立即返回 None。
    """
    robot = session.get(RobotRow, robot_id)
    if robot is None:
        raise CollectionNotFoundError(
            (
                _key_diagnostic(
                    robot_id,
                    "机器人编号不存在",
                    "刷新机器人登记页",
                    category=DiagnosticCategory.INPUT,
                ),
            )
        )
    try:
        public_path = checked_ssh_path(paths, "id_ed25519.pub")
        try:
            with public_path.open("rb") as stream:
                raw = stream.read(_PUBLIC_KEY_MAX_BYTES + 1)
        except FileNotFoundError:
            return SshPublicKey(public_key=None, copy_command=None)
        line = _public_line(raw)
        command = (
            copy_command(paths, robot.address, robot.ssh_port, robot.ssh_user)
            if robot.address and robot.ssh_user
            else None
        )
    except (OSError, ValueError, binascii.Error) as error:
        raise ExternalError(
            (
                _key_diagnostic(
                    robot_id, "平台公钥无法安全读取", "请管理员检查平台状态目录 ssh 下的公钥文件"
                ),
            )
        ) from error
    return SshPublicKey(public_key=line, copy_command=command)


def _key_diagnostic(
    robot_id: int,
    actual: str,
    next_step: str,
    *,
    category: DiagnosticCategory = DiagnosticCategory.EXTERNAL,
) -> Diagnostic:
    """不包含文件内容或异常载荷的公钥读取诊断。"""
    return Diagnostic(
        level=DiagnosticLevel.ERROR,
        category=category,
        stage="平台公钥",
        source="平台",
        objects=(DiagnosticObject(key="robot_id", value=str(robot_id)),),
        rule="平台只公开有效的 ed25519 公钥",
        actual=actual,
        expected="平台公钥可读",
        consequence="本次无法显示平台公钥",
        next_step=next_step,
    )


def _public_line(raw: bytes) -> str:
    """严格识别单行 ed25519 公钥；校验失败只抛固定文本，不泄露原始字节。"""
    line = raw.decode("ascii", errors="replace").removesuffix("\n")
    fields = line.split(" ", 2)
    if (
        not line.isascii()
        or len(raw) > _PUBLIC_KEY_MAX_BYTES
        or "\n" in line
        or "\r" in line
        or len(fields) < 2
        or fields[0] != "ssh-ed25519"
    ):
        raise ValueError("公钥格式无效")
    decoded = base64.b64decode(fields[1], validate=True)
    if len(decoded) != 51 or decoded[:19] != struct.pack(">I", 11) + b"ssh-ed25519" + struct.pack(
        ">I", 32
    ):
        raise ValueError("公钥编码无效")
    return line
