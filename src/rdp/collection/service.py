"""采集登记领域服务：只读写数据库，不连接机器人、不访问导航层（ADR 0005）。

复用 SQLAlchemy 事务、账号历史身份与 audit 追加接口；三种登记对象共用相同生命周期。
调用者持有 BEGIN IMMEDIATE，重复检查、业务写入与成功操作日志在同一事务提交。
"""

from dataclasses import dataclass
from datetime import datetime
from http import HTTPStatus
from typing import ClassVar, Literal, cast

from sqlalchemy import select
from sqlalchemy.orm import Session

from rdp.accounts.models import AccountRow
from rdp.accounts.service import authorize_job_actor
from rdp.accounts.types import SessionIdentity
from rdp.audit.records import append_operation
from rdp.audit.types import (
    AuditContext,
    AuditValues,
    ObjectRef,
    OperationDetails,
    OperationEvent,
    OperationResult,
    OperationType,
)
from rdp.collection.models import MethodRow, PurposeRow, RegistryRow, RobotRow
from rdp.collection.types import MethodInput, PurposeInput, RegistryKind, RegistryStatus, RobotInput
from rdp.infra.actors import ActorRef
from rdp.infra.diagnostics import (
    ConflictError,
    Diagnostic,
    DiagnosticCategory,
    DiagnosticLevel,
    DiagnosticObject,
    InputError,
)


class CollectionNotFoundError(InputError):
    """登记编号不存在，由统一入口映射为 404。"""

    http_status: ClassVar[HTTPStatus] = HTTPStatus.NOT_FOUND


@dataclass(frozen=True)
class ChangeContext:
    """一次登记写请求的身份、时刻及审计来源，领域层不持有 HTTP 对象。

    Attributes:
        identity: 已认证身份，写事务内重验。
        now: 同请求唯一 aware UTC 微秒时刻。
        audit: 必填来源 IP 和服务器请求编号。
    """

    identity: SessionIdentity
    now: datetime
    audit: AuditContext


@dataclass(frozen=True)
class RegistryRecord:
    """脱离数据库会话的登记快照，历史名称不随账号改名或删除变化。

    Attributes:
        id: 所属表永久编号，正整数。
        value: 规范化的机器人、采集方式或用途可编辑字段。
        status: active 或 retired。
        reference_count: 引用的数据集数量，非负整数。
        created_by: 创建时身份快照，系统账号编号为 None。
        created_at: 创建时 UTC 微秒时刻。
        updated_by: 最后修改时身份快照。
        updated_at: 最后修改时 UTC 微秒时刻，不倒退。
        creator_deleted: 原创建账号目前是否已删除，系统为 False。
        updater_deleted: 原修改账号目前是否已删除，系统为 False。
    """

    id: int
    value: RobotInput | MethodInput | PurposeInput
    status: RegistryStatus
    reference_count: int
    created_by: ActorRef
    created_at: datetime
    updated_by: ActorRef
    updated_at: datetime
    creator_deleted: bool
    updater_deleted: bool


_MODELS: dict[RegistryKind, type[RegistryRow]] = {
    "robots": RobotRow,
    "methods": MethodRow,
    "purposes": PurposeRow,
}
_OBJECT_KINDS: dict[RegistryKind, Literal["robot", "collection_method", "collection_purpose"]] = {
    "robots": "robot",
    "methods": "collection_method",
    "purposes": "collection_purpose",
}


def _problem[T: InputError | ConflictError](
    kind: type[T], field: str, actual: str, next_step: str
) -> T:
    """诊断只包含登记字段及已确认对象，不接受凭据或 SQL 错误原文。"""
    return kind(
        (
            Diagnostic(
                level=DiagnosticLevel.ERROR,
                category=DiagnosticCategory.CONFLICT
                if kind is ConflictError
                else DiagnosticCategory.INPUT,
                stage="采集登记",
                source="平台",
                objects=(DiagnosticObject(key="field", value=field),),
                rule="登记对象必须满足字段、唯一性及引用约束",
                actual=actual,
                expected="合法且不冲突的登记对象",
                consequence="本次修改未提交",
                next_step=next_step,
            ),
        )
    )


def reference_count(session: Session, kind: RegistryKind, identifier: int) -> int:
    """查询登记对象被数据集采集信息引用的数量。

    Args:
        session: 调用者持有的数据库会话，不提交或关闭。
        kind: robots、methods 或 purposes。
        identifier: 已存在对象的正整数编号。

    Returns:
        当前返回 0；M3-03 引入采集信息索引后在此接入统计。

    Raises:
        无。

    Side Effects:
        无；本版本没有采集信息索引可读取。

    Time Semantics:
        同步返回，不等待外部扫描。
    """
    return 0


