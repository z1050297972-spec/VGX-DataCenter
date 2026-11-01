"""日志入口的参数与响应适配；只使用批准的schema，不把ORM或64位数字直接送往浏览器。"""

from rdp.api.audit_schemas import (
    HistoricalActorResponse,
    LogFilters,
    LoginResponse,
    ObjectResponse,
    OperationResponse,
)
from rdp.audit.errors import AuditInputError
from rdp.audit.types import LoginView, LogQuery, OperationView
from rdp.infra.actors import ActorRef
from rdp.infra.db.validation import invalid_field
from rdp.infra.diagnostics import DefectError
from rdp.infra.ids import MAX_SQLITE_INTEGER


def identifier(value: str | None, field: str) -> int | None:
    """转换已声明的十进制编号，并在SQL之前补上SQLite范围检查，不回显拒绝值。"""
    if value is None:
        return None
    if (
        not value.isascii()
        or not value.isdecimal()
        or len(value) > 19
        or str(int(value)) != value
        or not 1 <= int(value) <= MAX_SQLITE_INTEGER
    ):
        raise AuditInputError(invalid_field(field, "1至2^63-1的规范十进制编号").diagnostics)
    return int(value)


def common(filters: LogFilters) -> LogQuery:
    """将Pydantic筛选送往领域，时间区间及游标绑定仍由领域校验。"""
    return LogQuery(
        filters.start,
        filters.end,
        identifier(filters.account_id, "account_id"),
        filters.cursor,
        filters.limit,
    )


def actor(value: ActorRef, deleted: bool) -> HistoricalActorResponse:
    """编号用字符串保留精度，运维与已删除身份的标记不能混淆。"""
    return HistoricalActorResponse(
        account_id=None if value.account_id is None else str(value.account_id),
        name=value.name,
        deleted=deleted,
    )


def operation(value: OperationView) -> OperationResponse:
    """序列化已校验的操作快照，输出映射失败按程序缺陷处理。"""
    try:
        event = value.event
        return OperationResponse(
            log_id=str(value.log_id),
            occurred_at=event.occurred_at,
            actor=actor(event.actor, value.actor_deleted),
            operation=event.operation,
            target=ObjectResponse(
                kind=event.target.kind,
                object_id=event.target.object_id,
                name=event.target.name,
                deleted=value.target_deleted,
            ),
            result=event.result,
            failure_category=event.failure_category,
            request_id=event.context.request_id,
            source_ip=event.context.source_ip,
            details=event.details,
        )
    except (ValueError, TypeError, AttributeError):
        raise DefectError() from None


def login(value: LoginView) -> LoginResponse:
    """序列化登录记录；匿名记录保持空身份，不拼接或猜测输入过的登录名。"""
    try:
        event = value.event
        return LoginResponse(
            log_id=str(value.log_id),
            occurred_at=event.occurred_at,
            account=None if event.account is None else actor(event.account, value.account_deleted),
            login_name=event.login_name,
            kind=event.kind,
            result=event.result,
            source_ip=event.context.source_ip,
            request_id=event.context.request_id,
            failure_category=event.failure_category,
            attempt_count=value.attempt_count,
        )
    except (ValueError, TypeError, AttributeError):
        raise DefectError() from None
