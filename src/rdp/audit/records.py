"""日志追加和读取契约（领域层，07），共享调用者的事务，不负责鉴权或提交。

SQLAlchemy/UTCDateTime 负责存取和 UTC；错误沿用基础层四类，不记录运行日志。
只提供记录结果、查询和设置保留期；等待期仅累加首条日志的次数，不改写原结果、来源或时间。
"""

from datetime import datetime
from typing import cast

from sqlalchemy import ColumnElement, select
from sqlalchemy.orm import Session

from rdp.audit import _query as queries
from rdp.audit import _validation as validate
from rdp.audit._context import validate_context
from rdp.audit._storage import operation
from rdp.audit.models import AuditSettingsRow, LoginLogRow, OperationLogRow
from rdp.audit.policy import DEFAULT_RETENTION_DAYS, MAX_RETENTION_DAYS, MIN_RETENTION_DAYS
from rdp.audit.types import (
    AuditValues,
    ExistingAccounts,
    LoginEvent,
    LoginKind,
    LoginQuery,
    LoginResult,
    LoginView,
    LogPage,
    ObjectRef,
    OperationDetails,
    OperationEvent,
    OperationQuery,
    OperationResult,
    OperationType,
    OperationView,
    RetentionChange,
)
from rdp.infra.db.validation import invalid_field


def append_operation(session: Session, event: OperationEvent) -> int:
    """在业务写事务中追加并 flush 一条操作结果。

    Args:
        session: session_scope 已获 BEGIN IMMEDIATE 的写 Session，不可空、不可并发使用。
        event: 不含秘密的 OperationEvent；成功无失败类别，失败必须有类别且 after 为空；
            明细版本 1，字段受 OPERATION_DETAIL_FIELDS 限制，UTF-8 至多 MAX_DETAILS_BYTES。

    Returns:
        新日志编号，1 至 2^63-1；未提交前不得向调用方宣称操作成功。

    Raises:
        AuditInputError: 事件类型、身份/对象编号、时刻、操作枚举、明细或结果组合非法；不回显拒绝值。
        InputError: 数据库或 UTC 数据损坏。
        ConflictError: 插入锁或约束冲突。
        ExternalError: 数据库 I/O 失败。
        DefectError: event.context 不是合法 AuditContext（含非法 IP 或请求编号）、只读/非受管会话或 SQL/映射错误；安全异常链不含参数。

    Side Effects:
        操作人允许账号、OPS_ACTOR 或 SYSTEM_ACTOR；空编号只能是两个固定身份。
        当前事务追加一行并 flush；不 commit、不另开事务、不修改已有日志。
        任意失败须由调用者退出整个工作单元回滚；成功日志与业务同时提交，回滚后两者均不留。
        操作人及对象取业务重读的名字快照，不按当前名字覆盖历史。

    Time Semantics:
        只使用 event.occurred_at，aware 输入转换 UTC 并保留微秒，不取系统时钟。
        回拨不拒绝或修正事件时间；事务已获锁，本函数不额外等待锁或重试。
    """
    event = validate.operation(event)
    with operation(session, write=True):
        row = OperationLogRow(
            occurred_at=event.occurred_at,
            actor_id=event.actor.account_id,
            actor_name=event.actor.name,
            operation=event.operation.value,
            object_kind=event.target.kind,
            object_id=event.target.object_id,
            object_name=event.target.name,
            result=event.result.value,
            failure_category=None
            if event.failure_category is None
            else event.failure_category.value,
            request_id=event.context.request_id,
            source_ip=event.context.source_ip,
            details=event.details.model_dump(mode="json", exclude_none=True),
        )
        session.add(row)
        session.flush()
        return row.log_id