def _record(session: Session, kind: RegistryKind, row: RegistryRow) -> RegistryRecord:
    """在当前快照查询历史账号是否仍存在，并复制规范字段，避免返回活 ORM。"""
    if isinstance(row, RobotRow):
        value: RobotInput | MethodInput | PurposeInput = RobotInput.model_validate(
            dict(
                name=row.name,
                robot_model=row.robot_model,
                serial_number=row.serial_number,
                macs=row.macs,
                address=row.address,
                ssh_port=row.ssh_port,
                ssh_user=row.ssh_user,
            )
        )
    elif isinstance(row, MethodRow):
        value = MethodInput.model_validate({"name": row.name, "data_origin": row.data_origin})
    else:
        value = PurposeInput(name=row.name)
    ids = frozenset(i for i in (row.created_by_id, row.updated_by_id) if i is not None)
    # 写响应仍在当前写事务内，直接查询公开账号模型，不调用只读事务专用的日志查询适配器。
    existing = frozenset(
        session.scalars(select(AccountRow.account_id).where(AccountRow.account_id.in_(ids)))
    )
    return RegistryRecord(
        row.id,
        value,
        cast(RegistryStatus, row.status),
        reference_count(session, kind, row.id),
        ActorRef(row.created_by_id, row.created_by_name),
        row.created_at,
        ActorRef(row.updated_by_id, row.updated_by_name),
        row.updated_at,
        row.created_by_id is not None and row.created_by_id not in existing,
        row.updated_by_id is not None and row.updated_by_id not in existing,
    )


def list_records(session: Session, kind: RegistryKind) -> tuple[RegistryRecord, ...]:
    """按永久编号列出指定登记表，包含停用对象。

    Args:
        session: 已由入口鉴权的只读业务会话。
        kind: robots、methods 或 purposes。

    Returns:
        编号升序的独立快照元组，可为空，身份删除标记按当前查询计算。

    Raises:
        SQLAlchemyError: 查询失败，由调用者数据库边界映射。

    Side Effects:
        无；只读登记表及历史账号存在性。

    Time Semantics:
        所有字段来自调用者同一读事务，不触发扫描或网络请求。
    """
    model = _MODELS[kind]
    return tuple(
        _record(session, kind, row) for row in session.scalars(select(model).order_by(model.id))
    )


def _get(session: Session, kind: RegistryKind, identifier: int) -> RegistryRow:
    """只按永久编号定位对象，不通过可变名称解析引用。"""
    row = session.get(_MODELS[kind], identifier)
    if row is None:
        raise _problem(
            CollectionNotFoundError, "id", f"{kind} #{identifier} 不存在", "刷新列表后选择现有对象"
        )
    return row


def _unique(
    session: Session,
    kind: RegistryKind,
    value: RobotInput | MethodInput | PurposeInput,
    identifier: int | None,
) -> None:
    """持写锁查名称、序列号和 MAC；停用对象仍占用唯一值。"""
    model = _MODELS[kind]
    for row in session.scalars(select(model)):
        if row.id == identifier:
            continue
        field = "name" if row.name == value.name else None
        if isinstance(value, RobotInput) and isinstance(row, RobotRow):
            if value.serial_number is not None and value.serial_number == row.serial_number:
                field = "serial_number"
            if {mac.mac for mac in value.macs} & {mac["mac"] for mac in row.macs}:
                field = "macs"
        if field is not None:
            raise _problem(
                ConflictError, field, f"与 {kind} #{row.id}（{row.name}）重复", "使用未被占用的值"
            )
    if isinstance(value, RobotInput) and len({mac.mac for mac in value.macs}) != len(value.macs):
        raise _problem(
            ConflictError, "macs", f"同一机器人（{value.name}）的 MAC 重复", "每块网卡只填写一次"
        )


def _event(
    kind: RegistryKind, row: RegistryRow, action: str, actor: ActorRef, context: ChangeContext
) -> OperationEvent:
    """登记变更与日志原子提交，对象类型区分两个独立词表的编号空间。"""
    operation = OperationType(f"{action}_{'robot' if kind == 'robots' else 'collection_term'}")
    return OperationEvent(
        context.now,
        actor,
        operation,
        ObjectRef(_OBJECT_KINDS[kind], str(row.id), row.name),
        OperationResult.SUCCESS,
        None,
        context.audit,
        OperationDetails(before=AuditValues(), after=AuditValues()),
    )


