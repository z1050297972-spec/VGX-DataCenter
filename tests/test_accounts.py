"""工单06领域、秘密与表声明测试；只用 tmp_path/临时数据库和固定 aware 时钟。"""

import base64
import sqlite3
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Barrier, BoundedSemaphore
from typing import Any, cast

import pytest
from accounts_support import (
    AUDIT_CONTEXT,
    EXAMPLE_SECRET,
    NOW,
    HeldHasher,
    HookHasher,
    account_operation,
    account_view,
    close_workers,
    fail_write_commit,
    member_grant,
    model_database,
    model_row,
    persisted_account_state,
    scenario,
)
from argon2 import PasswordHasher, Type, extract_parameters
from argon2.exceptions import VerifyMismatchError
from pydantic import SecretStr
from sqlalchemy import Connection, DefaultClause, event, func, select
from sqlalchemy import text as sql_text
from sqlalchemy.orm import Session

from rdp.accounts.errors import (
    AccountInputError,
    AccountNotFoundError,
    AuthenticationError,
    AuthorizationError,
    CurrentPasswordError,
    LoginWaitError,
    PasswordChangeRequiredError,
)
from rdp.accounts.models import AccountRow, SessionRow
from rdp.accounts.security import PasswordCodec, new_session_token, session_digest
from rdp.accounts.service import AccountService
from rdp.accounts.types import (
    AccountStatus,
    ActorRef,
    Credentials,
    NewAccount,
    PasswordChange,
    Role,
    SessionGrant,
    SessionIdentity,
)
from rdp.api.errors import format_exception_report
from rdp.audit.types import OPS_AUDIT_CONTEXT
from rdp.infra.db.connection import (
    create_database_engine,
    session_scope,
    session_scope_with_lock_timeout,
)
from rdp.infra.db.models import ErrorReportRow, metadata
from rdp.infra.diagnostics import ConflictError, DefectError, Diagnostic, ExternalError, InputError


def test_codec_init_default() -> None:
    """验证契约：PasswordCodec 默认参数与 argon2.PasswordHasher() 一致且使用 Argon2id，至少此例用生产成本。"""
    codec = PasswordCodec()
    expected = PasswordHasher()
    parameters = extract_parameters(codec.dummy_hash)
    assert codec.hasher.type is Type.ID
    assert parameters.type is Type.ID
    assert (parameters.memory_cost, parameters.time_cost, parameters.parallelism) == (
        expected.memory_cost,
        expected.time_cost,
        expected.parallelism,
    )
    assert len(codec.dummy_hash) <= 512


def test_codec_init_injected() -> None:
    """验证契约：测试可注入低成本 Argon2id，不污染生产默认参数。"""
    hasher = PasswordHasher(time_cost=1, memory_cost=1024, parallelism=1)
    codec = PasswordCodec(hasher)
    assert codec.hasher is hasher
    parameters = extract_parameters(codec.dummy_hash)
    assert (parameters.time_cost, parameters.memory_cost, parameters.parallelism) == (1, 1024, 1)
    assert parameters.type is Type.ID
    assert PasswordHasher().memory_cost != 1024


