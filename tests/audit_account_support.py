"""账号审计测试的公开服务场景；密码计算只替换外部Argon2成本，事务和日志均走真实实现。"""

from collections.abc import Callable, Generator
from contextlib import contextmanager
from pathlib import Path

from accounts_support import AUDIT_CONTEXT, EXAMPLE_SECRET, NOW, model_database
from argon2 import PasswordHasher
from pydantic import SecretStr

from rdp.accounts.security import PasswordCodec
from rdp.accounts.service import AccountService, existing_account_ids
from rdp.accounts.types import AccountStatus, Credentials, NewAccount, PasswordChange, Role
from rdp.audit.records import query_operations
from rdp.audit.types import OPS_AUDIT_CONTEXT, LogQuery, OperationQuery, OperationView
from rdp.infra.db.connection import session_scope


@contextmanager
def account_action(root: Path, case: str) -> Generator[tuple[AccountService, Callable[[], object]]]:
    """准备每种账号写操作，返回只执行目标动作的闭包；在yield前完成所有前置操作。"""
    root.mkdir(parents=True, exist_ok=True)
    with model_database(root) as engine:
        service = AccountService(
            engine, PasswordCodec(PasswordHasher(time_cost=1, memory_cost=1024, parallelism=1))
        )
        command = NewAccount(Credentials("admin", EXAMPLE_SECRET), "管理员", Role.ADMINISTRATOR)
        if case == "create_first_admin":
            yield (
                service,
                lambda: service.create_first_admin(command, now=NOW, audit=OPS_AUDIT_CONTEXT),
            )
            return
        service.create_first_admin(command, now=NOW, audit=OPS_AUDIT_CONTEXT)
        grant = service.login(Credentials("admin", EXAMPLE_SECRET), now=NOW, audit=AUDIT_CONTEXT)
        member = service.create_account(
            grant.identity,
            NewAccount(Credentials("member", EXAMPLE_SECRET), "成员", Role.MEMBER),
            now=NOW,
            audit=AUDIT_CONTEXT,
        )
        if case == "enable":
            service.set_status(
                grant.identity,
                member.account_id,
                AccountStatus.DISABLED,
                now=NOW,
                audit=AUDIT_CONTEXT,
            )
        actions: dict[str, Callable[[], object]] = {
            "set_retention": lambda: service.set_log_retention(
                grant.identity, 7, now=NOW, audit=AUDIT_CONTEXT
            ),
            "create_account": lambda: service.create_account(
                grant.identity,
                NewAccount(Credentials("other", EXAMPLE_SECRET), "另一成员", Role.MEMBER),
                now=NOW,
                audit=AUDIT_CONTEXT,
            ),
            "set_role": lambda: service.set_role(
                grant.identity, member.account_id, Role.ADMINISTRATOR, now=NOW, audit=AUDIT_CONTEXT
            ),
            "disable": lambda: service.set_status(
                grant.identity,
                member.account_id,
                AccountStatus.DISABLED,
                now=NOW,
                audit=AUDIT_CONTEXT,
            ),
            "enable": lambda: service.set_status(
                grant.identity,
                member.account_id,
                AccountStatus.ENABLED,
                now=NOW,
                audit=AUDIT_CONTEXT,
            ),
            "reset_password": lambda: service.reset_password(
                grant.identity,
                member.account_id,
                SecretStr("replacement-value"),
                now=NOW,
                audit=AUDIT_CONTEXT,
            ),
            "delete_account": lambda: service.delete_account(
                grant.identity, member.account_id, now=NOW, audit=AUDIT_CONTEXT
            ),
            "change_password": lambda: service.change_password(
                grant.identity,
                PasswordChange(EXAMPLE_SECRET, SecretStr("replacement-value")),
                now=NOW,
                audit=AUDIT_CONTEXT,
            ),
            "reset_password_from_ops": lambda: service.reset_password_from_ops(
                "member", SecretStr("replacement-value"), now=NOW, audit=OPS_AUDIT_CONTEXT
            ),
        }
        yield service, actions[case]


def operations(service: AccountService) -> tuple[OperationView, ...]:
    """通过日志公开查询读取全部少量样本，避免从内部日志实现取期望。"""
    with session_scope(service.engine, read_only=True) as session:
        return query_operations(session, OperationQuery(LogQuery()), existing_account_ids).items
