"""作业持久化与唯一状态转换（领域层，08）；调用者拥有短事务，不在这里等待作业。

SQLAlchemy 负责有条件 UPDATE 和事务；不复制队列库，ADR 0005 已排除不符合恢复语义的队列。
除创建行的初始 queued 外，所有 state/outcome/起止时间写入只在 transition_job。
数据库错误经现有 translate_database_error 分类；本层补对象上下文，不记录运行日志。
"""

import json
from copy import deepcopy
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any, cast

from sqlalchemy import CursorResult, select, text, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from rdp.infra.actors import ActorRef, is_display_name
from rdp.infra.diagnostics import ConflictError, DefectError, DiagnosticCategory
from rdp.infra.ids import MAX_SQLITE_INTEGER
from rdp.infra.state import StatePaths
from rdp.jobs import _storage, _views
from rdp.jobs.errors import JobNotFoundError
from rdp.jobs.models import JobRow, WorkerHeartbeatRow
from rdp.jobs.outcome import calculate_outcome
from rdp.jobs.policy import JOB_DISPLAY_NAME_MAX_CHARS, JOB_PARAMETERS_MAX_BYTES
from rdp.jobs.registry import JobDefinition, JobRegistry
from rdp.jobs.types import ExecutionSnapshot, JobRecord, JobState, JobSummary, WorkerHeartbeat


@dataclass(frozen=True)
class StateChange:
    """一次比较并更新的状态意图；终态摘要由转换函数产生。

    Attributes:
        expected: 调用方读到的旧状态，不允许跳过比较。
        target: 希望写入的新状态，只接受工单六条合法边。
        now: aware UTC 微秒时刻，不以回拨拒绝转换。
        aborted: 仅running→completed可为True；取消或中断必须False。
        log_path: queued→running必填的已在当前领取事务预留的相对logs路径；其他边必须None，保留原路径。
    """

    expected: JobState
    target: JobState
    now: datetime
    aborted: bool = False
    log_path: str | None = None


@dataclass(frozen=True)
class NewJob:
    """已校验且无秘密的提交内容，事务内操作者身份仍须重验。

    Attributes:
        definition: 当前登记定义，参数按其模型通过验证。
        parameters: JSON 对象，至多 JOB_PARAMETERS_MAX_BYTES；重新提交保留原参数值。
        actor: 事务内重读得到的账号编号和显示名；不接受 account_id=None。
        now: 入口提供的 aware 时刻，统一 UTC 微秒。
        resubmitted_from: 终态原作业正编号，普通提交 None。
    """

    definition: JobDefinition
    parameters: dict[str, object]
    actor: ActorRef
    now: datetime
    resubmitted_from: int | None


def insert_job(session: Session, command: NewJob) -> JobRecord:
    """在业务事务中分配永久编号并插入排队中的作业。

    Args:
        session: 已获 BEGIN IMMEDIATE 的受管写 Session，不跨线程共享。
        command: 参数已按登记模型校验的 NewJob，审计操作者来自事务内重验。

    Returns:
        已 flush 的 queued 记录；无开始/结束/日志路径/结果，计数均零，尚未提交。

    Raises:
        DefectError: 调用者传入无效 NewJob、非法时刻、非受管写 Session 或 SQL 映射缺陷。
        InputError: 既有数据库损坏。
        ConflictError: 编号耗尽、约束或写入竞争。
        ExternalError: 插入或 flush 的数据库 I/O 失败。

    Side Effects:
        只新增一行；不提交、不启动执行、不写文件。调用者随后 append_operation，同事务提交；
        任意失败退出工作单元整体回滚，不能留下未审计作业。

    Time Semantics:
        使用 command.now，不另读时钟；写锁已经取得，不增加等待或重试。
    """
    _validate_new_job(command)
    with _storage.operation(session, write=True):
        # 写事务已经持有排他写锁；先区分序列耗尽与真正的磁盘满，不能将所有SQLITE_FULL改为冲突。
        sequence = session.scalar(text("SELECT seq FROM sqlite_sequence WHERE name='jobs'"))
        if sequence is not None and sequence >= MAX_SQLITE_INTEGER:
            raise ConflictError(
                (
                    _storage.diagnostic(
                        MAX_SQLITE_INTEGER,
                        "作业编号已耗尽，历史编号不能复用",
                        DiagnosticCategory.CONFLICT,
                    ),
                )
            )
        row = JobRow(
            type_name=command.definition.type_name,
            display_name=command.definition.display_name,
            parameters=deepcopy(command.parameters),
            submitter_id=command.actor.account_id,
            submitter_name=command.actor.name,
            submitted_at=_storage.moment(command.now),
            resubmitted_from=command.resubmitted_from,
            state=JobState.QUEUED.value,
            recovery_mode=command.definition.recovery_mode.value,
            recovery_count=0,
            artifacts=[],
            diagnostics=[],
        )
        session.add(row)
        session.flush()
        return _views.record(row)


