"""账号 HTTP 路由契约（06），只编排领域服务、响应和 cookie，不自行写 SQL。

账号路由进入 OpenAPI；全局鉴权在读取请求体和执行路由之前统一生效。
每个写操作只在领域提交后返回成功，异常交统一 problem 边界，不在中间层重复报告。
所有路由都禁止记录或报告口令、cookie、令牌及哈希，中间层不打日志，入口只报告一次。
注入时钟统一由 get_account_now 校验；非法时钟是 DefectError，不把它混入用户字段的 422。
"""

from collections.abc import Callable
from functools import partial
from typing import Annotated, cast

import anyio
from fastapi import APIRouter, Depends, Path, Query
from fastapi.responses import Response

from rdp.accounts._issues import problem
from rdp.accounts.errors import AccountInputError
from rdp.accounts.policy import ARGON2_MAX_CONCURRENCY, ARGON2_QUEUE_TIMEOUT_S
from rdp.accounts.types import Credentials, NewAccount, PasswordChange
from rdp.api._account_context import identity as _identity
from rdp.api.account_auth import (
    AccountRequestContext,
    clear_session_cookie,
    get_admin_context,
    get_authenticated_context,
    get_login_context,
    set_session_cookie,
)
from rdp.api.account_schemas import (
    AccountListResponse,
    AccountResponse,
    ChangePasswordRequest,
    CreateAccountRequest,
    LoginRequest,
    ResetPasswordRequest,
    RoleRequest,
    StatusRequest,
    account_response,
)
from rdp.infra.diagnostics import ExternalError
from rdp.infra.ids import MAX_SQLITE_INTEGER

# 所有失败响应由 install_error_handlers 合并 ProblemResponse；这里额外声明 G2 的安全重试头。
router = APIRouter(
    prefix="/api",
    tags=["账号与会话"],
    responses={
        429: {
            "description": "等待后重试",
            "headers": {
                "Retry-After": {
                    "description": "向上取整的剩余秒数，1-60",
                    "schema": {"type": "integer", "minimum": 1, "maximum": 60},
                }
            },
        }
    },
)
AuthenticatedContext = Annotated[AccountRequestContext, Depends(get_authenticated_context)]
AdminContext = Annotated[AccountRequestContext, Depends(get_admin_context)]
LoginContext = Annotated[AccountRequestContext, Depends(get_login_context)]
TargetId = Annotated[str, Path(pattern=r"^[1-9][0-9]{0,18}$", max_length=19)]


# Web与同步运维共用既有并发常量；专用token不占AnyIO公共线程池，等待最多一秒。
_password_slots = anyio.CapacityLimiter(ARGON2_MAX_CONCURRENCY)
_password_threads = anyio.CapacityLimiter(ARGON2_MAX_CONCURRENCY)


async def _password_work[T](callback: Callable[[], T]) -> T:
    """先异步等计算名额，再在独立token下执行完整领域操作，结束后释放资源。"""
    try:
        with anyio.fail_after(ARGON2_QUEUE_TIMEOUT_S):
            await _password_slots.acquire()
    except TimeoutError:
        raise problem(ExternalError, "哈希资源繁忙，请稍后重试。", field="password") from None
    try:
        return await anyio.to_thread.run_sync(callback, limiter=_password_threads)
    finally:
        _password_slots.release()


