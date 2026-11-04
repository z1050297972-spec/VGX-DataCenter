"""调度页只读服务（领域层，09）；只查询数据库与入口注入的静态配置，不访问 worker 资源池。"""

from datetime import datetime, timedelta
from typing import cast

from pydantic import TypeAdapter, ValidationError
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from rdp.accounts.service import authorize_job_actor
from rdp.infra.db.connection import session_scope
from rdp.infra.db.validation import invalid_field
from rdp.infra.diagnostics import (
    DIAGNOSTIC_SAMPLE_LIMIT,
    DefectError,
    Diagnostic,
    DiagnosticCategory,
    DiagnosticLevel,
)
from rdp.jobs import _audit, _storage
from rdp.jobs.models import JobRow, WorkerHeartbeatRow
from rdp.jobs.policy import SCHEDULE_LOOKAHEAD_DAYS
from rdp.jobs.records import find_job
from rdp.jobs.schedule_records import latest_submission, submission_dates
from rdp.jobs.schedules import next_run_at
from rdp.jobs.scheduling_models import WorkerGpuCheckRow
from rdp.jobs.scheduling_types import (
    GpuAvailability,
    GpuUsage,
    ScheduleView,
    SchedulingCatalog,
    SchedulingSnapshot,
    TypeUsage,
)
from rdp.jobs.service import JobRequest
from rdp.jobs.types import JobState, WorkerHeartbeat


