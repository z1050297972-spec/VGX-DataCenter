"""账号测试的外部 Argon2 边界替身与有界线程资源；不替换平台内部函数。"""

import sqlite3
from collections.abc import Callable, Generator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from threading import Condition, Event, Lock
from typing import Any, Literal, override

from argon2 import PasswordHasher
from pydantic import SecretStr
from sqlalchemy import Connection, Engine, event, select

from rdp.accounts.models import AccountRow, SessionRow
from rdp.accounts.security import PasswordCodec
from rdp.accounts.service import AccountService
from rdp.accounts.types import (
    AccountStatus,
    AccountView,
    ActorRef,
    Credentials,
    NewAccount,
    PasswordChange,
    Role,
    SessionGrant,
)
from rdp.audit.types import OPS_AUDIT_CONTEXT, AuditContext
from rdp.infra.db.connection import create_database_engine, session_scope
from rdp.infra.db.models import metadata


class HeldHasher(PasswordHasher):
    """在库边界可控地暂停运算，观察平台跨实例的并发上限。"""

    def __init__(self) -> None:
        """先使用真实低成本 Argon2，hold 后才阻塞，不影响编码器初始化。"""
        super().__init__(time_cost=1, memory_cost=1024, parallelism=1)
        self.hold = Event()
        self.release = Event()
        self.changed = Condition(Lock())
        self.active = 0
        self.maximum = 0
        self.entered = 0

    def _enter(self) -> None:
        """所有测试等待最多四秒，失败时也能在 finally 回收线程。"""
        if not self.hold.is_set():
            return
        with self.changed:
            self.active += 1
            self.entered += 1
            self.maximum = max(self.maximum, self.active)
            self.changed.notify_all()
        try:
            if not self.release.wait(4):
                raise TimeoutError("测试释放超时")
        finally:
            with self.changed:
                self.active -= 1

    def wait_entered(self, count: int) -> bool:
        """最多两秒等待指定数量的库调用入场。"""
        with self.changed:
            return self.changed.wait_for(lambda: self.entered >= count, timeout=2)

    @override
    def hash(self, password: str | bytes, *, salt: bytes | None = None) -> str:
        """用有界等待包住真实库哈希，保持标准签名和编码格式。"""
        self._enter()
        return super().hash(password, salt=salt)


def close_workers(pool: ThreadPoolExecutor, hasher: HeldHasher) -> None:
    """先释放所有被测库调用，再等待有上限的测试工作退出，防止资源污染。"""
    hasher.release.set()
    pool.shutdown(wait=True, cancel_futures=True)


# 业务时刻固定为 UTC，测试不依赖机器本地时区。


# 固定的 HTTP 领域调用来源；实际 HTTP 测试由请求编号中间件覆盖。
AUDIT_CONTEXT = AuditContext("127.0.0.1", "123e4567e89b42d3a456426614174000")
NOW = datetime(2026, 10, 25, 12, 30, 10, 123456, tzinfo=UTC)
EXAMPLE_SECRET = SecretStr("test-example-credential")


@contextmanager
def model_database(root: Path) -> Generator[Engine]:
    """只在调用者的 tmp_path 中建模型表，所有路径最终关闭引擎。"""
    engine = create_database_engine(root / "test.sqlite3")
    try:
        metadata.create_all(engine)
        yield engine
    finally:
        engine.dispose()


def model_row(name: str = "member", role: str = "member", **changes: Any) -> AccountRow:
    """提供有效基准行，变异输入由测试明确覆盖，不调用业务校验构造期望。"""
    values: dict[str, Any] = dict(
        login_name=name,
        display_name="示例账号",
        role=role,
        password_hash=PasswordHasher(time_cost=1, memory_cost=1024, parallelism=1).hash(
            EXAMPLE_SECRET.get_secret_value()
        ),
        created_at=NOW,
        updated_at=NOW,
        created_by_id=None,
        created_by_name="运维",
        updated_by_id=None,
        updated_by_name="运维",
    )
    return AccountRow(**(values | changes))


def account_view() -> AccountView:
    """提供独立的已知身份快照，便于验证值对象和响应转换。"""
    return AccountView(
        1,
        "admin",
        "显示名",
        Role.ADMINISTRATOR,
        AccountStatus.ENABLED,
        False,
        NOW,
        NOW,
        ActorRef(None, "运维"),
        ActorRef(None, "运维"),
    )


@contextmanager
def scenario(root: Path) -> Generator[tuple[AccountService, SessionGrant]]:
    """通过公开服务创建首号并登录，调用者只观察业务返回和明确要求的持久化边界。"""
    with model_database(root) as engine:
        service = AccountService(
            engine, PasswordCodec(PasswordHasher(time_cost=1, memory_cost=1024, parallelism=1))
        )
        service.create_first_admin(
            NewAccount(Credentials("admin", EXAMPLE_SECRET), "管理员", Role.ADMINISTRATOR),
            now=NOW,
            audit=OPS_AUDIT_CONTEXT,
        )
        yield (
            service,
            service.login(Credentials("admin", EXAMPLE_SECRET), now=NOW, audit=AUDIT_CONTEXT),
        )