@router.post("/auth/login", response_model=AccountResponse, status_code=200, operation_id="login")
async def login(body: LoginRequest, response: Response, context: LoginContext) -> AccountResponse:
    """验证登录并设置新会话 cookie。

    Args:
        body: 登录名和 SecretStr 口令，无默认、不在 query 或日志中传递。
        response: 未发送的响应，供设置 cookie。
        context: 已验证 Origin 的免登录上下文，identity=None。

    Returns:
        HTTP 200 AccountResponse，必须改口令标记原样返回；原文仅进入 HttpOnly cookie，不进入 JSON。

    Raises:
        AccountInputError: 登录名/口令字段不合法，422；框架校验不回显 body。
        AuthenticationError: 未知、停用或错口令，统一“账号或口令错误”的 401。
        AuthorizationError: POST 登录缺失/null/非法或不同源 Origin，403。
        LoginWaitError: 启用账号仍在 G2 等待或连续第五次错误，429 带 Retry-After，等待期间不哈希。
        InputError: 数据库、UTC 列或已存口令编码损坏，400。
        ConflictError: 重读哈希/G2 状态已变化需重试，或SQLite 写锁/约束冲突，409；不计失败、不签发会话。
        ExternalError: 数据库不可用/I/O 失败或 Argon2 名额排队超过 1 秒，502，不计错口令。
        DefectError: 注入时钟非法/回调失败，或登录装配、哈希、熵源或响应转换错误，500；报告前脱敏。

    Side Effects:
        调用 service.login；只有事务提交后才设置新 cookie，登录成功不复用传入的旧令牌。
        本次增加的失败计数由领域提交后才响应；429 输出 Retry-After，失败不设置新 cookie；等待期只累加首条等待日志的次数。

    Time Semantics:
        POST 先检查 Origin，领域事务完成后才发新 cookie；本次增加的失败计数必须提交后才发送对应 401/429，已有等待的429只累加同一等待期日志的次数。
        只用 context.now；先结束只读快照，在事务外核验/按需重哈希，释放 Argon2 名额后再重读写入。
        Argon2经CapacityLimiter异步排队最多1秒，计算使用专用线程名额；短写事务获锁最多约5秒。
        回拨不报 409、不改已有等待截止；请求取消不保证已经开始的提交被取消。
    """
    grant = await _password_work(
        partial(
            context.service.login,
            Credentials(body.login_name, body.password),
            now=context.now,
            audit=context.audit,
        )
    )
    set_session_cookie(response, grant)
    return account_response(grant.identity.account)


@router.post("/auth/logout", response_class=Response, status_code=204, operation_id="logout")
def logout(response: Response, context: AuthenticatedContext) -> Response:
    """撤销当前登录并删除 cookie。

    Args:
        response: 未发送的响应，供清除 cookie。
        context: 有效当前身份，强制改密账号也可使用。

    Returns:
        HTTP 204，无响应体；服务端撤销提交后清 cookie。

    Raises:
        AuthenticationError: cookie 缺失/过期/撤销或账号不可用，401 并清 cookie。
        AuthorizationError: POST 的 Origin 缺失/null/不合法或不同源，403。
        InputError: 认证或撤销会话时数据库损坏，400。
        ConflictError: 初始认证查询、已获锁后的过期删除或当前会话撤销的 SQLite 锁冲突，409；活动刷新获锁失败不在此列。
        ExternalError: 数据库未启用、读取、撤销、提交或清理 I/O 失败，502。
        DefectError: 注入时钟非法/回调失败，或认证装配、撤销 SQL 或 cookie 响应状态错误，500；报告前脱敏。

    Side Effects:
        只撤销当前会话，不撤销其他会话；失败不返回伪成功。重复 HTTP 请求因已无身份返回 401 并清 cookie。

    Time Semantics:
        使用 context.now，不根据时间延长当前会话；允许强制改密账号登出，不运行 Argon2。
        同步撤销事务提交后才返回 204 并清 cookie，SQLite 单次锁等待约 5 秒，无自动重试。
    """
    context.service.logout(_identity(context), now=context.now, audit=context.audit)
    clear_session_cookie(response)
    response.status_code = 204
    return response


