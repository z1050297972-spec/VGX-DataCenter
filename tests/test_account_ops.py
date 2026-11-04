"""工单06可注入密码读取的运维测试；只用 tmp_path/临时数据库和固定 aware 时钟。"""

import sqlite3
import warnings
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from getpass import GetPassWarning
from pathlib import Path
from typing import cast

import pytest
from accounts_support import (
    AUDIT_CONTEXT,
    EXAMPLE_SECRET,
    NOW,
    HeldHasher,
    close_workers,
    model_database,
    scenario,
)
from argon2 import PasswordHasher
from pydantic import SecretStr
from sqlalchemy import Connection, event, select

from rdp.accounts.errors import AccountInputError, AccountNotFoundError, AuthenticationError
from rdp.accounts.models import AccountRow
from rdp.accounts.security import PasswordCodec
from rdp.accounts.service import AccountService
from rdp.accounts.types import AccountStatus, ActorRef, Credentials, Role
from rdp.api.errors import format_exception_report
from rdp.infra.db.connection import session_scope
from rdp.infra.diagnostics import ConflictError, DefectError, ExternalError, InputError
from rdp.ops.accounts import create_first_admin, reset_account_password


def test_create_first_admin_success(tmp_path: Path) -> None:
    """验证契约：两次无回显输入一致后才调用领域服务，传固定aware时刻，不访问真实配置/状态目录。"""
    with model_database(tmp_path) as engine:
        service = AccountService(
            engine, PasswordCodec(PasswordHasher(time_cost=1, memory_cost=1024, parallelism=1))
        )
        prompts: list[str] = []

        def reader(prompt: str) -> str:
            prompts.append(prompt)
            return EXAMPLE_SECRET.get_secret_value()

        account = create_first_admin(service, "admin", "管理员", now=NOW, read_password=reader)
        assert len(prompts) == 2 and all(
            EXAMPLE_SECRET.get_secret_value() not in prompt for prompt in prompts
        )
        assert account.created_at == NOW and account.role is Role.ADMINISTRATOR
        assert not account.must_change_password and account.created_by == ActorRef(None, "运维")
        assert (
            service.login(
                Credentials("admin", EXAMPLE_SECRET), now=NOW, audit=AUDIT_CONTEXT
            ).identity.account
            == account
        )


def test_create_first_admin_mismatch(tmp_path: Path) -> None:
    """验证契约：UTF-8 字节以常量时间比较，两次不同给安全 AccountInputError，无数据库写入。"""
    with model_database(tmp_path) as engine:
        service = AccountService(
            engine, PasswordCodec(PasswordHasher(time_cost=1, memory_cost=1024, parallelism=1))
        )
        values = iter(["不同密码🙂🙂🙂🙂🙂🙂", "不同密码🙂🙂🙂🙂🙂🙃"])
        with pytest.raises(AccountInputError) as caught:
            create_first_admin(
                service, "admin", "管理员", now=NOW, read_password=lambda prompt: next(values)
            )
        assert "不同密码" not in format_exception_report(caught.value)
        with session_scope(engine, read_only=True) as session:
            assert not session.scalars(select(AccountRow)).all()


def test_create_first_admin_echo(tmp_path: Path) -> None:
    """验证契约：默认getpass遇GetPassWarning拒绝回显回退，ExternalError且未开始事务。"""
    with model_database(tmp_path) as engine:
        service = AccountService(
            engine, PasswordCodec(PasswordHasher(time_cost=1, memory_cost=1024, parallelism=1))
        )

        def reader(prompt: str) -> str:
            warnings.warn("无回显不可用", GetPassWarning, stacklevel=2)
            pytest.fail("禁止在警告后继续回显读取")

        with pytest.raises(ExternalError):
            create_first_admin(service, "admin", "管理员", now=NOW, read_password=reader)
        with session_scope(engine, read_only=True) as session:
            assert not session.scalars(select(AccountRow)).all()


