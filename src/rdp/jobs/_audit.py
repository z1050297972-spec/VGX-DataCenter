"""作业领域到操作日志的白名单适配；账号适配包含账号私有逻辑，作业只复用审计公共追加接口。"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING, cast

from sqlalchemy import Engine
from sqlalchemy.orm import Session

from rdp.audit._context import validate_context
from rdp.audit.policy import AUDIT_APPEND_FAILED
from rdp.audit.records import append_operation
from rdp.audit.service import append_failed_operation
from rdp.audit.types import (
    AuditValues,
    ObjectRef,
    OperationDetails,
    OperationEvent,
    OperationResult,
    OperationType,
)
from rdp.infra.actors import ActorRef
from rdp.infra.diagnostics import (
    ConflictError,
    DefectError,
    DiagnosticCategory,
    ExternalError,
    InputError,
)
from rdp.jobs import _storage
from rdp.jobs.types import JobRecord

if TYPE_CHECKING:
    from rdp.jobs.service import JobRequest


def validate_request(request: JobRequest) -> None:
    """时间和审计来源在任何业务读写前校验，不能在错误来源下先改变作业。"""
    from rdp.jobs.service import JobRequest

    if not isinstance(cast(object, request), JobRequest):
        raise DefectError()
    _storage.moment(request.now)
    validate_context(request.audit)


def values(record: JobRecord | None, *, submission: bool = False) -> AuditValues:
    """不读取parameters；重新提交来源只允许出现在提交明细。"""
    if record is None:
        return AuditValues()
    return AuditValues(
        job_id=str(record.job_id),
        job_type=record.type_name,
        job_state=record.state.value,
        resubmitted_from=str(record.resubmitted_from)
        if submission and record.resubmitted_from is not None
        else None,
    )


def event(
    request: JobRequest, actor: ActorRef, operation: OperationType, before: JobRecord | None
) -> OperationEvent:
    """开始执行前保留已确认的对象快照，未分配新编号用固定名字。"""
    return OperationEvent(
        request.now,
        actor,
        operation,
        target(before),
        OperationResult.SUCCESS,
        None,
        request.audit,
        OperationDetails(before=values(before), after=AuditValues()),
    )


def target(record: JobRecord | None) -> ObjectRef:
    """显示名上限40加19位编号不超过64，不截断身份或伪装账号对象。"""
    return (
        ObjectRef("job", None, "新作业")
        if record is None
        else ObjectRef("job", str(record.job_id), f"{record.display_name} #{record.job_id}")
    )


def finish(session: Session, before: OperationEvent, record: JobRecord) -> None:
    """新状态和成功日志使用调用方同一事务，提交之后才向入口返回。"""
    details = OperationDetails(
        before=before.details.before,
        after=values(record, submission=before.operation is OperationType.SUBMIT_JOB),
    )
    append_operation(session, replace(before, target=target(record), details=details))


def failed(engine: Engine, before: OperationEvent | None, error: Exception) -> None:
    """业务事务退出后才短锁补记；执行前的拒绝没有事件，不能误记失败操作。"""
    if before is None:
        return
    category = (
        error.category
        if isinstance(error, (InputError, ConflictError, ExternalError, DefectError))
        else DiagnosticCategory.DEFECT
    )
    failure = replace(
        before,
        result=OperationResult.FAILURE,
        failure_category=category,
        details=OperationDetails(before=before.details.before, after=AuditValues()),
    )
    try:
        append_failed_operation(engine, failure)
    except Exception:
        error.add_note(AUDIT_APPEND_FAILED)