def append_login(
    session: Session, event: LoginEvent, *, waiting_until: datetime | None = None
) -> int:
    """在登录事务里记录结果，同一等待期的重复尝试累加到首条日志。

    Args:
        session: 已获锁的受管写 Session，不可空、不可并发。
        event: 已确认结果的 LoginEvent；未知账号的 account/login_name/request_id 必须为空；
            logout/session_expired 结果必须为 success，已知账号编号和快照必填；
            FAILURE 必须带四类失败类别，其余结果不带类别；未确认身份的 FAILURE 身份和请求编号均为空。

        waiting_until: 已确认账号等待期的UTC截止；None不合并，等待结束后的新尝试另起记录。

    Returns:
        已 flush 但尚未提交的正整数日志编号；合并时返回首条编号。

    Raises:
        AuditInputError: 登录事件的类型、账号快照、时间或类型/结果组合非法，不回显输入原文。
        InputError: 数据库或 UTC 数据损坏。
        ConflictError: 插入锁或约束冲突。
        ExternalError: 数据库 I/O 失败。
        DefectError: 登录事件上下文类型/IP/请求编号非法，或不满足匿名事件去编号要求；以及非受管写会话、SQL/映射错误。

    Side Effects:
        普通结果追加一行；同一账号和等待截止的WAITING结果只累加attempt_count，保留首条时间和来源。
        不提交；与 G2 计数、会话签发或实际删除同时提交/回滚。
        不写口令、口令哈希、令牌、摘要、cookie，不为未知登录名创建账号。
        未获短锁的过期删除不调用本函数；并发已经删除的会话不重复记。

    Time Semantics:
        使用注入事件时间转换 UTC，保留微秒；回拨不拒绝，不重写历史。
        调用者已持有写锁，无额外获锁或自动重试。
    """
    event = validate.login(event)
    with operation(session, write=True):
        if event.result is LoginResult.WAITING and waiting_until is not None:
            previous = session.scalar(
                select(LoginLogRow).where(
                    LoginLogRow.account_id
                    == (None if event.account is None else event.account.account_id),
                    LoginLogRow.kind == LoginKind.LOGIN.value,
                    LoginLogRow.result == LoginResult.WAITING.value,
                    LoginLogRow.waiting_until == waiting_until,
                )
            )
            if previous is not None:
                previous.attempt_count += 1
                session.flush()
                return previous.log_id
        row = LoginLogRow(
            waiting_until=waiting_until if event.result is LoginResult.WAITING else None,
            occurred_at=event.occurred_at,
            account_id=None if event.account is None else event.account.account_id,
            account_name=None if event.account is None else event.account.name,
            login_name=event.login_name,
            kind=event.kind.value,
            result=event.result.value,
            source_ip=event.context.source_ip,
            request_id=event.context.request_id,
            failure_category=None
            if event.failure_category is None
            else event.failure_category.value,
        )
        session.add(row)
        session.flush()
        return row.log_id


def query_operations(
    session: Session, query: OperationQuery, existing_accounts: ExistingAccounts
) -> LogPage[OperationView]:
    """按时间、操作人、对象账号、类型和结果交集查询操作日志。

    Args:
        session: 已完成管理员重验的受管只读事务，不可空，不能升级写事务。
        query: start 含下界/end 不含上界，aware 输入转 UTC，start 必须小于 end；
            common.account_id 筛选操作人，target_account_id 筛选 kind=account 的对象编号，二者均可独立省略；
            同时提供按 AND 取交集，不按当前名字或账号存在性过滤；设置对象和空对象编号不匹配对象账号条件。
            分页 1 至 AUDIT_PAGE_LIMIT 项，两个账号编号都必须是非 bool 的 1 至 2^63-1 整数。
        existing_accounts: 上层适配器；同 Session 批量查本页操作人/账号对象编号，至多 2*limit 个，
            返回仍存在的编号，不查询名字、不另开事务、不修改数据。

    Returns:
        时间倒序、同时间编号倒序的页，允许为空；仅编号不存在才标 deleted，运维不标。
        游标为有版本的 base64url JSON，含末项 UTC 时间/编号、首页最大编号和规范化筛选 SHA-256；
        limit、日志种类、操作人及对象账号两项筛选均纳入摘要；改变任一账号条件必须重开首页。
        后页满足 id<=首页最大编号及键严格小于末项。
        有下一页才给 next_cursor；刷新首页可看到并发新增，清除导致的空缺不补造记录。

    Raises:
        AuditInputError: naive/溢出/倒置区间、非法编号/枚举/limit，游标超长、畸形、版本未知、
            与当前筛选不匹配或内部键越界；不回显游标载荷。
        InputError: 数据库、时刻或已存明细损坏；不跳过坏行而制造完整结果假象。
        ConflictError: 查询锁冲突。
        ExternalError: 数据库读取或清理 I/O 失败。
        DefectError: SQL/映射错误，或存在性适配器返回请求集合以外编号、写库或其他程序错误。

    Side Effects:
        无（只读日志和账号存在性）；不因账号改名改写历史，不按保留期隐藏尚未清除的记录。

    Time Semantics:
        查询只比较记录 UTC 绝对时刻，不使用墙钟或“最近访问”水位；时间上界未传即无上界。
        因而回拨不漏查未来时间戳，也不把新追加的旧时间记录夹进已开始的翻页。
        同页身份存在性与日志使用同一读快照；普通 SQLite 单次锁等待最多 5000 毫秒，无重试。
    """
    if not isinstance(cast(object, query), OperationQuery):
        failure = validate.invalid("query")
        raise failure
    if query.operation is not None and not isinstance(cast(object, query.operation), OperationType):
        failure = validate.invalid("operation")
        raise failure
    if query.result is not None and not isinstance(cast(object, query.result), OperationResult):
        failure = validate.invalid("result")
        raise failure
    if query.target_account_id is not None:
        validate.identifier(query.target_account_id)
    plan = queries.prepare(
        query.common,
        {
            "kind": "operations",
            "operation": query.operation,
            "result": query.result,
            "target": query.target_account_id,
        },
    )
    filters: list[ColumnElement[bool]] = []
    if query.common.account_id is not None:
        filters.append(OperationLogRow.actor_id == query.common.account_id)
    if query.target_account_id is not None:
        filters.extend(
            (
                OperationLogRow.object_kind == "account",
                OperationLogRow.object_id == str(query.target_account_id),
            )
        )
    if query.operation is not None:
        filters.append(OperationLogRow.operation == query.operation.value)
    if query.result is not None:
        filters.append(OperationLogRow.result == query.result.value)
    with operation(session):
        found, maximum = queries.rows(session, OperationLogRow, plan, filters)
        selected = found[: plan.common.limit]
        events = tuple(queries.operation_event(row) for row in selected)
        identifiers = frozenset(
            key
            for item in events
            for key in (
                item.actor.account_id,
                int(item.target.object_id)
                if item.target.kind == "account" and item.target.object_id is not None
                else None,
            )
            if key is not None
        )
        present = queries.existing(session, identifiers, existing_accounts)
        items = tuple(
            OperationView(
                row.log_id,
                item,
                item.actor.account_id is not None and item.actor.account_id not in present,
                item.target.kind == "account"
                and item.target.object_id is not None
                and int(item.target.object_id) not in present,
            )
            for row, item in zip(selected, events, strict=True)
        )
        cursor = (
            queries.encode(selected[-1], maximum, plan.fingerprint)
            if len(found) > len(selected)
            else None
        )
        return LogPage(items, cursor)


