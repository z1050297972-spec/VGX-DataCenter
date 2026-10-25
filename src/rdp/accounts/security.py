"""账号领域秘密边界（06 G3），复用 argon2-cffi、secrets、hashlib、hmac 和 threading.BoundedSemaphore。

PasswordHasher 默认使用 Argon2id；测试可注入更低成本但仍使用 Argon2id 的 hasher。
Argon2 库异常转换成固定安全 DefectError 并 suppress_context，避免底层消息进入完整报错。
所有实例共享进程内 ARGON2_MAX_CONCURRENCY=2 个名额；初始化假哈希、hash、verify 及其重哈希均受限。
用标准库 BoundedSemaphore，单次入场最多等待 ARGON2_QUEUE_TIMEOUT_S=1 秒，以 monotonic 计时；
超时抛 ExternalError（安全诊断“哈希资源繁忙，请稍后重试。”），不得开始 Argon2 或自行重试。
取得名额后在 finally 释放，成功、拒绝及异常均不泄漏名额；verify 与紧接的重哈希共用一次名额，
内部重哈希不递归申请第二个名额。排队超时只限制入场，不强行中断已开始的 Argon2 运算。
调用方不得持有数据库事务申请名额或执行 Argon2；等待发生于同步工作线程；不持有名额等待另一项 Argon2 任务。请求取消不提前释放仍在运算的名额，
只有运算真实退出后才释放；不同进程的上限分别生效。
只在内存中解包 SecretStr；不记录日志，不把秘密放入异常、诊断、repr 或 OpenAPI 示例。
"""

import base64
import hashlib
import re
import secrets
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass, field
from threading import BoundedSemaphore
from typing import cast

from argon2 import PasswordHasher, Type, extract_parameters
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from pydantic import SecretStr

from rdp.accounts._inputs import password_text
from rdp.accounts._issues import problem
from rdp.accounts.errors import AuthenticationError
from rdp.accounts.policy import (
    ARGON2_MAX_CONCURRENCY,
    ARGON2_QUEUE_TIMEOUT_S,
    MAX_ARGON_MEMORY_KIB,
    MAX_ARGON_PARALLELISM,
    MAX_ARGON_TIME_COST,
    PASSWORD_HASH_MAX_CHARS,
    SESSION_TOKEN_BYTES,
    SESSION_TOKEN_PATTERN,
)
from rdp.infra.diagnostics import DefectError, ExternalError, InputError


@dataclass(frozen=True)
class PasswordCheck:
    """口令核验结果；替代哈希仅由成功登录事务保存。

    Attributes:
        matched: 是否匹配，布尔、无单位、不可空、无默认；未知账号和错口令均 False。
        replacement_hash: 新的 Argon2id 编码，1-512 个字符、无单位、无默认；无需重哈希为 None，
            matched=False 时必须为 None；排除 repr，不返回接口。
    """

    matched: bool
    replacement_hash: str | None = field(repr=False)


