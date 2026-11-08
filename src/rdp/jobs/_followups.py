"""转换流水线的原子后继提交；只在作业唯一终态事务里追加队列和审计。

复用已有作业表和审计，不另建去重表；事务回滚连同前驱终态回滚，重启不会漏提或重复提交。
"""

from datetime import datetime

from sqlalchemy.orm import Session

from rdp.audit.types import (
    AuditContext,
    AuditValues,
    OperationDetails,
    OperationEvent,
    OperationResult,
    OperationType,
)
from rdp.infra.actors import SYSTEM_ACTOR
from rdp.jobs import _audit
from rdp.jobs.conversion.ingest_models import APPLY_TYPE, CHECK_TYPE
from rdp.jobs.outcome import JobOutcome
from rdp.jobs.records import NewJob, insert_job
from rdp.jobs.registry import JobRegistry
from rdp.jobs.types import JobRecord, JobState


def submit_followup(
    session: Session, registry: JobRegistry, record: JobRecord, now: datetime
) -> None:
    """转换成功提交检查，检查明确自动就绪后提交确认，其他终态不产生后继。"""
    if (
        record.state is not JobState.COMPLETED
        or record.summary is None
        or record.summary.outcome not in (JobOutcome.SUCCEEDED, JobOutcome.SUCCEEDED_WITH_WARNINGS)
    ):
        return
    if record.type_name.startswith("convert_"):
        name = CHECK_TYPE
        parameters: dict[str, object] = {"conversion_job_id": record.job_id, "automatic": True}
    elif (
        record.type_name == CHECK_TYPE
        and record.progress is not None
        and record.progress.ingest_check is not None
        and record.progress.ingest_check.automatic_ready
    ):
        name = APPLY_TYPE
        parameters = {"preview_job_id": record.job_id}
    else:
        return
    definition = registry.lookup(name)
    if definition is None:
        return
    checked = definition.parameters_model.model_validate(parameters).model_dump(mode="json")
    event = OperationEvent(
        now,
        SYSTEM_ACTOR,
        OperationType.SUBMIT_JOB,
        _audit.target(None),
        OperationResult.SUCCESS,
        None,
        AuditContext(None, None),
        OperationDetails(before=AuditValues(), after=AuditValues()),
    )
    followup = insert_job(session, NewJob(definition, checked, SYSTEM_ACTOR, now, None))
    _audit.finish(session, event, followup)