def member_grant(
    service: AccountService,
    administrator: SessionGrant,
    *,
    name: str = "member",
    role: Role = Role.MEMBER,
) -> SessionGrant:
    """通过建号、登录、首次改密完成可使用的第二身份，避免测试绕开强制改密。"""
    from rdp.accounts.types import PasswordChange

    service.create_account(
        administrator.identity,
        NewAccount(Credentials(name, EXAMPLE_SECRET), "成员", role),
        now=NOW,
        audit=AUDIT_CONTEXT,
    )
    initial = service.login(Credentials(name, EXAMPLE_SECRET), now=NOW, audit=AUDIT_CONTEXT)
    return service.change_password(
        initial.identity,
        PasswordChange(EXAMPLE_SECRET, SecretStr("member-updated-value")),
        now=NOW,
        audit=AUDIT_CONTEXT,
    )


class CallbackHasher(PasswordHasher):
    """在真实库核验结束后触发另一连接的竞争操作，观察写事务是否重验快照。"""

    def __init__(self, callback: Callable[[], None]) -> None:
        """保存测试调度点，仍用真实的低成本 Argon2。"""
        super().__init__(time_cost=1, memory_cost=1024, parallelism=1)
        self.callback = callback

    @override
    def verify(self, hash: str | bytes, password: str | bytes) -> Literal[True]:
        """库返回正确结果后制造并发提交，不替换平台的事务或权限函数。"""
        result = super().verify(hash, password)
        self.callback()
        return result


@contextmanager
def fail_write_commit(engine: Engine) -> Generator[None]:
    """在驱动提交边界模拟 I/O 失败，只拦写工作单元并成对移除事件。"""

    def fail(connection: Connection) -> None:
        if not connection.get_execution_options().get("rdp_read_only"):
            error = sqlite3.OperationalError("测试提交 I/O 失败")
            error.sqlite_errorcode = sqlite3.SQLITE_IOERR
            raise error

    event.listen(engine, "commit", fail)
    try:
        yield
    finally:
        event.remove(engine, "commit", fail)


class HookHasher(PasswordHasher):
    """在真实库计算返回前提供调度点，便于另一连接提交并发状态变化。"""

    def __init__(self) -> None:
        """默认不触发钩子，避免构造编码器的假哈希参与业务调度。"""
        super().__init__(time_cost=1, memory_cost=1024, parallelism=1)
        self.on_hash: Callable[[], object] | None = None
        self.on_verify: Callable[[], object] | None = None

    @override
    def hash(self, password: str | bytes, *, salt: bytes | None = None) -> str:
        """库执行真实哈希后再触发测试同步点。"""
        result = super().hash(password, salt=salt)
        if self.on_hash is not None:
            self.on_hash()
        return result

    @override
    def verify(self, hash: str | bytes, password: str | bytes) -> Literal[True]:
        """库真实核验成功后触发另一连接，不替换领域状态检查。"""
        result = super().verify(hash, password)
        if self.on_verify is not None:
            self.on_verify()
        return result


@contextmanager
def account_operation(
    root: Path, operation: str
) -> Generator[tuple[AccountService, Callable[[], object]]]:
    """通过已批准公共服务准备六种哈希入口，不创建真实状态目录。"""
    with model_database(root) as engine:
        service = AccountService(
            engine, PasswordCodec(PasswordHasher(time_cost=1, memory_cost=1024, parallelism=1))
        )
        command = NewAccount(Credentials("admin", EXAMPLE_SECRET), "管理员", Role.ADMINISTRATOR)
        if operation == "create_first_admin":
            yield (
                service,
                lambda: service.create_first_admin(command, now=NOW, audit=OPS_AUDIT_CONTEXT),
            )
            return
        service.create_first_admin(command, now=NOW, audit=OPS_AUDIT_CONTEXT)
        grant = service.login(Credentials("admin", EXAMPLE_SECRET), now=NOW, audit=AUDIT_CONTEXT)
        operations: dict[str, Callable[[], object]] = {
            "login": lambda: service.login(
                Credentials("admin", EXAMPLE_SECRET), now=NOW, audit=AUDIT_CONTEXT
            ),
            "change_password": lambda: service.change_password(
                grant.identity,
                PasswordChange(EXAMPLE_SECRET, SecretStr("replacement-value")),
                now=NOW,
                audit=AUDIT_CONTEXT,
            ),
            "create_account": lambda: service.create_account(
                grant.identity,
                NewAccount(Credentials("member", EXAMPLE_SECRET), "成员", Role.MEMBER),
                now=NOW,
                audit=AUDIT_CONTEXT,
            ),
            "reset_password": lambda: service.reset_password(
                grant.identity, 1, SecretStr("replacement-value"), now=NOW, audit=AUDIT_CONTEXT
            ),
            "reset_password_from_ops": lambda: service.reset_password_from_ops(
                "admin", SecretStr("replacement-value"), now=NOW, audit=OPS_AUDIT_CONTEXT
            ),
        }
        yield service, operations[operation]


def persisted_account_state(
    engine: Engine,
) -> tuple[tuple[tuple[Any, ...], ...], tuple[tuple[Any, ...], ...]]:
    """观察契约承诺的提交边界；只在测试内比较前后持久化值，不格式化或记录秘密。"""
    with session_scope(engine, read_only=True) as session:
        accounts = tuple(
            tuple(row)
            for row in session.execute(select(AccountRow.__table__).order_by(AccountRow.account_id))
        )
        sessions = tuple(
            tuple(row)
            for row in session.execute(
                select(SessionRow.__table__).order_by(SessionRow.token_digest)
            )
        )
        return accounts, sessions
