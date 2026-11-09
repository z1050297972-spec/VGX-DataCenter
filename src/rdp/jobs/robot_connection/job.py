"""M5-02 的两层连接作业；标准库负责进程和网络，现有框架负责状态、取消、诊断。

所有连接仅由 worker 显式注入能力后执行；参数只存机器人编号，执行前重读可变登记。
"""

import shlex
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Engine

from rdp.collection.models import RobotRow
from rdp.collection.service import CollectionNotFoundError
from rdp.infra.db.connection import session_scope
from rdp.infra.diagnostics import (
    DefectError,
    Diagnostic,
    DiagnosticCategory,
    DiagnosticLevel,
    DiagnosticObject,
    ExternalError,
)
from rdp.infra.ids import MAX_SQLITE_INTEGER
from rdp.infra.state import StatePaths
from rdp.jobs.execution import ExecutionContext
from rdp.jobs.registry import JobDefinition
from rdp.jobs.robot_connection._keys import ensure_key
from rdp.jobs.robot_connection._process import run
from rdp.jobs.robot_connection.keys import checked_ssh_path, copy_command
from rdp.jobs.types import JobProgress, RecoveryMode

# M5-02：网络层 DNS+TCP 合计 3 秒，SSH 登录合计 10 秒，握手最多 5 秒。
NETWORK_TIMEOUT_S = 3.0
LOGIN_TIMEOUT_S = 10.0
SSH_CONNECT_TIMEOUT_S = 5
CONNECTION_JOB_TYPE = "robot_connection_check"


class ConnectionParameters(BaseModel):
    """连接检查只接收永久编号，不把连接信息或凭据复制进作业。"""

    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)
    robot_id: int = Field(strict=True, ge=1, le=MAX_SQLITE_INTEGER)


@dataclass(frozen=True)
class ConnectionDependencies:
    """worker 私有的连接能力；Web 登记类型时不提供。

    Attributes:
        engine: 已迁移的平台数据库引擎，执行时只读登记。
        paths: 已初始化的本地可信状态目录布局。
        ssh: 系统 SSH 绝对路径；测试注入临时假程序，不能来自请求。
        ssh_keygen: 系统密钥生成器绝对路径；仅生成平台状态目录内的密钥。
    """

    engine: Engine
    paths: StatePaths
    ssh: Path = Path("/usr/bin/ssh")
    ssh_keygen: Path = Path("/usr/bin/ssh-keygen")


def build_connection_definition(dependencies: ConnectionDependencies | None) -> JobDefinition:
    """登记无需 GPU 或存储根的机器人连接检查类型。

    Args:
        dependencies: worker 的数据库、状态目录和可信程序路径；Web 传 None，仅能提交。

    Returns:
        默认并发 1、恢复方式 interrupt 的检查机器人连接定义。

    Raises:
        无。

    Side Effects:
        仅构造定义，不生成密钥、不启动进程、不访问网络。

    Time Semantics:
        启动期同步登记；中断后需人工重提，避免恢复时意外连接机器人。
    """

    def execute(context: ExecutionContext) -> None:
        if dependencies is None or not isinstance(context.parameters, ConnectionParameters):
            raise DefectError()
        _execute(context, dependencies)

    return JobDefinition(
        CONNECTION_JOB_TYPE, "检查机器人连接", ConnectionParameters, RecoveryMode.INTERRUPT, execute
    )


def _diagnostic(
    robot_id: int,
    stage: str,
    actual: str,
    next_step: str,
    *,
    category: DiagnosticCategory = DiagnosticCategory.EXTERNAL,
) -> Diagnostic:
    """只报告安全分类，绝不把 SSH 原始输出或私钥加入诊断。"""
    return Diagnostic(
        level=DiagnosticLevel.ERROR,
        category=category,
        stage=stage,
        source="平台",
        objects=(DiagnosticObject(key="robot_id", value=str(robot_id)),),
        rule="机器人连接必须逐层通过",
        actual=actual,
        expected="网络可达且平台公钥登录成功",
        consequence="本次检查失败；后续层不执行（网络失败时登录层未执行）",
        next_step=next_step,
    )


def _progress(context: ExecutionContext, network: str, login: str, done: int, failed: int) -> None:
    """一个检查为一个作业；两层状态保留在现有进度摘要，失败不伪装部分成功。"""
    context.reporter.report(
        JobProgress(
            stage_index=1,
            stage_count=1,
            stage_name=f"网络：{network}；登录：{login}",
            done=done,
            total=2,
            unit="层",
            total_items=done,
            failed_items=failed,
            warning_count=0,
        )
    )


