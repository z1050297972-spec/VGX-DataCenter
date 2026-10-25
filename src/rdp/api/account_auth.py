"""HTTP 账号鉴权边界（06），默认拒绝、显式白名单；领域层不理解 Request/cookie。

骨架不调用 install_account_security，现有接口保持原行为；实现阶段由 create_app 统一安装，
不是由每条路由手工决定是否鉴权。所有同步 SQL/Argon2 移入 FastAPI 工作线程。
认证用独立短事务，业务 get_read_session 不升级；账号写操作由领域在写锁内再次校验。
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Annotated

from fastapi import FastAPI, Request, Security
from fastapi.responses import Response
from fastapi.security import APIKeyCookie

from rdp.accounts.policy import SESSION_IDLE_TIMEOUT
from rdp.accounts.service import AccountService
from rdp.accounts.types import SessionGrant, SessionIdentity

# HTTP 阶段不能使用 __Host- 前缀（要求 Secure）；M5 上 HTTPS 时同时升级 cookie 策略。
SESSION_COOKIE_NAME = "rdp_session"
# G1 的 7*24*3600 秒只在签发/改密/活动刷新已提交时续期，普通响应不重复发送令牌。
SESSION_COOKIE_MAX_AGE_S = int(SESSION_IDLE_TIMEOUT.total_seconds())
# 白名单按方法+精确路径，禁止 startswith 绕过；健康 HEAD 不是公开操作，只按错误方法返回 405。
PUBLIC_API_OPERATIONS = frozenset({("GET", "/api/health"), ("POST", "/api/auth/login")})
# 强制改密仍可查本人、改密和登出；没有管理员或错误详情的特例。
PASSWORD_CHANGE_OPERATIONS = frozenset(
    {("GET", "/api/auth/me"), ("POST", "/api/auth/password"), ("POST", "/api/auth/logout")}
)
# 仅公开 APIKeyCookie 声明，auto_error=False 让缺失凭据走统一 401 ProblemResponse。
SESSION_COOKIE = APIKeyCookie(
    name=SESSION_COOKIE_NAME, auto_error=False, scheme_name="SessionCookie"
)


@dataclass(frozen=True)
class AccountRequestContext:
    """当前请求使用的领域服务、时刻和已验证身份。

    Attributes:
        service: AccountService，不可空、无单位、无默认；应用启动时构造，应用不拥有引擎生命周期。
        now: 请求开始时注入的 aware UTC 时刻，微秒、不可空、无默认，同请求只取一次。
        identity: 会话快照，无单位、无默认；只有登录及健康白名单可为 None。
    """

    service: AccountService
    now: datetime
    identity: SessionIdentity | None


def install_account_security(app: FastAPI) -> None:
    """为整个应用安装默认拒绝的 API 访问边界。

    Args:
        app: 尚未启动的 create_app 应用，不可空；database/clock 已由入口绑定。

    Returns:
        无；database 非空时构造默认 PasswordCodec 和 AccountService，绑定 app.state.account_service；
        生产不接收来自请求的哈希参数。所有 /api 和 /api/*（含后注册路由和兜底）统一经 enforce_api_access；
        此边界在 FastAPI 读取/解析 JSON、校验 path/query/body 之前运行，不能只用普通路由 Depends 代替。
        仅 PUBLIC_API_OPERATIONS 免登录，静态资源不鉴权、由前端导航守卫处理。
        所有请求按 enforce_api_access 的固定顺序；公开路径错误方法也先检查 Origin，再返回 405/Allow。

    Raises:
        DefectError: 已启动、重复安装、Argon2 初始化失败或路由安全装配不完整，拒绝部分安装。
        ExternalError: 初始化 dummy_hash 时 Argon2 名额排队超过 1 秒；离线 OpenAPI 不构造编码器。

    Side Effects:
        修改内存中的应用依赖/中间件和 OpenAPI 安全声明；不打开会话或在安装时生成用户令牌。
        有数据库时 PasswordCodec 初始化会生成一次 dummy_hash，需读取系统熵源和执行一次哈希。
        docs/redoc/openapi.json 由 create_app 无条件禁用，不由本函数有条件控制。
        骨架阶段不调用本函数；实现后任何遗漏单路由 Depends 都不能绕过全局边界。

    Time Semantics:
        只在应用启动前同步安装，不读业务墙钟；初始化最多排队 1 秒，Argon2 运算无硬实时保证或重试。
    """
    raise NotImplementedError


def enforce_api_access(request: Request) -> None:
    """为 API 请求统一校验来源、身份及强制改口令限制。

    Args:
        request: 当前请求，不可空；只读方法、路径、Origin/Host 和 cookie，不回显凭据。

    Returns:
        无；按以下固定优先级处理，不得为了先报路由错误而跳过 Origin 或认证：
        1. 非 GET/HEAD/OPTIONS 先检查 Origin；缺失、null、非法或不一致一律 403，任何路径都适用。
        2. 公开操作仅 GET /api/health 与 POST /api/auth/login；免身份认证，不免第一步。
           健康/登录公开路径的错误方法只保留到第六步返回 405，不执行公开操作，也不要求身份。
        3. 其余路径认证；缺失或过期会话返回 401，包括未知业务路径。
        4. 已认证账号若必须改密且不在允许操作集合，返回 403，包括未知路径或错误方法。
        5. 对管理员路径检查角色，成员返回 403。由声明 get_admin_context 的已注册路由收集路径模板，
           用 FastAPI 的 iter_route_contexts 展开 include_router 的有效路径和依赖，包含前缀及嵌套，
           不可只扫描 app.routes 顶层的 APIRoute；后注册路由也须纳入同一分类。
           忽略 HTTP 方法匹配权限，不先校验目标编号的取值；不能因方法错或 body/path/query 错而绕过角色。
           成员以 PUT /api/accounts 或错误编号调用已知管理员模板仍先 403；管理员随后才可能得到 405/422。
        6. 再按路由返回不存在的 404，或方法不对的 405/Allow；未知且不匹配管理员模板的路径不猜角色限制。
        7. 身份、强制改密、角色和路由均通过后才让 FastAPI 读取/解析请求体及校验参数，不合格返回 422。
        需要账号能力时缓存同请求 AccountRequestContext；健康白名单不要求数据库、cookie 或业务时钟。
        所有已登录且已完成改密的账号（含成员）可读错误详情，不把该接口划为管理员路径。

    Raises:
        AuthenticationError: 非白名单缺失/失效会话，401 带诊断；响应删除无效 cookie。
        AuthorizationError: 不安全方法的 Origin 缺失/null/非法/不同源，或成员访问管理员路径（包括错方法），403 带诊断。
        PasswordChangeRequiredError: 强制改密账号请求 PASSWORD_CHANGE_OPERATIONS 以外接口，403 带诊断。
        InputError: 数据库损坏。
        ConflictError: 初始认证查询、过期删除或非获锁阶段的数据库锁/约束冲突；仅活动刷新获锁失败继续放行。
        ExternalError: 数据库缺失或 I/O 失败，不按匿名放行。
        DefectError: 服务、SQL 或注入时钟非法/回调失败，500；不带秘密的原始异常链。

    Side Effects:
        Origin 失败时不读取口令体或刷新/修改数据库。认证独立提交活动更新或过期删除，
        后续业务失败也不回滚已提交的活动。只有 identity.activity_refreshed=True 才可用已验证原令牌续 cookie；
        未到间隔、并发已刷新或 BUSY 跳过均不重发 Set-Cookie；登录/改密签发覆盖旧续期，登出及 401 的清除优先。
        在任何路由读取 cookie 或调用认证前设置仅含阶段的请求标记，认证成功后清除，失败时保留；
        handle_error 和 ErrorBoundary 据此对所有路由的认证异常脱敏，不能只按账号路径决定。
        不缓存角色、不记录请求头/体或日志；同步数据库工作在工作线程执行。

    Time Semantics:
        同请求由 get_account_now 校验并缓存时刻，clock 仅调用一次；默认 UTC 墙钟，可通过 create_app(clock=...) 注入。
        回拨的负经过时长按 0，不报冲突、不改变已存期限；活动刷新通过独立连接把 BEGIN 的 busy_timeout 设置为 100 毫秒，失败跳过且不重试。
        过期删除或其他存储失败不放行，沿用 AccountService.authenticate 的区分，不执行 Argon2。
    """
    raise NotImplementedError


def check_origin(request: Request) -> None:
    """拒绝来源无法证明为本站的写请求。

    Args:
        request: 当前请求，读取 method、唯一 Origin 和 Host，以及服务器识别的 scheme。

    Returns:
        无；GET/HEAD/OPTIONS 通过。其他方法仅当 Origin 为单个合法 http/https origin，
        与 request.url 的 scheme/小写 hostname/有效端口完全相同时通过；默认端口 80/443 规范化。

    Raises:
        AuthorizationError: Origin 缺失/null/重复/多值、含用户信息/路径/query/fragment、Host 缺失或非法，
            或 origin 不同，403；诊断只说明规则，不回显头内容。

    Side Effects:
        无；不读取 body，不写库。所有无 Origin 写请求都拒绝，包括命令行脚本；脚本必须自己显式带正确 Origin。
        本站依据服务器 scheme 与 Host，不信任 X-Forwarded-*；代理和 Host/DNS 信任由 M5 部署确认。
        它阻止浏览器跨站提交，不声称能阻止可任意伪造 HTTP 头的直接客户端。

    Time Semantics:
        同步纯校验，在任何认证刷新、登录计数或业务写入前执行，无时钟或等待。
    """
    raise NotImplementedError


def get_account_now(request: Request) -> datetime:
    """取得并校验当前请求唯一的服务端时刻。

    Args:
        request: 当前请求，create_app 已保存可选 clock；不接受任何客户端日期参数代替服务端时钟。

    Returns:
        aware UTC datetime，微秒不丢，同请求缓存同一值；clock=None 时使用 UTC 墙钟。
        时刻必须可转换到 UTC，且加 LOGIN_WAIT 后仍在 datetime 可表示范围内。

    Raises:
        DefectError: 回调抛 Exception、返回非 datetime/naive/无有效偏移，或 UTC 换算/等待截止加时溢出；
            这是平台配置或程序缺陷，返回 500，不转换成用户参数 422，不回显回调返回值或原始异常消息。

    Side Effects:
        首次调用读取一次时钟并仅缓存校验通过的时刻；不读 body/cookie，不写数据库或日志。
        领域直接调用仍可对非法 now 抛 AccountInputError；HTTP 在调用领域前完成本校验，
        不捕获所有 AccountInputError 一概改为 500，用户字段错误仍走原来的输入错误。

    Time Semantics:
        同步获取一次，不根据请求阶段重复取时刻；回拨的有效时刻照常传入领域，不能误当非法。
        无等待或重试；取消等非 Exception 的控制流由外层保持原语义。
    """
    raise NotImplementedError


def get_login_context(request: Request) -> AccountRequestContext:
    """为免登录的登录接口提供已校验来源的服务和时刻。

    Args:
        request: POST /api/auth/login 的请求，不读取或接受已有 cookie 身份。

    Returns:
        identity=None 的 AccountRequestContext；使用同请求唯一注入时刻及应用服务。

    Raises:
        AuthorizationError: Origin 不符合 check_origin。
        ExternalError: 应用未配置账号数据库。
        DefectError: 应用服务错误，或 get_account_now 判定时钟非法/回调失败；固定安全诊断。

    Side Effects:
        只检查来源并缓存请求上下文，不校验口令、不写库、不生成令牌。

    Time Semantics:
        clock 同请求只调用一次，使用 UTC 微秒，无重试。
    """
    raise NotImplementedError


def get_authenticated_context(
    request: Request,
    cookie: Annotated[str | None, Security(SESSION_COOKIE)],
) -> AccountRequestContext:
    """提供全局鉴权结果并在 OpenAPI 声明 cookie 安全需求。

    Args:
        request: 当前受保护 API 请求，不可空。
        cookie: APIKeyCookie 提取的原文，仅声明和交给 SecretStr；None 为缺失，不记录或回显。

    Returns:
        identity 非 None 的 AccountRequestContext；复用全局守卫结果，不重复刷新会话或读时钟。

    Raises:
        AuthenticationError: 无有效身份，401。
        AuthorizationError: 写请求来源不合法，403。
        PasswordChangeRequiredError: 强制改密尚未完成且当前路径不在允许集合，403。
        InputError: 数据库损坏。
        ConflictError: 初始认证查询、过期删除或非获锁阶段的数据库锁/约束冲突；活动刷新获锁失败不抛 409。
        ExternalError: 无数据库或存储失败。
        DefectError: 装配错误或 get_account_now 判定时钟非法/回调失败，禁止把 cookie 内容拼入异常。

    Side Effects:
        未运行全局守卫时执行同一 enforce_api_access，不能成为绕过路径；否则只读缓存身份和已完成的权限检查结果。
        来源校验和认证副作用见 enforce_api_access，不碰业务查询会话。

    Time Semantics:
        同请求复用时刻与身份；在业务执行前完成。
    """
    raise NotImplementedError


def get_admin_context(
    request: Request,
    cookie: Annotated[str | None, Security(SESSION_COOKIE)],
) -> AccountRequestContext:
    """为管理员操作声明并复核先于参数校验的角色要求。

    Args:
        request: 已由全局入口保护的管理员路径请求；本依赖没有 body/path/query 参数，不能依赖它们先校验。
        cookie: 仅供安全声明及认证的原文；可为 None，不记录、不回显，认证结果按请求缓存。

    Returns:
        当前启用、已完成强制改密的管理员 AccountRequestContext；复用已认证身份和已校验时刻。

    Raises:
        AuthenticationError: 未登录、会话失效或账号不可用，401。
        PasswordChangeRequiredError: 当前账号必须先改口令，403。
        AuthorizationError: Origin 不合格或当前角色不是管理员，403；角色拒绝必须早于坏 JSON/参数的 422。
        InputError: 认证数据库损坏。
        ConflictError: 初始认证或过期删除的锁冲突；活动刷新获锁超时只跳过刷新。
        ExternalError: 数据库未启用或 I/O 失败。
        DefectError: 安全装配错误、注入时钟非法/回调失败或认证程序错误，不回显凭据。

    Side Effects:
        全局守卫先根据本依赖的路由模板完成权限分类和检查，本依赖再次核对缓存角色，不重复刷新。
        缺少缓存时补齐同一守卫流程，不能绕过 Origin/认证/强制改密；不读取或验证请求体。
        领域方法仍需在自己的写事务里重验会话与角色，不能把入口缓存当作事务权限保证。

    Time Semantics:
        角色检查发生在路由方法判定和 FastAPI 参数校验前；方法错误的成员也先得 403。
        不另读时钟或执行 Argon2；复用认证阶段的短刷新等待语义，不自动重试。
    """
    raise NotImplementedError


def set_session_cookie(response: Response, grant: SessionGrant) -> None:
    """仅在会话签发或活动刷新已提交后设置 cookie。

    Args:
        response: 尚未发送的响应对象，不可空。
        grant: 登录/改密已提交的新 SessionGrant，或 authenticate 实际提交活动更新后，
            由其 identity 和当前已验证 cookie 原文组成的 SessionGrant；其他情况禁止调用。

    Returns:
        无；设置 rdp_session、HttpOnly、SameSite=Lax、Path=/、Max-Age=604800、无 Domain。

    Raises:
        DefectError: grant 或响应状态非法；只输出安全诊断，不附令牌异常链。

    Side Effects:
        只在登录成功、本人改密成功或 activity_refreshed=True 时修改 Set-Cookie，普通响应不重发；
        Secure=False 是 M0-M4 HTTP 的权宜，M5 上 HTTPS 时改 True。
        服务端过期判断优先于 cookie；发包失败可能留下服务端会话，之后按过期规则清理，不回滚已提交事务。

    Time Semantics:
        同步设置；Max-Age 为相对秒数，不依赖浏览器与服务端墙钟一致；无等待。
    """
    raise NotImplementedError


def clear_session_cookie(response: Response) -> None:
    """用与设置一致的属性删除浏览器会话 cookie。

    Args:
        response: 尚未发送的响应对象，不可空。

    Returns:
        无；rdp_session 的 Max-Age=0，Path=/、无 Domain、HttpOnly、SameSite=Lax。

    Raises:
        DefectError: 响应已发送或不可修改，不回显请求/响应头。

    Side Effects:
        只改响应头，不替代服务端撤销；发送失败不能保证浏览器已删除，但已撤销令牌仍不能使用。

    Time Semantics:
        登出事务提交后或 401 响应时执行，同步无等待。
    """
    raise NotImplementedError


def account_api_fallback(request: Request) -> Response:
    """在角色检查通过后按 S1 区分未知 API 路径与已知路径的错误方法。

    Args:
        request: 已按 enforce_api_access 顺序检查的 /api 或 /api/* 请求；
            健康/登录路径错误方法可免身份，但写请求仍须先通过 Origin。

    Returns:
        路径不存在时 404 JSON {detail: Not Found}；存在但方法不符时 405 JSON
        {detail: Method Not Allowed}，Allow 为该路径所有已注册方法去重排序、逗号分隔；
        匹配动态路径但不包括本兜底和静态挂载，不因查询参数改变判断，不回退 SPA。

    Raises:
        DefectError: 路由装配损坏，无法可靠判断已注册的方法。

    Side Effects:
        无；只读路由声明并构造响应，不写库，不消费请求 body，不记录敏感路径参数。

    Time Semantics:
        同步匹配，无时钟、等待或重试；原有响应请求编号中间件继续生效。
    """
    raise NotImplementedError