def query_logins(
    session: Session, query: LoginQuery, existing_accounts: ExistingAccounts
) -> LogPage[LoginView]:
    """按时间、账号、登录类型和结果交集查询登录日志。

    Args:
        session: 已完成管理员重验的受管只读事务，不可空。
        query: aware 时间范围 [start,end)，None 为无界；账号按内部编号筛选；limit 为 1 至 100。
        existing_accounts: 同 Session 的上层批量存在性查询，最多 limit 个编号，结果须为输入子集。

    Returns:
        (occurred_at DESC, log_id DESC) 的页；未知账号显示“账号不存在”，不合成登录名。
        已删账号保留当时显示名/登录名并标 account_deleted；同名重建不能接管记录。
        游标沿用 query_operations 的版本、筛选绑定和首页编号上界规则，末页为 None。

    Raises:
        AuditInputError: 区间、时区、编号、limit、枚举或游标不合格；跨日志种类/筛选复用游标拒绝。
        InputError: 数据库、UTC 列或存量登录事件的身份/结果组合损坏。
        ConflictError: 查询锁冲突。
        ExternalError: 数据库读取或结束事务 I/O 失败。
        DefectError: SQL/映射或存在性回调错误。

    Side Effects:
        无（只读登录日志和本页账号编号的存在性）；不触发账号/G2/会话写入。

    Time Semantics:
        UTC 微秒区间，不读当前时钟；回拨不排除未来记录。按固定键排序，不以插入时长算顺序。
        每次查询一个只读快照，SQLite 单次锁等待最多 5000 毫秒，不重试、不轮询。
    """
    if not isinstance(cast(object, query), LoginQuery):
        failure = validate.invalid("query")
        raise failure
    if query.kind is not None and not isinstance(cast(object, query.kind), LoginKind):
        failure = validate.invalid("kind")
        raise failure
    if query.result is not None and not isinstance(cast(object, query.result), LoginResult):
        failure = validate.invalid("result")
        raise failure
    plan = queries.prepare(
        query.common, {"kind": "logins", "event_kind": query.kind, "result": query.result}
    )
    filters: list[ColumnElement[bool]] = []
    if query.common.account_id is not None:
        filters.append(LoginLogRow.account_id == query.common.account_id)
    if query.kind is not None:
        filters.append(LoginLogRow.kind == query.kind.value)
    if query.result is not None:
        filters.append(LoginLogRow.result == query.result.value)
    with operation(session):
        found, maximum = queries.rows(session, LoginLogRow, plan, filters)
        selected = found[: plan.common.limit]
        events = tuple(queries.login_event(row) for row in selected)
        identifiers = frozenset(
            item.account.account_id
            for item in events
            if item.account is not None and item.account.account_id is not None
        )
        present = queries.existing(session, identifiers, existing_accounts)
        items = tuple(
            LoginView(
                row.log_id,
                item,
                item.account is not None and item.account.account_id not in present,
                row.attempt_count,
            )
            for row, item in zip(selected, events, strict=True)
        )
        cursor = (
            queries.encode(selected[-1], maximum, plan.fingerprint)
            if len(found) > len(selected)
            else None
        )
        return LogPage(items, cursor)


