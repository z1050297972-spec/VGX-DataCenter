"""作业提交、取消、重提与查询服务（08）；Web 只访问数据库和受限日志尾，不执行作业。

依赖accounts只使用service.authorize_job_actor、existing_account_ids及公开types/models；不导入下划线模块，复用第6张鉴权规则，
不缓存角色。依赖 audit 使写操作与操作日志原子提交；执行前拒绝不记日志，执行后失败
回滚再按第 7 张短事务补记，补记失败附固定标记交 API 边界报告，不在本层打日志。
"""

from dataclasses import dataclass, replace
from datetime import date, datetime
from typing import cast

from sqlalchemy import Engine, select

from rdp.accounts.service import authorize_job_actor, existing_account_ids
from rdp.accounts.types import SessionIdentity
from rdp.audit.types import (
    AuditContext,
    AuditValues,
    OperationDetails,
    OperationEvent,
    OperationResult,
    OperationType,
)
from rdp.infra.actors import SYSTEM_ACTOR, is_display_name
from rdp.infra.db.connection import session_scope, session_scope_with_lock_timeout
from rdp.infra.diagnostics import ConflictError, DefectError, DiagnosticCategory
from rdp.jobs import _audit, _pagination, _storage, _views, policy
from rdp.jobs._parameters import validate as validate_parameters
from rdp.jobs.models import JobRow, WorkerHeartbeatRow
from rdp.jobs.records import NewJob, StateChange, find_job, insert_job, transition_job
from rdp.jobs.registry import JobDefinition, JobRegistry
from rdp.jobs.schedule_records import insert_submission
from rdp.jobs.scheduling_models import ScheduleSubmissionRow
from rdp.jobs.scheduling_types import ScheduledJob, ScheduleSubmission
from rdp.jobs.types import JobPage, JobQuery, JobRecord, JobState, WorkerHeartbeat


@dataclass(frozen=True)
class JobRequest:
    """入口必须显式提供的身份和审计上下文，不接受前端声明操作者。

    Attributes:
        identity: 已认证 SessionIdentity；服务在业务事务中重新核验会话、启停和强制改密。
        now: 本请求唯一 aware 时刻，转换 UTC 微秒；非法注入值为 DefectError。
        audit: ASGI 来源及服务器请求编号，必填；无 client 的 IP 可空，request_id 不可空。
    """

    identity: SessionIdentity
    now: datetime
    audit: AuditContext


