"""写导航层的操作日志摘要（领域层，M1-07，ADR 0009 L15）。

操作日志只记摘要：谁、什么时候、作业编号、操作类型、涉及的数据集、改了几个文件几条链接、结果，
加一个变更记录编号；前像和后像全文不进数据库（它们在 nav-changes 里）。
摘要的字段落在既有的 OperationDetails.after 白名单里（本票给 AuditValues 加了字段），
对象是新增的 ObjectRef 种类 `navigation_write`（对象编号 = 写入作业编号 = 变更记录编号）。
本模块只构造事件和追加，不决定记什么时候记（pipeline 和 recovery 决定）。
"""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import Engine

from rdp.audit.types import AuditContext, OperationEvent, OperationResult, OperationType
from rdp.infra.actors import ActorRef
from rdp.infra.diagnostics import DiagnosticCategory


@dataclass(frozen=True)
class NavigationAuditFacts:
    """构造一条写导航层操作日志所需的事实，全部由调用方显式给出。

    Attributes:
        operation: 操作码：create_link、create_dataset、repoint_dataset、set_data_origin、revert_change、
            rollback_navigation_write（中断恢复的回滚）、confirm_navigation_recovery（管理员确认）之一。
        job_id: 写入作业编号，≥ 1；确认操作填被清掉日志的作业中最小的一个。
        actor: 提交人身份快照；中断恢复的回滚记为"系统"（ActorRef(None, "系统")）。
        context: 来源 IP 和请求编号。worker 里没有请求，显式传 OPS_AUDIT_CONTEXT；确认操作传页面请求的上下文。
        occurred_at: aware 时刻，UTC，由注入时钟生成。
        result: 成功或失败。作业回滚为失败，并带 failure_category。
        failure_category: 失败类别；成功必须为 None。
        dataset_ids: 涉及的数据集，至多 AUDIT_DATASET_ID_LIMIT 个，多出的只体现在 dataset_count。
        dataset_count: 涉及的数据集总数，≥ len(dataset_ids)。
        file_count: 改了几个文件，≥ 0。
        link_count: 改了几条链接，≥ 0。
        change_record_id: 变更记录编号（文本，等于作业编号）；没有生成变更记录（例如冲突失败、没写任何东西）为 None。
        reverts_job_id: 仅撤回作业：被撤回的作业编号。
    """

    operation: OperationType
    job_id: int
    actor: ActorRef
    context: AuditContext
    occurred_at: datetime
    result: OperationResult
    failure_category: DiagnosticCategory | None
    dataset_ids: tuple[str, ...]
    dataset_count: int
    file_count: int
    link_count: int
    change_record_id: str | None
    reverts_job_id: int | None


def navigation_operation_event(facts: NavigationAuditFacts) -> OperationEvent:
    """把事实组装成一条操作日志事件。

    Args:
        facts: 事实，字段约束见 NavigationAuditFacts。

    Returns:
        OperationEvent：对象为 ObjectRef("navigation_write", str(job_id), "写导航层 #<job_id>")，
        details.before 为空，details.after 含数据集编号、个数、文件数、链接数、变更记录编号等白名单字段；
        失败事件的 after 仍含已确认的计数，但 change_record_id 取决于是否真的写了变更记录。

    Raises:
        AuditInputError: 事实不合约（计数为负、成功却带失败类别、数据集编号超出上限而未给总数等）。

    Side Effects:
        无；不追加、不查库。

    Time Semantics:
        同步纯函数；occurred_at 由调用方的注入时钟给出。
    """
    raise NotImplementedError


def append_navigation_audit(engine: Engine, event: OperationEvent) -> int:
    """在独立短事务里追加一条写导航层的操作日志。

    Args:
        engine: 受管 SQLite 引擎。
        event: navigation_operation_event 的结果。

    Returns:
        新日志编号，≥ 1。

    Raises:
        AuditInputError: 事件不合约。
        ConflictError: 事务入场后约束冲突或写锁等待超过 AUDIT_SHORT_LOCK_TIMEOUT_MS。
        ExternalError: 数据库 I/O 失败。作业已写完导航层时调用方只记 ERROR 并给作业加警告，不回滚导航层。

    Side Effects:
        追加一行 operation_logs。写导航层的作业成功后不与导航层写入同一事务（两个存储不能同事务）：
        先写导航层和变更记录，最后追加操作日志，操作日志缺失可以从变更记录补出，反过来不行。

    Time Semantics:
        短事务，BEGIN 最多等 AUDIT_SHORT_LOCK_TIMEOUT_MS=100 毫秒，不重试；操作日志保留 30 天后被清除，
        变更记录不受影响。
    """
    raise NotImplementedError