class PasswordCodec:
    """一个应用或运维调用拥有的 Argon2id 验证器，不持有用户原文。

    Attributes:
        hasher: argon2.PasswordHasher，不可空、无单位；默认 PasswordHasher() 的库参数。
        dummy_hash: 进程初始化时随机秘密的 Argon2id 编码，不可空、无默认、最多 512 字符；
            原始随机秘密立即丢弃，未知账号也走一次 verify，不为每次请求重新生成。
    """

    hasher: PasswordHasher
    dummy_hash: str

    def __init__(self, hasher: PasswordHasher | None = None) -> None:
        """构造默认 Argon2id 编码器和一次性假账号哈希。

        Args:
            hasher: 已配置的 Argon2id PasswordHasher，无单位；None 使用库默认值，测试可降成本。

        Returns:
            无；保存 hasher 和随机 dummy_hash，不保留假口令原文。

        Raises:
            ExternalError: 共享 Argon2 名额排队超过 1 秒，安全资源繁忙诊断；不创建半初始化编码器。
            DefectError: hasher 不是 Argon2id，或熵源、哈希初始化失败；转换为安全异常且不保留秘密异常链。

        Side Effects:
            只在内存分配 Argon2 工作区并向系统熵源取随机数，不访问数据库、日志或网络。

        Time Semantics:
            启动时假哈希也申请共享名额，最多排队 1 秒；运算成本由库参数决定，无硬实时承诺或重试。
        """
        try:
            self.hasher = PasswordHasher() if hasher is None else hasher
            if (
                not isinstance(cast(object, self.hasher), PasswordHasher)
                or self.hasher.type is not Type.ID
            ):
                raise DefectError()
            # 初始化的假哈希也须计入全进程并发上限。
            with _capacity():
                self.dummy_hash = self.hasher.hash(secrets.token_bytes(32))
        except ExternalError:
            raise
        except Exception:
            raise DefectError() from None

    def hash(self, password: SecretStr) -> str:
        """校验长度并生成带独立随机盐的 Argon2id 口令哈希。

        Args:
            password: SecretStr，10-128 个 Unicode 码点，允许空格和任意组合；拒绝代理码点，不归一化。

        Returns:
            不超过 512 字符的 Argon2id 编码，含盐和参数；同口令多次调用得到不同哈希。

        Raises:
            AccountInputError: 类型错误、码点数不在范围或含代理码点；不回显原文。
            ExternalError: 共享名额排队超过 1 秒，返回资源繁忙，不开始哈希。
            DefectError: Argon2 或熵源失败；只抛安全固定诊断，压制原始异常链。

        Side Effects:
            仅熵源读取和内存哈希；失败不返回部分哈希，不存储原文或写日志。

        Time Semantics:
            在同步工作线程最多排队 1 秒，以 monotonic 测量；哈希期间占一个名额，退出必释放，无重试。
        """
        raw = password_text(password)
        with _capacity():
            try:
                return self.hasher.hash(raw)
            except Exception:
                raise DefectError() from None

    def verify(self, encoded: str | None, password: SecretStr) -> PasswordCheck:
        """验证口令，并在成功且参数过时时产生替代哈希。

        Args:
            encoded: 1-512 字符的已存 Argon2id 编码；None 表示未知或停用账号，使用 dummy_hash。
            password: 同 hash 的 SecretStr 约束，不修剪或归一化。

        Returns:
            已知有效账号匹配时 matched=True，check_needs_rehash 为真时带替代哈希；
            不匹配或 encoded=None 时 False/None。比较由 Argon2 库执行，禁止自行比较口令字符串。

        Raises:
            AccountInputError: password 不满足 hash 的输入约束。
            InputError: 已存编码损坏、不是 Argon2id 或参数超过 policy.MAX_ARGON_* 成本，视为存量数据问题；不输出哈希。
            ExternalError: 共享名额排队超过 1 秒，不执行验证或重哈希。
            DefectError: Argon2 运行失败；不把含秘密的底层消息或异常链交给报告器。

        Side Effects:
            只做内存核验/可选重哈希；encoded=None 也做一次同成本 dummy verify，返回 False/None；
            不存数据库、不计失败次数。假验证只统一这条计算路径，不承诺账号存在性不可探测。
            verify 和需要的重哈希在同一名额内顺序执行，不调用会重新入场的公开 hash，异常也释放名额。

        Time Semantics:
            最多排队 1 秒，monotonic 计时；已入场的验证/重哈希无硬实时上限，不自动重试或保证网络级恒定耗时。
        """
        raw = password_text(password)
        if encoded is not None:
            _check_encoded(encoded)
        with _capacity():
            try:
                self.hasher.verify(self.dummy_hash if encoded is None else encoded, raw)
                replacement = (
                    self.hasher.hash(raw)
                    if encoded is not None and self.hasher.check_needs_rehash(encoded)
                    else None
                )
                return PasswordCheck(matched=encoded is not None, replacement_hash=replacement)
            except VerifyMismatchError:
                return PasswordCheck(matched=False, replacement_hash=None)
            except (InvalidHashError, VerificationError):
                failure = problem(InputError, "已存口令编码不合法", field="password_hash")
                raise failure from None
            except Exception:
                raise DefectError() from None


