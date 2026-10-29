"""全局标记"导航层恢复失败"（领域层，M1-07，ADR 0005 修订、ADR 0009 L14）。

存放位置：数据库表 `nav_recovery_failure`，单行；有这一行就表示写导航层的作业被挡住。
选数据库而不是状态目录里的文件，是因为 Web 和 worker 只通过 SQLite 联系（ADR 0005），
页面顶部的提示、作业页面的"对不上的项"和管理员的确认都在数据库里一个事务完成，
并且它跟随 SQLite 备份。表由 pending 迁移 v0010 创建（冻结 DDL 见该迁移）。

不新增作业状态：触发它的作业仍是"已中断"，标记是另一个全局事实。重启 worker 不会清除它；
只有管理员确认（acknowledge_recovery_block）才清除。本模块 Web 和 worker 两侧都可 import：
读和确认只碰数据库与状态目录，不碰导航层。
"""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import Engine
from sqlalchemy.orm import Session

from rdp.audit.types import AuditContext
from rdp.infra.actors import ActorRef
from rdp.infra.state import StatePaths
from rdp.jobs.navwrite.models import MismatchItem


@dataclass(frozen=True)
class RecoveryBlock:
    """当前生效的"导航层恢复失败"标记。

    Attributes:
        set_at: 第一次设置的 UTC 时刻（带时区）；之后并入新项不改它。
        job_ids: 留有对不上项的写入作业编号，升序、不重复，≥ 1 项。
        items: 对不上的项样例，至多 MARKER_ITEM_SAMPLE_LIMIT 条，按作业编号、步骤序号升序。
        total_items: 对不上的项总数，≥ len(items)；总数始终完整（规范 6.6）。
    """

    set_at: datetime
    job_ids: tuple[int, ...]
    items: tuple[MismatchItem, ...]
    total_items: int


@dataclass(frozen=True)
class AcknowledgeRequest:
    """管理员确认的请求上下文，调用方必须显式提供，漏传即报错。

    Attributes:
        actor: 确认的管理员身份快照，account_id 不能为 None（运维命令不能解除，必须在页面上确认）。
        context: 来源 IP 和请求编号。
        now: 注入的 aware 时刻，UTC。
    """

    actor: ActorRef
    context: AuditContext
    now: datetime


@dataclass(frozen=True)
class AcknowledgeResult:
    """一次确认的结果。

    Attributes:
        cleared_job_ids: 已归档并清掉日志的作业编号，升序。
        audit_log_id: 追加的 confirm_navigation_recovery 操作日志编号，≥ 1。
    """

    cleared_job_ids: tuple[int, ...]
    audit_log_id: int


def read_recovery_block(session: Session) -> RecoveryBlock | None:
    """读取当前的恢复失败标记。

    Args:
        session: 受管 Session，只读事务即可；调用方负责关闭。

    Returns:
        有标记时返回 RecoveryBlock，没有时返回 None。

    Raises:
        InputError: 标记行的 JSON 列损坏、无法解析成 MismatchItem。

    Side Effects:
        无（只读数据库）。

    Time Semantics:
        读取当前已提交的状态；Web 页面顶部提示每次轮询作业列表时读一次，worker 每轮领取前读一次，不缓存。
    """
    raise NotImplementedError


def is_navigation_write_blocked(session: Session) -> bool:
    """判断写导航层的作业此刻是否被挡住。

    Args:
        session: 受管 Session，只读事务即可。

    Returns:
        存在恢复失败标记为 True。作业循环据此跳过 writes_navigation 的作业类型，其作业留在排队中，不开始。

    Raises:
        InputError: 同 read_recovery_block。

    Side Effects:
        无（只读数据库）。

    Time Semantics:
        每轮领取之前读取（约 1 秒一次，WORKER_POLL_INTERVAL_S）；标记被确认后下一轮即放行，不需要重启 worker。
    """
    raise NotImplementedError


def record_recovery_block(
    session: Session, items: tuple[MismatchItem, ...], *, now: datetime
) -> RecoveryBlock:
    """设置或扩充恢复失败标记，把对不上的项并入。

    Args:
        session: 受管 Session，处于调用方的写事务中。
        items: 本次发现的对不上的项，非空。
        now: 注入的 aware 时刻，UTC；仅在新建标记时写入 set_at。

    Returns:
        合并后的 RecoveryBlock：job_ids 取并集，items 去重后取前 MARKER_ITEM_SAMPLE_LIMIT 条，total_items 为全部。

    Raises:
        InputError: items 为空。
        ConflictError: 事务入场后的约束冲突或提交竞争。

    Side Effects:
        插入或更新 nav_recovery_failure 的唯一一行。不写操作日志，由 recovery 另行追加。

    Time Semantics:
        在恢复流程的一个短写事务内完成；同一次启动里先于任何作业领取。
    """
    raise NotImplementedError


def acknowledge_recovery_block(
    engine: Engine, paths: StatePaths, request: AcknowledgeRequest
) -> AcknowledgeResult:
    """管理员人工核对、修好之后确认：归档日志、记操作日志、删日志、清标记。

    Args:
        engine: 受管 SQLite 引擎。
        paths: 已初始化的状态布局。
        request: 确认者、来源和时刻。

    Returns:
        AcknowledgeResult。

    Raises:
        ConflictError: 当前没有恢复失败标记（已被别人确认，或从未设置）。
        InputError: request.actor 不是账号管理员（account_id 为 None）。
        ExternalError: 归档变更记录、删日志或数据库写入失败。

    Side Effects:
        对标记里每个作业：把写入日志归档进 nav-changes（outcome 为 manually_confirmed，记下确认时对不上的项），
        再删除日志目录；然后在一个数据库事务里追加 confirm_navigation_recovery 操作日志并删除标记行。
        失败时标记保留，已归档的日志再确认一次是幂等的（归档先写临时文件再 rename，重复写入同样内容）。
        不碰导航层。由 Web 调用，因为管理员在页面上确认；这里写的是状态目录，不是导航层。

    Time Semantics:
        同步；顺序固定：先归档并删日志，最后清标记。崩在中间时标记还在，写操作继续被挡住，
        宁可多挡也不提前放行。确认之后下一轮作业领取（约 1 秒）即放行排队的写作业。
    """
    raise NotImplementedError
