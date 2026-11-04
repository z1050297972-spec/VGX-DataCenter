"""argparse 运维命令边界（11 M3），不实现账号、迁移或作业业务，也不依赖 Web 入口。

参数解析复用标准库；生产 Web 回调由 rdp.cli 注入，保持 api 与 ops 的依赖隔离。
密码只经已有 accounts 交互函数读取，不支持命令行密码或环境变量密码。
"""

import argparse
import logging
import sys
from collections.abc import Callable, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass
from threading import Event
from typing import Literal, TextIO, override

from rdp.accounts.security import PasswordCodec
from rdp.accounts.service import AccountService
from rdp.infra.config import load_config
from rdp.infra.db.connection import create_database_engine
from rdp.infra.db.migration import check_database_version, migrate
from rdp.infra.diagnostics import (
    ConflictError,
    DefectError,
    ExternalError,
    InputError,
    render_diagnostic,
)
from rdp.infra.state import initialize_state, state_paths
from rdp.infra.timeutil import ensure_utc
from rdp.infra.version import read_platform_version
from rdp.ops.accounts import create_first_admin, reset_account_password
from rdp.ops.lifecycle import start_worker
from rdp.ops.rebuild import rebuild_index
from rdp.ops.runtime import RuntimeInputs, ServiceRuntime, prepare_service
from rdp.ops.status import check_web_port, check_worker_stopped, has_active_jobs

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Command:
    """解析后的运维动作；不持有原始密码或 argparse Namespace。

    Attributes:
        name: web、worker、migrate、create-admin、reset-password、status、rebuild-index 或 version。
        no_stderr: 只适用于 web/worker；其他命令必须为 False。
        login_name: 账号命令的登录名；其他命令为 None，领域函数负责账号字段校验。
        display_name: create-admin 的显示名，其他命令为 None。
        status_check: status 必须选择 active-jobs、port 或 worker-stopped；其他命令为 None。
    """

    name: Literal[
        "web",
        "worker",
        "migrate",
        "create-admin",
        "reset-password",
        "status",
        "version",
        "rebuild-index",
    ]
    no_stderr: bool = False
    login_name: str | None = None
    display_name: str | None = None
    status_check: Literal["active-jobs", "port", "worker-stopped"] | None = None


@dataclass(frozen=True)
class Console:
    """终端输入输出依赖；测试使用内存流和密码替身。

    Attributes:
        stdout: 帮助、版本及成功摘要流，不输出密码。
        stderr: 参数错误和运维失败诊断流；--no-stderr 禁止服务运行日志写入此流。
        read_password: 无回显密码读取函数，接收中文提示；生产复用 getpass。
    """

    stdout: TextIO
    stderr: TextIO
    read_password: Callable[[str], str]


def parse_command(argv: Sequence[str], *, console: Console) -> Command:
    """用 argparse 解析最小运维命令，不触发运行环境初始化。

    Args:
        argv: 不含可执行文件名的字符串序列，可为空；不接受密码参数。
        console: 帮助和参数诊断的输出流，此函数不读密码。

    Returns:
        Command；create-admin 接收 <登录名> <显示名>，reset-password 接收 <登录名>。
        web/worker 允许 --no-stderr；status 必须且只能选
        --active-jobs、--check-port 或 --worker-stopped 中一个。
        顶层 --version 产生 version 动作，各子命令均支持 --help。

    Raises:
        SystemExit: --help 输出后 code=0；缺命令、未知选项、缺位置参数或互斥冲突 code=2。
        OSError: 输出帮助或参数诊断失败。

    Side Effects:
        仅向 console 输出帮助或参数错误；不读配置、数据库、版本文件，不创建目录。

    Time Semantics:
        同步解析，无时钟、交互等待或重试。
    """
    parser = _parser(console)
    arguments = parser.parse_args(argv)
    if arguments.version:
        if arguments.command is not None:
            parser.error("--version 不与子命令合用")
        return Command("version")
    if arguments.command is None:
        parser.error("必须指定子命令")
    return Command(
        arguments.command,
        getattr(arguments, "no_stderr", False),
        getattr(arguments, "login_name", None),
        getattr(arguments, "display_name", None),
        getattr(arguments, "status_check", None),
    )