def transition_job(session: Session, job_id: int, change: StateChange) -> JobRecord:
    """执行唯一状态转换，并在终态冻结与日志共用的摘要。

    Args:
        session: 已获普通 busy_timeout 写锁的受管 Session；禁止使用可跳过的进度事务。
        job_id: 正整数，1 至 2^63-1。
        change: 旧状态、新状态、UTC 时刻及整体中止标记。

    Returns:
        新快照；合法边恰为 queued→running、queued→cancelled、running→completed、
        running→cancelling、cancelling→cancelled、running→interrupted。
        第一次running在同一次条件UPDATE中保存started_at和log_path；终态设置ended_at，cancelling不写结束时间。
        仅 completed 调用 calculate_outcome(total_items,failed_items,warning_count,aborted)，
        其他状态 outcome=None；cancelled/interrupted 保留计数、进度、产物且没有结果。

    Raises:
        DefectError: 非法边（含自转换）、非法编号/时钟/aborted、领取缺少合法log_path或存量状态/计数损坏；不执行 UPDATE。
        JobNotFoundError: 编号不存在。
        ConflictError: WHERE job_id=:id AND state=:expected 更新行数为零，或约束/数据库锁冲突。
        InputError: 数据库损坏。
        ExternalError: 更新、flush 或摘要存储 I/O 失败。

    Side Effects:
        所有状态写入集中于此，比较更新后 flush，不 commit，不记操作日志或运行日志。
        状态、时间、结果和摘要在一个事务中改变；调用者负责整个事务回滚，不跳过失败。
        排队取消先提交时worker的旧queued候选领取冲突且不执行；worker先提交时取消服务在
        BEGIN IMMEDIATE内读到running，以该当前状态为expected转cancelling并记日志，不凭旧快照返回冲突。

    Time Semantics:
        UTC 墙钟允许回拨，不修改首次开始时间；耗时取已经保存的 monotonic 片段。
        由外层普通 session_scope 提供 BUSY_TIMEOUT_MS 预算，不自动重试或重新读取后换边。
    """
    job_id = _storage.identifier(job_id, internal=True)
    _validate_change(change)
    now = _storage.moment(change.now)
    with _storage.operation(session, write=True):
        row = session.get(JobRow, job_id)
        if row is None:
            raise JobNotFoundError(
                (_storage.diagnostic(job_id, "作业记录不存在", DiagnosticCategory.INPUT),)
            )
        _views.record(row)
        if row.state != change.expected.value:
            failure = _state_conflict(job_id)
            raise failure
        values = _transition_values(row, change, now)
        changed = session.execute(
            update(JobRow)
            .where(JobRow.job_id == job_id, JobRow.state == change.expected.value)
            .values(**values)
            .execution_options(synchronize_session=False)
        )
        if cast(CursorResult[Any], changed).rowcount != 1:
            failure = _state_conflict(job_id)
            raise failure
        session.flush()
        session.expire(row)
        return _views.record(row)


def find_job(session: Session, job_id: int) -> JobRecord:
    """读取一个永久作业记录，供事务内决策和详情查询。

    Args:
        session: 受管只读或写 Session，不并发使用。
        job_id: 严格正整数，最大 2^63-1。

    Returns:
        脱离 Session 的完整快照；提交人删除标记由服务在同一快照补齐。

    Raises:
        JobInputError: 编号类型或范围非法。
        JobNotFoundError: 没有该编号，不以空记录代替。
        InputError: 数据库或存量 JSON 无法解码。
        ConflictError: 读取锁冲突。
        ExternalError: 数据库读取失败。
        DefectError: 行内状态/摘要不一致、映射错误或非受管 Session。

    Side Effects:
        无；只读一行，不延长保留期，不访问日志或账号数据。

    Time Semantics:
        只返回事务快照中的 UTC 时刻，不查当前时钟或等待未来作业。
    """
    job_id = _storage.identifier(job_id)
    with _storage.operation(session):
        row = session.get(JobRow, job_id)
        if row is None:
            raise JobNotFoundError(
                (_storage.diagnostic(job_id, "作业记录不存在", DiagnosticCategory.INPUT),)
            )
        return _views.record(row)