def new_session_token() -> SecretStr:
    """生成仅在 cookie 边界使用的高熵会话原文。

    Args:
        无。

    Returns:
        secrets.token_urlsafe(32) 的 SecretStr，43 位 URL 安全 ASCII，256 位熵，无默认值。

    Raises:
        DefectError: 系统熵源失败，固定安全诊断，不回显任何部分令牌。

    Side Effects:
        只读系统熵源，不入库、不写日志；失败没有部分会话。

    Time Semantics:
        同步生成，无时钟读取或重试。
    """
    try:
        return SecretStr(secrets.token_urlsafe(SESSION_TOKEN_BYTES))
    except Exception:
        raise DefectError() from None


def session_digest(token: SecretStr) -> str:
    """把高熵会话原文转换成可索引的 SHA-256 摘要。

    Args:
        token: 严格 43 位 URL 安全 ASCII 的 SecretStr，不可空；必须解码成 32 字节且重新编码完全一致。

    Returns:
        64 位小写 SHA-256 hex；对高熵随机令牌无需盐或慢哈希，原文不持久化。

    Raises:
        AuthenticationError: 非法类型、长度、字符或非规范编码，使用统一未登录诊断，不回显原文。

    Side Effects:
        无；仅内存转换，不读数据库，不记日志。

    Time Semantics:
        同步、无时钟；查库后还须 hmac.compare_digest 复核固定长度摘要，避免普通字符串比较。
    """
    if not isinstance(cast(object, token), SecretStr):
        failure = problem(AuthenticationError, "会话无效", field="session")
        raise failure
    raw = token.get_secret_value()
    if re.fullmatch(SESSION_TOKEN_PATTERN, raw) is None:
        failure = problem(AuthenticationError, "会话无效", field="session")
        raise failure
    decoded = base64.urlsafe_b64decode(raw + "=")
    if (
        len(decoded) != SESSION_TOKEN_BYTES
        or base64.urlsafe_b64encode(decoded).decode("ascii").rstrip("=") != raw
    ):
        failure = problem(AuthenticationError, "会话无效", field="session")
        raise failure
    return hashlib.sha256(decoded).hexdigest()


def _check_encoded(encoded: object) -> None:
    """先限定存量编码与资源成本，再交 Argon2，避免损坏参数造成失控分配。"""
    try:
        if not isinstance(encoded, str) or not 1 <= len(encoded) <= PASSWORD_HASH_MAX_CHARS:
            raise ValueError()
        value = extract_parameters(encoded)
        if (
            value.type is not Type.ID
            or not 1 <= value.memory_cost <= MAX_ARGON_MEMORY_KIB
            or not 1 <= value.time_cost <= MAX_ARGON_TIME_COST
            or not 1 <= value.parallelism <= MAX_ARGON_PARALLELISM
        ):
            raise ValueError()
    except Exception:
        failure = problem(InputError, "已存口令编码或成本不合法", field="password_hash")
        raise failure from None


# 跨实例共享名额，不能按每个请求另建信号量而放大内存峰值。
_slots = BoundedSemaphore(ARGON2_MAX_CONCURRENCY)


@contextmanager
def _capacity() -> Generator[None]:
    """只限制进入运算的排队时间，名额必须留到真实运算结束才释放。"""
    if not _slots.acquire(timeout=ARGON2_QUEUE_TIMEOUT_S):
        failure = problem(ExternalError, "哈希资源繁忙，请稍后重试。", field="password")
        raise failure
    try:
        yield
    finally:
        _slots.release()