@router.get("/auth/me", response_model=AccountResponse, status_code=200, operation_id="who_am_i")
def who_am_i(context: AuthenticatedContext) -> AccountResponse:
    """返回当前账号身份以驱动页面权限和强制改密。

    Args:
        context: 有效当前身份，允许 must_change_password=True，不接受指定目标账号。

    Returns:
        HTTP 200 AccountResponse，不返回任何哈希、cookie 或失败计数。

    Raises:
        AuthenticationError: 无有效会话、过期、撤销或账号不可用，401 并清 cookie。
        InputError: 认证读取的数据库或 UTC 列损坏，400。
        ConflictError: 初始认证只读查询或已获锁后的过期删除冲突，409；活动刷新获锁失败不抛 409。
        ExternalError: 认证数据库未启用或 I/O 失败，502。
        DefectError: 注入时钟非法/回调失败，或请求上下文装配、认证 SQL 或快照响应转换错误，500；报告前脱敏。

    Side Effects:
        仅把认证得到的快照转换为安全响应；认证活动刷新独立提交，不另开业务写会话。

    Time Semantics:
        GET 不检查 Origin；身份阶段使用同请求 context.now，允许强制改密账号访问，不运行 Argon2。
        返回前结束认证查询，若发生必要的活动刷新则按认证契约处理；本路由没有额外业务写事务。
        仅活动更新实际提交时可续 cookie；初始查询沿用普通锁预算，过期删除和活动刷新 BEGIN 都最多等 100 毫秒。
    """
    return account_response(_identity(context).account)


@router.post(
    "/auth/password",
    response_model=AccountResponse,
    status_code=200,
    operation_id="change_own_password",
)
async def change_own_password(
    body: ChangePasswordRequest, response: Response, context: AuthenticatedContext
) -> AccountResponse:
    """本人改口令并轮换 cookie。

    Args:
        body: 当前和新 SecretStr，10-128 个码点，不能相同。
        response: 未发送的响应，供设置新 cookie。
        context: 当前身份，允许强制改密账号访问。

    Returns:
        HTTP 200 AccountResponse，must_change_password=False，Set-Cookie 为新令牌。

    Raises:
        AccountInputError: 当前/新口令字段不合格或新旧相同，422。
        CurrentPasswordError: AccountInputError 的 400 子类，提示“当前口令不正确”，不清 cookie、不跳登录。
        AuthenticationError: 会话失效/账号不可用，401；单纯旧口令错误不属于此类。
        AuthorizationError: POST 的 Origin 缺失/null/不合法或不同源，403。
        LoginWaitError: 当前启用账号的 G2 等待或旧口令连续第五次失败，429 带 Retry-After。
        InputError: 数据库、UTC 列或已存口令编码损坏，400。
        ConflictError: 写事务重读哈希/G2 与快照不一致需重试，或数据库锁/约束冲突，409；不应用旧验证结果。
        ExternalError: 数据库 I/O 或 Argon2 名额排队超过 1 秒，502，不计为旧口令错误。
        DefectError: 注入时钟非法/回调失败，或改密哈希、SQL、会话令牌生成或响应转换错误，500；报告前脱敏。

    Side Effects:
        调用 service.change_password；同事务撤销全部旧会话、新建当前会话，提交后才发 cookie。
        旧口令错误前四次提交计数后 400，第五次 429/Retry-After；均不清 cookie，保留改密页面。

    Time Semantics:
        允许强制改密账号；采用 context.now，回拨不报错、不改已有 G2 截止，修改时间不倒退。
        只读快照结束后在事务外核验旧口令并算好新哈希，再进短写事务复核、提交，之后才发送 200/新 cookie；旧口令失败计数提交后才发送 400/429。
        Argon2 入场及运算不持有数据库事务；每次排队最多 1 秒，完成并释放名额后写锁最多约 5 秒，无重试。
    """
    grant = await _password_work(
        partial(
            context.service.change_password,
            _identity(context),
            PasswordChange(body.current_password, body.new_password),
            now=context.now,
            audit=context.audit,
        )
    )
    set_session_cookie(response, grant)
    return account_response(grant.identity.account)


