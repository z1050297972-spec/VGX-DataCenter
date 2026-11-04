"""账号领域到日志领域的白名单适配；不读取请求或记录秘密，不拥有业务写事务。"""

from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import datetime

from sqlalchemy import Engine
from sqlalchemy.orm import Session

from rdp.accounts import _records as records
from rdp.accounts.errors import (
    AccountInputError,
    AuthenticationError,
    AuthorizationError,
    PasswordChangeRequiredError,
)
from rdp.accounts.models import AccountRow
from rdp.accounts.types import ActorRef
from rdp.audit.policy import AUDIT_APPEND_FAILED
from rdp.audit.records import append_operation
from rdp.audit.service import append_failed_operation
from rdp.audit.types import (
    OPERATION_DETAIL_FIELDS,
    AuditContext,
    AuditValues,
    ObjectRef,
    OperationDetails,
    OperationEvent,
    OperationResult,
    OperationType,
)
from rdp.infra.diagnostics import (
    ConflictError,
    DefectError,
    DiagnosticCategory,
    ExternalError,
    InputError,
)


def actor(row: AccountRow) -> ActorRef:
    """仅复制已校验账号的编号及显示名，不能把ORM或秘密当成审计上下文。"""
    view = records.view(row)
    return ActorRef(view.account_id, view.display_name)


def values(kind: OperationType, row: AccountRow | None) -> AuditValues:
    """按操作码提取唯一白名单，创建前和删除后为空对象。"""
    if row is None:
        return AuditValues()
    view = records.view(row)
    fields: dict[str, object] = {
        "login_name": view.login_name,
        "display_name": view.display_name,
        "role": view.role.value,
        "status": view.status.value,
        "must_change_password": view.must_change_password,
    }
    return AuditValues.model_validate({key: fields[key] for key in OPERATION_DETAIL_FIELDS[kind]})


def make_event(
    kind: OperationType, by: ActorRef, row: AccountRow | None, audit: AuditContext, now: datetime
) -> OperationEvent:
    """在变更前保存不可变事件模板；失败新建始终没有对象编号。"""
    target = (
        ObjectRef("account", None, "新账号")
        if row is None
        else ObjectRef("account", str(row.account_id), row.display_name)
    )
    return OperationEvent(
        now,
        by,
        kind,
        target,
        OperationResult.SUCCESS,
        None,
        audit,
        OperationDetails(before=values(kind, row), after=AuditValues()),
    )


def finish(session: Session, event: OperationEvent, row: AccountRow | None) -> None:
    """在业务事务中追加成功结果，新增对象在flush取得编号之后才写成功快照。"""
    target = (
        event.target if row is None else ObjectRef("account", str(row.account_id), row.display_name)
    )
    details = OperationDetails(before=event.details.before, after=values(event.operation, row))
    append_operation(session, replace(event, target=target, details=details))


@dataclass
class Attempt:
    """业务执行期间只保留安全日志快照，不保存命令或凭据。

    Attributes:
        event: 已确认的对象及操作人快照，不可空；保留期读到旧值后可替换。
        started: 是否越过方法声明的执行边界，默认False；获锁失败不能冒充已执行。
    """

    event: OperationEvent
    started: bool = False


@contextmanager
def attempt(engine: Engine, event: OperationEvent, *, started: bool = False) -> Generator[Attempt]:
    """包在业务事务之外，只有事务关闭后才补记失败；身份/权限/字段拒绝永不记操作日志。"""
    state = Attempt(event, started)
    try:
        yield state
    except Exception as error:
        excluded = isinstance(
            error,
            (
                AuthenticationError,
                AuthorizationError,
                PasswordChangeRequiredError,
                AccountInputError,
            ),
        )
        if state.started and not excluded:
            category = (
                error.category
                if isinstance(error, (InputError, ConflictError, ExternalError, DefectError))
                else DiagnosticCategory.DEFECT
            )
            failed = replace(
                state.event,
                result=OperationResult.FAILURE,
                failure_category=category,
                details=OperationDetails(before=state.event.details.before, after=AuditValues()),
            )
            try:
                append_failed_operation(engine, failed)
            except Exception:
                error.add_note(AUDIT_APPEND_FAILED)
        raise


def rejected(session: Session, event: OperationEvent, failure: InputError) -> None:
    """旧密码验证失败与G2共用当前写事务，不在计数提交之后再另开事务。"""
    append_operation(
        session,
        replace(
            event,
            result=OperationResult.FAILURE,
            failure_category=failure.category,
            details=OperationDetails(before=event.details.before, after=AuditValues()),
        ),
    )