def get_retention(session: Session) -> int:
    """读取两种日志共用的数据库保留期，未设置时返回批准的默认值。

    Args:
        session: 受管读或写 Session，不可空；权限由上层处理。

    Returns:
        7-365 的整数天数；无设置行时为 DEFAULT_RETENTION_DAYS=30，损坏行不能回退默认。

    Raises:
        InputError: 保留期行值越界、非整数或数据库损坏。
        ConflictError: 读取锁冲突。
        ExternalError: 读取 I/O 故障。
        DefectError: 非受管 Session、SQL 或映射错误。

    Side Effects:
        无（只读设置），无行不补建，不与运行日志/作业日志/报错表保留期混用。

    Time Semantics:
        天定义为 UTC 24 小时，不按本机日历或 DST 换算；不读时钟。
        沿用工作单元单次 5000 毫秒锁上限，无重试。
    """
    with operation(session):
        row = session.get(AuditSettingsRow, 1)
        if row is None:
            return DEFAULT_RETENTION_DAYS
        if (
            type(row.retention_days) is not int
            or not MIN_RETENTION_DAYS <= row.retention_days <= MAX_RETENTION_DAYS
        ):
            failure = invalid_field("retention_days", "数据库保留期为7至365的整数天数")
            raise failure
        return row.retention_days


def change_retention(session: Session, change: RetentionChange) -> int:
    """在已授权写事务中修改共同保留期并追加该改动的操作日志。

    Args:
        session: BEGIN IMMEDIATE 内已由账号服务重验管理员的受管写 Session，不可空。
        change: days 为非 bool 整数 7-365，actor 是重验后的管理员，时间及来源已校验。

    Returns:
        生效天数；与当前有效值相同则不建设置行、不追加操作日志。

    Raises:
        AuditInputError: days、actor 或事件时间不满足保留期变更字段约束，不写设置。
        InputError: 既有设置损坏，不能以默认值掩盖。
        ConflictError: 设置或操作日志约束冲突。
        ExternalError: 设置、日志写入或 flush I/O 失败。
        DefectError: change.context 非法或缺少管理员请求编号，或非受管写 Session、SQL/映射错误。

    Side Effects:
        账号服务在管理员预检通过并进入写事务时已开始执行，本函数读取旧设置并判定是否有实际变化。
        保存设置并追加 SET_RETENTION 成功日志，before/after 各仅 retention_days，
        对象为 audit_settings/retention/日志保留期；调用方一次提交，失败必须整体回滚。
        执行后失败由上层在回滚后单独短事务补记 FAILURE；本函数不嵌套事务或清除日志。

    Time Semantics:
        事件时刻使用 change.occurred_at 的 UTC 微秒，回拨不拒绝变更。
        已持写锁，不另外获锁/重试；新设置仅影响下一次 purge_expired 的截止计算。
    """
    if not isinstance(cast(object, change), RetentionChange):
        failure = validate.invalid("retention")
        raise failure
    validate_context(change.context)
    validate.actor(change.actor)
    validate.identifier(change.actor.account_id)
    occurred_at = validate.moment(change.occurred_at)
    if type(change.days) is not int or not MIN_RETENTION_DAYS <= change.days <= MAX_RETENTION_DAYS:
        failure = validate.invalid("days")
        raise failure
    with operation(session, write=True):
        previous = get_retention(session)
        if change.days == previous:
            return previous
        row = session.get(AuditSettingsRow, 1)
        if row is None:
            row = AuditSettingsRow(settings_id=1, retention_days=change.days)
            session.add(row)
        else:
            row.retention_days = change.days
        append_operation(
            session,
            OperationEvent(
                occurred_at,
                change.actor,
                OperationType.SET_RETENTION,
                ObjectRef("audit_settings", "retention", "日志保留期"),
                OperationResult.SUCCESS,
                None,
                change.context,
                OperationDetails(
                    before=AuditValues(retention_days=previous),
                    after=AuditValues(retention_days=change.days),
                ),
            ),
        )
        return change.days