@router.get(
    "/accounts", response_model=AccountListResponse, status_code=200, operation_id="list_accounts"
)
def list_accounts(
    context: AdminContext,
    after_id: Annotated[str, Query(pattern=r"^(0|[1-9][0-9]{0,18})$", max_length=19)] = "0",
) -> AccountListResponse:
    """为管理员按内部编号游标分页列出账号。

    Args:
        context: 已完成改密的管理员身份，领域在事务内再次核验角色。
        after_id: 规范十进制文本 0 至 2^63-1，默认 0；转换前校验上限，不接受前导零。

    Returns:
        HTTP 200 AccountListResponse，每页最多 100 项、编号升序；空页合法，末页 next_after_id=null。

    Raises:
        AccountInputError: after_id 不是规范十进制游标、超出 0 至 2^63-1，422。
        AuthenticationError: 当前会话缺失/失效或账号不可用，401。
        PasswordChangeRequiredError: 当前账号必须先改口令，403。
        AuthorizationError: 当前角色不是管理员，403；GET 不检查 Origin。
        InputError: 数据库或 UTC 列损坏，400。
        ConflictError: 认证/列表只读查询或已获锁后的过期删除 SQLite 冲突，409；刷新获锁失败不抛 409。
        ExternalError: 数据库未启用、查询或结束读事务时 I/O 失败，502。
        DefectError: 注入时钟非法/回调失败，或列表 SQL、映射或安全响应转换错误，500。

    Side Effects:
        查询是独立只读工作单元，认证刷新另用短事务；不泄漏口令或令牌。

    Time Semantics:
        使用 context.now 核验身份，业务列表在单独 BEGIN/query_only 快照内完成，结束读事务后发送响应。
        没有列表写入、Argon2 或 G2 判定；负会话经过时长按 0，不因回拨报错。
        SQLite 单次读取锁等待约 5 秒，无轮询或重试；认证活动更新独立于本查询。
    """
    page = context.service.list_accounts(
        _identity(context), after_id=_identifier(after_id, cursor=True), now=context.now
    )
    return AccountListResponse(
        items=tuple(account_response(item) for item in page.items),
        next_after_id=None if page.next_after_id is None else str(page.next_after_id),
    )


@router.post(
    "/accounts", response_model=AccountResponse, status_code=201, operation_id="create_account"
)
async def create_account(body: CreateAccountRequest, context: AdminContext) -> AccountResponse:
    """管理员新建启用且首次必须改口令的账号。

    Args:
        body: 登录名、显示名、角色和初始 SecretStr，不接受审计身份或状态覆盖。
        context: 已完成改密的管理员身份。

    Returns:
        HTTP 201 AccountResponse，status=enabled、must_change_password=True，不为目标签发会话。

    Raises:
        AccountInputError: 登录名、显示名、初始口令或角色不合格，422。
        AuthenticationError: 当前会话缺失/失效或账号不可用，401。
        PasswordChangeRequiredError: 当前管理员必须先改口令，403。
        AuthorizationError: POST 的 Origin 不合格或当前角色不是管理员，403。
        InputError: 数据库或 UTC 列损坏，400。
        ConflictError: 登录名重复或创建事务 SQLite 锁/约束冲突，409。
        ExternalError: 数据库不可用/I/O 失败或 Argon2 入场排队超过 1 秒，502。
        DefectError: 注入时钟非法/回调失败，或初始口令哈希、创建 SQL 或响应转换错误，500；报告前脱敏。

    Side Effects:
        领域先在事务外算好初始哈希，再在写事务重验管理员并创建；失败不留账号，登录名冲突为 409。

    Time Semantics:
        以 context.now 作为创建和修改的 UTC 时刻；事务内重验管理员权限，回拨不拒绝。
        哈希入场最多排队 1 秒且不持数据库事务，完成后才申请约 5 秒预算的写锁；提交后发 201，不建目标 cookie、不重试。
    """
    command = NewAccount(Credentials(body.login_name, body.password), body.display_name, body.role)
    return account_response(
        await _password_work(
            partial(
                context.service.create_account,
                _identity(context),
                command,
                now=context.now,
                audit=context.audit,
            )
        )
    )