def test_create_first_admin_abort(tmp_path: Path) -> None:
    """验证契约：EOFError和KeyboardInterrupt分别原样传播，取消后无账号/会话变更。"""
    with model_database(tmp_path) as engine:
        service = AccountService(
            engine, PasswordCodec(PasswordHasher(time_cost=1, memory_cost=1024, parallelism=1))
        )
        for error in (EOFError(), KeyboardInterrupt()):

            def reader(prompt: str, error: BaseException = error) -> str:
                raise error

            with pytest.raises(type(error)) as caught:
                create_first_admin(service, "admin", "管理员", now=NOW, read_password=reader)
            assert caught.value is error
        with session_scope(engine, read_only=True) as session:
            assert not session.scalars(select(AccountRow)).all()


def test_create_first_admin_input_error(tmp_path: Path) -> None:
    """验证契约：读密码I/O归ExternalError，未知回调错误归安全DefectError，不保留原始秘密异常链。"""
    with model_database(tmp_path) as engine:
        service = AccountService(
            engine, PasswordCodec(PasswordHasher(time_cost=1, memory_cost=1024, parallelism=1))
        )
        for original, expected in [
            (OSError("private-read-value"), ExternalError),
            (RuntimeError("private-read-value"), DefectError),
        ]:

            def reader(prompt: str, original: BaseException = original) -> str:
                raise original

            with pytest.raises(expected) as caught:
                create_first_admin(service, "admin", "管理员", now=NOW, read_password=reader)
            assert "private-read-value" not in format_exception_report(caught.value)
        with session_scope(engine, read_only=True) as session:
            assert not session.scalars(select(AccountRow)).all()


def test_create_first_admin_domain_errors(tmp_path: Path) -> None:
    """验证契约：逐项传播领域的输入/冲突/外部/缺陷错误，字段错误归AccountInputError、调用方now非法归DefectError，均不写入。"""
    with model_database(tmp_path) as engine:
        service = AccountService(
            engine, PasswordCodec(PasswordHasher(time_cost=1, memory_cost=1024, parallelism=1))
        )

        def invoke(login: str = "admin") -> object:
            return create_first_admin(
                service,
                login,
                "管理员",
                now=NOW,
                read_password=lambda prompt: EXAMPLE_SECRET.get_secret_value(),
            )

        with pytest.raises(AccountInputError):
            invoke("BAD-NAME")
        for code, expected in [
            (sqlite3.SQLITE_CORRUPT, InputError),
            (sqlite3.SQLITE_BUSY, ConflictError),
            (sqlite3.SQLITE_IOERR, ExternalError),
            (sqlite3.SQLITE_ERROR, DefectError),
        ]:

            def failing(
                connection: Connection,
                cursor: object,
                statement: str,
                *args: object,
                code: int = code,
            ) -> None:
                if statement.startswith("SELECT"):
                    error = sqlite3.OperationalError("测试领域存储故障")
                    error.sqlite_errorcode = code
                    raise error

            event.listen(engine, "before_cursor_execute", failing)
            try:
                with pytest.raises(expected):
                    invoke()
            finally:
                event.remove(engine, "before_cursor_execute", failing)
        with session_scope(engine, read_only=True) as session:
            assert not session.scalars(select(AccountRow)).all()


def test_create_first_admin_lifecycle(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], caplog: pytest.LogCaptureFixture
) -> None:
    """验证契约：不迁移、不创建默认路径、不dispose调用者引擎，不打印或记录密码。"""
    with model_database(tmp_path) as engine:
        service = AccountService(
            engine, PasswordCodec(PasswordHasher(time_cost=1, memory_cost=1024, parallelism=1))
        )

        def reader(prompt: str) -> str:
            with session_scope(engine) as session:
                assert session.scalar(select(AccountRow.account_id)) is None
            return EXAMPLE_SECRET.get_secret_value()

        account = create_first_admin(service, "admin", "管理员", now=NOW, read_password=reader)
        assert (
            service.login(
                Credentials("admin", EXAMPLE_SECRET), now=NOW, audit=AUDIT_CONTEXT
            ).identity.account
            == account
        )
        assert not capsys.readouterr().out and EXAMPLE_SECRET.get_secret_value() not in caplog.text


