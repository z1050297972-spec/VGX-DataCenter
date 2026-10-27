"""日志 HTTP 字段声明（07），编号用文本保留 64 位精度，前端从 OpenAPI 生成类型。

明细直接复用领域白名单，不另造可装载秘密的 JSON 类型；未知账号身份为空。
删除标记与历史名字分开传输，由页面安全显示“名字（已删除）”，不接受写日志请求体。
"""

from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from rdp.api.account_schemas import AccountId, DisplayName, LoginName
from rdp.audit.policy import (
    AUDIT_CURSOR_MAX_CHARS,
    AUDIT_PAGE_LIMIT,
    MAX_RETENTION_DAYS,
    MIN_RETENTION_DAYS,
)
from rdp.audit.types import LoginKind, LoginResult, OperationDetails, OperationResult, OperationType
from rdp.infra.diagnostics import DiagnosticCategory

CursorText = Annotated[str, Field(min_length=1, max_length=AUDIT_CURSOR_MAX_CHARS)]


class AuditPayload(BaseModel):
    """日志的共同字段策略，不回显错误输入。

    Attributes:
        model_config: frozen/extra=forbid/hide_input_in_errors 固定配置。
    """

    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)


class LogFilters(AuditPayload):
    """两个列表共用的 query 字段；字符串编号不能经 JS Number。

    Attributes:
        start: aware ISO 8601 时刻，含下界；默认 None，无下界。
        end: aware ISO 8601 时刻，不含上界且晚于 start；默认 None，无上界。
        account_id: 1 至 2^63-1 的规范十进制文本；默认 None，全部账号，含历史已删编号。
        cursor: 上一页返回的 opaque 游标，1-512 字符；默认 None，首页。
        limit: 整数 1 至 AUDIT_PAGE_LIMIT，默认 AUDIT_PAGE_LIMIT。
    """

    start: AwareDatetime | None = None
    end: AwareDatetime | None = None
    account_id: AccountId | None = None
    cursor: CursorText | None = None
    limit: int = Field(default=AUDIT_PAGE_LIMIT, ge=1, le=AUDIT_PAGE_LIMIT)


class OperationFilters(LogFilters):
    """操作日志筛选，继承时间、操作人 account_id 和游标，可同时限定对象账号。

    Attributes:
        operation: OperationType；默认 None，全部。
        result: success/failure；默认 None，全部。
        target_account_id: 对象账号的规范十进制编号，1 至 2^63-1；默认 None，不限制对象。
            仅匹配 account 类型对象；与操作人 account_id 取交集，已删除编号仍可查询。
    """

    operation: OperationType | None = None
    result: OperationResult | None = None
    target_account_id: AccountId | None = None


class LoginFilters(LogFilters):
    """登录日志筛选，继承时间、账号编号和游标。

    Attributes:
        kind: login/logout/session_expired；默认 None，全部。
        result: LoginResult；默认 None，全部。
    """

    kind: LoginKind | None = None
    result: LoginResult | None = None


class HistoricalActorResponse(AuditPayload):
    """不可变历史身份和本次查询所得的删除标记。

    Attributes:
        account_id: 正整数十进制文本；运维或系统 None，未知登录账号不构造本对象。
        name: 当时显示名，1-64 码点；空编号固定为“运维”或“系统”。
        deleted: 当前快照编号不存在为 True；运维/系统 False，必填。
    """

    account_id: AccountId | None
    name: DisplayName
    deleted: bool


class ObjectResponse(AuditPayload):
    """对象的历史名字，保留给未来撤回功能定位。

    Attributes:
        kind: account/audit_settings/job，必填；job 不表示账号。
        object_id: 账号/作业编号十进制文本或设置键 retention；失败新建尚无编号时 None。
        name: 当时显示名、固定设置名或“作业显示名 #编号”，1-64 码点，必填。
        deleted: 账号编号已不存在为 True；设置、作业或未分配编号为 False。
    """

    kind: Literal["account", "audit_settings", "job"]
    object_id: str | None = Field(max_length=64)
    name: DisplayName
    deleted: bool


class OperationResponse(AuditPayload):
    """一条安全的操作日志，不返回异常文本或当前名字代替快照。

    Attributes:
        log_id: 正整数十进制文本，1 至 2^63-1，必填。
        occurred_at: aware UTC ISO 8601，微秒，必填。
        actor: 历史 ActorRef 和删除标记，必填。
        operation: 稳定具名操作类型，必填。
        target: 对象快照，必填。
        result: success/failure，必填。
        failure_category: 失败四类之一；成功 None。
        request_id: 当前请求 uuid4 hex；运维 None。
        source_ip: 规范 IPv4/IPv6；不可获得或运维 None。
        details: 版本 1 的 before/after 白名单 JSON，必填。
    """

    log_id: AccountId
    occurred_at: AwareDatetime
    actor: HistoricalActorResponse
    operation: OperationType
    target: ObjectResponse
    result: OperationResult
    failure_category: DiagnosticCategory | None
    request_id: str | None = Field(min_length=32, max_length=32)
    source_ip: str | None = Field(max_length=45)
    details: OperationDetails


class LoginResponse(AuditPayload):
    """一条登录日志；未知账号不输出输入的登录名。

    Attributes:
        log_id: 正整数十进制编号，必填。
        occurred_at: aware UTC ISO 8601，微秒，必填。
        account: 已确认历史身份；未知账号 None。
        login_name: 已存账号登录名；未知账号 None。
        kind: 登录、登出或过期删除类型，必填。
        result: LoginResult，必填。
        source_ip: ASGI client 的 IP；缺失 None。
        request_id: 请求编号；未知账号 None。
        failure_category: 执行故障的四类类别；其他结果 None，不带内部异常文本。
    """

    log_id: AccountId
    occurred_at: AwareDatetime
    account: HistoricalActorResponse | None
    login_name: LoginName | None
    kind: LoginKind
    result: LoginResult
    source_ip: str | None = Field(max_length=45)
    request_id: str | None = Field(min_length=32, max_length=32)
    failure_category: DiagnosticCategory | None


class OperationListResponse(AuditPayload):
    """操作日志的倒序游标页。

    Attributes:
        items: 0 至 AUDIT_PAGE_LIMIT 个操作日志，时间/编号倒序。
        next_cursor: 下一页 opaque 游标；末页 None。
    """

    items: tuple[OperationResponse, ...] = Field(max_length=AUDIT_PAGE_LIMIT)
    next_cursor: CursorText | None


class LoginListResponse(AuditPayload):
    """登录日志的倒序游标页。

    Attributes:
        items: 0 至 AUDIT_PAGE_LIMIT 个登录日志，时间/编号倒序。
        next_cursor: 下一页 opaque 游标；末页 None。
    """

    items: tuple[LoginResponse, ...] = Field(max_length=AUDIT_PAGE_LIMIT)
    next_cursor: CursorText | None


class RetentionPayload(AuditPayload):
    """保留期请求及响应的相同字段，不开放其他设置。

    Attributes:
        days: 严格非 bool 整数，MIN_RETENTION_DAYS 至 MAX_RETENTION_DAYS，单位天，必填。
    """

    days: int = Field(strict=True, ge=MIN_RETENTION_DAYS, le=MAX_RETENTION_DAYS)
