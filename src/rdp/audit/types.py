"""日志领域的类型和版本化明细（07/H1-H3），不含 ORM、HTTP 或秘密字段。

明细用已有 Pydantic 的 extra=forbid 拒绝未知字段，再由追加边界按操作类型收紧白名单。
不接收任意 JSON 或异常消息；before/after 留给 M1 撤回，失败记录的 after 必须为空。
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from rdp.audit.policy import (
    AUDIT_PAGE_LIMIT,
    DETAILS_VERSION,
    MAX_RETENTION_DAYS,
    MIN_RETENTION_DAYS,
)
from rdp.infra.actors import DISPLAY_NAME_MAX_CHARS, ActorRef
from rdp.infra.diagnostics import DiagnosticCategory


class OperationType(StrEnum):
    """稳定的操作码；新增操作用新增枚举值，不改历史值（第 8 张可增加作业操作）。"""

    CREATE_ACCOUNT = "create_account"
    SET_ROLE = "set_role"
    DISABLE_ACCOUNT = "disable_account"
    ENABLE_ACCOUNT = "enable_account"
    RESET_PASSWORD = "reset_password"  # noqa: S105  # 理由：稳定操作/结果码，不是口令。
    RESET_PASSWORD_FROM_OPS = "reset_password_from_ops"  # noqa: S105  # 理由：稳定操作/结果码，不是口令。
    DELETE_ACCOUNT = "delete_account"
    CHANGE_PASSWORD = "change_password"  # noqa: S105  # 理由：稳定操作/结果码，不是口令。
    CREATE_FIRST_ADMIN = "create_first_admin"
    SET_RETENTION = "set_retention"
    SUBMIT_JOB = "submit_job"
    CANCEL_JOB = "cancel_job"
    # M1-03：布局是当前账号偏好，复用account对象，不新增日志表对象种类。
    SET_DATASET_LAYOUT = "set_dataset_layout"


class OperationResult(StrEnum):
    """操作是否提交；失败类别另存 DiagnosticCategory，不拼接异常文本。"""

    SUCCESS = "success"
    FAILURE = "failure"


class LoginKind(StrEnum):
    """只记录登录、显式登出及访问触发的过期删除，不将管理撤销冒充登出。"""

    LOGIN = "login"
    LOGOUT = "logout"
    SESSION_EXPIRED = "session_expired"


class LoginResult(StrEnum):
    """登录验证结果；第五次错口令仍是 wrong_password，执行故障单列 failure，不伪造凭据结论。"""

    SUCCESS = "success"
    WRONG_PASSWORD = "wrong_password"  # noqa: S105  # 理由：稳定操作/结果码，不是口令。
    DISABLED = "disabled"
    WAITING = "waiting"
    ACCOUNT_MISSING = "account_missing"
    FAILURE = "failure"


class AuditValues(BaseModel):
    """v1 的平面白名单，秘密无字段可容纳；None 表示未提供，序列化时排除。

    Attributes:
        model_config: frozen/extra=forbid/hide_input_in_errors；未知字段拒绝且不回显值。
        login_name: 已确认账号的登录名，3-32 字符；默认 None，不接受未知输入原文。
        display_name: 已确认账号的显示名，1-64 码点；默认 None。
        role: administrator/member；默认 None，不含权限令牌。
        status: enabled/disabled；默认 None。
        must_change_password: 严格布尔；默认 None，仅表示强制改密标记。
        retention_days: 严格整数 7-365 天；默认 None。
        job_id: 作业正编号的规范十进制文本，最大 2^63-1；默认 None。
        job_type: 稳定英文类型键，1-64 字符；默认 None，不存显示名或参数。
        job_state: jobs.JobState 的稳定英文码，before/after 分别存前后状态；默认 None。
        resubmitted_from: 原作业正编号文本；仅重新提交的 after 提供，默认 None。
        dataset_layout: 当前账号的数据集布局A/B/C；仅SET_DATASET_LAYOUT使用，默认None。
    """

    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)
    login_name: str | None = Field(default=None, strict=True, min_length=3, max_length=32)
    display_name: str | None = Field(
        default=None, strict=True, min_length=1, max_length=DISPLAY_NAME_MAX_CHARS
    )
    role: Literal["administrator", "member"] | None = None
    status: Literal["enabled", "disabled"] | None = None
    must_change_password: bool | None = Field(default=None, strict=True)
    retention_days: int | None = Field(
        default=None, strict=True, ge=MIN_RETENTION_DAYS, le=MAX_RETENTION_DAYS
    )

    job_id: str | None = Field(default=None, strict=True, pattern=r"^[1-9][0-9]{0,18}$")
    job_type: str | None = Field(default=None, strict=True, min_length=1, max_length=64)
    job_state: str | None = Field(default=None, strict=True, min_length=1, max_length=16)
    resubmitted_from: str | None = Field(default=None, strict=True, pattern=r"^[1-9][0-9]{0,18}$")
    dataset_layout: Literal["A", "B", "C"] | None = None


class OperationDetails(BaseModel):
    """v1 JSON 格式为 {version: 1, before: {...}, after: {...}}，不存执行命令。

    Attributes:
        model_config: frozen/extra=forbid/hide_input_in_errors，固定配置。
        version: 当前仅接受整数 1，无单位，默认 DETAILS_VERSION；bool 非法。
        before: 改动前已确认的白名单值，必填；新建为空对象。
        after: 成功提交的白名单值，必填；删除或失败为空对象，不能暗示失败改动已生效。
    """

    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)
    version: int = Field(default=DETAILS_VERSION, strict=True, ge=1, le=1)
    before: AuditValues
    after: AuditValues


# 规则集中定义，追加、查询解码和 HTTP schema 复用同一模型；未列的字段拒绝，不静默丢弃。
ACCOUNT_DETAIL_FIELDS = frozenset(
    {"login_name", "display_name", "role", "status", "must_change_password"}
)
OPERATION_DETAIL_FIELDS: dict[OperationType, frozenset[str]] = {
    OperationType.CREATE_ACCOUNT: ACCOUNT_DETAIL_FIELDS,
    OperationType.CREATE_FIRST_ADMIN: ACCOUNT_DETAIL_FIELDS,
    OperationType.DELETE_ACCOUNT: ACCOUNT_DETAIL_FIELDS,
    OperationType.SET_ROLE: frozenset({"role"}),
    OperationType.DISABLE_ACCOUNT: frozenset({"status"}),
    OperationType.ENABLE_ACCOUNT: frozenset({"status"}),
    OperationType.RESET_PASSWORD: frozenset({"must_change_password"}),
    OperationType.RESET_PASSWORD_FROM_OPS: frozenset({"must_change_password"}),
    OperationType.CHANGE_PASSWORD: frozenset({"must_change_password"}),
    OperationType.SET_RETENTION: frozenset({"retention_days"}),
    OperationType.SUBMIT_JOB: frozenset({"job_id", "job_type", "job_state", "resubmitted_from"}),
    OperationType.CANCEL_JOB: frozenset({"job_id", "job_type", "job_state"}),
    OperationType.SET_DATASET_LAYOUT: frozenset({"dataset_layout"}),
}


@dataclass(frozen=True)
class AuditContext:
    """入口明确传递的来源；遗漏必填参数为 TypeError，传入非法值为 DefectError。

    HTTP 服务要求有效服务器请求编号；IP 无法取得可以为空，不允许用空上下文掩盖漏传。
    未知账号登录事件按 H2 去掉编号是显式脱敏；运维两个字段为空，由 OPS_AUDIT_CONTEXT 表达。

    Attributes:
        source_ip: ASGI client 的 IPv4/IPv6 地址，规范化文本，最长 45 字符；无 client 或运维为 None。
            只接受 ipaddress 可解析的无作用域 IP；非法 ASGI 地址记空，不信任 X-Forwarded-For。
        request_id: 当前服务器生成的 uuid4 hex（32 位），运维为 None；不采信客户端同名头。
    """

    source_ip: str | None
    request_id: str | None


# 运维没有 ASGI 来源或请求编号，必须显式传此不可变值，不能将它用作服务参数默认值。
OPS_AUDIT_CONTEXT = AuditContext(source_ip=None, request_id=None)


@dataclass(frozen=True)
class ObjectRef:
    """操作对象的独立快照，不建立会随账号删除而消失的外键。

    Attributes:
        kind: account、audit_settings 或 job；旧值含义不变（08 批准扩展）。
        object_id: account/job 为 1 至 2^63-1 的十进制文本；失败新建尚未分配编号为 None；设置固定 retention。
        name: 已确认显示名或固定“日志保留期”，1-64 码点；job 为“显示名 #编号”，最多 61 码点；失败新建account固定“新账号”，job尚无编号固定“新作业”，不抄输入。
    """

    kind: Literal["account", "audit_settings", "job"]
    object_id: str | None
    name: str


@dataclass(frozen=True)
class OperationEvent:
    """待追加的操作结果，不携带会话或异常对象。

    Attributes:
        occurred_at: 入口注入的 aware 时刻，转换 UTC 保存微秒，必填。
        actor: 第 6 张 ActorRef；运维为 ActorRef(None, "运维")，必填。
        operation: OperationType，必填，稳定码。
        target: 对象类型、编号及名字快照，必填。
        result: success 或 failure，必填。
        failure_category: 失败必填四类之一，成功必须为 None；不存异常消息。
        context: 显式来源及请求编号，必填。
        details: 按操作码限制的 v1 before/after JSON，必填，UTF-8 最多 MAX_DETAILS_BYTES。
    """

    occurred_at: datetime
    actor: ActorRef
    operation: OperationType
    target: ObjectRef
    result: OperationResult
    failure_category: DiagnosticCategory | None
    context: AuditContext
    details: OperationDetails


@dataclass(frozen=True)
class LoginEvent:
    """一次登录尝试或实际会话删除的记录，未知账号不存输入原文（H2）。

    Attributes:
        occurred_at: aware 时刻，保存 UTC 微秒，必填。
        account: 已确认账号的 ActorRef；未知或执行故障尚未读到身份时 None，不用运维代替匿名。
        login_name: 账号存在时保存已存登录名，3-32 字符；身份未确认必须 None。
        kind: login/logout/session_expired，必填。
        result: LoginResult；logout/session_expired 固定 success，账号未知固定 account_missing。
        context: 入口来源和请求编号；未知账号除时间/类型/结果外只保存来源 IP，请求编号也为空。
        failure_category: FAILURE 时必填四类之一；其他结果 None，默认 None，不保存异常原文。
    """

    occurred_at: datetime
    account: ActorRef | None
    login_name: str | None
    kind: LoginKind
    result: LoginResult
    context: AuditContext
    failure_category: DiagnosticCategory | None = None


@dataclass(frozen=True)
class LogQuery:
    """共同的时间、账号及游标筛选；列表不用 offset。

    Attributes:
        start: 含下界的 aware 时刻，转换 UTC 微秒；None 表示无下界。
        end: 不含上界的 aware 时刻；None 表示无上界，必须晚于 start。
        account_id: 正整数内部编号；操作日志筛选操作人，登录日志筛选账号，None 表示全部。
        cursor: 上页返回的 opaque base64url 文本，最多 AUDIT_CURSOR_MAX_CHARS；None 表示首页。
        limit: 非 bool 整数，1 至 AUDIT_PAGE_LIMIT，默认 AUDIT_PAGE_LIMIT。
    """

    start: datetime | None = None
    end: datetime | None = None
    account_id: int | None = None
    cursor: str | None = None
    limit: int = AUDIT_PAGE_LIMIT


@dataclass(frozen=True)
class OperationQuery:
    """操作日志的交集筛选。

    Attributes:
        common: LogQuery，必填。
        operation: OperationType，None 表示全部。
        result: OperationResult，None 表示全部。
        target_account_id: 对象账号编号，非 bool 整数 1 至 2^63-1；默认 None 不限制对象。
            仅匹配 kind=account 且 object_id 为该编号的记录；与 common.account_id 操作人条件取交集。
            按历史编号筛选，账号删除后仍可查；设置对象或失败新建的空编号不匹配。
    """

    common: LogQuery
    operation: OperationType | None = None
    result: OperationResult | None = None
    target_account_id: int | None = None


@dataclass(frozen=True)
class LoginQuery:
    """登录日志的交集筛选。

    Attributes:
        common: LogQuery，必填。
        kind: LoginKind，None 表示全部。
        result: LoginResult，None 表示全部。
    """

    common: LogQuery
    kind: LoginKind | None = None
    result: LoginResult | None = None


@dataclass(frozen=True)
class OperationView:
    """脱离 Session 的历史记录；删除标记按本次查询快照计算，不改存量名字。

    Attributes:
        log_id: 自动分配的 1 至 2^63-1 编号，必填。
        event: 已保存的 OperationEvent，必填。
        actor_deleted: 操作人编号已不存在为 True；运维为 False，必填。
        target_deleted: 账号对象的编号已不存在为 True；设置、作业或未分配编号为 False，必填。
    """

    log_id: int
    event: OperationEvent
    actor_deleted: bool
    target_deleted: bool


@dataclass(frozen=True)
class LoginView:
    """登录记录及当前删除标记。

    Attributes:
        log_id: 自动分配的 1 至 2^63-1 编号，必填。
        event: 保存的 LoginEvent，必填。
        account_deleted: 原编号不存在为 True；未知账号为 False，必填。
    """

    log_id: int
    event: LoginEvent
    account_deleted: bool


@dataclass(frozen=True)
class LogPage[T]:
    """稳定的时间倒序游标页，允许为空。

    Attributes:
        items: (occurred_at DESC, log_id DESC) 顺序的元组，0 至请求 limit 项。
        next_cursor: 有后续记录时的 v1 游标；末页为 None，长度至多 AUDIT_CURSOR_MAX_CHARS。
    """

    items: tuple[T, ...]
    next_cursor: str | None


@dataclass(frozen=True)
class RetentionChange:
    """已授权的共同保留期变更，不携带权限声明。

    Attributes:
        days: 非 bool 整数，7-365 天，无默认。
        actor: 已在写事务内重验的管理员快照，account_id 不能为 None。
        context: 来源 IP 和当前请求编号，必填。
        occurred_at: 注入的 aware 时刻，UTC 微秒，无默认。
    """

    days: int
    actor: ActorRef
    context: AuditContext
    occurred_at: datetime


@dataclass(frozen=True)
class PurgeResult:
    """一次保留期清除提交后的精确计数。

    Attributes:
        operation_count: 已删除操作日志条数，整数且 >= 0。
        login_count: 已删除登录日志条数，整数且 >= 0。
        retention_days: 本次写事务读取的共同保留期，7-365 天。
        cutoff: now 减保留期的 aware UTC 微秒时刻，严格早于它的记录已清除。
    """

    operation_count: int
    login_count: int
    retention_days: int
    cutoff: datetime


# 上层账号适配器在同一个只读 Session 查询存在的编号；audit 不导入账号模型或按名字关联。
type ExistingAccounts = Callable[[Session, frozenset[int]], frozenset[int]]