def run_cli(
    argv: Sequence[str],
    *,
    inputs: RuntimeInputs,
    console: Console,
    web: Callable[[ServiceRuntime], int],
    signals: Callable[[Event], AbstractContextManager[None]],
) -> int:
    """分派运维命令并把边界失败映射为可供进程使用的退出码。

    Args:
        argv: 不含程序名的参数；解析规则以 parse_command 为准。
        inputs: 显式环境、home、时钟和部署布局，测试不得使用真实默认目录。
        console: 输出和密码输入；账号命令复用 create_first_admin/reset_account_password。
        web: Web 生命周期回调，接收 prepare_service 的资源，负责等待报错线程并释放引擎。
        signals: worker 停止事件的信号上下文，生产为 stop_signals；测试传无全局副作用替身。

    Returns:
        帮助、版本、维护成功、空闲状态为 0；参数错误为 2；运行失败为 1；
        status --active-jobs 检出 running/cancelling 或 --worker-stopped 检出持锁为 3；
        worker 原样返回 WorkerExit.code。
        web 返回回调退出码；交互 EOF 或 Ctrl-C 返回 130。

    Raises:
        BaseException: 除 SystemExit、KeyboardInterrupt 和 Exception 外的进程级终止原样传播。

    Side Effects:
        version 只读取版本事实并输出一行；status 走只读检查，不初始化目录或日志、不迁移。
        服务走 prepare_service；worker 传 StorageAccessChecker、版本和完整 WorkerScheduling，
        Web 必须传入真实引擎。启动失败只在此边界记录一次诊断，版本闸门明确提示 rdp migrate。
        账号命令读取两次密码再调用现有领域事务；本层不另补成功操作日志。
        rebuild-index同步独占worker锁清空并重建索引，成功日志与发布同事务；不统计大小。
        --no-stderr 下已配置日志的服务失败只进文件；日志初始化之前失败仍可输出终端诊断。
        不吞 worker 非零码，不在同进程重启；lock_retained=True 时不 dispose 仍被线程使用的引擎。

    Time Semantics:
        帮助先于配置读取；服务持续到停止，worker 停止预算沿用 WORKER_STOP_TIMEOUT_S。
        维护命令的事务/密码等待分别沿用 migrate 与 accounts 的契约，无额外重试。
    """
    previous_handlers = logging.getLogger().handlers
    try:
        command = parse_command(argv, console=console)
        if command.name == "version":
            console.stdout.write(
                read_platform_version(inputs.layout, package_version=inputs.package_version) + "\n"
            )
            return 0
        if command.name in ("web", "worker"):
            runtime = prepare_service(command.name, no_stderr=command.no_stderr, inputs=inputs)
            if command.name == "web":
                return web(runtime)
            return start_worker(runtime, inputs=inputs, signals=signals)
        if command.name == "status":
            return _status(command, inputs)
        if command.name == "rebuild-index":
            return rebuild_index(inputs, stdout=console.stdout)
        return run_maintenance(command, inputs=inputs, console=console)
    except SystemExit as error:
        return error.code if isinstance(error.code, int) else 1
    except (EOFError, KeyboardInterrupt):
        return 130
    except Exception as error:
        message = _failure_text(error)
        if logging.getLogger().handlers is not previous_handlers:
            logger.error("运维命令失败：%s", message)
        else:
            console.stderr.write("运维命令失败：" + message + "\n")
        return 1


def run_maintenance(command: Command, *, inputs: RuntimeInputs, console: Console) -> int:
    """执行迁移或本地账号恢复，并管理本次使用的数据库资源。

    Args:
        command: 仅 migrate、create-admin、reset-password，账号参数必须完整。
        inputs: 配置和时钟依赖；不要求前端已构建，不探测 GPU 或装配调度。
        console: 成功摘要和无回显输入；不接受明文密码参数。

    Returns:
        成功为 0；失败向外传播，由 run_cli 统一转换退出码。

    Raises:
        InputError: 数据库或账号数据非法、账号不存在；账号命令要求版本匹配。
        ConflictError: 首管理员已存在、迁移锁/业务写锁冲突。
        ExternalError: 数据库、哈希资源或终端 I/O 失败。
        DefectError: command 非维护命令、必填上下文缺失或注入时钟无效。
        ValueError: 配置或状态布局校验失败。
        OSError: 配置、状态目录、迁移备份或输出流访问失败。
        EOFError: 密码输入结束；沿用现有无部分账号写入的保证。
        KeyboardInterrupt: 操作者取消密码输入或迁移，传播给 run_cli。

    Side Effects:
        migrate 初始化状态目录并调用现有迁移入口，保留它的备份和失败回滚语义。
        账号命令先检查版本再构造 AccountService；成功日志与账号修改仍由领域原子提交。
        finally 释放本次引擎；不启动服务、不改 systemd、不自动迁移账号命令的数据库。

    Time Semantics:
        migrate 要求操作者已停止 Web 和 worker；入口不会强制停止别的进程。
        UTC 时刻每次维护动作取一次；密码交互不持事务，锁和备份预算复用已有入口。
    """
    if command.name not in ("migrate", "create-admin", "reset-password"):
        raise DefectError
    try:
        now = ensure_utc(inputs.clock.now())
    except Exception as error:
        raise DefectError from error
    config = load_config(environ=inputs.environ, home=inputs.home).config
    paths = state_paths(config, ())
    if command.name == "migrate":
        initialize_state(paths)
        result = migrate(paths, now=now)
        console.stdout.write(
            f"数据库版本：{result.current_revision}；备份：{result.backup or '无'}\n"
        )
        return 0
    check_database_version(paths.database)
    if command.login_name is None or (
        command.name == "create-admin" and command.display_name is None
    ):
        raise DefectError
    engine = create_database_engine(paths.database)
    try:
        service = AccountService(engine, PasswordCodec())
        if command.name == "create-admin" and command.display_name is not None:
            account = create_first_admin(
                service,
                command.login_name,
                command.display_name,
                now=now,
                read_password=console.read_password,
            )
        else:
            account = reset_account_password(
                service, command.login_name, now=now, read_password=console.read_password
            )
        console.stdout.write(f"账号操作成功：{account.login_name}\n")
        return 0
    finally:
        engine.dispose()