@router.patch(
    "/accounts/{account_id}/role",
    response_model=AccountResponse,
    status_code=200,
    operation_id="set_account_role",
)
def set_account_role(
    account_id: TargetId, body: RoleRequest, context: AdminContext
) -> AccountResponse:
    """管理员修改角色并保护最后一个启用管理员。

    Args:
        account_id: 目标正整数十进制文本，1 至 2^63-1，直接调用也检查。
        body: role 为 administrator/member。
        context: 已完成改密的管理员身份。

    Returns:
        HTTP 200 AccountResponse；值不变时原样返回、不写审计时间。

    Raises:
        AccountInputError: 目标编号或 Role 不合格，422。
        AuthenticationError: 当前会话缺失/失效或账号不可用，401。
        PasswordChangeRequiredError: 当前管理员必须先改口令，403。
        AuthorizationError: PATCH 的 Origin 不合格或当前角色不是管理员，403。
        AccountNotFoundError: 目标账号不存在，404。
        InputError: 数据库或 UTC 列损坏，400。
        ConflictError: 降级会失去最后启用管理员，或SQLite 写锁/约束冲突，409。
        ExternalError: 数据库未启用或角色变更/会话撤销/提交/清理 I/O 失败，502。
        DefectError: 注入时钟非法/回调失败，或角色修改 SQL、映射或响应转换错误，500。

    Side Effects:
        写锁内重验权限/目标/管理员计数，角色实际改变同事务撤销目标全部会话；最后管理员冲突 409。

    Time Semantics:
        以 context.now 核验身份；实际角色改变的修改时间取 max(已存, now)，同角色不改时间，回拨不报错。
        角色与会话撤销在同事务提交后才发送 200，操作自己成功后旧 cookie 下一请求 401。
        同步 SQL 的写锁等待约 5 秒，无 Argon2 或自动重试。
    """
    return account_response(
        context.service.set_role(
            _identity(context),
            _identifier(account_id),
            body.role,
            now=context.now,
            audit=context.audit,
        )
    )


@router.patch(
    "/accounts/{account_id}/status",
    response_model=AccountResponse,
    status_code=200,
    operation_id="set_account_status",
)
def set_account_status(
    account_id: TargetId, body: StatusRequest, context: AdminContext
) -> AccountResponse:
    """管理员启停账号并在停用时撤销全部会话。

    Args:
        account_id: 1 至 2^63-1 的规范十进制文本。
        body: status 为 enabled/disabled。
        context: 已完成改密的管理员身份。

    Returns:
        HTTP 200 AccountResponse；相同状态不产生写入；启用不恢复旧会话。

    Raises:
        AccountInputError: 目标编号或 AccountStatus 不合格，422。
        AuthenticationError: 当前会话缺失/失效或账号不可用，401。
        PasswordChangeRequiredError: 当前管理员必须先改口令，403。
        AuthorizationError: PATCH 的 Origin 不合格或当前角色不是管理员，403。
        AccountNotFoundError: 目标账号不存在，404。
        InputError: 数据库或 UTC 列损坏，400。
        ConflictError: 停用会失去最后启用管理员，或SQLite 写锁/约束冲突，409。
        ExternalError: 数据库不可用或启停/会话删除/提交/清理 I/O 失败，502。
        DefectError: 注入时钟非法/回调失败，或状态修改 SQL、映射或响应转换错误，500。

    Side Effects:
        领域写锁内执行不变量检查、修改和必要的会话删除；失败整体回滚，不能停用最后管理员。

    Time Semantics:
        使用 context.now；实际变更的修改时刻不小于已存值，同状态不改时间，回拨不报错。
        停用和会话删除原子提交后才发送 200，停用自己后旧 cookie 下一请求 401；启用不恢复旧会话。
        SQLite 写锁等待约 5 秒，无 Argon2 或自动重试。
    """
    return account_response(
        context.service.set_status(
            _identity(context),
            _identifier(account_id),
            body.status,
            now=context.now,
            audit=context.audit,
        )
    )