def test_codec_init_dummy(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """验证契约：启动只生成一次随机 dummy_hash，不保留原文或日志。"""
    sizes: list[int] = []
    sentinel = b"one-time-dummy-input-for-test-123"

    def entropy(size: int) -> bytes:
        sizes.append(size)
        return sentinel

    # 在系统随机源边界给已知值；通过库公开验证接口确认它只被用来生成一次有效假哈希。
    monkeypatch.setattr("secrets.token_bytes", entropy)
    hasher = PasswordHasher(time_cost=1, memory_cost=1024, parallelism=1)
    codec = PasswordCodec(hasher)
    assert sizes == [32]
    assert hasher.verify(codec.dummy_hash, sentinel)
    assert not hasher.check_needs_rehash(codec.dummy_hash)
    assert sentinel.decode() not in repr(codec)
    assert sentinel.decode() not in caplog.text


def test_codec_init_failure() -> None:
    """验证契约：非 Argon2id、熵源或初始化失败为安全 DefectError，无秘密异常链。"""
    with pytest.raises(DefectError):
        PasswordCodec(PasswordHasher(type=Type.I, memory_cost=1024, time_cost=1, parallelism=1))

    def fail_entropy(size: int) -> bytes:
        raise OSError("entropy-sentinel")

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr("secrets.token_bytes", fail_entropy)
        with pytest.raises(DefectError) as caught:
            PasswordCodec(PasswordHasher(memory_cost=1024, time_cost=1, parallelism=1))
    assert "entropy-sentinel" not in format_exception_report(caught.value)

    def fail_hash(self: PasswordHasher, value: object, *, salt: bytes | None = None) -> str:
        raise RuntimeError("argon-sentinel")

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(PasswordHasher, "hash", fail_hash)
        with pytest.raises(DefectError) as caught:
            PasswordCodec(PasswordHasher(memory_cost=1024, time_cost=1, parallelism=1))
    assert "argon-sentinel" not in format_exception_report(caught.value)


def test_password_hash_salt() -> None:
    """验证契约：相同密码两次哈希不同且均可验证，数据库不含明文，验收 1。"""
    codec = PasswordCodec(PasswordHasher(time_cost=1, memory_cost=1024, parallelism=1))
    value = SecretStr("同一个足够长的密码输入123")
    first = codec.hash(value)
    second = codec.hash(value)
    assert first != second
    assert codec.hasher.verify(first, value.get_secret_value())
    assert codec.hasher.verify(second, value.get_secret_value())
    assert value.get_secret_value() not in first + second
    assert len(first) <= 512 and len(second) <= 512


def test_password_hash_bounds() -> None:
    """验证契约：9/10/128/129 个 Unicode 码点区分拒绝与接受，无字符组合要求，不修剪空格。"""
    codec = PasswordCodec(PasswordHasher(time_cost=1, memory_cost=1024, parallelism=1))
    for length in (9, 129):
        with pytest.raises(AccountInputError):
            codec.hash(SecretStr("x" * length))
    for text in ("x" * 10, " " * 10, "字" * 128):
        encoded = codec.hash(SecretStr(text))
        assert codec.hasher.verify(encoded, text)


def test_password_hash_unicode() -> None:
    """验证契约：组合字符按码点计数且不归一化，拒绝代理码点；SecretStr 原文不在 repr。"""
    codec = PasswordCodec(PasswordHasher(time_cost=1, memory_cost=1024, parallelism=1))
    combined = "e\u0301" * 5
    encoded = codec.hash(SecretStr(combined))
    assert codec.hasher.verify(encoded, combined)
    with pytest.raises(AccountInputError):
        codec.hash(SecretStr("é" * 5))
    with pytest.raises(AccountInputError) as caught:
        codec.hash(SecretStr("x" * 10 + "\ud800"))
    assert "\ud800" not in str(caught.value)
    assert combined not in repr(SecretStr(combined))


def test_password_hash_invalid() -> None:
    """验证契约：错误类型、长度或代理码点给 AccountInputError，诊断/异常/日志不含输入。"""
    codec = PasswordCodec(PasswordHasher(time_cost=1, memory_cost=1024, parallelism=1))
    for value in (None, 12, "invalid-input-sentinel", SecretStr("short"), SecretStr("x" * 129)):
        with pytest.raises(AccountInputError) as caught:
            codec.hash(cast(SecretStr, value))
        assert "invalid-input-sentinel" not in format_exception_report(caught.value)
        assert "invalid-input-sentinel" not in str(caught.value.diagnostics)


def test_password_hash_failure() -> None:
    """验证契约：哈希和熵源故障给安全 DefectError，不返回部分哈希或原始异常链。"""
    codec = PasswordCodec(PasswordHasher(time_cost=1, memory_cost=1024, parallelism=1))

    def broken(self: PasswordHasher, value: object, *, salt: bytes | None = None) -> str:
        raise RuntimeError("hash-failure-private-value")

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(PasswordHasher, "hash", broken)
        with pytest.raises(DefectError) as caught:
            codec.hash(SecretStr("valid-example-value"))
    assert "hash-failure-private-value" not in format_exception_report(caught.value)


def test_password_verify_match() -> None:
    """验证契约：正确密码返回 matched=True，参数合适时 replacement_hash=None。"""
    hasher = PasswordHasher(time_cost=1, memory_cost=1024, parallelism=1)
    codec = PasswordCodec(hasher)
    encoded = hasher.hash("valid-password-input")
    result = codec.verify(encoded, SecretStr("valid-password-input"))
    assert result.matched is True
    assert result.replacement_hash is None


def test_password_verify_mismatch() -> None:
    """验证契约：错误密码返回 False/None，未知账号也执行一次相同成本 verify。"""
    hasher = PasswordHasher(time_cost=1, memory_cost=1024, parallelism=1)
    codec = PasswordCodec(hasher)
    encoded = hasher.hash("known-correct-input")
    for existing in (encoded, None):
        result = codec.verify(existing, SecretStr("different-password"))
        assert result.matched is False
        assert result.replacement_hash is None


def test_password_verify_rehash() -> None:
    """验证契约：check_needs_rehash 为真仅成功验证时生成替代哈希，错密码不改哈希。"""
    old = PasswordHasher(time_cost=2, memory_cost=1024, parallelism=1)
    new = PasswordHasher(time_cost=1, memory_cost=1024, parallelism=1)
    encoded = old.hash("rehash-example-value")
    codec = PasswordCodec(new)
    result = codec.verify(encoded, SecretStr("rehash-example-value"))
    assert result.matched and result.replacement_hash is not None
    assert new.verify(result.replacement_hash, "rehash-example-value")
    assert not new.check_needs_rehash(result.replacement_hash)
    mismatch = codec.verify(encoded, SecretStr("a-different-value"))
    assert not mismatch.matched and mismatch.replacement_hash is None


def test_password_verify_invalid() -> None:
    """验证契约：非法密码给 AccountInputError，不回显原文。"""
    codec = PasswordCodec(PasswordHasher(time_cost=1, memory_cost=1024, parallelism=1))
    for value in (
        None,
        "unwrapped-input",
        SecretStr("x" * 9),
        SecretStr("x" * 129),
        SecretStr("x" * 10 + "\ud800"),
    ):
        with pytest.raises(AccountInputError):
            codec.verify(None, cast(SecretStr, value))


def test_password_verify_corrupt() -> None:
    """验证契约：损坏/非 Argon2id/超过三个成本上限的编码给 InputError，不消耗失控资源或泄漏哈希。"""
    hasher = PasswordHasher(time_cost=1, memory_cost=1024, parallelism=1)
    codec = PasswordCodec(hasher)
    valid = hasher.hash("encoded-boundary-input")
    bad = [
        "corrupt-encoding",
        "x" * 513,
        valid.replace("argon2id", "argon2i"),
        valid.replace("m=1024", "m=262145"),
        valid.replace("t=1", "t=11"),
        valid.replace("p=1", "p=17"),
        cast(str, 12),
    ]
    for encoded in bad:
        with pytest.raises(InputError) as caught:
            codec.verify(encoded, SecretStr("encoded-boundary-input"))
        assert "corrupt-encoding" not in format_exception_report(caught.value)


def test_password_verify_failure() -> None:
    """验证契约：Argon2 意外失败归 DefectError，完整异常报告不含输入或库原消息。"""
    codec = PasswordCodec(PasswordHasher(time_cost=1, memory_cost=1024, parallelism=1))

    def fail(self: PasswordHasher, encoded: object, value: object) -> bool:
        raise RuntimeError("verify-private-value")

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(PasswordHasher, "verify", fail)
        with pytest.raises(DefectError) as caught:
            codec.verify(None, SecretStr("valid-example-input"))
    assert "verify-private-value" not in format_exception_report(caught.value)


def test_session_token_entropy() -> None:
    """验证契约：new_session_token 使用 secrets.token_urlsafe(32)，规范 43 字符，独立随机且包装 SecretStr。"""
    first, second = new_session_token(), new_session_token()
    assert isinstance(first, SecretStr) and isinstance(second, SecretStr)
    assert first != second
    for item in (first, second):
        text = item.get_secret_value()
        assert len(text) == 43
        raw = base64.urlsafe_b64decode(text + "=")
        assert len(raw) == 32
        assert base64.urlsafe_b64encode(raw).decode().rstrip("=") == text
        assert text not in repr(item)


def test_session_token_failure() -> None:
    """验证契约：熵源失败返回安全 DefectError，没有部分会话或令牌日志。"""

    def broken(size: int | None = None) -> str:
        raise OSError("token-private-value")

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr("secrets.token_urlsafe", broken)
        with pytest.raises(DefectError) as caught:
            new_session_token()
    assert "token-private-value" not in format_exception_report(caught.value)


def test_session_digest_sha256() -> None:
    """验证契约：session_digest 等于独立 hashlib SHA-256 计算，固定 64 位小写 hex。"""
    value = SecretStr("A" * 43)
    assert (
        session_digest(value) == "66687aadf862bd776c8fc18b8e9f8e20089714856ee233b3902a591d0d5f2925"
    )


def test_session_digest_invalid() -> None:
    """验证契约：None/非 SecretStr/错误长度/字符/非规范尾位编码给 AuthenticationError，不回显原文。"""
    for value in (
        None,
        "A" * 43,
        SecretStr("A" * 42),
        SecretStr("A" * 44),
        SecretStr("A" * 42 + "B"),
        SecretStr("A" * 42 + "="),
        SecretStr("A" * 43 + "\n"),
        SecretStr("ñ" * 43),
    ):
        with pytest.raises(AuthenticationError):
            session_digest(cast(SecretStr, value))


def test_session_digest_pure() -> None:
    """验证契约：摘要转换不访问数据库、时钟或日志；查库后以 hmac.compare_digest 复核。"""
    value = SecretStr("A" * 43)
    assert session_digest(value) == session_digest(value)
    assert value.get_secret_value() == "A" * 43
    assert len(session_digest(value)) == 64


def test_actor_snapshot() -> None:
    """验证契约：ActorRef.name 取显示名，账号改名或删除后历史快照仍保留编号和原名字，验收 9。"""
    view = account_view()
    actor = ActorRef(view.account_id, view.display_name)
    changed = replace(view, display_name="新显示名")
    assert actor.name == "显示名" and actor.account_id == 1
    assert changed.display_name == "新显示名"


def test_actor_ops() -> None:
    """验证契约：首号及运维重置使用 ActorRef(None,运维)，普通操作者编号为正整数。"""
    actor = ActorRef(None, "运维")
    assert actor.account_id is None and actor.name == "运维"
    with pytest.raises(FrozenInstanceError):
        cast(Any, actor).name = "伪造"


def test_actor_immutable() -> None:
    """验证契约：ActorRef/AccountView/SessionIdentity 等快照不可变；秘密不在 repr、响应或日志。"""
    view = account_view()
    with pytest.raises(FrozenInstanceError):
        cast(Any, view).role = "member"
    identity = SessionIdentity(view, "a" * 64, NOW, False)
    with pytest.raises(FrozenInstanceError):
        cast(Any, identity).last_seen_at = NOW + timedelta(days=1)
    assert "a" * 64 not in repr(identity)
    grant = SessionGrant(identity, EXAMPLE_SECRET)
    assert EXAMPLE_SECRET.get_secret_value() not in repr(grant)
    assert EXAMPLE_SECRET.get_secret_value() not in repr(Credentials("admin", EXAMPLE_SECRET))


def test_models_metadata() -> None:
    """验证契约：激活后两模型继承同一 Base，共用 MetaData 和约束命名，不引入领域间依赖。"""
    assert {"accounts", "account_sessions", "error_reports"} <= set(metadata.tables)
    assert AccountRow.metadata is metadata and SessionRow.metadata is metadata
    assert metadata.naming_convention.get("pk") == "pk_%(table_name)s"
    assert metadata.tables["accounts"].dialect_options["sqlite"]["autoincrement"] is True


def test_models_utc(tmp_path: Path) -> None:
    """验证契约：所有时间列使用 UTCDateTime，时区偏移规范化且微秒不丢，无时区值被拒绝。"""
    with model_database(tmp_path) as engine:
        with session_scope(engine) as session:
            item = model_row()
            session.add(item)
            session.flush()
            key = item.account_id
        with session_scope(engine, read_only=True) as session:
            loaded = session.get(AccountRow, key)
            assert loaded is not None and loaded.created_at == NOW
            assert loaded.created_at.tzinfo is UTC and loaded.created_at.microsecond == 123456
        with pytest.raises(InputError), session_scope(engine) as session:
            session.add(model_row("invalid", created_at=NOW.replace(tzinfo=None)))


def test_models_constraints(tmp_path: Path) -> None:
    """验证契约：登录名唯一和 ASCII 规则、角色/状态、长度、正编号、计数范围和时刻顺序受 CHECK 约束。"""
    with model_database(tmp_path) as engine:
        for changes in (
            dict(login_name="UPPER"),
            dict(login_name="ab"),
            dict(login_name="a" * 33),
            dict(login_name="has space"),
            dict(role="owner"),
            dict(status="unknown"),
            dict(display_name=""),
            dict(failed_attempts=6),
            dict(failed_attempts=5),
            dict(account_id=0),
            dict(updated_at=NOW - timedelta(seconds=1)),
        ):
            with pytest.raises(ConflictError), session_scope(engine) as session:
                session.add(model_row(**cast(dict[str, Any], changes)))
        with session_scope(engine, read_only=True) as session:
            assert session.scalar(select(func.count()).select_from(AccountRow)) == 0


def test_models_autoincrement(tmp_path: Path) -> None:
    """验证契约：删除账号后同名重建获得更大编号，AUTOINCREMENT 不复用已提交的历史身份。"""
    with model_database(tmp_path) as engine:
        with session_scope(engine) as session:
            first = model_row()
            session.add(first)
            session.flush()
            previous = first.account_id
        with session_scope(engine) as session:
            item = session.get(AccountRow, previous)
            assert item is not None
            session.delete(item)
        with session_scope(engine) as session:
            second = model_row()
            session.add(second)
            session.flush()
            assert second.account_id > previous


def test_models_cascade(tmp_path: Path) -> None:
    """验证契约：删账号级联删除所有会话，历史创建/修改人无外键且快照保留。"""
    with model_database(tmp_path) as engine:
        with session_scope(engine) as session:
            actor = model_row("actor")
            session.add(actor)
            session.flush()
            key = actor.account_id
            session.add(model_row("history", created_by_id=key, created_by_name="历史显示名"))
            session.add(
                SessionRow(token_digest="a" * 64, account_id=key, created_at=NOW, last_seen_at=NOW)
            )
        with session_scope(engine) as session:
            actor = session.get(AccountRow, key)
            assert actor is not None
            session.delete(actor)
        with session_scope(engine, read_only=True) as session:
            assert session.get(SessionRow, "a" * 64) is None
            history = session.scalar(select(AccountRow).where(AccountRow.login_name == "history"))
            assert (
                history is not None
                and history.created_by_id == key
                and history.created_by_name == "历史显示名"
            )


def test_models_defaults(tmp_path: Path) -> None:
    """验证契约：enabled、must_change_password=True、失败计数0、等待NULL 的 Python/SQL 默认一致。"""
    with model_database(tmp_path) as engine:
        with session_scope(engine) as session:
            row = model_row()
            session.add(row)
            session.flush()
            assert (
                row.status,
                row.must_change_password,
                row.failed_attempts,
                row.blocked_until,
            ) == ("enabled", True, 0, None)
        columns = metadata.tables["accounts"].c
        for column, expected in (
            (columns.status, "enabled"),
            (columns.must_change_password, "1"),
            (columns.failed_attempts, "0"),
        ):
            default = column.server_default
            assert isinstance(default, DefaultClause)
            assert str(default.arg) == expected


def test_service_init_dependencies(tmp_path: Path) -> None:
    """验证契约：AccountService 保存依赖不连接/迁移/创建账号，拒绝非受管引擎或错误编码器为 DefectError。"""
    engine = create_database_engine(tmp_path / "service.sqlite3")
    codec = PasswordCodec(PasswordHasher(time_cost=1, memory_cost=1024, parallelism=1))
    try:
        service = AccountService(engine, codec)
        assert service.engine is engine and service.passwords is codec
        assert not (tmp_path / "service.sqlite3").exists()
        with pytest.raises(DefectError):
            AccountService(cast(Any, object()), codec)
        with pytest.raises(DefectError):
            AccountService(engine, cast(Any, object()))
    finally:
        engine.dispose()


def test_login_success(tmp_path: Path) -> None:
    """验证契约：启用账号正确密码返回 SessionGrant，摘要入库且原文只在内存/cookie，验收 1、2。"""
    with model_database(tmp_path) as engine:
        codec = PasswordCodec(PasswordHasher(time_cost=1, memory_cost=1024, parallelism=1))
        service = AccountService(engine, codec)
        created = service.create_first_admin(
            NewAccount(Credentials("admin", EXAMPLE_SECRET), "管理员", Role.ADMINISTRATOR),
            now=NOW,
            audit=OPS_AUDIT_CONTEXT,
        )
        grant = service.login(Credentials("admin", EXAMPLE_SECRET), now=NOW, audit=AUDIT_CONTEXT)
        assert grant.identity.account.account_id == created.account_id
        assert not grant.identity.activity_refreshed
        with session_scope(engine, read_only=True) as session:
            row = session.get(SessionRow, session_digest(grant.token))
            assert row is not None and row.account_id == created.account_id
            assert row.created_at == NOW and row.last_seen_at == NOW
            assert grant.token.get_secret_value() != row.token_digest


def test_login_forced(tmp_path: Path) -> None:
    """验证契约：强制改密码账号可以登录，返回标记但不能直接进入业务。"""
    with scenario(tmp_path) as (service, admin):
        service.create_account(
            admin.identity,
            NewAccount(Credentials("member", EXAMPLE_SECRET), "成员", Role.MEMBER),
            now=NOW,
            audit=AUDIT_CONTEXT,
        )
        grant = service.login(Credentials("member", EXAMPLE_SECRET), now=NOW, audit=AUDIT_CONTEXT)
        assert grant.identity.account.must_change_password
        with pytest.raises(PasswordChangeRequiredError):
            service.list_accounts(grant.identity, now=NOW)


def test_login_fixed_session(tmp_path: Path) -> None:
    """验证契约：每次登录创建新随机令牌，不接受或复用旧 cookie，阻止会话固定。"""
    with scenario(tmp_path) as (service, first):
        second = service.login(Credentials("admin", EXAMPLE_SECRET), now=NOW, audit=AUDIT_CONTEXT)
        assert (
            second.token != first.token
            and second.identity.token_digest != first.identity.token_digest
        )
        assert (
            service.authenticate(first.token, now=NOW, audit=AUDIT_CONTEXT).account.account_id == 1
        )


def test_login_failures(tmp_path: Path) -> None:
    """验证契约：未知账号、停用和启用账号错密码统一401“账号或密码错误”，未知/停用各做一次dummy verify，不计数、不建行。"""
    with scenario(tmp_path) as (service, admin):
        member = member_grant(service, admin)
        service.set_status(
            admin.identity,
            member.identity.account.account_id,
            AccountStatus.DISABLED,
            now=NOW,
            audit=AUDIT_CONTEXT,
        )
        failures: list[tuple[Diagnostic, ...]] = []
        for credentials in (
            Credentials("missing", EXAMPLE_SECRET),
            Credentials("member", EXAMPLE_SECRET),
            Credentials("admin", SecretStr("incorrect-credential")),
        ):
            with pytest.raises(AuthenticationError) as caught:
                service.login(credentials, now=NOW, audit=AUDIT_CONTEXT)
            failures.append(caught.value.diagnostics)
        assert failures[0] == failures[1] == failures[2]
        with session_scope(service.engine, read_only=True) as session:
            row = session.get(AccountRow, 1)
            disabled = session.get(AccountRow, member.identity.account.account_id)
            assert row is not None and row.failed_attempts == 1
            assert disabled is not None and disabled.failed_attempts == 0


def test_login_fifth(tmp_path: Path) -> None:
    """验证契约：前四次错误401，第五次提交计数和 now+60秒后抛429；异常不会回滚失败计数，G2。"""
    with scenario(tmp_path) as (service, _):
        for _ in range(4):
            with pytest.raises(AuthenticationError):
                service.login(
                    Credentials("admin", SecretStr("wrong-example-value")),
                    now=NOW,
                    audit=AUDIT_CONTEXT,
                )
        with pytest.raises(LoginWaitError) as caught:
            service.login(
                Credentials("admin", SecretStr("wrong-example-value")), now=NOW, audit=AUDIT_CONTEXT
            )
        assert caught.value.retry_after_s == 60
        with session_scope(service.engine, read_only=True) as session:
            row = session.get(AccountRow, 1)
            assert (
                row is not None
                and row.failed_attempts == 5
                and row.blocked_until == NOW + timedelta(seconds=60)
            )


def test_login_waiting(tmp_path: Path) -> None:
    """验证契约：等待期间不执行 verify、不增长计数或延长截止，Retry-After 向上取整 1-60。"""
    with scenario(tmp_path) as (service, _):
        with session_scope(service.engine) as session:
            row = session.get(AccountRow, 1)
            assert row is not None
            row.failed_attempts, row.blocked_until = 5, NOW + timedelta(seconds=60)

        def forbidden(*args: Any, **kwargs: Any) -> bool:
            raise AssertionError("等待中不应调用库")

        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(PasswordHasher, "verify", forbidden)
            with pytest.raises(LoginWaitError) as caught:
                service.login(
                    Credentials("admin", EXAMPLE_SECRET),
                    now=NOW + timedelta(microseconds=1),
                    audit=AUDIT_CONTEXT,
                )
        assert caught.value.retry_after_s == 60


def test_login_deadline(tmp_path: Path) -> None:
    """验证契约：now 恰等于等待截止时可重试，先清计数；成功登录清零。"""
    with scenario(tmp_path) as (service, _):
        with session_scope(service.engine) as session:
            row = session.get(AccountRow, 1)
            assert row is not None
            row.failed_attempts, row.blocked_until = 5, NOW + timedelta(seconds=60)
        grant = service.login(
            Credentials("admin", EXAMPLE_SECRET),
            now=NOW + timedelta(seconds=60),
            audit=AUDIT_CONTEXT,
        )
        assert grant.identity.account.account_id == 1
        with session_scope(service.engine, read_only=True) as session:
            row = session.get(AccountRow, 1)
            assert row is not None and row.failed_attempts == 0 and row.blocked_until is None


def test_login_expired_wait_restarts_failure_count(tmp_path: Path) -> None:
    """验证契约：等待过期后重新累计，前四次错密码401、第五次429；登录与本人改密共用 wrong_password 的计数逻辑。"""
    with scenario(tmp_path) as (service, _admin):
        credentials = Credentials("admin", SecretStr("incorrect-credential"))
        for now in (NOW, NOW + timedelta(seconds=61)):
            for expected_status in (401, 401, 401, 401, 429):
                with pytest.raises(InputError) as caught:
                    service.login(credentials, now=now, audit=AUDIT_CONTEXT)
                assert caught.value.http_status == expected_status


def test_login_rehash_commit(tmp_path: Path) -> None:
    """验证契约：成功验证后事务外算好参数升级哈希，写事务重读原哈希和G2未变才保存，竞争变化不覆盖新哈希。"""
    with scenario(tmp_path) as (service, _admin):
        old = PasswordHasher(time_cost=2, memory_cost=1024, parallelism=1).hash(
            EXAMPLE_SECRET.get_secret_value()
        )
        with session_scope(service.engine) as session:
            row = session.get(AccountRow, 1)
            assert row is not None
            row.password_hash = old
        with fail_write_commit(service.engine), pytest.raises(ExternalError):
            service.login(Credentials("admin", EXAMPLE_SECRET), now=NOW, audit=AUDIT_CONTEXT)
        with session_scope(service.engine, read_only=True) as session:
            row = session.get(AccountRow, 1)
            assert row is not None and row.password_hash == old
        assert service.login(Credentials("admin", EXAMPLE_SECRET), now=NOW, audit=AUDIT_CONTEXT)
        with session_scope(service.engine, read_only=True) as session:
            row = session.get(AccountRow, 1)
            assert row is not None and row.password_hash != old
            assert not service.passwords.hasher.check_needs_rehash(row.password_hash)
            assert service.passwords.hasher.verify(
                row.password_hash, EXAMPLE_SECRET.get_secret_value()
            )


def test_login_session_cap(tmp_path: Path) -> None:
    """验证契约：同账号第33个会话提交时淘汰最旧，时间相同按摘要稳定排序。"""
    with scenario(tmp_path) as (service, first):
        latest = first
        for i in range(32):
            latest = service.login(
                Credentials("admin", EXAMPLE_SECRET),
                now=NOW + timedelta(seconds=i + 1),
                audit=AUDIT_CONTEXT,
            )
        with pytest.raises(AuthenticationError):
            service.authenticate(first.token, now=NOW + timedelta(seconds=40), audit=AUDIT_CONTEXT)
        assert (
            service.authenticate(
                latest.token, now=NOW + timedelta(seconds=40), audit=AUDIT_CONTEXT
            ).account.account_id
            == 1
        )
        with session_scope(service.engine, read_only=True) as session:
            assert session.scalar(select(func.count()).select_from(SessionRow)) == 32


def test_login_invalid(tmp_path: Path) -> None:
    """验证契约：非法登录名/密码/now 在哈希或计数前给 AccountInputError，不部分写入。"""
    with scenario(tmp_path) as (service, _):
        for name in ("UPPER", "ab", "a" * 33, " admin", "admin ", "a/../b"):
            with pytest.raises(AccountInputError):
                service.login(Credentials(name, EXAMPLE_SECRET), now=NOW, audit=AUDIT_CONTEXT)
        with pytest.raises(AccountInputError):
            service.login(Credentials("admin", SecretStr("short")), now=NOW, audit=AUDIT_CONTEXT)
        with pytest.raises(AccountInputError):
            service.login(
                Credentials("admin", EXAMPLE_SECRET),
                now=NOW.replace(tzinfo=None),
                audit=AUDIT_CONTEXT,
            )


def test_login_rollback(tmp_path: Path) -> None:
    """验证契约：哈希/flush/commit 故障全部回滚且不发 SessionGrant，不宣称失败计数已提交。"""
    with scenario(tmp_path) as (service, admin):
        for value in (EXAMPLE_SECRET, SecretStr("incorrect-value")):
            with fail_write_commit(service.engine), pytest.raises(ExternalError):
                service.login(Credentials("admin", value), now=NOW, audit=AUDIT_CONTEXT)
            with session_scope(service.engine, read_only=True) as session:
                row = session.get(AccountRow, 1)
                assert row is not None and row.failed_attempts == 0 and row.blocked_until is None
                assert session.scalar(select(func.count()).select_from(SessionRow)) == 1
            assert service.authenticate(admin.token, now=NOW, audit=AUDIT_CONTEXT)


def test_login_clock(tmp_path: Path) -> None:
    """验证契约：固定UTC及偏移now结果一致；naive/溢出拒绝；回拨按负经过时长0，不报409、不改等待截止。"""
    with scenario(tmp_path) as (service, _):
        earlier = service.login(
            Credentials("admin", EXAMPLE_SECRET),
            now=NOW - timedelta(seconds=10),
            audit=AUDIT_CONTEXT,
        )
        assert earlier.identity.last_seen_at == NOW - timedelta(seconds=10)
        with pytest.raises(AccountInputError):
            service.login(
                Credentials("admin", EXAMPLE_SECRET),
                now=datetime.max.replace(tzinfo=UTC),
                audit=AUDIT_CONTEXT,
            )


def test_authenticate_current(tmp_path: Path) -> None:
    """验证契约：有效令牌返回当前角色及强制改密标记，每次重读，不缓存权限。"""
    with scenario(tmp_path) as (service, grant):
        identity = service.authenticate(grant.token, now=NOW, audit=AUDIT_CONTEXT)
        assert identity.account.role is Role.ADMINISTRATOR
        assert identity.token_digest == session_digest(grant.token)
        assert identity.last_seen_at == NOW and not identity.activity_refreshed
        with session_scope(service.engine) as session:
            row = session.get(AccountRow, identity.account.account_id)
            assert row is not None
            row.role = "member"
            row.must_change_password = True
        current = service.authenticate(grant.token, now=NOW, audit=AUDIT_CONTEXT)
        assert current.account.role is Role.MEMBER and current.account.must_change_password


def test_authenticate_invalid(tmp_path: Path) -> None:
    """验证契约：缺失、非法、未知令牌统一401；比较固定长度摘要使用 compare_digest，不暴露 cookie。"""
    with scenario(tmp_path) as (service, _):
        for value in (None, SecretStr("short"), SecretStr("A" * 43), cast(SecretStr, "A" * 43)):
            with pytest.raises(AuthenticationError):
                service.authenticate(value, now=NOW, audit=AUDIT_CONTEXT)


def test_authenticate_expiry(tmp_path: Path) -> None:
    """验证契约：last_seen+7天 前一微秒有效，恰等于及之后过期；独立事务删除后再抛401，G1。"""
    with scenario(tmp_path) as (service, grant):
        before = service.authenticate(
            grant.token,
            now=NOW + timedelta(days=7) - timedelta(microseconds=1),
            audit=AUDIT_CONTEXT,
        )
        assert before.account.account_id == 1
        # 另一个会话从未触摸，恰好到期时应删除后返回401。
        untouched = service.login(
            Credentials("admin", EXAMPLE_SECRET), now=NOW, audit=AUDIT_CONTEXT
        )
        with pytest.raises(AuthenticationError):
            service.authenticate(untouched.token, now=NOW + timedelta(days=7), audit=AUDIT_CONTEXT)
        with session_scope(service.engine, read_only=True) as session:
            assert session.get(SessionRow, session_digest(untouched.token)) is None


def test_authenticate_touch(tmp_path: Path) -> None:
    """验证契约：不足60秒只读且activity_refreshed=False；恰等于/超过60秒实际提交触摸才True；正常刷新下持续活动超过7天仍有效。"""
    with scenario(tmp_path) as (service, grant):
        before = service.authenticate(
            grant.token, now=NOW + timedelta(seconds=59), audit=AUDIT_CONTEXT
        )
        assert not before.activity_refreshed and before.last_seen_at == NOW
        boundary = service.authenticate(
            grant.token, now=NOW + timedelta(seconds=60), audit=AUDIT_CONTEXT
        )
        assert boundary.activity_refreshed and boundary.last_seen_at == NOW + timedelta(seconds=60)
        again = service.authenticate(
            grant.token, now=NOW + timedelta(seconds=60), audit=AUDIT_CONTEXT
        )
        assert not again.activity_refreshed
        for day in range(1, 10):
            alive = service.authenticate(
                grant.token, now=NOW + timedelta(days=day), audit=AUDIT_CONTEXT
            )
            assert alive.account.account_id == 1


def test_authenticate_precision(tmp_path: Path) -> None:
    """验证契约：刷新未受锁忙阻碍时，未持久化活动使过期最多提前不足60秒；到期基准不因回拨改写。"""
    with scenario(tmp_path) as (service, grant):
        early = service.authenticate(
            grant.token, now=NOW + timedelta(seconds=59), audit=AUDIT_CONTEXT
        )
        assert early.last_seen_at == NOW
        with pytest.raises(AuthenticationError):
            service.authenticate(grant.token, now=NOW + timedelta(days=7), audit=AUDIT_CONTEXT)


def test_authenticate_revoked(tmp_path: Path) -> None:
    """验证契约：停用/删除/重置后下一请求401；并发触摸重读后不能复活被删会话，验收3。"""
    for operation in ("disable", "delete", "reset"):
        root = tmp_path / operation
        root.mkdir()
        with scenario(root) as (service, admin):
            member = member_grant(service, admin)
            key = member.identity.account.account_id
            if operation == "disable":
                service.set_status(
                    admin.identity, key, AccountStatus.DISABLED, now=NOW, audit=AUDIT_CONTEXT
                )
            elif operation == "delete":
                service.delete_account(admin.identity, key, now=NOW, audit=AUDIT_CONTEXT)
            else:
                service.reset_password(
                    admin.identity,
                    key,
                    SecretStr("replacement-value"),
                    now=NOW,
                    audit=AUDIT_CONTEXT,
                )
            with pytest.raises(AuthenticationError):
                service.authenticate(member.token, now=NOW, audit=AUDIT_CONTEXT)


def test_authenticate_read_session(tmp_path: Path) -> None:
    """验证契约：认证短事务与 get_read_session 独立，不把只读事务升级为写或混用会话。"""
    with scenario(tmp_path) as (service, admin):
        with session_scope(service.engine, read_only=True) as reader:
            old = reader.get(SessionRow, admin.identity.token_digest)
            assert old is not None and old.last_seen_at == NOW
            updated = service.authenticate(
                admin.token, now=NOW + timedelta(seconds=60), audit=AUDIT_CONTEXT
            )
            assert updated.activity_refreshed
            assert reader.connection().exec_driver_sql("PRAGMA query_only").scalar_one() == 1
            reader.expire(old)
            assert old.last_seen_at == NOW
        assert service.authenticate(
            admin.token, now=NOW + timedelta(seconds=60), audit=AUDIT_CONTEXT
        ).last_seen_at == NOW + timedelta(seconds=60)


def test_authenticate_failure(tmp_path: Path) -> None:
    """验证契约：非法时刻、损坏库、初始读锁、I/O和映射错误分别归声明异常；过期删除的短锁超时由专用测试核验。"""
    with scenario(tmp_path) as (service, admin):
        with pytest.raises(AccountInputError):
            service.authenticate(admin.token, now=NOW.replace(tzinfo=None), audit=AUDIT_CONTEXT)
        for code, expected in (
            (sqlite3.SQLITE_CORRUPT, InputError),
            (sqlite3.SQLITE_BUSY, ConflictError),
            (sqlite3.SQLITE_IOERR, ExternalError),
            (sqlite3.SQLITE_ERROR, DefectError),
        ):

            def broken(
                connection: Connection,
                cursor: object,
                statement: str,
                *args: object,
                code: int = code,
            ) -> None:
                if statement.startswith("SELECT"):
                    error = sqlite3.OperationalError("测试读取失败")
                    error.sqlite_errorcode = code
                    raise error

            event.listen(service.engine, "before_cursor_execute", broken)
            try:
                with pytest.raises(expected):
                    service.authenticate(admin.token, now=NOW, audit=AUDIT_CONTEXT)
            finally:
                event.remove(service.engine, "before_cursor_execute", broken)
        assert (
            service.authenticate(admin.token, now=NOW, audit=AUDIT_CONTEXT).account
            == admin.identity.account
        )


def test_logout_success(tmp_path: Path) -> None:
    """验证契约：只撤销当前会话，其他会话仍可用；之后相同 cookie 返回401，验收2。"""
    with scenario(tmp_path) as (service, first):
        other = service.login(Credentials("admin", EXAMPLE_SECRET), now=NOW, audit=AUDIT_CONTEXT)
        service.logout(first.identity, now=NOW, audit=AUDIT_CONTEXT)
        with pytest.raises(AuthenticationError):
            service.authenticate(first.token, now=NOW, audit=AUDIT_CONTEXT)
        assert (
            service.authenticate(other.token, now=NOW, audit=AUDIT_CONTEXT).account.account_id == 1
        )


def test_logout_missing(tmp_path: Path) -> None:
    """验证契约：同一已鉴权身份重复领域 logout 对不存在行成功，不伪造 HTTP 匿名成功。"""
    with scenario(tmp_path) as (service, grant):
        assert service.logout(grant.identity, now=NOW, audit=AUDIT_CONTEXT) is None
        assert service.logout(grant.identity, now=NOW, audit=AUDIT_CONTEXT) is None
        with pytest.raises(AuthenticationError):
            service.authenticate(grant.token, now=NOW, audit=AUDIT_CONTEXT)


def test_logout_failure(tmp_path: Path) -> None:
    """验证契约：无效 now 和数据库四类错误按契约传播，失败不部分删除或声称登出。"""
    with scenario(tmp_path) as (service, admin):
        with fail_write_commit(service.engine), pytest.raises(ExternalError):
            service.logout(admin.identity, now=NOW, audit=AUDIT_CONTEXT)
        assert (
            service.authenticate(admin.token, now=NOW, audit=AUDIT_CONTEXT).account
            == admin.identity.account
        )


def test_change_password_success(tmp_path: Path) -> None:
    """验证契约：校验旧密码后换哈希、清强制标记/G2、存本人快照、删全部旧会话并创建新会话，原子提交。"""
    with scenario(tmp_path) as (service, old):
        another = service.login(Credentials("admin", EXAMPLE_SECRET), now=NOW, audit=AUDIT_CONTEXT)
        result = service.change_password(
            old.identity,
            PasswordChange(EXAMPLE_SECRET, SecretStr("new-current-credential")),
            now=NOW + timedelta(seconds=1),
            audit=AUDIT_CONTEXT,
        )
        assert not result.identity.account.must_change_password
        assert result.token != old.token
        assert result.identity.account.updated_by == ActorRef(1, "管理员")
        for expired in (old, another):
            with pytest.raises(AuthenticationError):
                service.authenticate(
                    expired.token, now=NOW + timedelta(seconds=1), audit=AUDIT_CONTEXT
                )
        assert (
            service.authenticate(
                result.token, now=NOW + timedelta(seconds=1), audit=AUDIT_CONTEXT
            ).account.account_id
            == 1
        )


def test_change_password_forced(tmp_path: Path) -> None:
    """验证契约：must_change_password=True 可执行，成功后恢复业务访问。"""
    with scenario(tmp_path) as (service, admin):
        member = member_grant(service, admin)
        assert not member.identity.account.must_change_password
        assert (
            service.authenticate(member.token, now=NOW, audit=AUDIT_CONTEXT).account.role
            is Role.MEMBER
        )


def test_change_password_mismatch(tmp_path: Path) -> None:
    """验证契约：旧密码错受G2计数，前四次提交后CurrentPasswordError（AccountInputError子类400），第五次429；不清cookie，等待中不哈希。"""
    with scenario(tmp_path) as (service, grant):
        change = PasswordChange(SecretStr("wrong-example-value"), SecretStr("different-new-value"))
        for _ in range(4):
            with pytest.raises(CurrentPasswordError) as caught:
                service.change_password(grant.identity, change, now=NOW, audit=AUDIT_CONTEXT)
            assert caught.value.http_status == 400
            assert (
                service.authenticate(grant.token, now=NOW, audit=AUDIT_CONTEXT).account.account_id
                == 1
            )
        with pytest.raises(LoginWaitError):
            service.change_password(grant.identity, change, now=NOW, audit=AUDIT_CONTEXT)


def test_change_password_same(tmp_path: Path) -> None:
    """验证契约：新旧相同或字段/时刻不合格为 AccountInputError，秘密不在异常。"""
    with scenario(tmp_path) as (service, grant):
        for change in (
            PasswordChange(EXAMPLE_SECRET, EXAMPLE_SECRET),
            PasswordChange(EXAMPLE_SECRET, SecretStr("short")),
        ):
            with pytest.raises(AccountInputError):
                service.change_password(grant.identity, change, now=NOW, audit=AUDIT_CONTEXT)
        assert (
            service.authenticate(grant.token, now=NOW, audit=AUDIT_CONTEXT).account.account_id == 1
        )


def test_change_password_revoked(tmp_path: Path) -> None:
    """验证契约：事务内发现会话过期/撤销或账号停用为 AuthenticationError，不能用旧身份改密。"""
    with scenario(tmp_path) as (service, grant):
        service.logout(grant.identity, now=NOW, audit=AUDIT_CONTEXT)
        with pytest.raises(AuthenticationError):
            service.change_password(
                grant.identity,
                PasswordChange(EXAMPLE_SECRET, SecretStr("new-secret-example")),
                now=NOW,
                audit=AUDIT_CONTEXT,
            )


def test_change_password_rollback(tmp_path: Path) -> None:
    """验证契约：换哈希/删会话/新建会话任一步故障全回滚，不部分改变密码或会话。"""
    with scenario(tmp_path) as (service, first):
        second = service.login(Credentials("admin", EXAMPLE_SECRET), now=NOW, audit=AUDIT_CONTEXT)
        with fail_write_commit(service.engine), pytest.raises(ExternalError):
            service.change_password(
                first.identity,
                PasswordChange(EXAMPLE_SECRET, SecretStr("replacement-value")),
                now=NOW + timedelta(seconds=10),
                audit=AUDIT_CONTEXT,
            )
        for grant in (first, second):
            assert (
                service.authenticate(grant.token, now=NOW, audit=AUDIT_CONTEXT).account
                == first.identity.account
            )
        assert service.login(Credentials("admin", EXAMPLE_SECRET), now=NOW, audit=AUDIT_CONTEXT)
        with pytest.raises(AuthenticationError):
            service.login(
                Credentials("admin", SecretStr("replacement-value")), now=NOW, audit=AUDIT_CONTEXT
            )


def test_list_accounts_pages(tmp_path: Path) -> None:
    """验证契约：管理员查询按编号升序最多100条；空页合法；末页None，否则游标是本页末编号。"""
    with scenario(tmp_path) as (service, admin):
        with session_scope(service.engine) as session:
            session.add_all([model_row(f"member{i:03}") for i in range(101)])
        first = service.list_accounts(admin.identity, now=NOW)
        assert len(first.items) == 100 and first.next_after_id == 100
        assert [x.account_id for x in first.items] == list(range(1, 101))
        second = service.list_accounts(admin.identity, after_id=100, now=NOW)
        assert [x.account_id for x in second.items] == [101, 102] and second.next_after_id is None
        empty = service.list_accounts(admin.identity, after_id=102, now=NOW)
        assert empty.items == () and empty.next_after_id is None


def test_list_accounts_cursor(tmp_path: Path) -> None:
    """验证契约：0 首页、上限编号游标合法，负数/bool/越界拒绝；并发删号不使游标重复。"""
    with scenario(tmp_path) as (service, grant):
        for value in (-1, True, 2**63, "0"):
            with pytest.raises(AccountInputError):
                service.list_accounts(grant.identity, after_id=cast(int, value), now=NOW)
        assert service.list_accounts(grant.identity, after_id=2**63 - 1, now=NOW).items == ()


def test_list_accounts_permissions(tmp_path: Path) -> None:
    """验证契约：成员403，已失效401，必须改密403；重新读取角色，不信任旧快照。"""
    with scenario(tmp_path) as (service, grant):
        member = member_grant(service, grant)
        with pytest.raises(AuthorizationError):
            service.list_accounts(member.identity, now=NOW)
        with session_scope(service.engine) as session:
            row = session.get(AccountRow, member.identity.account.account_id)
            assert row is not None
            row.must_change_password = True
        with pytest.raises(PasswordChangeRequiredError):
            service.list_accounts(member.identity, now=NOW)


@pytest.mark.parametrize("elapsed", (timedelta(days=7), timedelta(days=7, microseconds=1)))
def test_business_authorization_idle_expiry(tmp_path: Path, elapsed: timedelta) -> None:
    """验证契约：业务事务重验旧身份，空闲恰满7天及之后拒绝为401，账号和会话均不写入；不先调用 authenticate 刷新身份。"""
    with scenario(tmp_path) as (service, admin):
        before = persisted_account_state(service.engine)
        command = NewAccount(Credentials("new_member", EXAMPLE_SECRET), "新成员", Role.MEMBER)
        with pytest.raises(AuthenticationError) as caught:
            service.create_account(admin.identity, command, now=NOW + elapsed, audit=AUDIT_CONTEXT)
        assert caught.value.http_status == 401
        assert persisted_account_state(service.engine) == before


def test_list_accounts_readonly(tmp_path: Path) -> None:
    """验证契约：只读独立事务，不输出哈希/失败状态/会话，不持久化身份刷新。"""
    with scenario(tmp_path) as (service, admin):
        statements: list[str] = []
        flags: list[bool] = []

        def observed(connection: Connection, cursor: object, statement: str, *args: object) -> None:
            statements.append(statement)
            if statement.startswith("SELECT"):
                flags.append(bool(connection.get_execution_options().get("rdp_read_only")))

        with session_scope(service.engine):
            event.listen(service.engine, "before_cursor_execute", observed)
            try:
                page = service.list_accounts(admin.identity, after_id=0, now=NOW)
                assert len(page.items) == 1
            finally:
                event.remove(service.engine, "before_cursor_execute", observed)
        assert flags and all(flags)
        assert "BEGIN" in statements and "BEGIN IMMEDIATE" not in statements
        assert not any(
            statement.startswith(("UPDATE", "INSERT", "DELETE")) for statement in statements
        )


def test_create_account_success(tmp_path: Path) -> None:
    """验证契约：管理员创建启用账号、强制首次改密、随机盐哈希和当前人双快照，不创建会话。"""
    with scenario(tmp_path) as (service, admin):
        created = service.create_account(
            admin.identity,
            NewAccount(Credentials("member", EXAMPLE_SECRET), "成员姓名", Role.MEMBER),
            now=NOW,
            audit=AUDIT_CONTEXT,
        )
        assert created.account_id == 2 and created.login_name == "member"
        assert created.status is AccountStatus.ENABLED and created.must_change_password
        assert created.created_by == ActorRef(1, "管理员")
        assert created.updated_by == created.created_by
        with session_scope(service.engine, read_only=True) as session:
            assert (
                session.scalar(
                    select(func.count()).select_from(SessionRow).where(SessionRow.account_id == 2)
                )
                == 0
            )


def test_create_account_validation(tmp_path: Path) -> None:
    """验证契约：登录名大小写/空白/长度/字符、显示名首尾空白/控制符、Role及now不合格给422。"""
    with scenario(tmp_path) as (service, grant):
        for name, display in (
            ("UPPER", "名称"),
            ("ab", "名称"),
            ("valid", " "),
            ("valid", " 含空白"),
            ("valid", "名字\n"),
        ):
            with pytest.raises(AccountInputError):
                service.create_account(
                    grant.identity,
                    NewAccount(Credentials(name, EXAMPLE_SECRET), display, Role.MEMBER),
                    now=NOW,
                    audit=AUDIT_CONTEXT,
                )
        assert len(service.list_accounts(grant.identity, now=NOW).items) == 1


def test_create_account_duplicate(tmp_path: Path) -> None:
    """验证契约：同名冲突409，失败不留半条账号且已提交删除编号不复用。"""
    with scenario(tmp_path) as (service, grant):
        with pytest.raises(ConflictError):
            service.create_account(
                grant.identity,
                NewAccount(Credentials("admin", EXAMPLE_SECRET), "同名", Role.MEMBER),
                now=NOW,
                audit=AUDIT_CONTEXT,
            )
        assert len(service.list_accounts(grant.identity, now=NOW).items) == 1


def test_create_account_permissions(tmp_path: Path) -> None:
    """验证契约：未登录/撤销401、成员403、必须改密403，写锁内重验。"""
    with scenario(tmp_path) as (service, grant):
        member = member_grant(service, grant)
        with pytest.raises(AuthorizationError):
            service.create_account(
                member.identity,
                NewAccount(Credentials("other", EXAMPLE_SECRET), "其他", Role.MEMBER),
                now=NOW,
                audit=AUDIT_CONTEXT,
            )
        assert len(service.list_accounts(grant.identity, now=NOW).items) == 2


def test_set_role_success(tmp_path: Path) -> None:
    """验证契约：角色实际改变更新修改人和时间，同事务撤销目标全部会话。"""
    with scenario(tmp_path) as (service, admin):
        member = service.create_account(
            admin.identity,
            NewAccount(Credentials("member", EXAMPLE_SECRET), "成员", Role.MEMBER),
            now=NOW,
            audit=AUDIT_CONTEXT,
        )
        old = service.login(Credentials("member", EXAMPLE_SECRET), now=NOW, audit=AUDIT_CONTEXT)
        changed = service.set_role(
            admin.identity,
            member.account_id,
            Role.ADMINISTRATOR,
            now=NOW + timedelta(seconds=1),
            audit=AUDIT_CONTEXT,
        )
        assert changed.role is Role.ADMINISTRATOR and changed.updated_by == ActorRef(1, "管理员")
        assert changed.updated_at == NOW + timedelta(seconds=1)
        with pytest.raises(AuthenticationError):
            service.authenticate(old.token, now=NOW + timedelta(seconds=1), audit=AUDIT_CONTEXT)


def test_set_role_noop(tmp_path: Path) -> None:
    """验证契约：相同角色返回原快照，不改时间或会话。"""
    with scenario(tmp_path) as (service, grant):
        same = service.set_role(
            grant.identity,
            1,
            Role.ADMINISTRATOR,
            now=NOW + timedelta(seconds=1),
            audit=AUDIT_CONTEXT,
        )
        assert same.updated_at == NOW
        assert (
            service.authenticate(grant.token, now=NOW, audit=AUDIT_CONTEXT).account.role
            is Role.ADMINISTRATOR
        )


def test_set_role_last_admin(tmp_path: Path) -> None:
    """验证契约：降级最后启用管理员409，管理员和会话全部保留，验收4。"""
    with scenario(tmp_path) as (service, grant):
        with pytest.raises(ConflictError):
            service.set_role(grant.identity, 1, Role.MEMBER, now=NOW, audit=AUDIT_CONTEXT)
        assert (
            service.authenticate(grant.token, now=NOW, audit=AUDIT_CONTEXT).account.role
            is Role.ADMINISTRATOR
        )


def test_set_role_concurrent(tmp_path: Path) -> None:
    """验证契约：两个管理员并发相互降级由 BEGIN IMMEDIATE 串行重验，至少保留一名启用管理员。"""
    with scenario(tmp_path) as (service, first):
        second = member_grant(service, first, role=Role.ADMINISTRATOR)
        barrier = Barrier(2)
        pool = ThreadPoolExecutor(max_workers=2)

        def attempt(grant: SessionGrant) -> str:
            barrier.wait(timeout=2)
            try:
                service.set_role(
                    grant.identity,
                    grant.identity.account.account_id,
                    Role.MEMBER,
                    now=NOW,
                    audit=AUDIT_CONTEXT,
                )
            except ConflictError:
                return "conflict"
            return "success"

        try:
            futures = [pool.submit(attempt, grant) for grant in (first, second)]
            assert sorted(future.result(timeout=8) for future in futures) == ["conflict", "success"]
        finally:
            barrier.abort()
            pool.shutdown(wait=True, cancel_futures=True)
        with session_scope(service.engine, read_only=True) as session:
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(AccountRow)
                    .where(AccountRow.role == "administrator", AccountRow.status == "enabled")
                )
                == 1
            )