class _Parser(argparse.ArgumentParser):
    """保留argparse标准帮助与退出码，只把输出路由到显式终端流。"""

    console: Console

    @override
    def _print_message(self, message: str, file: object = None) -> None:
        """帮助走stdout，参数错误走stderr，不替换进程全局标准流。"""
        if message:
            target = self.console.stderr if file is sys.stderr else self.console.stdout
            target.write(message)


def _parser(console: Console) -> _Parser:
    """在一处声明运维参数，不允许缩写、不接受密码字段。"""
    parser = _Parser(prog="rdp", description="机器人数据平台运维入口", allow_abbrev=False)
    parser.console = console
    parser.add_argument("--version", action="store_true", help="显示包版本与构建提交")
    subcommands = parser.add_subparsers(dest="command", parser_class=_Parser)
    descriptions = {
        "web": "启动 Web 服务",
        "worker": "启动后台作业 worker",
        "migrate": "升级数据库到当前版本",
        "create-admin": "创建首个管理员",
        "reset-password": "重置账号密码并撤销旧会话",
        "status": "只读检查作业、worker 锁或监听端口",
        "rebuild-index": "停止 worker 后清空并重建数据集索引",
    }
    for name, description in descriptions.items():
        child = subcommands.add_parser(
            name, help=description, description=description, allow_abbrev=False
        )
        child.console = console
        if name in ("web", "worker"):
            child.add_argument("--no-stderr", action="store_true", help="只写日志文件")
        if name in ("create-admin", "reset-password"):
            child.add_argument("login_name", help="登录名")
        if name == "create-admin":
            child.add_argument("display_name", help="显示名")
        if name == "status":
            child.epilog = "退出码 1：检查失败；2：参数错误。检查失败不能当作可安全维护。"
            group = child.add_mutually_exclusive_group(required=True)
            for option, value, help_text in (
                (
                    "--active-jobs",
                    "active-jobs",
                    "检查运行中或正在取消的作业；0：无活跃作业；3：有活跃作业",
                ),
                (
                    "--check-port",
                    "port",
                    "检查配置的监听地址和端口；0：端口可用；1：占用或检查失败",
                ),
                (
                    "--worker-stopped",
                    "worker-stopped",
                    "检查 worker 单实例锁；0：锁未被持有；3：锁被占用",
                ),
            ):
                group.add_argument(
                    option, dest="status_check", action="store_const", const=value, help=help_text
                )
    return parser


def _failure_text(error: Exception) -> str:
    """公开诊断逐条呈现；未知异常只给安全类别，不回显密码或异常载荷。"""
    if isinstance(error, (InputError, ConflictError, ExternalError)):
        return (
            "\n".join(render_diagnostic(item) for item in error.diagnostics)
            + "；数据库版本问题请运行 rdp migrate"
        )
    if isinstance(error, (ValueError, OSError)):
        return str(error)
    return f"程序缺陷（{type(error).__name__}），请检查配置与运行日志"


def _status(command: Command, inputs: RuntimeInputs) -> int:
    """状态命令只解析配置与路径，不初始化目录、日志或迁移数据库。"""
    config = load_config(environ=inputs.environ, home=inputs.home).config
    paths = state_paths(config, ())
    if command.status_check == "active-jobs":
        return 3 if has_active_jobs(paths.database) else 0
    if command.status_check == "worker-stopped":
        return 0 if check_worker_stopped(paths.worker_lock).allowed else 3
    if command.status_check == "port":
        check_web_port(config.web)
        return 0
    raise DefectError