def test_reset_account_password_success(tmp_path: Path) -> None:
    """验证契约：两次无回显输入一致后才调用领域服务，传固定aware时刻，不访问真实配置/状态目录。"""
    with scenario(tmp_path) as (service, grant):
        value = SecretStr("replacement-credential")
        prompts: list[str] = []

        def reader(prompt: str) -> str:
            prompts.append(prompt)
            return value.get_secret_value()

        account = reset_account_password(service, "admin", now=NOW, read_password=reader)
        assert len(prompts) == 2 and account.must_change_password
        assert account.updated_at == NOW and account.updated_by == ActorRef(None, "运维")
        with pytest.raises(AuthenticationError):
            service.authenticate(grant.token, now=NOW, audit=AUDIT_CONTEXT)
        assert (
            service.login(
                Credentials("admin", value), now=NOW, audit=AUDIT_CONTEXT
            ).identity.account
            == account
        )


def test_reset_account_password_mismatch(tmp_path: Path) -> None:
    """验证契约：UTF-8 字节以常量时间比较，两次不同给安全 AccountInputError，无数据库写入。"""
    with scenario(tmp_path) as (service, grant):
        values = iter(["replacement-value-one", "replacement-value-two"])
        with pytest.raises(AccountInputError):
            reset_account_password(
                service, "admin", now=NOW, read_password=lambda prompt: next(values)
            )
        assert (
            service.authenticate(grant.token, now=NOW, audit=AUDIT_CONTEXT).account
            == grant.identity.account
        )
        assert service.login(Credentials("admin", EXAMPLE_SECRET), now=NOW, audit=AUDIT_CONTEXT)


def test_reset_account_password_echo(tmp_path: Path) -> None:
    """验证契约：默认getpass遇GetPassWarning拒绝回显回退，ExternalError且未开始事务。"""
    with scenario(tmp_path) as (service, grant):

        def reader(prompt: str) -> str:
            warnings.warn("无回显不可用", GetPassWarning, stacklevel=2)
            pytest.fail("不能在警告后继续读取")

        with pytest.raises(ExternalError):
            reset_account_password(service, "admin", now=NOW, read_password=reader)
        assert (
            service.authenticate(grant.token, now=NOW, audit=AUDIT_CONTEXT).account
            == grant.identity.account
        )


def test_reset_account_password_abort(tmp_path: Path) -> None:
    """验证契约：EOFError和KeyboardInterrupt分别原样传播，取消后无账号/会话变更。"""
    with scenario(tmp_path) as (service, grant):
        for original in (EOFError(), KeyboardInterrupt()):

            def reader(prompt: str, original: BaseException = original) -> str:
                raise original

            with pytest.raises(type(original)) as caught:
                reset_account_password(service, "admin", now=NOW, read_password=reader)
            assert caught.value is original
            assert (
                service.authenticate(grant.token, now=NOW, audit=AUDIT_CONTEXT).account
                == grant.identity.account
            )


def test_reset_account_password_input_error(tmp_path: Path) -> None:
    """验证契约：读密码I/O归ExternalError，未知回调错误归安全DefectError，不保留原始秘密异常链。"""
    with scenario(tmp_path) as (service, grant):
        for original, expected in [
            (OSError("private-read-value"), ExternalError),
            (RuntimeError("private-read-value"), DefectError),
        ]:

            def reader(prompt: str, original: BaseException = original) -> str:
                raise original

            with pytest.raises(expected) as caught:
                reset_account_password(service, "admin", now=NOW, read_password=reader)
            assert "private-read-value" not in format_exception_report(caught.value)
            assert (
                service.authenticate(grant.token, now=NOW, audit=AUDIT_CONTEXT).account
                == grant.identity.account
            )


