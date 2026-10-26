"""本地账号恢复入口（06），只读交互口令并调用领域服务，不在此实现权限或 SQL。

复用 getpass；不提供命令解析，第 11 张再接 CLI。所有输入先完成，再开始领域写事务。
操作日志由领域事务负责；本入口只额外报告补记失败，不把口令放命令行参数、环境变量或异常消息。
"""

import hmac
import warnings
from collections.abc import Callable
from datetime import datetime
from getpass import GetPassWarning, getpass
from typing import cast

from pydantic import SecretStr

from rdp.accounts._inputs import password_text
from rdp.accounts._issues import problem
from rdp.accounts.errors import AccountInputError
from rdp.accounts.policy import LOGIN_WAIT
from rdp.accounts.service import AccountService
from rdp.accounts.types import AccountView, Credentials, NewAccount, Role
from rdp.audit.types import OPS_AUDIT_CONTEXT
from rdp.infra.diagnostics import DefectError, ExternalError
from rdp.infra.timeutil import ensure_utc
from rdp.ops.audit import report_audit_append_failure


def create_first_admin(
    service: AccountService,
    login_name: str,
    display_name: str,
    *,
    now: datetime,
    read_password: Callable[[str], str] = getpass,
) -> AccountView:
    """两次隐式读取口令后创建首个管理员。

    Args:
        service: 已迁移临时或生产数据库的 AccountService，不可空、不接管生命周期。
        login_name: 3-32 位严格小写 ASCII 登录名，不修剪、不折叠大小写。
        display_name: 1-64 个码点，无首尾空白或控制字符。
        now: 调用方传入的 aware 时刻，UTC 规范化、微秒精度，不在函数内读时钟。
        read_password: 接收固定中文提示、返回原文的可注入函数；默认 getpass，测试用内存替身。

    Returns:
        启用管理员 AccountView，must_change_password=False，操作者快照为运维；不签发会话。

    Raises:
        AccountInputError: 两次口令不一致或长度/字段不合法；不输出任何原文。
        ConflictError: 已有任何管理员（含停用）、登录名重复或写锁/约束冲突。
        InputError: 数据库损坏，沿用领域服务。
        ExternalError: 默认 getpass 无法无回显读取（含 GetPassWarning）、输入 I/O、数据库 I/O 或 Argon2 名额排队超过 1 秒。
        DefectError: 调用方 now 不是有效 aware 时刻、UTC 换算/截止加时溢出，或哈希/数据库程序错误，固定安全诊断，压制读口令回调的原始异常消息。
        EOFError: 输入结束，原样传播且不开始写事务。
        KeyboardInterrupt: 用户取消，原样传播且不开始写事务。

    Side Effects:
        先校验调用方提供的 now；非法值归平台 DefectError，不把它与用户输入错误混淆。
        两次读取后用常量时间比较 UTF-8 字节，再包装 SecretStr 调用领域服务；默认输入必须无回显，
        不允许 getpass 自动退回回显模式。成功仅创建一条账号；错误/取消不留部分账号。
        首号判断在 BEGIN IMMEDIATE 内完成，并发只有一个成功；不建真实默认状态目录。

    Time Semantics:
        交互等待由操作者决定，无自动重试；口令输入期间不持数据库锁，所有写时间采用 now。
        PasswordCodec 入场最多排队 1 秒，排队/运算不持数据库事务，释放名额后才申请最多约 5 秒的写锁；
        超时不计失败、不留账号；不 dispose 引擎。
    """
    moment = _moment(now)
    secret = _read_pair(read_password)
    try:
        return service.create_first_admin(
            NewAccount(Credentials(login_name, secret), display_name, Role.ADMINISTRATOR),
            now=moment,
            audit=OPS_AUDIT_CONTEXT,
        )
    except Exception as error:
        report_audit_append_failure(error)
        raise


def reset_account_password(
    service: AccountService,
    login_name: str,
    *,
    now: datetime,
    read_password: Callable[[str], str] = getpass,
) -> AccountView:
    """通过可信本地运维重置已有账号口令以恢复访问。

    Args:
        service: AccountService，不可空；不创建数据库或接管生命周期。
        login_name: 已有账号的严格登录名，3-32 位小写 ASCII。
        now: 注入的 aware 当前时刻，微秒精度，UTC 规范化。
        read_password: 与 create_first_admin 相同的两次无回显读口令函数，默认 getpass。

    Returns:
        更新后的 AccountView，must_change_password=True，不改变角色或启停状态。

    Raises:
        AccountInputError: 两次输入不一致或口令/登录名不合法，不回显原文。
        AccountNotFoundError: 目标账号不存在；此信息仅限可信本地运维。
        ConflictError: 写锁或约束冲突。
        InputError: 数据库损坏。
        ExternalError: 无法无回显读取、输入 I/O、数据库 I/O 或 Argon2 名额排队超过 1 秒。
        DefectError: 调用方 now 无效/UTC 换算或截止加时溢出，或哈希、SQL、读口令回调程序错误，固定安全诊断，不保留秘密异常链。
        EOFError: 输入结束，不开始事务。
        KeyboardInterrupt: 取消输入，不开始事务。

    Side Effects:
        先将调用方非法 now 归 DefectError；两次无回显输入并常量时间比较后，领域在事务外算好新哈希，
        再在写事务保存该哈希、清 G2、置强制改密、删目标全部会话，
        修改人记 ActorRef(None,"运维")；失败全回滚，不恢复已有停用账号、不返回口令或令牌。

    Time Semantics:
        输入和 Argon2 排队/运算均不持锁；哈希最多排队 1 秒，结束后才申请约 5 秒的写锁，now 来自调用方，无重试。
    """
    moment = _moment(now)
    secret = _read_pair(read_password)
    try:
        return service.reset_password_from_ops(
            login_name, secret, now=moment, audit=OPS_AUDIT_CONTEXT
        )
    except Exception as error:
        report_audit_append_failure(error)
        raise


def _moment(value: datetime) -> datetime:
    """调用者提供的时钟错误属于平台缺陷，必须在任何口令读取前拒绝。"""
    try:
        moment = ensure_utc(value)
        _ = moment + LOGIN_WAIT
        return moment
    except Exception:
        raise DefectError() from None


def _read_pair(reader: Callable[[str], str]) -> SecretStr:
    """拒绝 getpass 的有回显降级；输入失败只保留安全类别，取消原样传播。"""
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", GetPassWarning)
            first = reader("请输入口令：")
            second = reader("请再次输入口令：")
        if not isinstance(cast(object, first), str) or not isinstance(cast(object, second), str):
            raise DefectError()
    except EOFError:
        raise
    except (OSError, GetPassWarning):
        raise problem(ExternalError, "无法安全读取口令，请使用支持无回显输入的终端") from None
    except Exception:
        raise DefectError() from None
    secret = SecretStr(first)
    first = password_text(secret)
    second = password_text(SecretStr(second))
    if not hmac.compare_digest(first.encode("utf-8"), second.encode("utf-8")):
        raise problem(AccountInputError, "两次输入的口令不一致")
    return secret