class SchedulingService:
    """任意登录账号可读的调度聚合，不持有跨请求 Session。"""

    def __init__(self, engine: Engine, catalog: SchedulingCatalog) -> None:
        """绑定调度页面的数据库及入口配置。

        Args:
            engine: 已迁移受管引擎，生命周期归 Web 入口。
            catalog: 已验证的上限、GPU 列表、定时规则和本地时区；Web 不自行寻找配置。

        Returns:
            无；不立即建立数据库连接。

        Raises:
            DefectError: 非受管引擎或配置类型/登记不一致。

        Side Effects:
            仅保存只读依赖；不创建资源池、锁、执行线程或外部进程。

        Time Semantics:
            启动时构造，配置变更重启生效；请求时刻由 snapshot 的 request 注入。
        """
        if (
            not isinstance(cast(object, engine), Engine)
            or not engine.get_execution_options().get("rdp_managed")
            or not isinstance(cast(object, catalog), SchedulingCatalog)
        ):
            raise DefectError()
        self.engine, self.catalog = engine, catalog

    def snapshot(self, request: JobRequest) -> SchedulingSnapshot:
        """读取同一数据库快照下的类型容量、GPU、写锁和每日计划。

        Args:
            request: 任意账号身份、唯一 aware 请求时刻和审计来源；事务内重验会话及强制改密。

        Returns:
            按类型键、卡号、规则名分别排序的快照，空登记/无卡/无历史分别为空集合或 None。
            类型数量用 running/cancelling 聚合，包括尚在恢复的记录；终态历史卡号不计占用。
            GPU 可用/移出池状态、核对诊断及持锁者全部由 worker 保存的数据库副本决定，心跳离线时仍保留最后观察并明确 worker_online=False。
            上次结果直接读 JobRecord，不自行从诊断样例计算；下次时刻用本机时区，返回 UTC。
            每日计划的用途说明取自当前登记规则，不依赖历史作业是否存在。

        Raises:
            AuthenticationError: 会话过期、撤销、账号停用或删除。
            PasswordChangeRequiredError: 账号需要先改密码。
            InputError: 数据库或存量去重/作业记录损坏。
            ConflictError: 只读快照锁竞争。
            ExternalError: 数据库查询或清理 I/O 失败，不伪装空闲资源。
            DefectError: 多个有效持锁者、同卡多个活跃占用、非法时钟或查询映射错误。

        Side Effects:
            无；只读作业、心跳及定时表，身份重验沿用 authorize_job_actor。
            聚合不加载全部队列；每规则只读最近行和有界未来日期窗，不查看日志文件、GPU 或 worker 内存；从 worker_gpu_checks 读卡的核对结果，
            按 instance_id 与当前心跳关联，不把旧实例结果冒充新实例；未匹配为 UNKNOWN。
            配置已移除的 GPU 不列为可用卡；已移除类型不列入当前类型容量，历史仍可在作业列表查询。

        Time Semantics:
            一个普通只读事务，锁最多 BUSY_TIMEOUT_MS；checked_at 用请求时刻，日历计算不另读系统时间。
            展示允许短锁跳过造成暂时落后；不以 UTC 墙钟回拨修改数据库历史。
        """
        _audit.validate_request(request)
        now = _storage.moment(request.now)
        with session_scope(self.engine, read_only=True) as session:
            authorize_job_actor(session, request.identity, now=now)
            active = JobRow.state.in_((JobState.RUNNING.value, JobState.CANCELLING.value))
            counts = {
                name: count
                for name, count in session.execute(
                    select(JobRow.type_name, func.count()).where(active).group_by(JobRow.type_name)
                )
            }
            holders = list(
                session.scalars(
                    select(JobRow.job_id).where(JobRow.holds_navigation_lock.is_(True)).limit(2)
                )
            )
            if len(holders) > 1:
                raise DefectError()
            owners: dict[int, int] = {}
            for index, number, count in session.execute(
                select(JobRow.gpu_index, func.min(JobRow.job_id), func.count())
                .where(active, JobRow.gpu_index.is_not(None))
                .group_by(JobRow.gpu_index)
            ):
                if count > 1 or index is None:
                    raise DefectError()
                owners[index] = number
            row = session.get(WorkerHeartbeatRow, 1)
            heartbeat = (
                None
                if row is None
                else _storage.heartbeat(
                    WorkerHeartbeat(row.instance_id, row.pid, row.started_at, row.last_seen_at)
                )
            )
            return SchedulingSnapshot(
                tuple(
                    TypeUsage(capacity, counts.get(capacity.type_name, 0))
                    for capacity in self.catalog.settings.types
                ),
                self._gpus(session, heartbeat, owners),
                holders[0] if holders else None,
                self._schedules(session, now),
                now,
                _storage.heartbeat_is_online(heartbeat, now),
            )

    def _schedules(self, session: Session, now: datetime) -> tuple[ScheduleView, ...]:
        """每条计划只读最近行和有界日期集；状态与摘要取自同一个数据库快照。"""
        try:
            today = now.astimezone(self.catalog.timezone).date()
            end = today + timedelta(days=SCHEDULE_LOOKAHEAD_DAYS)
        except (ValueError, OverflowError) as error:
            raise DefectError() from error
        views: list[ScheduleView] = []
        for definition in self.catalog.schedules.definitions():
            previous = latest_submission(session, definition.name)
            dates = submission_dates(session, definition.name, today, end)
            record = None if previous is None else find_job(session, previous.job_id)
            views.append(
                ScheduleView(
                    definition.name,
                    definition.description,
                    next_run_at(definition, dates, now=now, zone=self.catalog.timezone),
                    previous,
                    None if record is None else record.state,
                    None if record is None or record.summary is None else record.summary.outcome,
                )
            )
        return tuple(views)

    def _gpus(
        self, session: Session, heartbeat: WorkerHeartbeat | None, owners: dict[int, int]
    ) -> tuple[GpuUsage, ...]:
        """核对记录只与当前心跳实例关联；配置外卡不展示，损坏副本不能伪装健康。"""
        checks = (
            {}
            if heartbeat is None
            else {
                row.gpu_index: row
                for row in session.scalars(
                    select(WorkerGpuCheckRow).where(
                        WorkerGpuCheckRow.instance_id == heartbeat.instance_id,
                        WorkerGpuCheckRow.gpu_index.in_(self.catalog.settings.gpus),
                    )
                )
            }
        )
        views: list[GpuUsage] = []
        for index in self.catalog.settings.gpus:
            row = checks.get(index)
            if row is None:
                views.append(GpuUsage(index, owners.get(index), GpuAvailability.UNKNOWN, (), None))
                continue
            try:
                diagnostics = TypeAdapter(tuple[Diagnostic, ...]).validate_python(row.diagnostics)
            except ValidationError:
                raise invalid_field("gpu_checks", "合法的核卡诊断") from None
            if (
                row.available == bool(diagnostics)
                or len(diagnostics) > DIAGNOSTIC_SAMPLE_LIMIT
                or any(
                    item.category is not DiagnosticCategory.EXTERNAL
                    or item.level is not DiagnosticLevel.ERROR
                    for item in diagnostics
                )
            ):
                raise invalid_field("gpu_checks", "可用性与诊断一致的核对记录")
            views.append(
                GpuUsage(
                    index,
                    owners.get(index) if row.available else None,
                    GpuAvailability.AVAILABLE if row.available else GpuAvailability.EXCLUDED,
                    diagnostics,
                    row.checked_at,
                )
            )
        return tuple(views)