def next_queued_job(session: Session) -> JobRecord | None:
    """在只读快照选择提交最早的候选，不预先持有领取写锁。

    Args:
        session: 受管只读 Session，选择后立即退出事务，不能在此升级写事务。

    Returns:
        按job_id ASC的第一条queued快照，队列为空返回 None；
        未登记类型或过时参数也返回，交执行器失败收尾，不能堵住后续队列。

    Raises:
        InputError: 数据库或记录JSON损坏。
        ConflictError: 只读查询锁冲突。
        ExternalError: 读取I/O失败。
        DefectError: 非受管只读会话或查询映射错误。

    Side Effects:
        无；只查一行，不持写锁、不预占状态，不启动线程。

    Time Semantics:
        恢复队列处理完才调用；快照只反映选择瞬间，随后可能被Web取消，claim_job必须比较更新。
    """
    with _storage.operation(session):
        if session.info["rdp_read_only"] is not True:
            raise DefectError()
        row = session.scalars(
            select(JobRow)
            .where(JobRow.state == JobState.QUEUED.value)
            .order_by(JobRow.job_id)
            .limit(1)
        ).first()
        return None if row is None else _views.record(row)


def claim_job(session: Session, job_id: int, *, now: datetime, paths: StatePaths) -> JobRecord:
    """通过唯一状态转换领取已选择的排队候选。

    Args:
        session: 已获普通写锁的受管 Session，调用者持有 worker 单实例锁。
        job_id: 刚由next_queued_job读出的正编号，不能在失败时悄悄换候选。
        now: aware当前时刻，统一UTC微秒，非法时钟归DefectError。
        paths: 可信状态布局；仅检查logs下候选文件是否已存在，不在领取事务创建文件。

    Returns:
        queued→running后含started_at及非空log_path的快照；两者和状态同事务提交，之后才启动执行线程。

    Raises:
        JobNotFoundError: 已选编号不存在，永久记录被外部破坏。
        ConflictError: queued 条件更新失败，包含 Web 取消先提交；不改领别的作业。
        InputError: 数据库损坏。
        ExternalError: 查询、领取或候选日志路径的只读检查失败。
        DefectError: 非法编号/now、行结构/映射错误或调用方未使用受管会话。

    Side Effects:
        在当前BEGIN IMMEDIATE事务内，按UTC started_at的毫秒（向下截断）计算
        logs/<显示名>/2026-10-22_143015_123.log；与已登记路径或既有文件冲突时用_<job_id>后缀，
        后缀也冲突为DefectError，不覆盖。路径由UNIQUE(log_path)约束防止两个同毫秒作业同时预留同名。
        将路径传给transition_job(expected=queued,target=running)，至多改变一行，状态写入仍只有该函数。
        不创建文件、不提交、不启动线程；领取提交后即使尚未写日志开头就崩溃，恢复也能从记录找到路径。

    Time Semantics:
        同一轮至多领取WORKER_CONCURRENCY个；竞争失败等下一轮，不在事务里休眠或自动重试。
    """
    job_id = _storage.identifier(job_id, internal=True)
    now = _storage.moment(now)
    with _storage.operation(session, write=True):
        current = find_job(session, job_id)
        if current.state is not JobState.QUEUED:
            failure = _state_conflict(job_id)
            raise failure
        relative = _claim_log_path(session, current, paths, now)
        return transition_job(
            session, job_id, StateChange(JobState.QUEUED, JobState.RUNNING, now, log_path=relative)
        )