class JobService:
    """短事务领域服务，不持有 Session、线程或可变请求状态。"""

    def __init__(self, engine: Engine, registry: JobRegistry) -> None:
        """绑定受管数据库与入口私有的类型登记表。

        Args:
            engine: 已迁移到 0004 的受管 SQLite Engine，生命周期归入口。
            registry: 启动时已登记完成的 JobRegistry，Web 和 worker 各自构造。

        Returns:
            无；保存依赖，不连接数据库。

        Raises:
            DefectError: 非受管引擎、非 JobRegistry 或不可用依赖。

        Side Effects:
            无；不迁移、不创建状态目录、不执行示例作业。

        Time Semantics:
            构造无等待；调用方法各开自己的短事务，不跨请求共享会话。
        """
        if (
            not isinstance(cast(object, engine), Engine)
            or not engine.get_execution_options().get("rdp_managed")
            or not isinstance(cast(object, registry), JobRegistry)
        ):
            raise DefectError()
        self.engine, self.registry = engine, registry

    def submit(
        self, request: JobRequest, type_name: str, parameters: dict[str, object]
    ) -> JobRecord:
        """任何登录账号提交一个经类型模型校验的作业。

        Args:
            request: 必填身份、唯一请求时刻和审计来源；不要求管理员。
            type_name: 当前登记的稳定英文键。
            parameters: 不可信 JSON 对象，至多 JOB_PARAMETERS_MAX_BYTES，按当前模型严格校验。

        Returns:
            已提交的 queued 记录，提交人为事务内当前账号；有编号且名字为“系统”的账号照常提交，按编号区别固定系统身份。
            参数保留模型的 JSON 值和默认值。

        Raises:
            AuthenticationError: 事务内会话已撤销/过期或账号停用、删除。
            PasswordChangeRequiredError: 当前账号必须先改口令。
            JobInputError: 未登记类型、非法参数、额外字段或编码后超长；不回显原值。
            InputError: 数据库损坏。
            ConflictError: 写锁、约束或作业编号耗尽。
            ExternalError: 作业或审计写入/提交/清理失败。
            DefectError: 注入时刻/审计上下文、类型定义、SQL 或序列化错误。

        Side Effects:
            事务外先校验参数，写事务内重验身份；insert_job 与提交作业操作日志同事务提交。
            对象 kind=job，object_id 为编号文本，object_name 为“显示名 #编号”（最多 61 码点）。
            明细 v1 仅含 job_id、job_type、job_state；before 为空，after 为已提交值，无参数。
            校验或权限拒绝不记日志；开始写入后失败整体回滚，短锁补记失败日志，补记失败不覆盖原错误。

        Time Semantics:
            request.now 用于作业及审计，UTC 微秒；BUSY_TIMEOUT_MS 普通锁预算，补记最多
            AUDIT_SHORT_LOCK_TIMEOUT_MS，无重试，外部计算不放在写事务。
        """
        _audit.validate_request(request)
        definition, checked = _parameters(self.registry, type_name, parameters)
        attempted: OperationEvent | None = None
        try:
            with session_scope(self.engine) as session:
                actor = authorize_job_actor(session, request.identity, now=request.now)
                attempted = _audit.event(request, actor, OperationType.SUBMIT_JOB, None)
                record = insert_job(session, NewJob(definition, checked, actor, request.now, None))
                _audit.finish(session, attempted, record)
            return record
        except Exception as error:
            _audit.failed(self.engine, attempted, error)
            raise

    def submit_scheduled(
        self, definition: ScheduledJob, local_date: date, *, now: datetime
    ) -> ScheduleSubmission | None:
        """以固定系统身份原子提交每日作业、审计及日期去重行。

        Args:
            definition: 已在入口显式登记并校验的规则，类型和参数仍按当前 JobRegistry 重验。
            local_date: schedule_due 返回的本机本地日期，不能由 HTTP 客户端指定。
            now: 注入 aware UTC 时刻；作业、日志和去重行共用，不能隐式读钟。

        Returns:
            本次成功提交的 ScheduleSubmission；同一规则/日期已经提交返回 None，不新增作业或日志。

        Raises:
            JobInputError: 当前类型已删除或参数不再合格，不回显原参数。
            ConflictError: 短锁入场或入场后提交失败；日期唯一竞争单独识别并返回 None。
            InputError: 数据库或历史去重记录损坏。
            ExternalError: 作业/去重/日志插入或提交失败，整体回滚。
            DefectError: 规则、日期、注入时刻或内部系统身份不合法。

        Side Effects:
            事务外复用账号提交的类型/参数校验；事务内使用 insert_job 与相同操作日志适配，
            提交人为 SYSTEM_ACTOR，不伪造 SessionIdentity，不绕过公开 HTTP 的全局鉴权。
            AuditContext 为服务端明确的无请求编号/无 IP 系统来源；同一事务插入唯一日期记录。
            任一步失败回滚三者；真正开始执行后的失败沿用短锁失败审计补记，重复日期不记失败。
            HTTP 不暴露本入口；账号重新提交系统作业仍由 resubmit 写点按钮的当前账号。

        Time Semantics:
            BEGIN 最多 PROGRESS_LOCK_TIMEOUT_MS，忙由调度器下一轮重试；不在本函数内部睡眠。
            日期去重覆盖 worker 重启和墙钟回拨，不按执行完成时刻计算 24 小时补跑。
        """
        if (
            not isinstance(cast(object, definition), ScheduledJob)
            or not is_display_name(definition.name)
            or type(local_date) is not date
        ):
            raise DefectError()
        now = _storage.moment(now)
        job, parameters = _parameters(self.registry, definition.type_name, definition.parameters)
        attempted: OperationEvent | None = None
        try:
            with session_scope_with_lock_timeout(
                self.engine, busy_timeout_ms=policy.PROGRESS_LOCK_TIMEOUT_MS
            ) as session:
                if session.get(ScheduleSubmissionRow, (definition.name, local_date)) is not None:
                    return None
                attempted = OperationEvent(
                    now,
                    SYSTEM_ACTOR,
                    OperationType.SUBMIT_JOB,
                    _audit.target(None),
                    OperationResult.SUCCESS,
                    None,
                    AuditContext(None, None),
                    OperationDetails(before=AuditValues(), after=AuditValues()),
                )
                record = insert_job(session, NewJob(job, parameters, SYSTEM_ACTOR, now, None))
                _audit.finish(session, attempted, record)
                submission = ScheduleSubmission(definition.name, local_date, record.job_id, now)
                insert_submission(session, submission)
            return submission
        except Exception as error:
            _audit.failed(self.engine, attempted, error)
            raise

    def submit_system(
        self, type_name: str, parameters: dict[str, object], *, now: datetime
    ) -> JobRecord:
        """以固定系统身份提交非每日的内部作业，并原子记录提交审计。

        Args:
            type_name: 当前登记的稳定类型键，调用方必须是worker内部触发器，不暴露HTTP。
            parameters: 类型模型校验的无秘密JSON对象，遵循JOB_PARAMETERS_MAX_BYTES。
            now: 必填注入aware时刻，作业及操作日志共用同一UTC时刻。

        Returns:
            已提交queued记录，提交人固定SYSTEM_ACTOR（空账号编号、名字“系统”）。
            本方法每次成功调用创建一项；启动和间隔去重由当前worker触发器负责。

        Raises:
            JobInputError: 未登记类型、参数非法或编码超长，不回显载荷。
            InputError: 数据库损坏。
            ConflictError: PROGRESS_LOCK_TIMEOUT_MS短锁入场超时或约束竞争。
            ExternalError: 作业/审计写入或提交失败，二者整体回滚。
            DefectError: 注入时刻、定义或内部系统身份非法。

        Side Effects:
            事务外复用参数校验；事务内insert_job和既有提交操作日志一并提交。
            AuditContext明确为无请求编号/无IP；不伪造账号会话、不写每日日期去重行。
            执行写入后失败沿用短锁失败审计补记，失败补记不能掩盖原异常；不启动作业线程。

        Time Semantics:
            每次调用只尝试一次短事务，不等待下次触发点；锁忙交worker下一轮重试。
            不改变submit_scheduled的每日唯一及补跑契约。
        """
        now = _storage.moment(now)
        definition, checked = _parameters(self.registry, type_name, parameters)
        attempted: OperationEvent | None = None
        try:
            with session_scope_with_lock_timeout(
                self.engine, busy_timeout_ms=policy.PROGRESS_LOCK_TIMEOUT_MS
            ) as session:
                attempted = OperationEvent(
                    now,
                    SYSTEM_ACTOR,
                    OperationType.SUBMIT_JOB,
                    _audit.target(None),
                    OperationResult.SUCCESS,
                    None,
                    AuditContext(None, None),
                    OperationDetails(before=AuditValues(), after=AuditValues()),
                )
                record = insert_job(session, NewJob(definition, checked, SYSTEM_ACTOR, now, None))
                _audit.finish(session, attempted, record)
            return record
        except Exception as error:
            _audit.failed(self.engine, attempted, error)
            raise

    def cancel(self, request: JobRequest, job_id: int) -> JobRecord:
        """请求取消任意账号提交的作业，取消身份记为当前账号。

        Args:
            request: 当前已登录且完成改密的身份与审计上下文，不按提交人限制。
            job_id: 严格正整数，最大 2^63-1。

        Returns:
            queued→cancelled 或 running→cancelling 的已提交记录；后者表示请求已登记，未承诺工具已退出。

        Raises:
            AuthenticationError: 事务内重验时身份失效。
            PasswordChangeRequiredError: 当前账号必须先改口令。
            JobInputError: 编号格式/范围非法。
            JobNotFoundError: 原作业不存在。
            ConflictError: 已是 cancelling 或终态、条件 UPDATE 竞争失败，或写锁冲突。
            InputError: 数据库损坏。
            ExternalError: 状态/审计写入、提交或清理 I/O 失败。
            DefectError: 上下文非法、状态机或映射错误。

        Side Effects:
            先取得BEGIN IMMEDIATE写锁，再重验身份并读当前作业状态，transition_job仍使用WHERE state=:expected；
            worker先领取提交时本次读到running，成功转cancelling并记录当前账号取消，不能用事务外旧queued返回冲突。
            取消先提交时 worker 的 queued→running 失败且不执行。合法取消与操作日志原子提交，
            明细 before/after 带 job_id/job_type/job_state，对象为 job，不删除任何产物。
            已取消/正在取消/已完成/已中断及竞争败方均在执行前拒绝，不补记失败日志；
            真正开始更新后的存储失败按第 7 张补记，after 为空。

        Time Semantics:
            用请求 UTC 时刻；排队取消当次完成，运行中由主循环最多约一秒发现并在阶段边界停止。
            普通事务锁预算 BUSY_TIMEOUT_MS；补记 AUDIT_SHORT_LOCK_TIMEOUT_MS，无自动重试。
        """
        _audit.validate_request(request)
        _storage.identifier(job_id)
        attempted: OperationEvent | None = None
        try:
            with session_scope(self.engine) as session:
                actor = authorize_job_actor(session, request.identity, now=request.now)
                current = find_job(session, job_id)
                if current.state not in {JobState.QUEUED, JobState.RUNNING}:
                    raise ConflictError(
                        (
                            _storage.diagnostic(
                                job_id, "当前状态不允许取消", DiagnosticCategory.CONFLICT
                            ),
                        )
                    )
                attempted = _audit.event(request, actor, OperationType.CANCEL_JOB, current)
                target = (
                    JobState.CANCELLED if current.state is JobState.QUEUED else JobState.CANCELLING
                )
                record = transition_job(
                    session, job_id, StateChange(current.state, target, request.now)
                )
                _audit.finish(session, attempted, record)
            return record
        except Exception as error:
            _audit.failed(self.engine, attempted, error)
            raise

    def resubmit(self, request: JobRequest, job_id: int) -> JobRecord:
        """从终态作业复制参数，作为当前账号的新提交。

        Args:
            request: 点重新提交按钮的账号上下文，不要求原提交人或管理员。
            job_id: 原作业正编号，必须为 completed/cancelled/interrupted。

        Returns:
            新 queued 记录，新编号及提交时间，resubmitted_from 指向原记录；旧记录不变。

        Raises:
            AuthenticationError: 重验时会话或账号无效。
            PasswordChangeRequiredError: 账号须先改口令。
            JobNotFoundError: 原记录不存在。
            JobInputError: 编号非法、原类型已移除或原参数按当前模型无效；不回显原参数。
            ConflictError: 原记录非终态、写锁/约束冲突。
            InputError: 存量 JSON 或数据库损坏。
            ExternalError: 新记录/审计事务失败。
            DefectError: 时钟、上下文或映射错误。

        Side Effects:
            当前模型只验证兼容性，不向原参数补默认值或改写原值；成功复制原 JSON 新增一行。
            操作类型仍为提交作业，明细 after 加 resubmitted_from，页面显示“重新提交自 #N”。
            参数不入审计；权限、参数、非终态拒绝不记日志；执行失败回滚并按提交规则补记。

        Time Semantics:
            request.now 为新提交时间，旧开始/结束时间不复制；写锁最多 BUSY_TIMEOUT_MS，
            补记短锁，不调用 worker 或等待原作业。
        """
        _audit.validate_request(request)
        _storage.identifier(job_id)
        attempted: OperationEvent | None = None
        try:
            with session_scope(self.engine) as session:
                actor = authorize_job_actor(session, request.identity, now=request.now)
                original = find_job(session, job_id)
                if original.state not in {
                    JobState.COMPLETED,
                    JobState.CANCELLED,
                    JobState.INTERRUPTED,
                }:
                    raise ConflictError(
                        (
                            _storage.diagnostic(
                                job_id, "只有终态作业可以重新提交", DiagnosticCategory.CONFLICT
                            ),
                        )
                    )
                definition, _ = _parameters(self.registry, original.type_name, original.parameters)
                attempted = _audit.event(request, actor, OperationType.SUBMIT_JOB, None)
                record = insert_job(
                    session, NewJob(definition, original.parameters, actor, request.now, job_id)
                )
                _audit.finish(session, attempted, record)
            return record
        except Exception as error:
            _audit.failed(self.engine, attempted, error)
            raise

    def get(self, request: JobRequest, job_id: int) -> JobRecord:
        """向任意登录账号返回作业详情及提交人当前删除标记。

        Args:
            request: 身份及 UTC 请求时刻，只读事务仍重验会话和强制改密。
            job_id: 正整数作业编号。

        Returns:
            完整永久记录；账号已删除时保留历史名字并设置 submitter_deleted=True。
            SYSTEM_ACTOR 的编号为 None、名字“系统”、submitter_deleted=False，不查同名账号。

        Raises:
            AuthenticationError: 会话或账号失效。
            PasswordChangeRequiredError: 尚未完成强制改密。
            JobInputError: 编号非法。
            JobNotFoundError: 指定作业不存在。
            InputError: 持久化 JSON/数据库损坏。
            ConflictError: 读取锁冲突。
            ExternalError: 读取或清理失败。
            DefectError: 时钟/存量状态不一致或查询程序错误。

        Side Effects:
            无；同一只读快照查询作业及账号是否存在，不读取整份日志或修改历史名字。

        Time Semantics:
            请求时刻只用于身份核验，数据库时刻保留 UTC 微秒；读锁沿用 BUSY_TIMEOUT_MS，无轮询。
        """
        _audit.validate_request(request)
        _storage.identifier(job_id)
        with session_scope(self.engine, read_only=True) as session:
            authorize_job_actor(session, request.identity, now=request.now)
            record = find_job(session, job_id)
            identifier = record.submitted_by.account_id
            present = existing_account_ids(
                session, frozenset(() if identifier is None else (identifier,))
            )
            return replace(
                record, submitter_deleted=identifier is not None and identifier not in present
            )

    def list(self, request: JobRequest, query: JobQuery) -> JobPage:
        """按状态和稳定游标查询所有提交人的作业。

        Args:
            request: 任意登录账号上下文；不按角色或提交人缩小范围。
            query: 状态可空、limit 1-100、游标最长 512 字符；非法游标不回退首页。

        Returns:
            仅job_id DESC的有界页；自增编号就是提交顺序，submitted_at仅作展示；游标绑定状态、limit、首页最大编号，
            后续新增不插入既有翻页。状态会改变，跨页不承诺冻结整个队列；允许空页。
            系统提交记录的 submitted_by.account_id=None、submitter_deleted=False。

        Raises:
            AuthenticationError: 查询事务身份无效。
            PasswordChangeRequiredError: 强制改密未完成。
            JobInputError: 状态、分页、游标编码/版本/筛选绑定非法。
            InputError: 数据库或行内容损坏。
            ConflictError: 查询锁冲突。
            ExternalError: 读取 I/O 或关闭失败。
            DefectError: 注入时钟、查询映射或状态/结果不一致。

        Side Effects:
            无；最多读取 limit+1 行及当前页账号存在性，不全量加载作业，不记查看操作日志。

        Time Semantics:
            墙钟回拨不禁止查询未来提交记录；只读锁最多 BUSY_TIMEOUT_MS，无自动重试。
        """
        _audit.validate_request(request)
        cursor = _pagination.decode(query)
        with session_scope(self.engine, read_only=True) as session, _storage.operation(session):
            authorize_job_actor(session, request.identity, now=request.now)
            head = (
                session.scalar(select(JobRow.job_id).order_by(JobRow.job_id.desc()).limit(1))
                if cursor is None
                else cursor[0]
            )
            if head is None:
                return JobPage((), None)
            statement = select(JobRow).where(JobRow.job_id <= head)
            if query.state is not None:
                statement = statement.where(JobRow.state == query.state.value)
            if cursor is not None:
                statement = statement.where(JobRow.job_id < cursor[1])
            rows = session.scalars(
                statement.order_by(JobRow.job_id.desc()).limit(query.limit + 1)
            ).all()
            records = tuple(_views.record(row) for row in rows[: query.limit])
            present = existing_account_ids(
                session,
                frozenset(
                    record.submitted_by.account_id
                    for record in records
                    if record.submitted_by.account_id is not None
                ),
            )
            records = tuple(
                replace(
                    record,
                    submitter_deleted=record.submitted_by.account_id is not None
                    and record.submitted_by.account_id not in present,
                )
                for record in records
            )
            next_cursor = (
                _pagination.encode(query, head, records[-1].job_id)
                if len(rows) > query.limit
                else None
            )
            return JobPage(records, next_cursor)

    def heartbeat(self, request: JobRequest) -> WorkerHeartbeat | None:
        """读取最近 worker 心跳，供入口计算在线状态。

        Args:
            request: 任意已认证账号上下文，仍检查会话有效和强制改密。

        Returns:
            单行心跳快照；从未启动过 worker 时 None，不用伪造进程号或时刻。

        Raises:
            AuthenticationError: 会话失效。
            PasswordChangeRequiredError: 必须改口令。
            InputError: 数据库损坏。
            ConflictError: 心跳读取锁冲突。
            ExternalError: 查询失败，不将故障伪装成离线。
            DefectError: 非法时钟、心跳字段或 SQL 映射错误。

        Side Effects:
            无；只读心跳，不探测 PID、不触碰 worker 锁或运行日志。

        Time Semantics:
            heartbeat_online 使用 request.now 与存储的 UTC 时刻比较；不跨进程比较 monotonic。
        """
        _audit.validate_request(request)
        with session_scope(self.engine, read_only=True) as session, _storage.operation(session):
            authorize_job_actor(session, request.identity, now=request.now)
            row = session.get(WorkerHeartbeatRow, 1)
            return (
                None
                if row is None
                else _storage.heartbeat(
                    WorkerHeartbeat(row.instance_id, row.pid, row.started_at, row.last_seen_at)
                )
            )


def _parameters(
    registry: JobRegistry, type_name: str, parameters: dict[str, object]
) -> tuple[JobDefinition, dict[str, object]]:
    """参数校验在写事务外；只把固定字段诊断暴露给调用者，不回显拒绝的载荷。"""
    return validate_parameters(registry, type_name, parameters)