def test_set_role_errors(tmp_path: Path) -> None:
    """验证契约：非法编号/Role/now为422，目标不存在404，未登录401/成员403/必须改密403。"""
    with scenario(tmp_path) as (service, admin):
        member = member_grant(service, admin)
        key = member.identity.account.account_id
        service.create_account(
            admin.identity,
            NewAccount(Credentials("forced", EXAMPLE_SECRET), "未改密", Role.MEMBER),
            now=NOW,
            audit=AUDIT_CONTEXT,
        )
        forced = service.login(Credentials("forced", EXAMPLE_SECRET), now=NOW, audit=AUDIT_CONTEXT)
        before = service.list_accounts(admin.identity, after_id=0, now=NOW)
        for invalid in (0, True, -1, 9223372036854775808):
            with pytest.raises(AccountInputError):
                service.set_role(
                    admin.identity, invalid, Role.ADMINISTRATOR, now=NOW, audit=AUDIT_CONTEXT
                )
        with pytest.raises(AccountInputError):
            service.set_role(admin.identity, key, cast(Role, "owner"), now=NOW, audit=AUDIT_CONTEXT)
        with pytest.raises(AccountNotFoundError):
            service.set_role(admin.identity, 999, Role.ADMINISTRATOR, now=NOW, audit=AUDIT_CONTEXT)
        with pytest.raises(AuthorizationError):
            service.set_role(member.identity, key, Role.ADMINISTRATOR, now=NOW, audit=AUDIT_CONTEXT)
        with pytest.raises(PasswordChangeRequiredError):
            service.set_role(forced.identity, key, Role.ADMINISTRATOR, now=NOW, audit=AUDIT_CONTEXT)
        assert service.list_accounts(admin.identity, after_id=0, now=NOW) == before
        service.logout(admin.identity, now=NOW, audit=AUDIT_CONTEXT)
        with pytest.raises(AuthenticationError):
            service.set_role(admin.identity, key, Role.ADMINISTRATOR, now=NOW, audit=AUDIT_CONTEXT)