def save_progress(
    session: Session, job_id: int, snapshot: ExecutionSnapshot, *, now: datetime
) -> None:
    """保存最近执行快照及独立计数，不改变作业状态。

    Args:
        session: 已获写锁的受管Session；周期上报使用短锁，最终上报使用普通锁。
        job_id: 当前执行的正编号。
        snapshot: 上报对象的冻结快照，含最新进度、诊断、产物、工具退出码与有限非负elapsed_s；
            progress=None表示尚无上报，此时计数为零，不能覆盖已有非空进度。
        now: aware UTC更新时间，不以回拨伪造单调墙钟；快照耗时用monotonic而非本值计算。

    Returns:
        无；进度JSON和计数列一致，未知total保存NULL，诊断及产物快照与同一进度原子保存。

    Raises:
        JobNotFoundError: 作业不存在。
        ConflictError: 目标已为终态或条件更新/锁冲突。
        InputError: 数据库损坏。
        ExternalError: 写入I/O失败。
        DefectError: 非法快照/时钟、非受管会话或SQL错误。

    Side Effects:
        更新running/cancelling的进度、计数、elapsed_s、诊断、产物和退出码并flush，不提交。
        只有实际进度非空才更新progress_at；恢复前旧快照仍可用于日志中断段。
        调用者决定是否允许跳过未获短锁；已经进入事务后的失败不能冒充可跳过。

    Time Semantics:
        节流由ProgressReporter以monotonic完成；作业结束时允许一次不受节流限制的最终写入，
        与transition_job共用普通事务；崩溃后只累加已保存耗时片段，不计算停机等待时长。
    """
    job_id = _storage.identifier(job_id, internal=True)
    now = _storage.moment(now)
    checked, values = _views.snapshot_data(snapshot)
    with _storage.operation(session, write=True):
        current = find_job(session, job_id)
        if current.state not in {JobState.RUNNING, JobState.CANCELLING}:
            failure = _state_conflict(job_id)
            raise failure
        if checked.progress is None and current.progress is not None:
            raise DefectError()
        progress = checked.progress
        updates = values | {
            "total_items": 0 if progress is None else progress.total_items,
            "failed_items": 0 if progress is None else progress.failed_items,
            "warning_count": 0 if progress is None else progress.warning_count,
        }
        if progress is not None:
            updates["progress_at"] = now
        result = session.execute(
            update(JobRow)
            .where(
                JobRow.job_id == job_id,
                JobRow.state.in_((JobState.RUNNING.value, JobState.CANCELLING.value)),
            )
            .values(**updates)
            .execution_options(synchronize_session=False)
        )
        if cast(CursorResult[Any], result).rowcount != 1:
            failure = _state_conflict(job_id)
            raise failure
        session.flush()
        session.expire_all()


def save_heartbeat(session: Session, heartbeat: WorkerHeartbeat) -> None:
    """覆盖单行心跳，标识当前持锁实例。

    Args:
        session: 已获短写锁的受管 Session，只由当前 worker 主循环调用。
        heartbeat: 合法实例标识、正 pid 及两个 aware UTC 时刻。

    Returns:
        无；singleton_id=1 存在时更新、不存在时插入。

    Raises:
        ConflictError: 约束或写入锁冲突。
        InputError: 数据库损坏。
        ExternalError: 心跳存储 I/O 失败。
        DefectError: heartbeat 字段非法、非受管 Session 或 SQL 缺陷。

    Side Effects:
        只写心跳行，不记操作日志；调用者提交，失败回滚而保留上一次心跳。

    Time Semantics:
        now/started_at 均为 UTC 墙钟；写入节奏由 worker 的 monotonic 每 5 秒驱动。
    """
    checked = _storage.heartbeat(heartbeat)
    values = asdict(checked)
    with _storage.operation(session, write=True):
        statement = sqlite_insert(WorkerHeartbeatRow).values(singleton_id=1, **values)
        session.execute(
            statement.on_conflict_do_update(
                index_elements=[WorkerHeartbeatRow.singleton_id], set_=values
            )
        )
        session.flush()
        session.expire_all()


# 工单08仅允许六条边；其他入口不得自行赋state，恢复续跑/重跑也不新增自转换。
_ALLOWED_TRANSITIONS = frozenset(
    {
        (JobState.QUEUED, JobState.RUNNING),
        (JobState.QUEUED, JobState.CANCELLED),
        (JobState.RUNNING, JobState.COMPLETED),
        (JobState.RUNNING, JobState.CANCELLING),
        (JobState.CANCELLING, JobState.CANCELLED),
        (JobState.RUNNING, JobState.INTERRUPTED),
    }
)
_TERMINAL_STATES = frozenset({JobState.COMPLETED, JobState.CANCELLED, JobState.INTERRUPTED})


def _validate_change(change: StateChange) -> None:
    """先验证调用意图再读库，非法边和伪造路径不能退化为数据库约束冲突。"""
    if not isinstance(cast(object, change), StateChange):
        raise DefectError()
    if not isinstance(cast(object, change.expected), JobState) or not isinstance(
        cast(object, change.target), JobState
    ):
        raise DefectError()
    if (change.expected, change.target) not in _ALLOWED_TRANSITIONS:
        raise DefectError()
    if type(change.aborted) is not bool or (
        change.aborted and change.target is not JobState.COMPLETED
    ):
        raise DefectError()
    if change.target is JobState.RUNNING:
        _validate_relative_log(change.log_path)
    elif change.log_path is not None:
        raise DefectError()


def _validate_relative_log(value: object) -> None:
    """领取只能预留logs下一个类型目录的文件，不能由状态更新带入绝对/越界路径。"""
    if not isinstance(value, str) or "\x00" in value or "\\" in value:
        raise DefectError()
    path = PurePosixPath(value)
    if (
        str(path) != value
        or path.is_absolute()
        or len(path.parts) != 3
        or path.parts[0] != "logs"
        or ".." in path.parts
        or path.suffix != ".log"
    ):
        raise DefectError()