def save_record(
    session: Session,
    kind: RegistryKind,
    value: RobotInput | MethodInput | PurposeInput,
    *,
    identifier: int | None,
    context: ChangeContext,
) -> RegistryRecord:
    """创建或完整修改登记对象，保留永久编号和创建身份。

    Args:
        session: 已持 BEGIN IMMEDIATE 写锁的业务会话，由调用者提交。
        kind: 与 value 对应的 robots、methods 或 purposes。
        value: 已验证的完整字段；机器人 MAC 至多8项，端口1至65535。
        identifier: None 表示创建；正整数表示更新已存在对象，允许停用对象。
        context: 本次创建或编辑的认证身份、UTC时刻和审计来源，必填。

    Returns:
        更新后的独立快照；创建状态为 active，修改保持原状态。

    Raises:
        CollectionNotFoundError: 修改目标不存在。
        ConflictError: 名称、非空序列号或规范 MAC 已占用，包括停用对象。
        AuthenticationError: 当前会话或账号已失效。
        PasswordChangeRequiredError: 账号必须先改密码。
        SQLAlchemyError: 写入或审计失败，由调用者事务边界映射。

    Side Effects:
        新增或更新登记表并同事务追加一条操作日志；失败由调用者回滚，不提交部分对象。

    Time Semantics:
        先在写锁内重验身份、读取目标和查重，再写入及审计；修改时刻取原值与 now 较晚者。
        不自行申请事务、轮询或重试。
    """
    now = context.now
    actor = authorize_job_actor(session, context.identity, now=now)
    row = None if identifier is None else _get(session, kind, identifier)
    _unique(session, kind, value, identifier)
    if row is None:
        row = _MODELS[kind](
            status="active",
            created_by_id=actor.account_id,
            created_by_name=actor.name,
            created_at=now,
            updated_at=now,
        )
        session.add(row)
    for key, field in value.model_dump(mode="json").items():
        setattr(row, key, field)
    row.updated_by_id, row.updated_by_name = actor.account_id, actor.name
    row.updated_at = max(row.updated_at, now)
    session.flush()
    append_operation(
        session, _event(kind, row, "create" if identifier is None else "update", actor, context)
    )
    return _record(session, kind, row)


def set_status(
    session: Session,
    kind: RegistryKind,
    identifier: int,
    status: RegistryStatus,
    *,
    context: ChangeContext,
) -> RegistryRecord:
    """停用或恢复登记对象，同时记录最后修改人及操作日志。

    Args:
        session: 已取得写锁的业务会话，调用者负责提交。
        kind: robots、methods 或 purposes。
        identifier: 目标正整数编号。
        status: retired 表示停用，active 表示恢复。
        context: 本次启停请求的认证身份、UTC时刻及审计来源。

    Returns:
        状态变更后的独立快照，引用数和创建身份保留。

    Raises:
        CollectionNotFoundError: 编号不存在。
        AuthenticationError: 账号或会话已失效。
        PasswordChangeRequiredError: 当前账号须改密码。
        SQLAlchemyError: 状态或日志写入失败，由外层数据库边界映射。

    Side Effects:
        更新状态、修改人及时刻，并追加一条停用或恢复日志；失败随调用者事务回滚。

    Time Semantics:
        同事务先核验身份再修改，更新时间不倒退；不等外部资源或执行重试。
    """
    now = context.now
    actor = authorize_job_actor(session, context.identity, now=now)
    row = _get(session, kind, identifier)
    row.status = status
    row.updated_by_id, row.updated_by_name = actor.account_id, actor.name
    row.updated_at = max(row.updated_at, now)
    session.flush()
    append_operation(
        session, _event(kind, row, "retire" if status == "retired" else "restore", actor, context)
    )
    return _record(session, kind, row)


def delete_record(
    session: Session, kind: RegistryKind, identifier: int, *, context: ChangeContext
) -> None:
    """删除未被数据集引用的登记对象，保留其操作日志及编号高水位。

    Args:
        session: 已取得写锁的业务会话。
        kind: robots、methods 或 purposes。
        identifier: 已登记对象的正整数编号。
        context: 删除请求的认证身份、UTC时刻和审计来源。

    Returns:
        无；提交后对象不再出现在列表。

    Raises:
        CollectionNotFoundError: 编号不存在。
        ConflictError: 对象仍被数据集引用，提示改用停用。
        AuthenticationError: 账号或会话已失效。
        PasswordChangeRequiredError: 账号须改密码。
        SQLAlchemyError: 删除或审计失败，由调用者事务边界映射。

    Side Effects:
        删除一行并同事务记录原编号及名称；失败整体回滚，成功后编号不会复用。

    Time Semantics:
        先重验身份、定位对象并检查引用，再审计和删除；写锁保护全部步骤，无重试。
    """
    now = context.now
    actor = authorize_job_actor(session, context.identity, now=now)
    row = _get(session, kind, identifier)
    if reference_count(session, kind, identifier) > 0:
        error = _problem(
            ConflictError, "reference_count", "已被数据集引用，不能删除", "请改用停用，保留历史引用"
        )
        raise error
    append_operation(session, _event(kind, row, "delete", actor, context))
    session.delete(row)
    session.flush()