def test_reset_account_password_domain_errors(tmp_path: Path) -> None:
    """验证契约：逐项传播领域的输入/冲突/外部/缺陷错误，字段错误归AccountInputError、调用方now非法归DefectError，均不写入。"""
    with model_database(tmp_path) as engine:
        service = AccountService(
            engine, PasswordCodec(PasswordHasher(time_cost=1, memory_cost=1024, parallelism=1))
        )

        def invoke(login: str = "admin") -> object:
            return reset_account_password(
                service,
                login,
                now=NOW,
                read_password=lambda prompt: EXAMPLE_SECRET.get_secret_value(),
            )

        with pytest.raises(AccountInputError):
            invoke("BAD-NAME")
        for code, expected in [
            (sqlite3.SQLITE_CORRUPT, InputError),
            (sqlite3.SQLITE_BUSY, ConflictError),
            (sqlite3.SQLITE_IOERR, ExternalError),
            (sqlite3.SQLITE_ERROR, DefectError),
        ]:

            def failing(
                connection: Connection,
                cursor: object,
                statement: str,
                *args: object,
                code: int = code,
            ) -> None:
                if statement.startswith("SELECT"):
                    error = sqlite3.OperationalError("测试领域存储故障")
                    error.sqlite_errorcode = code
                    raise error

            event.listen(engine, "before_cursor_execute", failing)
            try:
                with pytest.raises(expected):
                    invoke()
            finally:
                event.remove(engine, "before_cursor_execute", failing)
        with session_scope(engine, read_only=True) as session:
            assert not session.scalars(select(AccountRow)).all()


def test_reset_account_password_lifecycle(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], caplog: pytest.LogCaptureFixture
) -> None:
    """验证契约：不迁移、不创建默认路径、不dispose调用者引擎，不打印或记录密码。"""
    with scenario(tmp_path) as (service, _grant):
        value = "replacement-credential"

        def reader(prompt: str) -> str:
            with session_scope(service.engine) as session:
                assert session.get(AccountRow, 1) is not None
            return value

        account = reset_account_password(service, "admin", now=NOW, read_password=reader)
        assert (
            service.login(
                Credentials("admin", SecretStr(value)), now=NOW, audit=AUDIT_CONTEXT
            ).identity.account
            == account
        )
        output = capsys.readouterr()
        assert value not in output.out + output.err + caplog.text


def test_specific_first_exists(tmp_path: Path) -> None:
    """验证契约：已有管理员含停用时首号函数ConflictError，首号成功标记False且操作人为运维。"""
    with scenario(tmp_path) as (service, _grant):
        with pytest.raises(ConflictError):
            create_first_admin(
                service,
                "another",
                "另一个",
                now=NOW,
                read_password=lambda prompt: EXAMPLE_SECRET.get_secret_value(),
            )
        with session_scope(service.engine) as session:
            row = session.get(AccountRow, 1)
            assert row is not None
            row.status = "disabled"
        with pytest.raises(ConflictError):
            create_first_admin(
                service,
                "another",
                "另一个",
                now=NOW,
                read_password=lambda prompt: EXAMPLE_SECRET.get_secret_value(),
            )
        with session_scope(service.engine, read_only=True) as session:
            assert len(session.scalars(select(AccountRow)).all()) == 1


def test_specific_reset_missing(tmp_path: Path) -> None:
    """验证契约：运维重置不存在目标AccountNotFoundError。"""
    with scenario(tmp_path) as (service, grant):
        with pytest.raises(AccountNotFoundError):
            reset_account_password(
                service,
                "missing",
                now=NOW,
                read_password=lambda prompt: EXAMPLE_SECRET.get_secret_value(),
            )
        assert (
            service.authenticate(grant.token, now=NOW, audit=AUDIT_CONTEXT).account
            == grant.identity.account
        )


