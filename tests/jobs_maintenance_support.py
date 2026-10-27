"""清除作业测试样本；通过公开追加入口建立独立时间边界，不访问真实日志目录。"""

from collections.abc import Sequence
from dataclasses import replace
from datetime import datetime

from accounts_support import AUDIT_CONTEXT
from audit_support import operation_event
from jobs_schedules_support import ScheduleCase
from sqlalchemy import Engine

from rdp.audit.records import append_login, append_operation
from rdp.audit.types import LoginEvent, LoginKind, LoginResult
from rdp.infra.actors import ActorRef
from rdp.infra.db.connection import session_scope
from rdp.infra.db.records import ErrorRecord, write_error
from rdp.infra.diagnostics import DiagnosticCategory
from rdp.jobs.execution import ExecutionWork
from rdp.jobs.progress import ExecutionSignals


def seed_errors(engine: Engine, moments: Sequence[datetime]) -> None:
    """每个时刻一条独立作业报错；编号由测试给定顺序产生，不依赖清除实现。"""
    with session_scope(engine) as session:
        for number, moment in enumerate(moments, 1):
            write_error(
                session,
                ErrorRecord(
                    error_id=str(number),
                    occurred_at=moment,
                    category=DiagnosticCategory.DEFECT,
                    summary="测试报错",
                    report="测试异常报告",
                    source_kind="job",
                ),
            )


def seed_audit(engine: Engine, operations: Sequence[datetime], logins: Sequence[datetime]) -> None:
    """两类日志独立计数，使用真实追加与统一身份校验。"""
    with session_scope(engine) as session:
        for moment in operations:
            append_operation(session, replace(operation_event(), occurred_at=moment))
        for moment in logins:
            append_login(
                session,
                LoginEvent(
                    moment,
                    ActorRef(7, "成员甲"),
                    "member",
                    LoginKind.LOGIN,
                    LoginResult.SUCCESS,
                    AUDIT_CONTEXT,
                ),
            )


def maintenance_work(case: ScheduleCase, type_name: str) -> tuple[ExecutionWork, ExecutionSignals]:
    """提交系统清除作业并由真实调度器领取，提供相互独立的停止信号。"""
    from threading import Event, Lock

    from rdp.jobs.progress import ExecutionMonitor
    from rdp.jobs.scheduling_types import ScheduledJob

    submission = case.service.submit_scheduled(
        ScheduledJob(type_name, type_name, {}), case.clock.wall.date(), now=case.clock.wall
    )
    assert submission is not None
    work = case.scheduler.claim_next()
    assert work is not None and work.record.job_id == submission.job_id
    return work, ExecutionSignals(Event(), Event(), ExecutionMonitor([], None, Lock()))