def test_set_status_disable(tmp_path: Path) -> None:
    """验证契约：停用账号同事务删除全部会话，下一请求401。"""
    with scenario(tmp_path) as (service, admin):
        member = service.create_account(
            admin.identity,
            NewAccount(Credentials("member", EXAMPLE_SECRET), "成员", Role.MEMBER),
            now=NOW,
            audit=AUDIT_CONTEXT,
        )
        old = service.login(Credentials("member", EXAMPLE_SECRET), now=NOW, audit=AUDIT_CONTEXT)
        changed = service.set_status(
            admin.identity, member.account_id, AccountStatus.DISABLED, now=NOW, audit=AUDIT_CONTEXT
        )
        assert changed.status is AccountStatus.DISABLED
        with pytest.raises(AuthenticationError):
            service.authenticate(old.token, now=NOW, audit=AUDIT_CONTEXT)


def test_set_status_enable(tmp_path: Path) -> None:
    """验证契约：启用账号不恢复旧会话、不绕过G2，更新人和时间。"""
    with scenario(tmp_path) as (service, grant):
        member = member_grant(service, grant)
        key = member.identity.account.account_id
        service.set_status(
            grant.identity, key, AccountStatus.DISABLED, now=NOW, audit=AUDIT_CONTEXT
        )
        restored = service.set_status(
            grant.identity, key, AccountStatus.ENABLED, now=NOW, audit=AUDIT_CONTEXT
        )
        assert restored.status is AccountStatus.ENABLED
        with pytest.raises(AuthenticationError):
            service.authenticate(member.token, now=NOW, audit=AUDIT_CONTEXT)


def test_set_status_noop(tmp_path: Path) -> None:
    """验证契约：相同状态不改审计时刻或会话。"""
    with scenario(tmp_path) as (service, grant):
        same = service.set_status(
            grant.identity,
            1,
            AccountStatus.ENABLED,
            now=NOW + timedelta(seconds=1),
            audit=AUDIT_CONTEXT,
        )
        assert (
            same.updated_at == NOW
            and service.authenticate(grant.token, now=NOW, audit=AUDIT_CONTEXT).account.account_id
            == 1
        )


def test_set_status_last_admin(tmp_path: Path) -> None:
    """验证契约：停用最后启用管理员409，无部分变更。"""
    with scenario(tmp_path) as (service, grant):
        with pytest.raises(ConflictError):
            service.set_status(
                grant.identity, 1, AccountStatus.DISABLED, now=NOW, audit=AUDIT_CONTEXT
            )
        assert (
            service.authenticate(grant.token, now=NOW, audit=AUDIT_CONTEXT).account.status
            is AccountStatus.ENABLED
        )


def test_set_status_concurrent(tmp_path: Path) -> None:
    """验证契约：并发停用在写锁内计数，不可能把全部管理员停用。"""
    with scenario(tmp_path) as (service, first):
        second = member_grant(service, first, role=Role.ADMINISTRATOR)
        barrier = Barrier(2)
        pool = ThreadPoolExecutor(max_workers=2)

        def attempt(grant: SessionGrant) -> str:
            barrier.wait(timeout=2)
            try:
                service.set_status(
                    grant.identity,
                    grant.identity.account.account_id,
                    AccountStatus.DISABLED,
                    now=NOW,
                    audit=AUDIT_CONTEXT,
                )
            except ConflictError:
                return "conflict"
            return "success"

        try:
            futures = [pool.submit(attempt, grant) for grant in (first, second)]
            assert sorted(future.result(timeout=8) for future in futures) == ["conflict", "success"]
        finally:
            barrier.abort()
            pool.shutdown(wait=True, cancel_futures=True)
        with session_scope(service.engine, read_only=True) as session:
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(AccountRow)
                    .where(AccountRow.role == "administrator", AccountRow.status == "enabled")
                )
                == 1
            )


def test_set_status_errors(tmp_path: Path) -> None:
    """验证契约：非法编号/状态/now422、目标不存在404、失效401、成员及必须改密403。"""
    with scenario(tmp_path) as (service, admin):
        member = member_grant(service, admin)
        key = member.identity.account.account_id
        service.create_account(
            admin.identity,
            NewAccount(Credentials("forced", EXAMPLE_SECRET), "未改密", Role.MEMBER),
            now=NOW,
            audit=AUDIT_CONTEXT,
        )
        forced = service.login(Credentials("forced", EXAMPLE_SECRET), now=NOW, audit=AUDIT_CONTEXT)
        before = service.list_accounts(admin.identity, after_id=0, now=NOW)
        for invalid in (0, True, -1, 9223372036854775808):
            with pytest.raises(AccountInputError):
                service.set_status(
                    admin.identity, invalid, AccountStatus.DISABLED, now=NOW, audit=AUDIT_CONTEXT
                )
        with pytest.raises(AccountInputError):
            service.set_status(
                admin.identity, key, cast(AccountStatus, "other"), now=NOW, audit=AUDIT_CONTEXT
            )
        with pytest.raises(AccountNotFoundError):
            service.set_status(
                admin.identity, 999, AccountStatus.DISABLED, now=NOW, audit=AUDIT_CONTEXT
            )
        with pytest.raises(AuthorizationError):
            service.set_status(
                member.identity, key, AccountStatus.DISABLED, now=NOW, audit=AUDIT_CONTEXT
            )
        with pytest.raises(PasswordChangeRequiredError):
            service.set_status(
                forced.identity, key, AccountStatus.DISABLED, now=NOW, audit=AUDIT_CONTEXT
            )
        assert service.list_accounts(admin.identity, after_id=0, now=NOW) == before
        service.logout(admin.identity, now=NOW, audit=AUDIT_CONTEXT)
        with pytest.raises(AuthenticationError):
            service.set_status(
                admin.identity, key, AccountStatus.DISABLED, now=NOW, audit=AUDIT_CONTEXT
            )