@router.post(
    "/accounts/{account_id}/password",
    response_model=AccountResponse,
    status_code=200,
    operation_id="reset_account_password",
)
async def reset_account_password(
    account_id: TargetId, body: ResetPasswordRequest, context: AdminContext
) -> AccountResponse:
    """管理员重置口令并要求目标再次登录后改密。

    Args:
        account_id: 目标规范正整数文本，1 至 2^63-1。
        body: 新 SecretStr，10-128 个 Unicode 码点。
        context: 已完成改密的管理员身份。

    Returns:
        HTTP 200 AccountResponse，must_change_password=True；不返回或签发目标 cookie。

    Raises:
        AccountInputError: 目标编号或新口令不合格，422。
        AuthenticationError: 当前会话缺失/失效或账号不可用，401。
        PasswordChangeRequiredError: 当前管理员必须先改口令，403。
        AuthorizationError: POST 的 Origin 不合格或当前角色不是管理员，403。
        AccountNotFoundError: 目标账号不存在，404。
        InputError: 数据库或 UTC 列损坏，400。
        ConflictError: 重置事务 SQLite 写锁或约束冲突，409。
        ExternalError: 数据库 I/O 或 Argon2 入场排队超过 1 秒，502。
        DefectError: 注入时钟非法/回调失败，或新口令哈希、重置 SQL 或响应转换错误，500；报告前脱敏。

    Side Effects:
        先在事务外算好新哈希；写事务仅重验权限/目标并保存预计算哈希、清 G2、强制改密和删除会话，失败全回滚。

    Time Semantics:
        以 context.now 的 UTC 值更新时刻，取 max(已存, now)；回拨不报错，清 G2 是显式重置动作。
        哈希在事务外最多排队 1 秒计算，释放名额后再以约 5 秒预算申请写锁；
        保存已计算结果、强制改密和删除会话同事务提交后发 200，不签发目标 cookie、不自动重试。
    """
    return account_response(
        await _password_work(
            partial(
                context.service.reset_password,
                _identity(context),
                _identifier(account_id),
                body.password,
                now=context.now,
                audit=context.audit,
            )
        )
    )


@router.delete(
    "/accounts/{account_id}",
    response_class=Response,
    status_code=204,
    operation_id="delete_account",
)
def delete_account(account_id: TargetId, context: AdminContext) -> Response:
    """管理员永久删除账号，历史名字快照不受影响。

    Args:
        account_id: 目标规范正整数文本，1 至 2^63-1。
        context: 已完成改密的管理员身份；客户端确认不能代替服务端检查。

    Returns:
        HTTP 204，无响应体；目标不存在为 404，删除最后启用管理员为 409。

    Raises:
        AccountInputError: 目标编号不合格，422。
        AuthenticationError: 当前会话缺失/失效或账号不可用，401。
        PasswordChangeRequiredError: 当前管理员必须先改口令，403。
        AuthorizationError: DELETE 的 Origin 不合格或当前角色不是管理员，403。
        AccountNotFoundError: 目标账号不存在，404。
        InputError: 数据库或 UTC 列损坏，400。
        ConflictError: 删除会失去最后启用管理员，或SQLite 写锁/约束冲突，409。
        ExternalError: 数据库不可用或删除/提交/清理 I/O 失败，502。
        DefectError: 注入时钟非法/回调失败，或删除 SQL 或映射错误，500。

    Side Effects:
        领域写事务中删除目标及全部会话，失败全回滚；同名重建使用新编号。

    Time Semantics:
        context.now 只用于当前会话检查，负经过时长取 0；不写已删除账号的修改时间，回拨不报错。
        账号及会话删除提交后发送 204；删除自己后旧 cookie 下一请求 401。
        同步写锁等待约 5 秒，无 Argon2 或自动重试；超时不能推断服务端已回滚。
    """
    context.service.delete_account(
        _identity(context), _identifier(account_id), now=context.now, audit=context.audit
    )
    return Response(status_code=204)


def _identifier(value: str, *, cursor: bool = False) -> int:
    """在转换前限制十进制文本长度与规范形状，避免64位编号精度丢失。"""
    field = "after_id" if cursor else "account_id"
    if (
        not isinstance(cast(object, value), str)
        or len(value) > 19
        or not value.isascii()
        or not value.isdecimal()
        or str(int(value)) != value
    ):
        raise problem(AccountInputError, "编号必须为规范十进制文本", field=field)
    number = int(value)
    if not (0 if cursor else 1) <= number <= MAX_SQLITE_INTEGER:
        raise problem(AccountInputError, "编号超出允许范围", field=field)
    return number
