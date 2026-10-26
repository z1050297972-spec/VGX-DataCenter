"""日志 HTTP 入口契约（07），仅管理员查询和改保留期，没有单条修改/删除接口。

所有路由显式使用 get_admin_context，使第 6 张全局边界在解析参数前检查角色，
顺序为 Origin → 白名单 → 认证 → 强制改密 → 角色 → 路由 → 参数。
路由声明提供 OpenAPI 和权限分类，不在导入时实例化领域模型或写数据库。
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request

from rdp.api.account_auth import AccountRequestContext, get_admin_context
from rdp.api.audit_schemas import (
    LoginFilters,
    LoginListResponse,
    OperationFilters,
    OperationListResponse,
    RetentionPayload,
)
from rdp.audit.types import AuditContext

router = APIRouter(prefix="/api/audit", tags=["audit"])
AdminContext = Annotated[AccountRequestContext, Depends(get_admin_context)]


def request_audit_context(request: Request) -> AuditContext:
    """从可信入口上下文提取日志来源和请求编号。

    Args:
        request: 当前 ASGI 请求；只读 client 和服务器上下文，不读 body 或转发头。

    Returns:
        AuditContext，source_ip 仅取 ASGI client[0]，由 ipaddress 规范化 IPv4/IPv6；
        client 缺失、地址非 IP 或带作用域时为空；request_id 从当前服务端请求上下文取。

    Raises:
        DefectError: 缺少服务器请求编号或编号非法，表明 RequestIdMiddleware 装配错误；不回显头。

    Side Effects:
        无；不信任 X-Forwarded-For/X-Real-IP/X-Request-ID，不查 DNS，不读 cookie，不写库。
        登录、登出、authenticate 及全部账号写操作的入口须显式传递返回值，不提供缺省来源。

    Time Semantics:
        同步纯提取，无网络、时钟或等待；代理信任留给 M5。
    """
    raise NotImplementedError


@router.get("/operations", response_model=OperationListResponse, operation_id="list_operation_logs")
def list_operations(
    context: AdminContext, filters: Annotated[OperationFilters, Query()]
) -> OperationListResponse:
    """向管理员提供操作日志的筛选和游标页。

    Args:
        context: 全局鉴权后的管理员身份、服务及唯一请求时刻；查询内仍重验。
        filters: aware 时间范围 [start,end)、操作人 account_id、对象账号 target_account_id、类型/结果及游标；
            两个编号独立可选，同时提供取交集，均按历史内部编号查询；每页 1-100 项。

    Returns:
        HTTP 200，UTC 微秒、时间/编号倒序的一页，编号为十进制文本，末页 next_cursor=null。

    Raises:
        AuthenticationError: 未登录或会话无效，401 并清 cookie。
        PasswordChangeRequiredError: 必须改口令，403。
        AuthorizationError: 成员访问管理员模板（包括错方法、坏参数），403，先于 405/422。
        AuditInputError: 筛选范围、时区、任一账号编号上限、游标绑定或分页非法，422，不回显输入。
        InputError: 数据库/历史明细损坏，400。
        ConflictError: 只读锁冲突，409。
        ExternalError: 数据库未配置、读取或清理失败，502。
        DefectError: 时钟/服务/SQL 或安全响应转换错误，500。

    Side Effects:
        只读业务日志；认证可能独立刷新会话，列表不写日志、创建设置或读取请求体。
        成员不能通过附加恶意 query 把权限拒绝变成参数错误。

    Time Semantics:
        复用 context.now 仅核验身份，筛选转 UTC [含下界,不含上界)；页面自行转本地显示。
        单次只读锁等待最多 5000 毫秒，无轮询/重试；回拨不限制查询截止。
    """
    raise NotImplementedError


@router.get("/logins", response_model=LoginListResponse, operation_id="list_login_logs")
def list_logins(
    context: AdminContext, filters: Annotated[LoginFilters, Query()]
) -> LoginListResponse:
    """向管理员提供登录、登出及过期记录的游标页。

    Args:
        context: 全局认证的管理员上下文；领域只读事务内再次核验权限。
        filters: 时间 [start,end)、账号编号、登录类型/结果和游标；每页上限 AUDIT_PAGE_LIMIT。

    Returns:
        HTTP 200 登录日志页；未知账号 account/login_name/request_id 均 null，已删身份带删除标记。

    Raises:
        AuthenticationError: 无有效身份，401 并清 cookie。
        PasswordChangeRequiredError: 必须改口令，403。
        AuthorizationError: 成员访问，403，优先于方法和参数错误。
        AuditInputError: 筛选、时间偏移、游标种类/筛选绑定或编号/limit 非法，422。
        InputError: 数据库或存量登录快照损坏，400。
        ConflictError: 查询锁冲突，409。
        ExternalError: 数据库未配置、读取/关闭 I/O 故障，502。
        DefectError: 时钟或响应映射错误，500，不显示秘密。

    Side Effects:
        只读登录日志及账号存在性；不会对显示过的登录失败再次增加 G2。

    Time Semantics:
        查询保留 UTC 微秒；无界查询含未来记录，不依赖本机时区或当前墙钟。
        单次锁等待最多 5000 毫秒，无自动重试。
    """
    raise NotImplementedError


@router.get("/retention", response_model=RetentionPayload, operation_id="get_audit_retention")
def get_retention(context: AdminContext) -> RetentionPayload:
    """读取操作日志页面上的共同保留期设置。

    Args:
        context: 已完成强制改密的管理员上下文。

    Returns:
        HTTP 200，days 为 7-365 整数；未设置过返回 30。

    Raises:
        AuthenticationError: 无有效身份，401。
        PasswordChangeRequiredError: 必须改口令，403。
        AuthorizationError: 成员，403；GET 不要求 Origin。
        InputError: 设置或数据库损坏，400，不能伪装默认值。
        ConflictError: 读取锁冲突，409。
        ExternalError: 数据库未配置或读取/清理 I/O 故障，502。
        DefectError: 时钟或设置响应构造错误，500。

    Side Effects:
        只读设置；无行时不建行、不触发清除、不记查询操作日志。

    Time Semantics:
        每天固定 UTC 24 小时；请求时刻仅用于身份核验，单次读锁最多 5000 毫秒，无重试。
    """
    raise NotImplementedError


@router.put("/retention", response_model=RetentionPayload, operation_id="set_audit_retention")
def set_retention(
    request: Request, context: AdminContext, body: RetentionPayload
) -> RetentionPayload:
    """管理员保存共同保留期，和该变更的操作日志原子提交。

    Args:
        request: 当前 PUT 请求，入口取来源 IP 和服务器请求编号；必须带同源 Origin。
        context: 已认证且已改密的管理员，在领域写锁内再次检查。
        body: 唯一 days 字段，非 bool 整数 7-365；多余字段拒绝。

    Returns:
        HTTP 200 生效天数；相同值幂等，不新增操作日志；超时不能推断服务端已回滚。

    Raises:
        AuthorizationError: Origin 缺失/非法/不同源或成员，403，优先于 body 校验。
        AuthenticationError: 非公开接口无有效会话，401 并清 cookie。
        PasswordChangeRequiredError: 必须改口令，403。
        AuditInputError: days 类型或范围不合法，422，不记操作日志。
        InputError: 既有设置或数据库损坏，400。
        ConflictError: 业务写锁或约束冲突，409。
        ExternalError: 设置/日志写入、提交或清理失败，502。
        DefectError: 时钟、AuditContext 类型/来源/请求编号、SQL 或响应错误，500；不把平台上下文缺陷映射成 422。

    Side Effects:
        set_log_retention 在管理员预检通过并进入写事务后开始执行，设置和成功日志同事务。
        执行后失败回滚，再短事务补记；补记失败由统一边界 ERROR，原错误保持原状态和诊断。
        不立即清除，不公开 purge 的 HTTP 入口。

    Time Semantics:
        同请求只取 context.now，UTC 微秒；回拨不拒绝。业务获锁最多 5000 毫秒，
        回滚后补记最多 100 毫秒，无自动重试；后续定时清除读取新设置。
    """
    raise NotImplementedError


def report_audit_append_failure(error: Exception) -> None:
    """在 API 异常边界额外记录日志补记失败，保持原业务错误。

    Args:
        error: 原业务异常；只读取可信 AUDIT_APPEND_FAILED 标记，不格式化原始对象或任意 notes。

    Returns:
        无；无标记不记录，有标记仅记一次 ERROR，原响应状态、诊断和错误编号不变。

    Raises:
        无；报告失败不掩盖原业务异常。

    Side Effects:
        仅运行日志，不写日志表、不递归补记；调用方为统一 handle_error/ErrorBoundary。
        使用模块 logger 和自动请求上下文，不记录口令、cookie、SQL 参数或第二异常链。
        仅消耗原异常的固定补记标记以保证重复报告幂等，不改原异常类别、诊断或其他安全清理提示。

    Time Semantics:
        与原请求异常处理同一边界，直接同步记录，无新增数据库/网络等待或重试。
    """
    raise NotImplementedError