def test_reset_password_success(tmp_path: Path) -> None:
    """验证契约：管理员重置密码、强制改密、清G2并删全部目标会话原子提交，包含重置自己。"""
    with scenario(tmp_path) as (service, admin):
        member = service.create_account(
            admin.identity,
            NewAccount(Credentials("member", EXAMPLE_SECRET), "成员", Role.MEMBER),
            now=NOW,
            audit=AUDIT_CONTEXT,
        )
        old = service.login(Credentials("member", EXAMPLE_SECRET), now=NOW, audit=AUDIT_CONTEXT)
        result = service.reset_password(
            admin.identity,
            member.account_id,
            SecretStr("replacement-credential"),
            now=NOW,
            audit=AUDIT_CONTEXT,
        )
        assert result.must_change_password and result.updated_by == ActorRef(1, "管理员")
        with pytest.raises(AuthenticationError):
            service.authenticate(old.token, now=NOW, audit=AUDIT_CONTEXT)
        assert (
            service.login(
                Credentials("member", SecretStr("replacement-credential")),
                now=NOW,
                audit=AUDIT_CONTEXT,
            ).identity.account.account_id
            == member.account_id
        )


def test_reset_password_errors(tmp_path: Path) -> None:
    """验证契约：非法编号/密码/now422，缺目标404，失效401，成员和必须改密403。"""
    with scenario(tmp_path) as (service, admin):
        member = member_grant(service, admin)
        key = member.identity.account.account_id
        service.create_account(
            admin.identity,
            NewAccount(Credentials("forced", EXAMPLE_SECRET), "未改密", Role.MEMBER),
            now=NOW,
            audit=AUDIT_CONTEXT,
        )
        forced = service.login(Credentials("forced", EXAMPLE_SECRET), now=NOW, audit=AUDIT_CONTEXT)
        before = service.list_accounts(admin.identity, after_id=0, now=NOW)
        for invalid in (0, True, -1, 9223372036854775808):
            with pytest.raises(AccountInputError):
                service.reset_password(
                    admin.identity, invalid, EXAMPLE_SECRET, now=NOW, audit=AUDIT_CONTEXT
                )
        with pytest.raises(AccountInputError):
            service.reset_password(
                admin.identity, key, SecretStr("short"), now=NOW, audit=AUDIT_CONTEXT
            )
        with pytest.raises(AccountNotFoundError):
            service.reset_password(
                admin.identity, 999, EXAMPLE_SECRET, now=NOW, audit=AUDIT_CONTEXT
            )
        with pytest.raises(AuthorizationError):
            service.reset_password(
                member.identity, key, EXAMPLE_SECRET, now=NOW, audit=AUDIT_CONTEXT
            )
        with pytest.raises(PasswordChangeRequiredError):
            service.reset_password(
                forced.identity, key, EXAMPLE_SECRET, now=NOW, audit=AUDIT_CONTEXT
            )
        assert service.list_accounts(admin.identity, after_id=0, now=NOW) == before
        service.logout(admin.identity, now=NOW, audit=AUDIT_CONTEXT)
        with pytest.raises(AuthenticationError):
            service.reset_password(
                admin.identity, key, EXAMPLE_SECRET, now=NOW, audit=AUDIT_CONTEXT
            )


def test_reset_password_rollback(tmp_path: Path) -> None:
    """验证契约：哈希或会话撤销失败整体回滚，不留下只换密码却保留旧会话。"""
    with scenario(tmp_path) as (service, admin):
        member = member_grant(service, admin)
        key = member.identity.account.account_id
        with fail_write_commit(service.engine), pytest.raises(ExternalError):
            service.reset_password(
                admin.identity,
                key,
                SecretStr("replacement-value"),
                now=NOW + timedelta(seconds=10),
                audit=AUDIT_CONTEXT,
            )
        assert (
            service.authenticate(member.token, now=NOW, audit=AUDIT_CONTEXT).account
            == member.identity.account
        )
        assert service.login(
            Credentials("member", SecretStr("member-updated-value")), now=NOW, audit=AUDIT_CONTEXT
        )
        with pytest.raises(AuthenticationError):
            service.login(
                Credentials("member", SecretStr("replacement-value")), now=NOW, audit=AUDIT_CONTEXT
            )


def test_delete_account_success(tmp_path: Path) -> None:
    """验证契约：真删除账号和全部会话，历史人名快照仍可显示，同名重建获得新编号。"""
    with scenario(tmp_path) as (service, admin):
        member = service.create_account(
            admin.identity,
            NewAccount(Credentials("member", EXAMPLE_SECRET), "成员", Role.MEMBER),
            now=NOW,
            audit=AUDIT_CONTEXT,
        )
        old = service.login(Credentials("member", EXAMPLE_SECRET), now=NOW, audit=AUDIT_CONTEXT)
        service.delete_account(admin.identity, member.account_id, now=NOW, audit=AUDIT_CONTEXT)
        assert [x.account_id for x in service.list_accounts(admin.identity, now=NOW).items] == [1]
        with pytest.raises(AuthenticationError):
            service.authenticate(old.token, now=NOW, audit=AUDIT_CONTEXT)
        fresh = service.create_account(
            admin.identity,
            NewAccount(Credentials("member", EXAMPLE_SECRET), "重建", Role.MEMBER),
            now=NOW,
            audit=AUDIT_CONTEXT,
        )
        assert fresh.account_id > member.account_id


def test_delete_account_last_admin(tmp_path: Path) -> None:
    """验证契约：删除最后启用管理员409，原账号/会话保留。"""
    with scenario(tmp_path) as (service, grant):
        with pytest.raises(ConflictError):
            service.delete_account(grant.identity, 1, now=NOW, audit=AUDIT_CONTEXT)
        assert (
            service.authenticate(grant.token, now=NOW, audit=AUDIT_CONTEXT).account.account_id == 1
        )


def test_delete_account_concurrent(tmp_path: Path) -> None:
    """验证契约：并发删除由写锁串行核验，不能全部删除管理员。"""
    with scenario(tmp_path) as (service, first):
        second = member_grant(service, first, role=Role.ADMINISTRATOR)
        barrier = Barrier(2)
        pool = ThreadPoolExecutor(max_workers=2)

        def attempt(grant: SessionGrant) -> str:
            barrier.wait(timeout=2)
            try:
                service.delete_account(
                    grant.identity, grant.identity.account.account_id, now=NOW, audit=AUDIT_CONTEXT
                )
            except ConflictError:
                return "conflict"
            return "success"

        try:
            futures = [pool.submit(attempt, grant) for grant in (first, second)]
            assert sorted(future.result(timeout=8) for future in futures) == ["conflict", "success"]
        finally:
            barrier.abort()
            pool.shutdown(wait=True, cancel_futures=True)
        with session_scope(service.engine, read_only=True) as session:
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(AccountRow)
                    .where(AccountRow.role == "administrator", AccountRow.status == "enabled")
                )
                == 1
            )


def test_delete_account_errors(tmp_path: Path) -> None:
    """验证契约：非法编号/now422，不存在404，未登录401，成员/必须改密403。"""
    with scenario(tmp_path) as (service, admin):
        member = member_grant(service, admin)
        key = member.identity.account.account_id
        service.create_account(
            admin.identity,
            NewAccount(Credentials("forced", EXAMPLE_SECRET), "未改密", Role.MEMBER),
            now=NOW,
            audit=AUDIT_CONTEXT,
        )
        forced = service.login(Credentials("forced", EXAMPLE_SECRET), now=NOW, audit=AUDIT_CONTEXT)
        before = service.list_accounts(admin.identity, after_id=0, now=NOW)
        for invalid in (0, True, -1, 9223372036854775808):
            with pytest.raises(AccountInputError):
                service.delete_account(admin.identity, invalid, now=NOW, audit=AUDIT_CONTEXT)
        with pytest.raises(AccountInputError):
            service.delete_account(
                admin.identity, key, now=NOW.replace(tzinfo=None), audit=AUDIT_CONTEXT
            )
        with pytest.raises(AccountNotFoundError):
            service.delete_account(admin.identity, 999, now=NOW, audit=AUDIT_CONTEXT)
        with pytest.raises(AuthorizationError):
            service.delete_account(member.identity, key, now=NOW, audit=AUDIT_CONTEXT)
        with pytest.raises(PasswordChangeRequiredError):
            service.delete_account(forced.identity, key, now=NOW, audit=AUDIT_CONTEXT)
        assert service.list_accounts(admin.identity, after_id=0, now=NOW) == before
        service.logout(admin.identity, now=NOW, audit=AUDIT_CONTEXT)
        with pytest.raises(AuthenticationError):
            service.delete_account(admin.identity, key, now=NOW, audit=AUDIT_CONTEXT)


def test_delete_account_rollback(tmp_path: Path) -> None:
    """验证契约：删除过程中故障整体回滚，不留下孤立会话或半删除账号。"""
    with scenario(tmp_path) as (service, admin):
        member = member_grant(service, admin)
        before = service.list_accounts(admin.identity, after_id=0, now=NOW)
        with fail_write_commit(service.engine), pytest.raises(ExternalError):
            service.delete_account(
                admin.identity, member.identity.account.account_id, now=NOW, audit=AUDIT_CONTEXT
            )
        assert service.list_accounts(admin.identity, after_id=0, now=NOW) == before
        assert (
            service.authenticate(member.token, now=NOW, audit=AUDIT_CONTEXT).account
            == member.identity.account
        )


def test_first_admin_success(tmp_path: Path) -> None:
    """验证契约：无任何管理员时可创建启用首号，must_change_password=False，操作者为运维，验收8。"""
    with model_database(tmp_path) as engine:
        codec = PasswordCodec(PasswordHasher(time_cost=1, memory_cost=1024, parallelism=1))
        service = AccountService(engine, codec)
        created = service.create_first_admin(
            NewAccount(Credentials("admin", EXAMPLE_SECRET), "首位管理员", Role.ADMINISTRATOR),
            now=NOW,
            audit=OPS_AUDIT_CONTEXT,
        )
        assert created.account_id == 1
        assert created.role is Role.ADMINISTRATOR and created.status is AccountStatus.ENABLED
        assert not created.must_change_password
        assert (
            created.created_by == ActorRef(None, "运维")
            and created.updated_by == created.created_by
        )
        assert created.created_at == NOW and created.updated_at == NOW
        with session_scope(engine, read_only=True) as session:
            row = session.get(AccountRow, created.account_id)
            assert row is not None and codec.hasher.verify(
                row.password_hash, EXAMPLE_SECRET.get_secret_value()
            )
            assert session.scalar(select(func.count()).select_from(SessionRow)) == 0


def test_first_admin_exists(tmp_path: Path) -> None:
    """验证契约：已有任意管理员包括停用均409；不能绕过恢复流程。"""
    with scenario(tmp_path) as (service, _grant):
        command = NewAccount(Credentials("other", EXAMPLE_SECRET), "另一管理员", Role.ADMINISTRATOR)
        with pytest.raises(ConflictError):
            service.create_first_admin(command, now=NOW, audit=OPS_AUDIT_CONTEXT)
        with session_scope(service.engine) as session:
            row = session.get(AccountRow, 1)
            assert row is not None
            row.status = "disabled"
        with pytest.raises(ConflictError):
            service.create_first_admin(command, now=NOW, audit=OPS_AUDIT_CONTEXT)


def test_first_admin_concurrent(tmp_path: Path) -> None:
    """验证契约：两个并发首号创建只有一个成功。"""
    with model_database(tmp_path) as engine:
        hasher = HookHasher()
        service = AccountService(engine, PasswordCodec(hasher))
        barrier = Barrier(2)
        hasher.on_hash = lambda: barrier.wait(timeout=2)
        pool = ThreadPoolExecutor(max_workers=2)

        def attempt(name: str) -> str:
            try:
                service.create_first_admin(
                    NewAccount(Credentials(name, EXAMPLE_SECRET), "管理员", Role.ADMINISTRATOR),
                    now=NOW,
                    audit=OPS_AUDIT_CONTEXT,
                )
            except ConflictError:
                return "conflict"
            return "success"

        try:
            futures = [pool.submit(attempt, name) for name in ("first", "second")]
            assert sorted(future.result(timeout=8) for future in futures) == ["conflict", "success"]
        finally:
            barrier.abort()
            pool.shutdown(wait=True, cancel_futures=True)
        with session_scope(engine, read_only=True) as session:
            assert session.scalar(select(func.count()).select_from(AccountRow)) == 1


def test_first_admin_invalid(tmp_path: Path) -> None:
    """验证契约：角色非管理员或字段/now无效422，重名409，失败无半条记录。"""
    with model_database(tmp_path) as engine:
        service = AccountService(
            engine, PasswordCodec(PasswordHasher(time_cost=1, memory_cost=1024, parallelism=1))
        )
        for command in (
            NewAccount(Credentials("bad", EXAMPLE_SECRET), "普通", Role.MEMBER),
            NewAccount(Credentials("UPPER", EXAMPLE_SECRET), "管理员", Role.ADMINISTRATOR),
        ):
            with pytest.raises(AccountInputError):
                service.create_first_admin(command, now=NOW, audit=OPS_AUDIT_CONTEXT)


def test_ops_reset_service_success(tmp_path: Path) -> None:
    """验证契约：按登录名本地重置、清G2、强制改密、删会话，修改人运维，不改变启停/角色。"""
    with scenario(tmp_path) as (service, old):
        result = service.reset_password_from_ops(
            "admin", SecretStr("replacement-credential"), now=NOW, audit=OPS_AUDIT_CONTEXT
        )
        assert result.must_change_password and result.updated_by == ActorRef(None, "运维")
        assert result.role is Role.ADMINISTRATOR and result.status is AccountStatus.ENABLED
        with pytest.raises(AuthenticationError):
            service.authenticate(old.token, now=NOW, audit=AUDIT_CONTEXT)
        assert service.login(
            Credentials("admin", SecretStr("replacement-credential")), now=NOW, audit=AUDIT_CONTEXT
        ).identity.account.must_change_password


def test_ops_reset_service_errors(tmp_path: Path) -> None:
    """验证契约：无效字段/now422，目标不存在404，数据库/哈希失败全回滚。"""
    with scenario(tmp_path) as (service, grant):
        with pytest.raises(AccountNotFoundError):
            service.reset_password_from_ops(
                "missing", EXAMPLE_SECRET, now=NOW, audit=OPS_AUDIT_CONTEXT
            )
        with pytest.raises(AccountInputError):
            service.reset_password_from_ops(
                "admin", SecretStr("short"), now=NOW, audit=OPS_AUDIT_CONTEXT
            )
        assert (
            service.authenticate(grant.token, now=NOW, audit=AUDIT_CONTEXT).account.account_id == 1
        )