def _state_conflict(job_id: int) -> ConflictError:
    """竞争只说明已确认编号的状态变化，不泄漏参数或操作者的秘密字段。"""
    return ConflictError(
        (_storage.diagnostic(job_id, "作业状态已变化", DiagnosticCategory.CONFLICT),)
    )


def _transition_values(row: JobRow, change: StateChange, now: datetime) -> dict[str, object]:
    """为唯一状态写入函数算更新值；此函数不执行SQL或改变ORM状态。"""
    values: dict[str, object] = {"state": change.target.value}
    if change.target is JobState.RUNNING:
        values.update(started_at=now, log_path=change.log_path)
    elif change.target in _TERMINAL_STATES:
        current = _views.record(row)
        outcome = None
        if change.target is JobState.COMPLETED:
            try:
                outcome = calculate_outcome(
                    total_items=row.total_items,
                    failed_items=row.failed_items,
                    warning_count=row.warning_count,
                    aborted=change.aborted,
                )
            except ValueError:
                raise DefectError() from None
        summary = JobSummary(
            state=change.target,
            outcome=outcome,
            progress=current.progress,
            total_items=row.total_items,
            failed_items=row.failed_items,
            warning_count=row.warning_count,
            aborted=change.aborted,
            elapsed_s=row.elapsed_s,
            artifacts=current.artifacts,
            tool_exit_code=row.tool_exit_code,
        )
        values.update(
            ended_at=now,
            outcome=outcome,
            aborted=change.aborted,
            summary=_views.summary_data(summary),
        )
    return values


def _claim_log_path(session: Session, record: JobRecord, paths: StatePaths, now: datetime) -> str:
    """在领取写锁中避让已登记及既有文件；只读路径，绝不在事务内创建或覆盖日志。"""
    if (
        not isinstance(cast(object, paths), StatePaths)
        or not paths.root.is_absolute()
        or paths.logs != paths.root / "logs"
    ):
        raise DefectError()
    if (
        Path(session.get_bind().engine.url.database or "") != paths.database
        or paths.logs.is_symlink()
    ):
        raise DefectError()
    name = record.display_name
    if (
        not is_display_name(name)
        or len(name) > JOB_DISPLAY_NAME_MAX_CHARS
        or "/" in name
        or "\\" in name
        or name in {".", ".."}
    ):
        raise DefectError()
    directory = paths.logs / name
    if directory.is_symlink():
        raise DefectError()
    # isoformat补齐小年份，毫秒向下截断；now已规范化UTC，去掉固定+00:00后缀。
    timestamp = (
        now.isoformat(timespec="milliseconds")[:-6]
        .replace("T", "_")
        .replace(":", "")
        .replace(".", "_")
    )
    base = f"logs/{name}/{timestamp}"
    for candidate in (base + ".log", base + f"_{record.job_id}.log"):
        reserved = session.scalar(
            select(JobRow.job_id).where(JobRow.log_path == candidate).limit(1)
        )
        if reserved is None and not _path_exists(paths.root / candidate):
            return candidate
    raise DefectError()


def _path_exists(path: Path) -> bool:
    """lstat把悬空软链接也算占用，避免exists把它误当可用路径；其他I/O故障交外层分类。"""
    try:
        path.lstat()
    except FileNotFoundError:
        return False
    return True


def _validate_new_job(command: NewJob) -> None:
    """写入前防止内部命令绕过模型或携带秘密字段；只验证有界参数，不执行作业或补写默认值。"""
    if not isinstance(cast(object, command), NewJob) or not isinstance(
        cast(object, command.actor), ActorRef
    ):
        raise DefectError()
    _storage.identifier(command.actor.account_id, internal=True)
    if not is_display_name(command.actor.name):
        raise DefectError()
    if command.resubmitted_from is not None:
        _storage.identifier(command.resubmitted_from, internal=True)
    registry = JobRegistry()
    registry.register(command.definition)
    try:
        if not isinstance(cast(object, command.parameters), dict):
            raise DefectError()
        if (
            len(json.dumps(command.parameters, ensure_ascii=False, allow_nan=False).encode())
            > JOB_PARAMETERS_MAX_BYTES
        ):
            raise DefectError()
        # 只检查兼容性；重新提交必须保留原JSON，不能把新模型默认值偷偷写入旧参数副本。
        command.definition.parameters_model.model_validate(command.parameters)
    except Exception:
        raise DefectError() from None
