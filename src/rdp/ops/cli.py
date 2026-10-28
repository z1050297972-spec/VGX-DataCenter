"""argparse 运维命令边界（11 M3），不实现账号、迁移或作业业务，也不依赖 Web 入口。

参数解析复用标准库；生产 Web 回调由 rdp.cli 注入，保持 api 与 ops 的依赖隔离。
口令只经已有 accounts 交互函数读取，不支持命令行口令或环境变量口令。
"""

from collections.abc import Callable, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass
from threading import Event
from typing import Literal, TextIO

from rdp.ops.runtime import RuntimeInputs, ServiceRuntime


@dataclass(frozen=True)
class Command:
    """解析后的运维动作；不持有原始口令或 argparse Namespace。

    Attributes:
        name: web、worker、migrate、create-admin、reset-password、status 或 version。
        no_stderr: 只适用于 web/worker；其他命令必须为 False。
        login_name: 账号命令的登录名；其他命令为 None，领域函数负责账号字段校验。
        display_name: create-admin 的显示名，其他命令为 None。
        status_check: status 必须选择 active-jobs、port 或 worker-stopped；其他命令为 None。
    """

    name: Literal["web", "worker", "migrate", "create-admin", "reset-password", "status", "version"]
    no_stderr: bool = False
    login_name: str | None = None
    display_name: str | None = None
    status_check: Literal["active-jobs", "port", "worker-stopped"] | None = None


@dataclass(frozen=True)
class Console:
    """终端输入输出依赖；测试使用内存流和口令替身。

    Attributes:
        stdout: 帮助、版本及成功摘要流，不输出口令。
        stderr: 参数错误和运维失败诊断流；--no-stderr 禁止服务运行日志写入此流。
        read_password: 无回显口令读取函数，接收中文提示；生产复用 getpass。
    """

    stdout: TextIO
    stderr: TextIO
    read_password: Callable[[str], str]


def parse_command(argv: Sequence[str], *, console: Console) -> Command:
    """用 argparse 解析最小运维命令，不触发运行环境初始化。

    Args:
        argv: 不含可执行文件名的字符串序列，可为空；不接受口令参数。
        console: 帮助和参数诊断的输出流，此函数不读口令。

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
    raise NotImplementedError


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
        console: 输出和口令输入；账号命令复用 create_first_admin/reset_account_password。
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
        账号命令读取两次口令再调用现有领域事务；本层不另补成功操作日志。
        --no-stderr 下已配置日志的服务失败只进文件；日志初始化之前失败仍可输出终端诊断。
        不吞 worker 非零码，不在同进程重启；lock_retained=True 时不 dispose 仍被线程使用的引擎。

    Time Semantics:
        帮助先于配置读取；服务持续到停止，worker 停止预算沿用 WORKER_STOP_TIMEOUT_S。
        维护命令的事务/口令等待分别沿用 migrate 与 accounts 的契约，无额外重试。
    """
    raise NotImplementedError


def run_maintenance(command: Command, *, inputs: RuntimeInputs, console: Console) -> int:
    """执行迁移或本地账号恢复，并管理本次使用的数据库资源。

    Args:
        command: 仅 migrate、create-admin、reset-password，账号参数必须完整。
        inputs: 配置和时钟依赖；不要求前端已构建，不探测 GPU 或装配调度。
        console: 成功摘要和无回显输入；不接受明文口令参数。

    Returns:
        成功为 0；失败向外传播，由 run_cli 统一转换退出码。

    Raises:
        InputError: 数据库或账号数据非法、账号不存在；账号命令要求版本匹配。
        ConflictError: 首管理员已存在、迁移锁/业务写锁冲突。
        ExternalError: 数据库、哈希资源或终端 I/O 失败。
        DefectError: command 非维护命令、必填上下文缺失或注入时钟无效。
        ValueError: 配置或状态布局校验失败。
        OSError: 配置、状态目录、迁移备份或输出流访问失败。
        EOFError: 口令输入结束；沿用现有无部分账号写入的保证。
        KeyboardInterrupt: 操作者取消口令输入或迁移，传播给 run_cli。

    Side Effects:
        migrate 初始化状态目录并调用现有迁移入口，保留它的备份和失败回滚语义。
        账号命令先检查版本再构造 AccountService；成功日志与账号修改仍由领域原子提交。
        finally 释放本次引擎；不启动服务、不改 systemd、不自动迁移账号命令的数据库。

    Time Semantics:
        migrate 要求操作者已停止 Web 和 worker；入口不会强制停止别的进程。
        UTC 时刻每次维护动作取一次；口令交互不持事务，锁和备份预算复用已有入口。
    """
    raise NotImplementedError