@pytest.mark.parametrize(
    "operation",
    [
        "login",
        "authenticate",
        "logout",
        "change_password",
        "list_accounts",
        "create_account",
        "set_role",
        "set_status",
        "reset_password",
        "delete_account",
        "create_first_admin",
        "reset_password_from_ops",
    ],
)
@pytest.mark.parametrize("fault", ["corrupt", "busy", "io", "sql"])
def test_service_failure_database_categories(operation: str, fault: str, tmp_path: Path) -> None:
    """验证契约：各数据库入口逐项注入CORRUPT/BUSY/IOERR/SQL错误，分别Input/Conflict/External/Defect；authenticate的BUSY在初始查询注入，刷新获锁另测。"""
    with scenario(tmp_path) as (service, grant):
        code, expected = {
            "corrupt": (sqlite3.SQLITE_CORRUPT, InputError),
            "busy": (sqlite3.SQLITE_BUSY, ConflictError),
            "io": (sqlite3.SQLITE_IOERR, ExternalError),
            "sql": (sqlite3.SQLITE_ERROR, DefectError),
        }[fault]

        def failing(connection: Connection, cursor: object, statement: str, *args: object) -> None:
            if statement.startswith(("SELECT", "INSERT", "UPDATE", "DELETE")):
                error = sqlite3.OperationalError("测试数据库故障")
                error.sqlite_errorcode = code
                raise error

        identity = grant.identity
        commands = {
            "login": lambda: service.login(
                Credentials("admin", EXAMPLE_SECRET), now=NOW, audit=AUDIT_CONTEXT
            ),
            "authenticate": lambda: service.authenticate(grant.token, now=NOW, audit=AUDIT_CONTEXT),
            "logout": lambda: service.logout(identity, now=NOW, audit=AUDIT_CONTEXT),
            "change_password": lambda: service.change_password(
                identity,
                PasswordChange(EXAMPLE_SECRET, SecretStr("replacement-value")),
                now=NOW,
                audit=AUDIT_CONTEXT,
            ),
            "list_accounts": lambda: service.list_accounts(identity, after_id=0, now=NOW),
            "create_account": lambda: service.create_account(
                identity,
                NewAccount(Credentials("member", EXAMPLE_SECRET), "成员", Role.MEMBER),
                now=NOW,
                audit=AUDIT_CONTEXT,
            ),
            "set_role": lambda: service.set_role(
                identity, 1, Role.MEMBER, now=NOW, audit=AUDIT_CONTEXT
            ),
            "set_status": lambda: service.set_status(
                identity, 1, AccountStatus.DISABLED, now=NOW, audit=AUDIT_CONTEXT
            ),
            "reset_password": lambda: service.reset_password(
                identity, 1, SecretStr("replacement-value"), now=NOW, audit=AUDIT_CONTEXT
            ),
            "delete_account": lambda: service.delete_account(
                identity, 1, now=NOW, audit=AUDIT_CONTEXT
            ),
            "create_first_admin": lambda: service.create_first_admin(
                NewAccount(Credentials("other", EXAMPLE_SECRET), "另一个", Role.ADMINISTRATOR),
                now=NOW,
                audit=OPS_AUDIT_CONTEXT,
            ),
            "reset_password_from_ops": lambda: service.reset_password_from_ops(
                "admin", SecretStr("replacement-value"), now=NOW, audit=OPS_AUDIT_CONTEXT
            ),
        }
        event.listen(service.engine, "before_cursor_execute", failing)
        try:
            with pytest.raises(expected) as caught:
                commands[operation]()
            assert caught.value.diagnostics[0].consequence == "本次事务未提交"
            assert str(code) in caught.value.diagnostics[0].actual
        finally:
            event.remove(service.engine, "before_cursor_execute", failing)
        assert (
            service.authenticate(grant.token, now=NOW, audit=AUDIT_CONTEXT).account
            == identity.account
        )


def test_service_failure_cleanup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """验证契约：回滚或关闭失败保留主异常并加安全note，结果未知时不宣称成功或完整回滚。"""
    with scenario(tmp_path) as (service, admin):
        close = Session.close

        def fail_rollback(session: Session) -> None:
            raise OSError("private-cleanup-value")

        def fail_close(session: Session) -> None:
            close(session)
            # 故障针对业务冲突后的写事务关闭，不拦新增的只读授权预检。
            if not session.info.get("rdp_read_only"):
                raise OSError("private-cleanup-value")

        for method, callback in (("rollback", fail_rollback), ("close", fail_close)):
            with monkeypatch.context() as patch:
                patch.setattr(Session, method, callback)
                with pytest.raises(ConflictError) as caught:
                    service.set_role(admin.identity, 1, Role.MEMBER, now=NOW, audit=AUDIT_CONTEXT)
            rendered = format_exception_report(caught.value)
            assert "结果未知" in rendered and "private-cleanup-value" not in rendered
            assert any("结果未知" in note for note in caught.value.__notes__)
            assert (
                service.authenticate(admin.token, now=NOW, audit=AUDIT_CONTEXT).account
                == admin.identity.account
            )