def test_specific_reset_atomic(tmp_path: Path) -> None:
    """验证契约：重置成功删全部会话、清G2、置必须改密，保留角色/状态；失败全回滚。"""
    with scenario(tmp_path) as (service, grant):
        for _ in range(4):
            with pytest.raises(AuthenticationError):
                service.login(
                    Credentials("admin", SecretStr("incorrect-value")), now=NOW, audit=AUDIT_CONTEXT
                )

        def failing(connection: Connection) -> None:
            raise sqlite3.OperationalError("测试提交失败")

        event.listen(service.engine, "commit", failing)
        try:
            with pytest.raises(DefectError):
                reset_account_password(
                    service, "admin", now=NOW, read_password=lambda prompt: "replacement-credential"
                )
        finally:
            event.remove(service.engine, "commit", failing)
        assert (
            service.authenticate(grant.token, now=NOW, audit=AUDIT_CONTEXT).account
            == grant.identity.account
        )
        with session_scope(service.engine, read_only=True) as session:
            row = session.get(AccountRow, 1)
            assert row is not None and row.failed_attempts == 4 and not row.must_change_password
        changed = reset_account_password(
            service, "admin", now=NOW, read_password=lambda prompt: "replacement-credential"
        )
        assert (
            changed.must_change_password
            and changed.role is Role.ADMINISTRATOR
            and changed.status is AccountStatus.ENABLED
        )
        with pytest.raises(AuthenticationError):
            service.authenticate(grant.token, now=NOW, audit=AUDIT_CONTEXT)
        with session_scope(service.engine, read_only=True) as session:
            row = session.get(AccountRow, 1)
            assert row is not None and row.failed_attempts == 0 and row.blocked_until is None


def test_argon2_capacity_failure(tmp_path: Path) -> None:
    """验证契约：首号创建和运维重置的Argon2容量超时给ExternalError，未留下账号、哈希、标记或会话的部分变更。"""
    with scenario(tmp_path) as (service, grant):
        hasher = HeldHasher()
        codec = PasswordCodec(hasher)
        hasher.hold.set()
        pool = ThreadPoolExecutor(max_workers=2)
        try:
            workers = [pool.submit(codec.hash, EXAMPLE_SECRET) for _ in range(2)]
            assert hasher.wait_entered(2)
            with pytest.raises(ExternalError):
                reset_account_password(
                    service, "admin", now=NOW, read_password=lambda prompt: "replacement-credential"
                )
            # 创建首号的已有管理员检查会先冲突，另用空库验证容量失败。
            (tmp_path / "empty").mkdir()
            with model_database(tmp_path / "empty") as engine:
                empty_service = AccountService(engine, service.passwords)
                with pytest.raises(ExternalError):
                    create_first_admin(
                        empty_service,
                        "admin",
                        "管理员",
                        now=NOW,
                        read_password=lambda prompt: EXAMPLE_SECRET.get_secret_value(),
                    )
                with session_scope(engine, read_only=True) as session:
                    assert not session.scalars(select(AccountRow)).all()
        finally:
            close_workers(pool, hasher)
        for worker in workers:
            assert worker.result(timeout=1)
        assert (
            service.authenticate(grant.token, now=NOW, audit=AUDIT_CONTEXT).account
            == grant.identity.account
        )


def test_invalid_now_is_defect(tmp_path: Path) -> None:
    """验证契约：运维入口收到非法now先抛安全DefectError，不读密码/写库；直接领域调用非法now仍AccountInputError。"""
    with scenario(tmp_path) as (service, grant):

        def reader(prompt: str) -> str:
            pytest.fail("非法时刻不能读取密码")

        for now in (
            NOW.replace(tzinfo=None),
            datetime.max.replace(tzinfo=UTC),
            cast(datetime, "private-clock"),
        ):
            for operation in ("create", "reset"):
                with pytest.raises(DefectError):
                    if operation == "create":
                        create_first_admin(
                            service, "other", "另一个", now=now, read_password=reader
                        )
                    else:
                        reset_account_password(service, "admin", now=now, read_password=reader)
            with pytest.raises(AccountInputError):
                service.login(Credentials("admin", EXAMPLE_SECRET), now=now, audit=AUDIT_CONTEXT)
        assert (
            service.authenticate(grant.token, now=NOW, audit=AUDIT_CONTEXT).account
            == grant.identity.account
        )