def _execute(context: ExecutionContext, dependencies: ConnectionDependencies) -> None:
    """读取当前登记后关闭事务，再逐层执行；任一失败立即交框架收口。"""
    parameters = ConnectionParameters.model_validate(context.parameters)
    robot_id = parameters.robot_id
    with session_scope(dependencies.engine, read_only=True) as session:
        row = session.get(RobotRow, robot_id)
        if row is None:
            raise CollectionNotFoundError(
                (
                    _diagnostic(
                        robot_id,
                        "机器人登记",
                        "机器人编号不存在",
                        "刷新机器人登记页",
                        category=DiagnosticCategory.INPUT,
                    ),
                )
            )
        address, port, user = row.address, row.ssh_port, row.ssh_user
    if address is None or user is None:
        raise ExternalError(
            (
                _diagnostic(
                    robot_id, "第 1 层 网络", "连接登记不完整", "去机器人登记页填写地址和 SSH 用户"
                ),
            )
        )
    try:
        private = ensure_key(dependencies.paths, dependencies.ssh_keygen, context)
    except (OSError, subprocess.SubprocessError) as error:
        raise ExternalError(
            (
                _diagnostic(
                    robot_id,
                    "平台密钥",
                    "无法准备平台 SSH 密钥",
                    "请管理员检查 ssh-keygen 和平台状态目录权限",
                ),
            )
        ) from error
    _progress(context, "检查中", "未执行", 0, 0)
    argv = (
        sys.executable,
        "-m",
        "rdp.jobs.robot_connection._network",
        address,
        str(port),
        str(NETWORK_TIMEOUT_S),
    )
    try:
        result = run(argv, NETWORK_TIMEOUT_S, context)
        if result.returncode != 0:
            raise OSError("DNS 解析或 TCP 连接失败")
    except (OSError, subprocess.SubprocessError) as error:
        _progress(context, "失败", "未执行", 1, 1)
        raise ExternalError(
            (
                _diagnostic(
                    robot_id,
                    "第 1 层 网络",
                    "DNS 解析或 TCP 连接失败（限时 3 秒）",
                    "机器人没开机、不在同一网络，或地址变了（DHCP），去机器人登记页核对地址",
                ),
            )
        ) from error

    _progress(context, "通过", "检查中", 1, 0)
    _login(context, dependencies, robot_id, (address, port, user), private)
    _progress(context, "通过", "通过", 2, 0)


def _login(
    context: ExecutionContext,
    dependencies: ConnectionDependencies,
    robot_id: int,
    target: tuple[str, int, str],
    private: Path,
) -> None:
    """SSH 仅用平台身份执行 true；关闭用户配置和 agent，避免额外身份或代理副作用。"""
    address, port, user = target
    known_hosts = checked_ssh_path(dependencies.paths, "known_hosts")
    # -F 禁止读取用户配置；-l 单独传用户名、-- 结束选项，登记值不能成为 SSH 开关。
    argv = (
        str(dependencies.ssh),
        "-F",
        "/dev/null",
        "-i",
        str(private),
        "-o",
        "BatchMode=yes",
        "-o",
        f"ConnectTimeout={SSH_CONNECT_TIMEOUT_S}",
        "-o",
        "StrictHostKeyChecking=accept-new",
        "-o",
        f"UserKnownHostsFile={shlex.quote(str(known_hosts))}",
        "-o",
        "GlobalKnownHostsFile=/dev/null",
        "-o",
        "IdentitiesOnly=yes",
        "-o",
        "IdentityAgent=none",
        "-o",
        "PreferredAuthentications=publickey",
        "-p",
        str(port),
        "-l",
        user,
        "--",
        address,
        "true",
    )
    try:
        result = run(argv, LOGIN_TIMEOUT_S, context)
    except (OSError, subprocess.SubprocessError) as error:
        _progress(context, "通过", "失败", 2, 1)
        raise ExternalError(
            (
                _diagnostic(
                    robot_id,
                    "第 2 层 登录",
                    "SSH 启动失败或登录超过 10 秒期限",
                    "检查工作站 SSH 程序和机器人网络后重新检查连接",
                ),
            )
        ) from error
    context.reporter.tool_exit(result.returncode)
    if result.returncode != 0:
        _progress(context, "通过", "失败", 2, 1)
        # OpenSSH 没有结构化错误码；固定 C locale 后只识别稳定提示，不回显原始输出。
        # 将来若系统 SSH 提供结构化诊断，可删除这段文本分类。
        if b"REMOTE HOST IDENTIFICATION HAS CHANGED" in result.stderr:
            actual = f"机器人主机密钥变化（SSH 退出码 {result.returncode}）"
            next_step = "机器人的主机密钥和上次记录的不一样，可能换了系统或被冒充；确认后由管理员删除平台 known_hosts 里的这一行"
        elif b"Permission denied" in result.stderr:
            actual = f"平台公钥登录被拒绝（SSH 退出码 {result.returncode}）"
            next_step = (
                "平台公钥还没加到机器人上：在工作站终端运行 "
                + copy_command(dependencies.paths, address, port, user)
                + "；也可在机器人登记页打开“平台公钥”复制完整命令"
            )
        else:
            actual = f"SSH 登录失败（退出码 {result.returncode}）"
            next_step = "核对机器人登记的 SSH 用户、端口及机器人 SSH 服务后重新检查连接"
        raise ExternalError((_diagnostic(robot_id, "第 2 层 登录", actual, next_step),))