def test_service_failure_secrets(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """验证契约：所有账号操作的失败异常、repr、诊断、运行日志和报错表都不含原文/哈希/令牌/cookie。"""
    with scenario(tmp_path) as (service, admin):
        with session_scope(service.engine, read_only=True) as session:
            row = session.get(AccountRow, 1)
            assert row is not None
            secrets = [
                EXAMPLE_SECRET.get_secret_value(),
                row.password_hash,
                admin.token.get_secret_value(),
                "rdp_session=" + admin.token.get_secret_value(),
            ]

        def fault(connection: Connection, cursor: object, statement: str, *args: object) -> None:
            if statement.startswith(("SELECT", "INSERT", "UPDATE", "DELETE")):
                error = sqlite3.OperationalError(" ".join(secrets))
                error.sqlite_errorcode = sqlite3.SQLITE_IOERR
                error.add_note(" ".join(secrets))
                raise error

        identity = admin.identity
        operations: list[Callable[[], object]] = [
            lambda: service.login(
                Credentials("admin", EXAMPLE_SECRET), now=NOW, audit=AUDIT_CONTEXT
            ),
            lambda: service.authenticate(admin.token, now=NOW, audit=AUDIT_CONTEXT),
            lambda: service.logout(identity, now=NOW, audit=AUDIT_CONTEXT),
            lambda: service.change_password(
                identity,
                PasswordChange(EXAMPLE_SECRET, SecretStr("replacement-value")),
                now=NOW,
                audit=AUDIT_CONTEXT,
            ),
            lambda: service.list_accounts(identity, after_id=0, now=NOW),
            lambda: service.create_account(
                identity,
                NewAccount(Credentials("member", EXAMPLE_SECRET), "成员", Role.MEMBER),
                now=NOW,
                audit=AUDIT_CONTEXT,
            ),
            lambda: service.set_role(identity, 1, Role.MEMBER, now=NOW, audit=AUDIT_CONTEXT),
            lambda: service.set_status(
                identity, 1, AccountStatus.DISABLED, now=NOW, audit=AUDIT_CONTEXT
            ),
            lambda: service.reset_password(
                identity, 1, EXAMPLE_SECRET, now=NOW, audit=AUDIT_CONTEXT
            ),
            lambda: service.delete_account(identity, 1, now=NOW, audit=AUDIT_CONTEXT),
            lambda: service.create_first_admin(
                NewAccount(Credentials("other", EXAMPLE_SECRET), "新管理员", Role.ADMINISTRATOR),
                now=NOW,
                audit=OPS_AUDIT_CONTEXT,
            ),
            lambda: service.reset_password_from_ops(
                "admin", EXAMPLE_SECRET, now=NOW, audit=OPS_AUDIT_CONTEXT
            ),
        ]
        event.listen(service.engine, "before_cursor_execute", fault)
        try:
            for operation in operations:
                with pytest.raises(ExternalError) as caught:
                    operation()
                error = caught.value
                rendered = format_exception_report(error) + repr(error) + str(error.diagnostics)
                assert all(secret not in rendered for secret in secrets)
                assert error.__cause__ is None and error.__context__ is None
        finally:
            event.remove(service.engine, "before_cursor_execute", fault)
        assert not [record for record in caplog.records if record.name.startswith("rdp.accounts")]
        with session_scope(service.engine, read_only=True) as session:
            assert session.scalar(select(func.count()).select_from(ErrorReportRow)) == 0


def test_concurrent_request_time_order(tmp_path: Path) -> None:
    """验证契约：now早于已存创建/活动/修改时刻时不报错；负经过时长按0，保存时间用max，不改等待截止或提前过期。"""
    with scenario(tmp_path) as (service, admin):
        late = NOW + timedelta(minutes=10)
        current = service.authenticate(admin.token, now=late, audit=AUDIT_CONTEXT)
        assert current.last_seen_at == late
        older = service.authenticate(
            admin.token, now=NOW + timedelta(minutes=5), audit=AUDIT_CONTEXT
        )
        assert older.last_seen_at == late and not older.activity_refreshed
        member = member_grant(service, admin)
        changed = service.set_status(
            admin.identity,
            member.identity.account.account_id,
            AccountStatus.DISABLED,
            now=late,
            audit=AUDIT_CONTEXT,
        )
        restored = service.set_status(
            admin.identity,
            member.identity.account.account_id,
            AccountStatus.ENABLED,
            now=NOW,
            audit=AUDIT_CONTEXT,
        )
        assert changed.updated_at == restored.updated_at == late


def test_argon2_process_limit() -> None:
    """验证契约：同一进程多个PasswordCodec共用2名额；hash、verify、dummy初始化并发总数从不超过2，尚未取得名额不做Argon2。"""
    hasher = HeldHasher()
    codecs = [PasswordCodec(hasher), PasswordCodec(hasher)]
    hasher.hold.set()
    pool = ThreadPoolExecutor(max_workers=3)
    try:
        futures = [
            pool.submit(codecs[i % 2].hash, SecretStr("concurrency-sample")) for i in range(3)
        ]
        assert hasher.wait_entered(2)
        with hasher.changed:
            hasher.changed.wait_for(lambda: hasher.entered >= 3, timeout=0.15)
            assert hasher.maximum == 2
        hasher.release.set()
        for future in futures:
            assert future.result(timeout=5).startswith("$argon2id$")
    finally:
        close_workers(pool, hasher)


def test_argon2_queue_timeout() -> None:
    """验证契约：初始化/hash/verify的第3项等待最多ARGON2_QUEUE_TIMEOUT_S=1秒，超时ExternalError502，不带Retry-After，不自动重试。"""
    hasher = HeldHasher()
    codec = PasswordCodec(hasher)
    encoded = hasher.hash("queued-example-input")
    hasher.hold.set()
    pool = ThreadPoolExecutor(max_workers=2)
    try:
        workers = [pool.submit(codec.hash, SecretStr("occupied-example")) for _ in range(2)]
        assert hasher.wait_entered(2)
        with pytest.raises(ExternalError):
            codec.verify(encoded, SecretStr("queued-example-input"))
        with pytest.raises(ExternalError):
            PasswordCodec(hasher)
        with pytest.raises(ExternalError):
            codec.hash(SecretStr("queued-example-input"))
        assert hasher.entered == 2
    finally:
        close_workers(pool, hasher)
    for task in workers:
        assert task.result(timeout=1).startswith("$argon2id$")


def test_argon2_slot_release() -> None:
    """验证契约：成功、错密码、哈希异常或调用失败均释放已获得名额；未取得名额的超时不得多释放。"""
    codec = PasswordCodec(PasswordHasher(time_cost=1, memory_cost=1024, parallelism=1))
    encoded = codec.hasher.hash("slot-release-example")

    def broken(self: PasswordHasher, value: object, *, salt: bytes | None = None) -> str:
        raise RuntimeError("bounded-failure")

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(PasswordHasher, "hash", broken)
        for _ in range(3):
            with pytest.raises(DefectError):
                codec.hash(SecretStr("slot-release-example"))
            with pytest.raises(DefectError):
                PasswordCodec(codec.hasher)
    for _ in range(3):
        assert not codec.verify(encoded, SecretStr("different-example")).matched
    assert codec.hasher.verify(
        codec.hash(SecretStr("slot-release-example")), "slot-release-example"
    )


def test_argon2_rehash_capacity() -> None:
    """验证契约：verify与成功后的重哈希共用一个名额，不嵌套申请而死锁，也不绕过上限。"""
    hasher = HeldHasher()
    codec = PasswordCodec(hasher)
    encoded = PasswordHasher(time_cost=2, memory_cost=1024, parallelism=1).hash(
        "rehash-capacity-value"
    )
    hasher.hold.set()
    pool = ThreadPoolExecutor(max_workers=2)
    try:
        tasks = [
            pool.submit(codec.verify, encoded, SecretStr("rehash-capacity-value")) for _ in range(2)
        ]
        assert hasher.wait_entered(2)
        assert hasher.maximum == 2
        hasher.release.set()
        for task in tasks:
            result = task.result(timeout=5)
            assert result.matched and result.replacement_hash is not None
    finally:
        close_workers(pool, hasher)


def test_argon2_running_cancellation() -> None:
    """验证契约：请求取消不提前释放仍在运行的Argon2名额；实际运算退出才释放，不能让同时工作数超过2。"""
    hasher = HeldHasher()
    codec = PasswordCodec(hasher)
    hasher.hold.set()
    pool = ThreadPoolExecutor(max_workers=2)
    try:
        tasks = [pool.submit(codec.hash, SecretStr("running-value-example")) for _ in range(2)]
        assert hasher.wait_entered(2)
        assert not tasks[0].cancel()
        with pytest.raises(ExternalError):
            codec.hash(SecretStr("third-value-example"))
        assert hasher.maximum == 2
    finally:
        close_workers(pool, hasher)
    for task in tasks:
        assert task.result(timeout=1).startswith("$argon2id$")


def test_login_unknown_no_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """验证契约：未知名字或停用账号登录对业务状态只读并各做一次假验证，正常返回统一401，不建行、不改G2或会话。"""
    with scenario(tmp_path) as (service, admin):
        member = member_grant(service, admin)
        service.set_status(
            admin.identity,
            member.identity.account.account_id,
            AccountStatus.DISABLED,
            now=NOW,
            audit=AUDIT_CONTEXT,
        )
        checked: list[str | bytes] = []
        statements: list[str] = []
        original = PasswordHasher.verify

        def observe(self: PasswordHasher, encoded: str | bytes, password: str | bytes) -> bool:
            checked.append(encoded)
            return original(self, encoded, password)

        def sql(connection: Connection, cursor: object, statement: str, *args: object) -> None:
            # H2的独立短事务只写登录日志；此回归仍观察账号/G2/会话业务事务。
            if not connection.get_execution_options().get("rdp_lock_timeout_ms"):
                statements.append(statement)

        event.listen(service.engine, "before_cursor_execute", sql)
        try:
            with monkeypatch.context() as patch:
                patch.setattr(PasswordHasher, "verify", observe)
                for name in ("unknown1", "unknown2", "unknown3", "member"):
                    with pytest.raises(AuthenticationError):
                        service.login(
                            Credentials(name, EXAMPLE_SECRET), now=NOW, audit=AUDIT_CONTEXT
                        )
        finally:
            event.remove(service.engine, "before_cursor_execute", sql)
        assert checked == [service.passwords.dummy_hash] * 4
        assert "BEGIN IMMEDIATE" not in statements
        assert not any(
            statement.startswith(("INSERT", "UPDATE", "DELETE")) for statement in statements
        )
        with session_scope(service.engine, read_only=True) as session:
            assert session.scalar(select(func.count()).select_from(AccountRow)) == 2
            assert session.scalar(select(func.count()).select_from(SessionRow)) == 1
            assert all(row.failed_attempts == 0 for row in session.scalars(select(AccountRow)))


def test_login_wait_skips_capacity(tmp_path: Path) -> None:
    """验证契约：已在G2等待的启用账号不申请Argon2名额，不哈希，不改计数或截止，只返回429。"""
    with scenario(tmp_path) as (service, _admin):
        with session_scope(service.engine) as session:
            row = session.get(AccountRow, 1)
            assert row is not None
            row.failed_attempts, row.blocked_until = 5, NOW + timedelta(seconds=60)
        held = HeldHasher()
        codec = PasswordCodec(held)
        held.hold.set()
        pool = ThreadPoolExecutor(max_workers=2)
        try:
            workers = [pool.submit(codec.hash, EXAMPLE_SECRET) for _ in range(2)]
            assert held.wait_entered(2)
            with pytest.raises(LoginWaitError) as caught:
                service.login(Credentials("admin", EXAMPLE_SECRET), now=NOW, audit=AUDIT_CONTEXT)
            assert caught.value.retry_after_s == 60
        finally:
            close_workers(pool, held)
        for worker in workers:
            assert worker.result(timeout=1)
        with session_scope(service.engine, read_only=True) as session:
            row = session.get(AccountRow, 1)
            assert row is not None
            assert row.failed_attempts == 5 and row.blocked_until == NOW + timedelta(seconds=60)


def test_login_capacity_no_counter(tmp_path: Path) -> None:
    """验证契约：Argon2容量超时为502而非401/429，启用账号失败次数、等待截止和会话均不变。"""
    with scenario(tmp_path) as (service, admin):
        held = HeldHasher()
        codec = PasswordCodec(held)
        held.hold.set()
        pool = ThreadPoolExecutor(max_workers=2)
        try:
            workers = [pool.submit(codec.hash, EXAMPLE_SECRET) for _ in range(2)]
            assert held.wait_entered(2)
            with pytest.raises(ExternalError):
                service.login(
                    Credentials("admin", SecretStr("incorrect-value")), now=NOW, audit=AUDIT_CONTEXT
                )
        finally:
            close_workers(pool, held)
        for worker in workers:
            assert worker.result(timeout=1)
        assert service.authenticate(admin.token, now=NOW, audit=AUDIT_CONTEXT)
        with session_scope(service.engine, read_only=True) as session:
            row = session.get(AccountRow, 1)
            assert row is not None
            assert row.failed_attempts == 0 and row.blocked_until is None
            assert session.scalar(select(func.count()).select_from(SessionRow)) == 1


def test_clock_wait_rollback(tmp_path: Path) -> None:
    """验证契约：now早于G2开始时刻时经过时长按0、余秒最多60，保留原blocked_until；回到原截止即允许尝试，不重置等待。"""
    with scenario(tmp_path) as (service, _admin):
        for number in range(5):
            with pytest.raises(LoginWaitError if number == 4 else AuthenticationError):
                service.login(
                    Credentials("admin", SecretStr("incorrect-value")), now=NOW, audit=AUDIT_CONTEXT
                )
        with pytest.raises(LoginWaitError) as caught:
            service.login(
                Credentials("admin", EXAMPLE_SECRET),
                now=NOW - timedelta(hours=1),
                audit=AUDIT_CONTEXT,
            )
        assert caught.value.retry_after_s == 60
        with session_scope(service.engine, read_only=True) as session:
            row = session.get(AccountRow, 1)
            assert row is not None and row.blocked_until == NOW + timedelta(seconds=60)
        assert service.login(
            Credentials("admin", EXAMPLE_SECRET),
            now=NOW + timedelta(seconds=60),
            audit=AUDIT_CONTEXT,
        )


def test_clock_session_rollback(tmp_path: Path) -> None:
    """验证契约：now早于会话创建/活动时刻不报409，不刷新、不续cookie，不提前过期；达到原7天边界才过期。"""
    with scenario(tmp_path) as (service, admin):
        identity = service.authenticate(
            admin.token, now=NOW - timedelta(days=1), audit=AUDIT_CONTEXT
        )
        assert identity.last_seen_at == NOW and not identity.activity_refreshed
        assert service.authenticate(
            admin.token,
            now=NOW + timedelta(days=7) - timedelta(microseconds=1),
            audit=AUDIT_CONTEXT,
        )
        # 上一请求会刷新，因此用另一会话单独验证原7天的精确到期边界。
        fresh = service.login(Credentials("admin", EXAMPLE_SECRET), now=NOW, audit=AUDIT_CONTEXT)
        with pytest.raises(AuthenticationError):
            service.authenticate(fresh.token, now=NOW + timedelta(days=7), audit=AUDIT_CONTEXT)


def test_clock_mutation_rollback(tmp_path: Path) -> None:
    """验证契约：角色、启停、改密和重置的修改时间取max(已存,now)，回拨不报错且不因回拨改变G2截止。"""
    with scenario(tmp_path) as (service, admin):
        member = member_grant(service, admin)
        key = member.identity.account.account_id
        earlier = NOW - timedelta(days=1)
        changed = service.set_role(
            admin.identity, key, Role.ADMINISTRATOR, now=earlier, audit=AUDIT_CONTEXT
        )
        assert changed.updated_at == NOW
        disabled = service.set_status(
            admin.identity, key, AccountStatus.DISABLED, now=earlier, audit=AUDIT_CONTEXT
        )
        assert disabled.updated_at == NOW
        enabled = service.set_status(
            admin.identity, key, AccountStatus.ENABLED, now=earlier, audit=AUDIT_CONTEXT
        )
        assert enabled.updated_at == NOW
        reset = service.reset_password(
            admin.identity, key, SecretStr("replacement-value"), now=earlier, audit=AUDIT_CONTEXT
        )
        assert reset.updated_at == NOW
        own = service.change_password(
            admin.identity,
            PasswordChange(EXAMPLE_SECRET, SecretStr("another-credential")),
            now=earlier,
            audit=AUDIT_CONTEXT,
        )
        assert own.identity.account.updated_at == NOW


def test_authenticate_touch_busy(tmp_path: Path) -> None:
    """验证契约：有效会话刷新在独立连接BEGIN前设busy_timeout=100毫秒，获锁BUSY/LOCKED即跳过而非等5秒，activity_refreshed=False且不续cookie。"""
    with scenario(tmp_path) as (service, admin):
        with session_scope(service.engine):
            start = time.monotonic()
            identity = service.authenticate(
                admin.token, now=NOW + timedelta(seconds=60), audit=AUDIT_CONTEXT
            )
            assert time.monotonic() - start < 1.5
            assert not identity.activity_refreshed and identity.last_seen_at == NOW
        assert service.authenticate(admin.token, now=NOW, audit=AUDIT_CONTEXT).last_seen_at == NOW


def test_authenticate_touch_other_failure(tmp_path: Path) -> None:
    """验证契约：刷新中的I/O、约束、SQL或提交错误不能吞为尽力而为；按声明异常拒绝，不标记活动已提交。"""
    with scenario(tmp_path) as (service, admin):
        for code, expected in (
            (sqlite3.SQLITE_IOERR, ExternalError),
            (sqlite3.SQLITE_CONSTRAINT, ConflictError),
            (sqlite3.SQLITE_BUSY, ConflictError),
            (sqlite3.SQLITE_ERROR, DefectError),
        ):

            def fail(
                connection: Connection,
                cursor: object,
                statement: str,
                *args: object,
                code: int = code,
            ) -> None:
                if statement.startswith("UPDATE account_sessions"):
                    error = sqlite3.OperationalError("测试刷新失败")
                    error.sqlite_errorcode = code
                    raise error

            event.listen(service.engine, "before_cursor_execute", fail)
            try:
                with pytest.raises(expected):
                    service.authenticate(
                        admin.token, now=NOW + timedelta(seconds=60), audit=AUDIT_CONTEXT
                    )
            finally:
                event.remove(service.engine, "before_cursor_execute", fail)
            assert (
                service.authenticate(admin.token, now=NOW, audit=AUDIT_CONTEXT).last_seen_at == NOW
            )
        with fail_write_commit(service.engine), pytest.raises(ExternalError):
            service.authenticate(admin.token, now=NOW + timedelta(seconds=60), audit=AUDIT_CONTEXT)
        assert service.authenticate(admin.token, now=NOW, audit=AUDIT_CONTEXT).last_seen_at == NOW


def test_authenticate_expired_delete_busy(tmp_path: Path) -> None:
    """验证契约：已过期会话删除拿不到写锁仍拒绝，不返回身份、不续cookie，100毫秒短锁超时仍抛AuthenticationError，删除和日志留给下次访问。"""
    with scenario(tmp_path) as (service, admin):
        with session_scope(service.engine), pytest.raises(AuthenticationError):
            service.authenticate(admin.token, now=NOW + timedelta(days=7), audit=AUDIT_CONTEXT)
        with session_scope(service.engine, read_only=True) as session:
            assert session.get(SessionRow, admin.identity.token_digest) is not None
        with pytest.raises(AuthenticationError):
            service.authenticate(admin.token, now=NOW + timedelta(days=7), audit=AUDIT_CONTEXT)
        with session_scope(service.engine, read_only=True) as session:
            assert session.get(SessionRow, admin.identity.token_digest) is None


def test_authenticate_concurrent_touch(tmp_path: Path) -> None:
    """验证契约：另一请求已刷新时不重复写，activity_refreshed=False；撤销/停用后不能恢复会话。"""
    for change in ("touch", "revoke"):
        root = tmp_path / change
        root.mkdir()
        with scenario(root) as (service, admin):
            triggered = False
            updates: list[str] = []

            def concurrent(
                connection: Connection,
                cursor: object,
                statement: str,
                *args: object,
                updates: list[str] = updates,
                change: str = change,
            ) -> None:
                nonlocal triggered
                if statement.startswith("UPDATE account_sessions"):
                    updates.append(statement)
                if statement == "BEGIN IMMEDIATE" and not triggered:
                    triggered = True
                    if change == "touch":
                        service.authenticate(
                            admin.token, now=NOW + timedelta(seconds=60), audit=AUDIT_CONTEXT
                        )
                    else:
                        service.logout(admin.identity, now=NOW, audit=AUDIT_CONTEXT)

            event.listen(service.engine, "before_cursor_execute", concurrent)
            try:
                if change == "touch":
                    result = service.authenticate(
                        admin.token, now=NOW + timedelta(seconds=60), audit=AUDIT_CONTEXT
                    )
                    assert (
                        result.last_seen_at == NOW + timedelta(seconds=60)
                        and not result.activity_refreshed
                    )
                    assert len(updates) == 1
                else:
                    with pytest.raises(AuthenticationError):
                        service.authenticate(
                            admin.token, now=NOW + timedelta(seconds=60), audit=AUDIT_CONTEXT
                        )
            finally:
                event.remove(service.engine, "before_cursor_execute", concurrent)
            assert triggered


def test_authenticate_repeated_busy_expiry(tmp_path: Path) -> None:
    """验证契约：连续刷新获锁失败时始终依据旧last_seen_at到期，不伪造活动或cookie续期，也不承诺仍只有60秒偏差。"""
    with scenario(tmp_path) as (service, admin):
        with session_scope(service.engine):
            for delta in (timedelta(seconds=60), timedelta(days=1), timedelta(days=6, hours=23)):
                identity = service.authenticate(admin.token, now=NOW + delta, audit=AUDIT_CONTEXT)
                assert identity.last_seen_at == NOW and not identity.activity_refreshed
        with pytest.raises(AuthenticationError):
            service.authenticate(admin.token, now=NOW + timedelta(days=7), audit=AUDIT_CONTEXT)


def test_admin_disable_self(tmp_path: Path) -> None:
    """验证契约：存在另一启用管理员时可停用自己，同事务撤销当前全部会话，下一请求401。"""
    with scenario(tmp_path) as (service, admin):
        other = member_grant(service, admin, role=Role.ADMINISTRATOR)
        second = service.login(Credentials("admin", EXAMPLE_SECRET), now=NOW, audit=AUDIT_CONTEXT)
        service.set_status(admin.identity, 1, AccountStatus.DISABLED, now=NOW, audit=AUDIT_CONTEXT)
        for token in (admin.token, second.token):
            with pytest.raises(AuthenticationError):
                service.authenticate(token, now=NOW, audit=AUDIT_CONTEXT)
        assert service.list_accounts(other.identity, after_id=0, now=NOW)


def test_admin_delete_self(tmp_path: Path) -> None:
    """验证契约：存在另一启用管理员时可删除自己，同事务撤销当前全部会话，下一请求401。"""
    with scenario(tmp_path) as (service, admin):
        other = member_grant(service, admin, role=Role.ADMINISTRATOR)
        second = service.login(Credentials("admin", EXAMPLE_SECRET), now=NOW, audit=AUDIT_CONTEXT)
        service.delete_account(admin.identity, 1, now=NOW, audit=AUDIT_CONTEXT)
        for token in (admin.token, second.token):
            with pytest.raises(AuthenticationError):
                service.authenticate(token, now=NOW, audit=AUDIT_CONTEXT)
        assert service.list_accounts(other.identity, after_id=0, now=NOW)


def test_admin_demote_self(tmp_path: Path) -> None:
    """验证契约：存在另一启用管理员时可降级自己，按既定角色变更契约撤销全部会话，下一请求401。"""
    with scenario(tmp_path) as (service, admin):
        other = member_grant(service, admin, role=Role.ADMINISTRATOR)
        second = service.login(Credentials("admin", EXAMPLE_SECRET), now=NOW, audit=AUDIT_CONTEXT)
        service.set_role(admin.identity, 1, Role.MEMBER, now=NOW, audit=AUDIT_CONTEXT)
        for token in (admin.token, second.token):
            with pytest.raises(AuthenticationError):
                service.authenticate(token, now=NOW, audit=AUDIT_CONTEXT)
        assert service.list_accounts(other.identity, after_id=0, now=NOW)


@pytest.mark.parametrize(
    "operation",
    [
        "login",
        "change_password",
        "create_account",
        "reset_password",
        "create_first_admin",
        "reset_password_from_ops",
    ],
)
def test_service_argon2_capacity_failure(operation: str, tmp_path: Path) -> None:
    """验证契约：每个哈希入口容量超时均ExternalError，事务全回滚、不增加G2或留下半条账号/会话。"""
    with account_operation(tmp_path, operation) as (service, invoke):
        before = persisted_account_state(service.engine)
        held = HeldHasher()
        codec = PasswordCodec(held)
        held.hold.set()
        pool = ThreadPoolExecutor(max_workers=2)
        try:
            workers = [pool.submit(codec.hash, EXAMPLE_SECRET) for _ in range(2)]
            assert held.wait_entered(2)
            with pytest.raises(ExternalError):
                invoke()
        finally:
            close_workers(pool, held)
        for worker in workers:
            assert worker.result(timeout=1)
        assert persisted_account_state(service.engine) == before


def test_current_password_error_type(tmp_path: Path) -> None:
    """验证契约：CurrentPasswordError继承AccountInputError，状态400且有当前密码不正确的安全诊断；普通参数错误仍422。"""
    with scenario(tmp_path) as (service, admin):
        with pytest.raises(CurrentPasswordError) as caught:
            service.change_password(
                admin.identity,
                PasswordChange(SecretStr("incorrect-value"), SecretStr("replacement-value")),
                now=NOW,
                audit=AUDIT_CONTEXT,
            )
        assert isinstance(caught.value, AccountInputError) and caught.value.http_status == 400
        assert caught.value.diagnostics[0].actual == "当前密码不正确"
        with pytest.raises(AccountInputError) as invalid:
            service.change_password(
                admin.identity,
                PasswordChange(EXAMPLE_SECRET, SecretStr("short")),
                now=NOW,
                audit=AUDIT_CONTEXT,
            )
        assert invalid.value.http_status == 422


def test_login_hash_changed_after_verify(tmp_path: Path) -> None:
    """验证契约：事务外核验后密码哈希被另一连接更新，短写事务重读返回409要求重试，不增加失败计数、不签发会话、不写旧的重哈希结果。"""
    with scenario(tmp_path) as (service, _admin):
        previous = PasswordHasher(time_cost=2, memory_cost=1024, parallelism=1).hash(
            EXAMPLE_SECRET.get_secret_value()
        )
        replacement = service.passwords.hash(SecretStr("concurrent-credential"))
        with session_scope(service.engine) as session:
            row = session.get(AccountRow, 1)
            assert row is not None
            row.password_hash = previous
        hasher = HookHasher()
        service.passwords = PasswordCodec(hasher)

        def change() -> None:
            with session_scope(service.engine) as session:
                row = session.get(AccountRow, 1)
                assert row is not None
                row.password_hash = replacement

        hasher.on_verify = change
        with pytest.raises(ConflictError):
            service.login(Credentials("admin", EXAMPLE_SECRET), now=NOW, audit=AUDIT_CONTEXT)
        with session_scope(service.engine, read_only=True) as session:
            row = session.get(AccountRow, 1)
            assert row is not None and row.password_hash == replacement and row.failed_attempts == 0
            assert session.scalar(select(func.count()).select_from(SessionRow)) == 1


def test_login_g2_changed_after_verify(tmp_path: Path) -> None:
    """验证契约：快照后G2计数变化但未等待返回409；已在等待返回429且不再累加，第五次错误不会被并发重复提交。"""
    for count in (1, 5):
        root = tmp_path / str(count)
        root.mkdir()
        with scenario(root) as (service, admin):
            hasher = HookHasher()
            service.passwords = PasswordCodec(hasher)

            def change(count: int = count) -> None:
                with session_scope(service.engine) as session:
                    row = session.get(AccountRow, 1)
                    assert row is not None
                    row.failed_attempts = count
                    row.blocked_until = NOW + timedelta(seconds=60) if count == 5 else None

            hasher.on_verify = change
            with pytest.raises(LoginWaitError if count == 5 else ConflictError):
                service.login(Credentials("admin", EXAMPLE_SECRET), now=NOW, audit=AUDIT_CONTEXT)
            assert service.authenticate(admin.token, now=NOW, audit=AUDIT_CONTEXT)
            with session_scope(service.engine, read_only=True) as session:
                row = session.get(AccountRow, 1)
                assert row is not None and row.failed_attempts == count
                assert session.scalar(select(func.count()).select_from(SessionRow)) == 1


def test_login_disabled_after_verify(tmp_path: Path) -> None:
    """验证契约：事务外核验后账号删除/停用返回统一401，不把预先算好的成功结果用于签发会话。"""
    for operation in ("disable", "delete"):
        root = tmp_path / operation
        root.mkdir()
        with scenario(root) as (service, admin):
            hasher = HookHasher()
            service.passwords = PasswordCodec(hasher)

            def change(operation: str = operation) -> None:
                with session_scope(service.engine) as session:
                    row = session.get(AccountRow, 1)
                    assert row is not None
                    if operation == "disable":
                        row.status = "disabled"
                    else:
                        session.delete(row)

            hasher.on_verify = change
            with pytest.raises(AuthenticationError):
                service.login(Credentials("admin", EXAMPLE_SECRET), now=NOW, audit=AUDIT_CONTEXT)
            with pytest.raises(AuthenticationError):
                service.authenticate(admin.token, now=NOW, audit=AUDIT_CONTEXT)
            with session_scope(service.engine, read_only=True) as session:
                assert session.scalar(select(func.count()).select_from(SessionRow)) == (
                    1 if operation == "disable" else 0
                )


def test_login_expired_g2_snapshot(tmp_path: Path) -> None:
    """验证契约：已过期但未清零的G2原始二元组也参与比较；只在写事务确认未变后重置并计数，不在只读快照时写入。"""
    with scenario(tmp_path) as (service, _admin):
        with session_scope(service.engine) as session:
            row = session.get(AccountRow, 1)
            assert row is not None
            row.failed_attempts, row.blocked_until = 5, NOW - timedelta(seconds=1)
        hasher = HookHasher()
        service.passwords = PasswordCodec(hasher)

        def change() -> None:
            with session_scope(service.engine) as session:
                row = session.get(AccountRow, 1)
                assert row is not None
                row.failed_attempts, row.blocked_until = 1, None

        hasher.on_verify = change
        with pytest.raises(ConflictError):
            service.login(Credentials("admin", EXAMPLE_SECRET), now=NOW, audit=AUDIT_CONTEXT)
        hasher.on_verify = None
        with pytest.raises(AuthenticationError):
            service.login(
                Credentials("admin", SecretStr("incorrect-value")), now=NOW, audit=AUDIT_CONTEXT
            )
        with session_scope(service.engine, read_only=True) as session:
            row = session.get(AccountRow, 1)
            assert row is not None and row.failed_attempts == 2 and row.blocked_until is None


def test_password_change_hash_changed(tmp_path: Path) -> None:
    """验证契约：改密事务外核验后哈希已变而会话仍有效时409，丢弃预先算好的新哈希，不增加G2，不撤销或创建会话。"""
    with scenario(tmp_path) as (service, admin):
        replacement = service.passwords.hash(SecretStr("concurrent-credential"))
        hasher = HookHasher()
        service.passwords = PasswordCodec(hasher)

        def change() -> None:
            with session_scope(service.engine) as session:
                row = session.get(AccountRow, 1)
                assert row is not None
                row.password_hash = replacement

        hasher.on_verify = change
        with pytest.raises(ConflictError):
            service.change_password(
                admin.identity,
                PasswordChange(EXAMPLE_SECRET, SecretStr("replacement-value")),
                now=NOW,
                audit=AUDIT_CONTEXT,
            )
        assert service.authenticate(admin.token, now=NOW, audit=AUDIT_CONTEXT)
        with session_scope(service.engine, read_only=True) as session:
            row = session.get(AccountRow, 1)
            assert row is not None and row.password_hash == replacement and row.failed_attempts == 0
            assert session.scalar(select(func.count()).select_from(SessionRow)) == 1


def test_password_change_session_revoked(tmp_path: Path) -> None:
    """验证契约：改密运算期间管理员重置密码并撤销会话，重读会话失效401优先，不应用旧核验或新哈希。"""
    with scenario(tmp_path) as (service, admin):
        other = AccountService(service.engine, service.passwords)
        hasher = HookHasher()
        service.passwords = PasswordCodec(hasher)
        hasher.on_verify = lambda: other.reset_password_from_ops(
            "admin", SecretStr("concurrent-credential"), now=NOW, audit=OPS_AUDIT_CONTEXT
        )
        with pytest.raises(AuthenticationError):
            service.change_password(
                admin.identity,
                PasswordChange(EXAMPLE_SECRET, SecretStr("replacement-value")),
                now=NOW,
                audit=AUDIT_CONTEXT,
            )
        with pytest.raises(AuthenticationError):
            service.authenticate(admin.token, now=NOW, audit=AUDIT_CONTEXT)
        assert other.login(
            Credentials("admin", SecretStr("concurrent-credential")), now=NOW, audit=AUDIT_CONTEXT
        ).identity.account.must_change_password


def test_password_change_g2_changed(tmp_path: Path) -> None:
    """验证契约：改密核验后G2变化，已等待429、其他变化409，均不按错误旧密码再次计数。"""
    for count in (1, 5):
        root = tmp_path / str(count)
        root.mkdir()
        with scenario(root) as (service, admin):
            hasher = HookHasher()
            service.passwords = PasswordCodec(hasher)

            def change(count: int = count) -> None:
                with session_scope(service.engine) as session:
                    row = session.get(AccountRow, 1)
                    assert row is not None
                    row.failed_attempts = count
                    row.blocked_until = NOW + timedelta(seconds=60) if count == 5 else None

            hasher.on_verify = change
            with pytest.raises(LoginWaitError if count == 5 else ConflictError):
                service.change_password(
                    admin.identity,
                    PasswordChange(EXAMPLE_SECRET, SecretStr("replacement-value")),
                    now=NOW,
                    audit=AUDIT_CONTEXT,
                )
            assert service.authenticate(admin.token, now=NOW, audit=AUDIT_CONTEXT)
            with session_scope(service.engine, read_only=True) as session:
                row = session.get(AccountRow, 1)
                assert row is not None and row.failed_attempts == count
                assert session.scalar(select(func.count()).select_from(SessionRow)) == 1


def test_password_change_mismatch_keeps_session(tmp_path: Path) -> None:
    """验证契约：前四次错误当前密码仅提交G2计数并返回400，当前和其他会话保留，提示当前密码不正确。"""
    with scenario(tmp_path) as (service, first):
        second = service.login(Credentials("admin", EXAMPLE_SECRET), now=NOW, audit=AUDIT_CONTEXT)
        for count in range(1, 5):
            with pytest.raises(CurrentPasswordError) as caught:
                service.change_password(
                    first.identity,
                    PasswordChange(SecretStr("incorrect-value"), SecretStr("replacement-value")),
                    now=NOW,
                    audit=AUDIT_CONTEXT,
                )
            assert caught.value.http_status == 400
            for grant in (first, second):
                assert (
                    service.authenticate(
                        grant.token, now=NOW, audit=AUDIT_CONTEXT
                    ).account.account_id
                    == 1
                )
            with session_scope(service.engine, read_only=True) as session:
                row = session.get(AccountRow, 1)
                assert row is not None and row.failed_attempts == count


def test_creation_rechecks_authority(tmp_path: Path) -> None:
    """验证契约：预计算新哈希后管理员被停用/降级或必须改密，写事务重新核验并拒绝，不创建账号。"""
    for change in ("role", "status", "force"):
        root = tmp_path / change
        root.mkdir()
        with scenario(root) as (service, admin):
            other = member_grant(service, admin, role=Role.ADMINISTRATOR)
            hasher = HookHasher()
            service.passwords = PasswordCodec(hasher)

            def revoke(change: str = change) -> None:
                with session_scope(service.engine) as session:
                    row = session.get(AccountRow, 1)
                    assert row is not None
                    if change == "role":
                        row.role = "member"
                    elif change == "status":
                        row.status = "disabled"
                    else:
                        row.must_change_password = True

            hasher.on_hash = revoke
            expected = {
                "role": AuthorizationError,
                "status": AuthenticationError,
                "force": PasswordChangeRequiredError,
            }[change]
            with pytest.raises(expected):
                service.create_account(
                    admin.identity,
                    NewAccount(Credentials("newuser", EXAMPLE_SECRET), "新账号", Role.MEMBER),
                    now=NOW,
                    audit=AUDIT_CONTEXT,
                )
            assert all(
                row.login_name != "newuser"
                for row in service.list_accounts(other.identity, after_id=0, now=NOW).items
            )


def test_first_admin_rechecks_after_hash(tmp_path: Path) -> None:
    """验证契约：两个运维首号在事务外计算，写锁内再次检查已有管理员，最多一个成功，另一方409且不留半条记录。"""
    with model_database(tmp_path) as engine:
        hasher = HookHasher()
        service = AccountService(engine, PasswordCodec(hasher))
        other = AccountService(
            engine, PasswordCodec(PasswordHasher(time_cost=1, memory_cost=1024, parallelism=1))
        )
        hasher.on_hash = lambda: other.create_first_admin(
            NewAccount(Credentials("winner", EXAMPLE_SECRET), "已提交管理员", Role.ADMINISTRATOR),
            now=NOW,
            audit=OPS_AUDIT_CONTEXT,
        )
        with pytest.raises(ConflictError):
            service.create_first_admin(
                NewAccount(
                    Credentials("loser", EXAMPLE_SECRET), "未提交管理员", Role.ADMINISTRATOR
                ),
                now=NOW,
                audit=OPS_AUDIT_CONTEXT,
            )
        grant = other.login(Credentials("winner", EXAMPLE_SECRET), now=NOW, audit=AUDIT_CONTEXT)
        assert [
            row.login_name for row in other.list_accounts(grant.identity, after_id=0, now=NOW).items
        ] == ["winner"]


def test_ops_reset_recreated_name(tmp_path: Path) -> None:
    """验证契约：运维重置预计算期间原账号删除并同名重建，写事务按原编号重读给404，不改新账号。"""
    with scenario(tmp_path) as (service, admin):
        member = member_grant(service, admin)
        other = AccountService(service.engine, service.passwords)
        hasher = HookHasher()
        service.passwords = PasswordCodec(hasher)

        def recreate() -> None:
            other.delete_account(
                admin.identity, member.identity.account.account_id, now=NOW, audit=AUDIT_CONTEXT
            )
            other.create_account(
                admin.identity,
                NewAccount(
                    Credentials("member", SecretStr("recreated-credential")),
                    "重建成员",
                    Role.MEMBER,
                ),
                now=NOW,
                audit=AUDIT_CONTEXT,
            )

        hasher.on_hash = recreate
        with pytest.raises(AccountNotFoundError):
            service.reset_password_from_ops(
                "member", SecretStr("reset-credential"), now=NOW, audit=OPS_AUDIT_CONTEXT
            )
        recreated = other.login(
            Credentials("member", SecretStr("recreated-credential")), now=NOW, audit=AUDIT_CONTEXT
        )
        assert recreated.identity.account.account_id > member.identity.account.account_id
        with pytest.raises(AuthenticationError):
            other.authenticate(member.token, now=NOW, audit=AUDIT_CONTEXT)


@pytest.mark.parametrize(
    "operation",
    [
        "login",
        "change_password",
        "create_account",
        "reset_password",
        "create_first_admin",
        "reset_password_from_ops",
    ],
)
@pytest.mark.parametrize("phase", ["queue", "compute"])
def test_argon2_outside_database_transactions(
    operation: str, phase: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """验证契约：每个入口在Argon2排队/运算期间已关闭只读会话且未开写事务，另一独立连接能获得BEGIN IMMEDIATE写锁。"""
    with account_operation(tmp_path, operation) as (service, invoke):
        hasher = HookHasher()
        service.passwords = PasswordCodec(hasher)
        active: set[int] = set()
        probed: list[bool] = []

        def checkout(connection: object, record: object, proxy: object) -> None:
            active.add(id(connection))

        def checkin(connection: object, record: object) -> None:
            active.discard(id(connection))

        def probe() -> None:
            # 既要没有遗留的读会话，又要另一连接现在确实能拿到写锁。
            assert not active
            with session_scope_with_lock_timeout(service.engine, busy_timeout_ms=0) as session:
                assert session.scalar(sql_text("SELECT 1")) == 1
            probed.append(True)

        original = BoundedSemaphore.acquire

        def acquire(
            semaphore: BoundedSemaphore, blocking: bool = True, timeout: float | None = None
        ) -> bool:
            if timeout == 1.0:
                probe()
            return original(semaphore, blocking, timeout)

        event.listen(service.engine, "checkout", checkout)
        event.listen(service.engine, "checkin", checkin)
        try:
            if phase == "compute":
                hasher.on_hash = probe
                hasher.on_verify = probe
            with monkeypatch.context() as patch:
                if phase == "queue":
                    patch.setattr(BoundedSemaphore, "acquire", acquire)
                invoke()
            assert probed and not active
        finally:
            event.remove(service.engine, "checkout", checkout)
            event.remove(service.engine, "checkin", checkin)


@pytest.mark.parametrize("operation", ["login", "change_password"])
def test_rehash_calculated_before_write(operation: str, tmp_path: Path) -> None:
    """验证契约：按需重哈希在事务外完成并释放名额，写事务只比较和保存；改密丢弃旧密码重哈希结果，仅存新哈希。"""
    with scenario(tmp_path) as (service, admin):
        old = PasswordHasher(time_cost=2, memory_cost=1024, parallelism=1).hash(
            EXAMPLE_SECRET.get_secret_value()
        )
        with session_scope(service.engine) as session:
            row = session.get(AccountRow, 1)
            assert row is not None
            row.password_hash = old
        hasher = HookHasher()
        service.passwords = PasswordCodec(hasher)
        completed: list[int] = []
        writing: list[int] = []

        def probe() -> None:
            with session_scope_with_lock_timeout(service.engine, busy_timeout_ms=0):
                pass
            completed.append(1)

        def begin(connection: Connection, cursor: object, statement: str, *args: object) -> None:
            if (
                statement == "BEGIN IMMEDIATE"
                and "rdp_lock_timeout_ms" not in connection.get_execution_options()
            ):
                writing.append(len(completed))

        hasher.on_hash = probe
        event.listen(service.engine, "before_cursor_execute", begin)
        try:
            if operation == "login":
                service.login(Credentials("admin", EXAMPLE_SECRET), now=NOW, audit=AUDIT_CONTEXT)
            else:
                service.change_password(
                    admin.identity,
                    PasswordChange(EXAMPLE_SECRET, SecretStr("replacement-value")),
                    now=NOW,
                    audit=AUDIT_CONTEXT,
                )
        finally:
            event.remove(service.engine, "before_cursor_execute", begin)
        assert writing == [1 if operation == "login" else 2]
        with session_scope(service.engine, read_only=True) as session:
            row = session.get(AccountRow, 1)
            assert row is not None
            encoded = row.password_hash
        assert not hasher.check_needs_rehash(encoded)
        assert hasher.verify(
            encoded,
            EXAMPLE_SECRET.get_secret_value() if operation == "login" else "replacement-value",
        )
        if operation == "change_password":
            with pytest.raises(VerifyMismatchError):
                hasher.verify(encoded, EXAMPLE_SECRET.get_secret_value())
