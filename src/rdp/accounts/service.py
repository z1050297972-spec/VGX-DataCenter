"""账号领域事务服务（06 G1-G3），每个方法拥有自己的工作单元，不向外泄漏 Session。

复用 session_scope：写事务先 BEGIN IMMEDIATE，再重读会话、角色和最后管理员计数。
登录失败是必须提交的状态：在事务内记录结果，正常退出提交后才抛 401/429；
其他失败回滚。认证与业务读事务分开，绝不把 get_read_session 升级为写会话。
不写运行日志；口令库异常先在 security 边界脱敏，数据库只允许 hide_parameters 引擎。
所有 Argon2 名额申请、排队、核验和哈希都在数据库事务之外；只读快照退出后才开始计算，
计算完成并释放名额后才进入 BEGIN IMMEDIATE。写事务内只重验状态并保存已算好的结果，禁止调用 PasswordCodec。
"""

import sqlite3
from dataclasses import replace
from datetime import datetime
from typing import cast

from pydantic import SecretStr
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from rdp.accounts import _audit as audit_log
from rdp.accounts import _login as login_flow
from rdp.accounts import _records as records
from rdp.accounts import _sessions as sessions
from rdp.accounts._boundary import protect
from rdp.accounts._inputs import password_change, password_text
from rdp.accounts._issues import problem
from rdp.accounts.errors import AccountInputError, AccountNotFoundError
from rdp.accounts.models import AccountRow, SessionRow
from rdp.accounts.policy import (
    ACCOUNT_PAGE_LIMIT,
    SESSION_IDLE_TIMEOUT,
    SESSION_TOUCH_INTERVAL,
    SESSION_TOUCH_LOCK_TIMEOUT_MS,
)
from rdp.accounts.security import PasswordCodec, session_digest
from rdp.accounts.types import (
    AccountPage,
    AccountStatus,
    AccountView,
    ActorRef,
    Credentials,
    NewAccount,
    PasswordChange,
    Role,
    SessionGrant,
    SessionIdentity,
)
from rdp.audit import _validation as audit_validation
from rdp.audit import records as audit_records
from rdp.audit._context import validate_context
from rdp.audit._storage import operation as audit_storage
from rdp.audit.policy import AUDIT_PAGE_LIMIT, MAX_RETENTION_DAYS, MIN_RETENTION_DAYS
from rdp.audit.records import append_login
from rdp.audit.types import (
    AuditContext,
    AuditValues,
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
from rdp.infra.actors import OPS_ACTOR
from rdp.infra.db.connection import session_scope, session_scope_with_lock_timeout
from rdp.infra.diagnostics import ConflictError, DefectError, InputError
from rdp.infra.timeutil import ensure_utc


class AccountService:
    """绑定引擎和密码编码器的领域服务，不缓存账号权限或持有长事务。

    Attributes:
        engine: create_database_engine 返回的引擎，无单位、不可空、无默认；生命周期由入口拥有。
        passwords: PasswordCodec，无单位、不可空、无默认；生产使用库默认参数。
    """

    engine: Engine
    passwords: PasswordCodec

    def __init__(self, engine: Engine, passwords: PasswordCodec) -> None:
        """保存账号服务的基础设施依赖。

        Args:
            engine: 已迁移的受管 SQLite Engine，不可空、无单位，不接管其生命周期。
            passwords: 不可空 PasswordCodec，生产使用 Argon2id 默认参数。

        Returns:
            无；得到无请求状态的服务，不连接数据库或注册模型。

        Raises:
            DefectError: engine 不是受管 SQLite 引擎或 passwords 类型错误。

        Side Effects:
            无；不读库、不迁移、不创建账号。

        Time Semantics:
            同步构造，不读时钟、无等待。
        """
        if (
            not isinstance(cast(object, engine), Engine)
            or engine.dialect.name != "sqlite"
            or not engine.get_execution_options().get("rdp_managed")
            or not isinstance(cast(object, passwords), PasswordCodec)
        ):
            raise DefectError()
        self.engine = engine
        self.passwords = passwords

    @protect
    def list_operations(
        self, identity: SessionIdentity, query: OperationQuery, *, now: datetime
    ) -> LogPage[OperationView]:
        """重验管理员并在同一只读快照查询操作日志及账号存在性。

        Args:
            identity: 当前会话，事务内重验管理员和强制改密状态。
            query: OperationQuery，UTC 区间和稳定游标；操作人 common.account_id 与对象 target_account_id 独立筛选且取交集，最多 AUDIT_PAGE_LIMIT 项。
            now: 注入 aware 时刻，UTC 微秒，仅用于会话核验，不截断日志时间范围。

        Returns:
            query_operations 返回的倒序页，包括操作人及账号对象的删除标记。

        Raises:
            AuthenticationError: 会话无效、账号停用/删除或已过期。
            AuthorizationError: 当前账号不是管理员。
            PasswordChangeRequiredError: 必须先改口令。
            AccountInputError: now 不合法。
            AuditInputError: 筛选或游标非法。
            InputError: 日志、账号或数据库损坏。
            ConflictError: 只读事务锁冲突。
            ExternalError: 读取/清理 I/O 失败。
            DefectError: SQL、映射或快照转换错误。

        Side Effects:
            无（在独立只读工作单元中重验身份、查询日志并调用 existing_account_ids）；
            不让 audit 导入账号模型，不缓存名字映射；认证刷新由请求入口独立处理。

        Time Semantics:
            会话负经过时长按 0；筛选比较事件绝对 UTC 时间，回拨不报冲突或漏查。
            单次 SQLite 锁等待最多 5000 毫秒，无重试。
        """
        moment = records.utc(now)
        with session_scope(self.engine, read_only=True) as session:
            sessions.authorize(session, identity, moment, admin=True)
            return audit_records.query_operations(session, query, existing_account_ids)

    @protect
    def list_logins(
        self, identity: SessionIdentity, query: LoginQuery, *, now: datetime
    ) -> LogPage[LoginView]:
        """重验管理员并读取登录日志及原账号是否仍存在。

        Args:
            identity: 当前会话，事务内重验，不信任旧角色。
            query: LoginQuery，时间 [start,end)，账号编号及类型/结果交集。
            now: 注入 aware 时刻，仅用于会话核验，UTC 微秒。

        Returns:
            倒序登录日志页；未知账号无名字，已删除账号仍有旧名字快照和删除标记。

        Raises:
            AuthenticationError: 会话或账号失效。
            AuthorizationError: 当前不是管理员。
            PasswordChangeRequiredError: 必须改口令。
            AccountInputError: now 非法。
            AuditInputError: 筛选/游标非法。
            InputError: 数据库、时间或登录快照损坏。
            ConflictError: 只读锁冲突。
            ExternalError: 数据库读取/清理 I/O 失败。
            DefectError: 查询或映射错误。

        Side Effects:
            无（同一只读 Session 重验权限、读取日志及 existing_account_ids）；不查询输入过的未知登录名。

        Time Semantics:
            身份负经过时长为 0，不因回拨拒绝；列表不读时钟，按存量时间/编号排序。
            单次锁等待最多 5000 毫秒，无重试、轮询或事务升级。
        """
        moment = records.utc(now)
        with session_scope(self.engine, read_only=True) as session:
            sessions.authorize(session, identity, moment, admin=True)
            return audit_records.query_logins(session, query, existing_account_ids)

    @protect
    def get_log_retention(self, identity: SessionIdentity, *, now: datetime) -> int:
        """向重验后的管理员返回共同保留期。

        Args:
            identity: 当前会话，读事务内重验管理员及强制改密限制。
            now: aware 时刻，UTC 微秒，用于会话检查。

        Returns:
            7-365 整数天数，无设置行返回 30，不补建行。

        Raises:
            AuthenticationError: 会话或账号失效。
            AuthorizationError: 非管理员。
            PasswordChangeRequiredError: 必须先改口令。
            AccountInputError: now 无效。
            InputError: 保留期值或数据库损坏，不回退默认值。
            ConflictError: 读取锁冲突。
            ExternalError: 数据库读取/关闭 I/O 失败。
            DefectError: SQL/映射错误。

        Side Effects:
            无（只读身份和数据库设置）；不影响作业/运行日志保留期。

        Time Semantics:
            单次锁等待最多 5000 毫秒，无重试；会话负经过时长取 0，天为 UTC 24 小时。
        """
        moment = records.utc(now)
        with session_scope(self.engine, read_only=True) as session:
            sessions.authorize(session, identity, moment, admin=True)
            return audit_records.get_retention(session)

    @protect
    def set_log_retention(
        self, identity: SessionIdentity, days: int, *, now: datetime, audit: AuditContext
    ) -> int:
        """管理员修改共同保留期并原子追加设置变更日志。

        Args:
            identity: 当前会话，在 BEGIN IMMEDIATE 内重验管理员和强制改密状态。
            days: 非 bool 整数，7-365 天。
            now: 注入 aware 当前时刻，转换 UTC 保存微秒。
            audit: 保留期 PUT 请求的 AuditContext，必填；服务器编号有效且非空，未取得来源 IP 时可为 None。

        Returns:
            生效天数；重复设置同一有效值不写设置或日志。

        Raises:
            AuthenticationError: 会话或账号失效。
            AuthorizationError: 非管理员。
            PasswordChangeRequiredError: 必须先改口令。
            AccountInputError: now 无效。
            AuditInputError: days 不是 7-365 的非 bool 整数，在改设置前拒绝。
            InputError: 当前设置或数据库损坏。
            ConflictError: 写锁或约束冲突。
            ExternalError: 设置/日志写入、提交或清理 I/O 失败。
            DefectError: audit 的类型、IP 或请求编号非法，或引擎、SQL、映射错误。
            TypeError: set_log_retention 调用漏传必填关键字参数 audit。

        Side Effects:
            先在只读事务完成字段、audit 和管理员预检，成功进入写事务即算开始执行，再重验权限及旧设置；
            change_retention 和 SET_RETENTION 成功日志同事务提交。失败整体回滚；执行后失败另开短事务补记，
            before 仅旧 retention_days，after={}。开始前/身份/角色/字段拒绝不记。
            补记失败附 AUDIT_APPEND_FAILED 安全标记，保留原异常并交入口 ERROR；不在这里清除旧日志。

        Time Semantics:
            主写锁最多 5000 毫秒，回滚后补记锁最多 100 毫秒，两者不重叠，无重试。
            日志用 now 的 UTC 微秒，回拨不拒绝；设置从下次清除事务起生效。
        """
        validate_context(audit)
        moment = records.utc(now)
        if type(days) is not int or not MIN_RETENTION_DAYS <= days <= MAX_RETENTION_DAYS:
            failure = audit_validation.invalid("days")
            raise failure
        with session_scope(self.engine, read_only=True) as session:
            actor = sessions.authorize(session, identity, moment, admin=True)
        before = OperationEvent(
            moment,
            audit_log.actor(actor),
            OperationType.SET_RETENTION,
            ObjectRef("audit_settings", "retention", "日志保留期"),
            OperationResult.SUCCESS,
            None,
            audit,
            OperationDetails(before=AuditValues(), after=AuditValues()),
        )
        with (
            audit_log.attempt(self.engine, before) as execution,
            session_scope(self.engine) as session,
        ):
            execution.started = True
            actor = sessions.authorize(session, identity, moment, admin=True)
            old = audit_records.get_retention(session)
            execution.started = old != days
            execution.event = replace(
                before,
                details=OperationDetails(
                    before=AuditValues(retention_days=old), after=AuditValues()
                ),
            )
            result = audit_records.change_retention(
                session, RetentionChange(days, audit_log.actor(actor), audit, moment)
            )
        return result

    @protect
    def login(
        self,
        credentials: Credentials,
        *,
        now: datetime,
        audit: AuditContext,
    ) -> SessionGrant:
        """验证登录并签发新的服务端会话。

        Args:
            credentials: Credentials，登录名和口令符合 policy 的严格边界；不允许 None。
            now: 请求开始时刻，aware datetime，精度微秒；所有等待与活动时刻均由它计算。
            audit: 本次登录入口提取的 AuditContext，必填；source_ip 无法取得可为 None，request_id 必须有效；未知账号落库时才按 H2 去掉编号。

        Returns:
            仅启用账号口令正确时返回 SessionGrant；每次新建随机令牌，防止会话固定；忽略旧 cookie。
            强制改口令账号仍可登录，快照保留 must_change_password=True；旧会话不复用。

        Raises:
            AccountInputError: 登录名/口令不合格，或领域直接调用的 now 无时区、UTC 换算/新截止加时溢出。
            AuthenticationError: 初始查询账号不存在/停用、重读账号已删除/停用或合法快照下核验口令错误；统一“账号或口令错误”。
            LoginWaitError: 初始快照或写事务重读发现启用账号正在等待，或成功提交连续第五次错误；剩余秒向上取整。
            InputError: 数据库/UTC 列或已存口令编码损坏。
            ConflictError: 账号仍启用且不在等待，但写事务重读的口令哈希或 G2 状态与快照不同，
                提示“账号状态已变化，请重试”，不计失败、不签发会话；以及 SQLite 写锁或约束冲突。
            ExternalError: 数据库 I/O/清理失败或 Argon2 排队超时；均不计错口令。
            DefectError: audit 不是有效的登录请求上下文（类型/IP/服务器编号错误），或登录哈希、熵源、SQL、映射错误；不附秘密异常链。
            TypeError: 调用 login 时遗漏必填关键字参数 audit，函数体尚未执行。

        Side Effects:
            输入校验不合格不记日志；未知账号完成 dummy verify 后经 append_missing_login 单独短事务记 ACCOUNT_MISSING，
            只存时间、登录类型、结果和来源 IP，绝不存输入登录名、口令、请求编号，不建账号、不计 G2。
            初始已停用或等待中的已知账号，在独立短写事务重读同一编号/状态后记 DISABLED/WAITING，不改 G2。
            合法核验结果进入已有写事务：前四次错口令的 G2 与 WRONG_PASSWORD 日志一起提交；第五次也记 WRONG_PASSWORD，
            然后抛原 LoginWaitError；等待期内的新尝试才记 WAITING。成功时 G2 清零、必要重哈希、会话签发及 SUCCESS 日志一起提交。
            并发重读发现已删除按 ACCOUNT_MISSING 脱敏；停用或等待记录对应结果。
            输入校验后读取账号状态时算开始执行；哈希/G2 并发冲突或计算/存储故障不编造凭据结论，
            原事务退出并回滚后经 append_failed_login 独立短事务记 FAILURE 和四类失败类别。
            已确认账号保留安全快照，未读到身份则 account/login_name/request_id 均空；已明确未知账号只记 ACCOUNT_MISSING。
            任一需写 G2/会话的事务中日志失败则状态全回滚，不签 cookie；补记失败仍保留最初异常。
            已有拒绝的独立日志补记失败不改变原拒绝：附 AUDIT_APPEND_FAILED 安全标记，由入口 ERROR，不能附秘密异常链。

        Time Semantics:
            仅使用注入 aware now 的 UTC 微秒；负经过时长按 0，既有等待截止不因回拨改变。
            从 blocked_until-60 秒算经过时长；剩余秒向上取整为 1-60，截止相等时允许尝试。
            只读查询结束后最多排队 1 秒再运算；Argon2 不持有任何数据库事务或写锁，完成后才等待写锁约 5 秒。
            原始 G2 快照比较包含已过期但尚未清零的状态，不能仅比较“当前是否等待”；整个操作不自动重试。
            独立拒绝日志的 BEGIN 最多等 100 毫秒；不重复获取 Argon2 名额，不自动重试。
        """
        validate_context(audit)
        moment = records.utc(now, wait=True)
        if not isinstance(cast(object, credentials), Credentials):
            failure = problem(AccountInputError, "登录字段不合法")
            raise failure
        records.login_name(credentials.login_name)
        password_text(credentials.password)
        return login_flow.login(self.engine, self.passwords, credentials, moment, audit)

    @protect
    def authenticate(
        self,
        token: SecretStr | None,
        *,
        now: datetime,
        audit: AuditContext,
    ) -> SessionIdentity:
        """核验当前会话并按最小间隔持久化活动时间。

        Args:
            token: cookie 的 SecretStr；None 表示缺失，不可把原文放诊断；合法时为规范 43 位令牌。
            now: 当前请求的 aware 时刻，精度微秒，不能来自客户端。
            audit: 本次受保护请求的来源及服务器请求编号，必填；无 client 时 IP 为 None，用于访问触发的过期删除日志。

        Returns:
            当前启用账号的 SessionIdentity；每次重读角色和 must_change_password，不缓存权限。
            只有本次实际提交活动更新才 activity_refreshed=True；未到间隔、BUSY 跳过或并发请求已刷新均为 False。

        Raises:
            AccountInputError: now 无时区或 UTC 换算溢出。
            AuthenticationError: 缺失/非法/未知令牌、账号已删/停用，或 max(0, now-last_seen_at) >= 7 天。
            InputError: 数据库或 UTC 列损坏。
            ConflictError: 初始只读认证查询、过期删除已获锁后的写入/提交或刷新中非获锁阶段的数据库锁/约束冲突；
                活动刷新及过期删除的 BEGIN 入场超时按下述短锁语义处理，不抛 ConflictError。
            ExternalError: 数据库读写、提交或清理 I/O 失败，不按有效身份放行。
            DefectError: 认证入口传来的 audit 非法或缺少请求编号，以及会话摘要、引擎配置、SQL/映射错误；不带令牌。
            TypeError: 调用 authenticate 时遗漏必填关键字参数 audit，函数体尚未执行。

        Side Effects:
            先只读核验当前会话，活动刷新仍按第 6 张的间隔更新 last_seen_at，不写操作或登录日志。
            访问发现空闲过期时，以 SESSION_TOUCH_LOCK_TIMEOUT_MS=100 毫秒申请独立短写锁；重读确认该会话仍过期且存在，
            才删除并在同事务写 SESSION_EXPIRED/SUCCESS，记录此次访问来源、服务器请求编号和账号快照。
            BEGIN 入场 BUSY/LOCKED 时跳过删除及日志，继续抛 AuthenticationError；下一次访问重新尝试，不放行过期身份。
            取得锁后的日志插入、删除或提交失败必须整体回滚，不能当成入场超时；并发已删不重复记，未知/撤销令牌不伪造过期记录。
            过期后再也没有被访问的会话不会被本函数删除，也不会产生“会话过期”日志；没有后台定时过期日志。
            audit 未传或值非法时，在认证数据库操作前失败，不能以空来源继续处理。

        Time Semantics:
            同请求唯一 aware now 转 UTC 后保留微秒；max(0, now-last_seen_at) 决定刷新与到期，回拨不改变旧活动时刻。
            初始只读查询锁上限 5000 毫秒；活动刷新和过期删除的 BEGIN 都只等 SESSION_TOUCH_LOCK_TIMEOUT_MS=100 毫秒。
            两种入场超时均不重试、不退回普通锁预算、不修改共享引擎；日志和实际过期删除以同次提交为准，不宣称磁盘 I/O 有硬实时总上限。
        """
        validate_context(audit)
        moment = records.utc(now)
        if token is None:
            failure = sessions.authentication_error()
            raise failure
        digest = session_digest(token)
        with session_scope(self.engine, read_only=True) as session:
            account, saved = sessions.load(session, digest)
            previous = sessions.identity(account, saved)
        elapsed = moment - previous.last_seen_at
        if elapsed < SESSION_TOUCH_INTERVAL:
            return previous
        return _refresh_identity(self.engine, digest, moment, previous, audit=audit)

    @protect
    def logout(
        self,
        identity: SessionIdentity,
        *,
        now: datetime,
        audit: AuditContext,
    ) -> None:
        """撤销当前会话，保留同账号其他会话。

        Args:
            identity: 已通过鉴权的身份；只取其摘要定位会话，不信任旧快照权限。
            now: aware 当前时刻，精度微秒。
            audit: 显式登出请求的 AuditContext，必填；请求编号来自服务器，来源 IP 缺失可为空，不能使用运维上下文。

        Returns:
            无；删除不存在的目标会话也视为成功，供同一已鉴权请求安全重入。

        Raises:
            AccountInputError: now 无时区或 UTC 换算溢出。
            InputError: 数据库损坏。
            ConflictError: 当前会话删除的 SQLite 写锁或约束冲突。
            ExternalError: 删除、提交、回滚或关闭连接的 I/O 故障。
            DefectError: 登出 audit 的类型、IP 或请求编号不合法，或会话删除的引擎/SQL/映射存在程序错误。
            TypeError: 调用 logout 时遗漏必填关键字参数 audit，函数体尚未执行。

        Side Effects:
            在当前会话删除的已有写事务中，只有重读发现会话存在且确实删除时追加 LOGOUT/SUCCESS，快照来自该行账号。
            业务删除和日志同事务提交，任一失败一起回滚；重复已鉴权调用的行已不存在时保持幂等成功，不追加重复日志。
            不删除其他会话，不写操作日志；提交后才允许入口清 cookie；来源及请求编号使用 audit。

        Time Semantics:
            now 转 UTC 作为本次登出日志的微秒时刻；不据此延长会话、计算 G2 或修改账号时间。
            回拨不阻止撤销；SQLite 单次写锁等待约 5 秒，无 Argon2、时钟读取或重试。
        """
        validate_context(audit)
        moment = records.utc(now)
        with session_scope(self.engine) as session:
            saved = session.get(SessionRow, identity.token_digest)
            if saved is None:
                return
            row = session.get(AccountRow, saved.account_id)
            if row is None:
                failure = problem(InputError, "会话账号不存在")
                raise failure
            session.delete(saved)
            append_login(
                session,
                LoginEvent(
                    moment,
                    audit_log.actor(row),
                    row.login_name,
                    LoginKind.LOGOUT,
                    LoginResult.SUCCESS,
                    audit,
                ),
            )

    @protect
    def change_password(
        self,
        identity: SessionIdentity,
        change: PasswordChange,
        *,
        now: datetime,
        audit: AuditContext,
    ) -> SessionGrant:
        """校验当前口令后改自己的口令并轮换全部会话。

        Args:
            identity: 当前会话身份，不接受目标账号编号；允许 must_change_password=True。
            change: 当前和新口令的 SecretStr，均 10-128 个码点；不允许新旧相同。
            now: aware 当前时刻，精度微秒。
            audit: 本人改密请求的来源上下文，必填；服务器请求编号不可空，IP 可因入口未取得 client 而为空。

        Returns:
            新 SessionGrant；must_change_password=False，只保留本次新会话。

        Raises:
            AccountInputError: 字段类型/长度、新旧口令相同，或领域直接调用的 now 无效、等待截止加时溢出。
            CurrentPasswordError: 状态快照一致且当前口令错误，诊断“当前口令不正确”，保留会话。
            AuthenticationError: 只读阶段或写事务重验发现当前会话失效/撤销、账号不存在/停用；不包含单纯旧口令错误。
            LoginWaitError: 初始或重读状态处于 G2 等待，或本次提交第五次旧口令错误；不清 cookie。
            InputError: 数据库/UTC 列或已存口令编码损坏。
            ConflictError: 会话仍有效且账号启用、不在等待，但口令哈希或原始 G2 状态已变化，请用户重试；以及 SQLite 写锁/约束冲突。
            ExternalError: 数据库 I/O/清理失败或事务外 Argon2 入场排队超时，不计失败。
            DefectError: 本人改密上下文不合法，或旧口令核验、新哈希、会话熵源及 SQL 程序错误；输出不含秘密。
            TypeError: 调用 change_password 时遗漏必填关键字参数 audit，函数体尚未执行。

        Side Effects:
            先检查 audit、输入和新旧口令不相同，在只读事务核验当前身份及 G2；初始等待期拒绝不算开始。
            退出只读事务并申请旧口令核验名额时算开始执行；验证正确才在事务外计算新哈希，释放所有名额后进入写事务。
            锁内重新验证身份，并逐项比较原哈希与 G2 快照，不能将并发变化当成旧口令错误。
            旧口令确实错误时，失败 CHANGE_PASSWORD 日志与递增 G2（第五次还设置等待截止）在同一个写事务提交；
            失败类别为 INPUT，before 仅已有 must_change_password，after={}；提交后前四次抛 CurrentPasswordError，第五次抛 LoginWaitError。
            这一分支不得另开短事务补写旧口令失败日志，也不写登录日志、不撤销或轮换当前会话；日志追加/提交失败则 G2 一起回滚。
            只有实际判定可提交时才返回口令拒绝；若 G2/日志事务本身失败，按存储故障回滚，再独立记录该执行故障，不伪装为已提交的错口令结果。
            旧口令正确时，新哈希、清 G2/强制标记、更新操作人、全部旧会话撤销及当前新会话，与成功操作日志原子提交。
            哈希计算故障、快照冲突及已开始后的数据库故障，原工作单元退出后短事务补记失败；明细只取安全标记，禁止写口令或会话摘要。
            字段/audit 不合法、初始身份/G2预检拒绝及后来重验的 AuthenticationError 不记；进入执行后重读 G2 已等待的 LoginWaitError 则补记输入类别失败。
            故障补记失败仍返回原计算、冲突或存储异常，仅增加 AUDIT_APPEND_FAILED 供入口报告，不能把第二异常变成新的业务结果。

        Time Semantics:
            会话/G2 计算都用同一 aware now 转 UTC；负经过时长为 0，回拨不重设等待截止，截止相等允许尝试。
            核验旧口令与计算新哈希分别最多排队 1 秒，均在读事务结束后、业务写事务开始前进行；业务写锁最多 5000 毫秒。
            错旧口令时，G2 与失败操作日志必须在同一次提交后才抛 CurrentPasswordError/LoginWaitError；没有第二个追加锁等待。
            其他执行故障回滚后的补记锁等待限 AUDIT_SHORT_LOCK_TIMEOUT_MS=100 毫秒；无自动重试，账号更新时间不倒退，新会话用原 now。
        """
        validate_context(audit)
        moment = records.utc(now, wait=True)
        password_change(change)
        with session_scope(self.engine, read_only=True) as session:
            previous = sessions.authorize(session, identity, moment, allow_change=True)
        waiting = sessions.wait_error(previous, moment)
        if waiting is not None:
            raise waiting
        before_event = audit_log.make_event(
            OperationType.CHANGE_PASSWORD, audit_log.actor(previous), previous, audit, moment
        )
        with audit_log.attempt(self.engine, before_event, started=True):
            checked = self.passwords.verify(previous.password_hash, change.current_password)
            encoded = self.passwords.hash(change.new_password) if checked.matched else None
            failure: InputError | None = None
            result: SessionGrant | None = None
            with session_scope(self.engine) as session:
                current_row = sessions.authorize(session, identity, moment, allow_change=True)
                row = sessions.confirm(current_row, previous, moment)
                audit_event = audit_log.make_event(
                    OperationType.CHANGE_PASSWORD, audit_log.actor(row), row, audit, moment
                )
                if not checked.matched:
                    failure = sessions.wrong_password(row, moment, current=True)
                    audit_log.rejected(session, audit_event, failure)
                else:
                    if encoded is None:
                        raise DefectError()
                    row.password_hash = encoded
                    row.must_change_password = False
                    row.failed_attempts, row.blocked_until = 0, None
                    records.stamp(row, ActorRef(row.account_id, row.display_name), moment)
                    sessions.revoke_all(session, row.account_id)
                    result = sessions.grant(session, row, moment)
                    audit_log.finish(session, audit_event, row)
        if failure is not None:
            raise failure
        if result is None:
            raise DefectError()
        return result

    @protect
    def list_accounts(
        self, identity: SessionIdentity, *, after_id: int = 0, now: datetime
    ) -> AccountPage:
        """按编号游标查询最多一百个账号。

        Args:
            identity: 管理员会话身份；每次查询重验当前权限。
            after_id: 非 bool 的整数，0 至 2^63-1，默认 0；排除该编号及更小项。
            now: aware 当前时刻，精度微秒。

        Returns:
            AccountPage，最多 100 条、编号升序，可为空；有后续页时 next_after_id 为本页最后编号，否则 None。

        Raises:
            AccountInputError: 游标不是非 bool 整数、越界，或 now 无时区/UTC 换算溢出。
            AuthenticationError: 同一只读快照内重验发现会话失效、过期或账号不可用。
            AuthorizationError: 当前账号不是管理员。
            PasswordChangeRequiredError: 当前账号尚未完成强制改密。
            InputError: 读取到损坏数据库或 UTC 列。
            ConflictError: SQLite 只读查询锁冲突。
            ExternalError: 查询、读事务结束或关闭连接时 I/O 失败。
            DefectError: 只读查询的引擎、SQL 或映射错误。

        Side Effects:
            在一个 BEGIN/query_only 只读工作单元内重验身份、角色并查询至多 100 条账号及下一页标志。
            不刷新或删除会话，不写审计时间，不输出哈希、失败计数或摘要；失败不返回部分列表，结束后关闭读事务。

        Time Semantics:
            now 只用于同一只读快照的会话有效性检查，转换 UTC 保留微秒；负经过时长按 0，回拨不报错。
            不申请写锁、不执行 Argon2，也不读墙钟；SQLite 单次读取锁等待沿用约 5 秒预算，查询不重试。
        """
        moment = records.utc(now)
        cursor = records.identifier(after_id, zero=True)
        with session_scope(self.engine, read_only=True) as session:
            sessions.authorize(session, identity, moment, admin=True)
            rows = session.scalars(
                select(AccountRow)
                .where(AccountRow.account_id > cursor)
                .order_by(AccountRow.account_id)
                .limit(ACCOUNT_PAGE_LIMIT + 1)
            ).all()
            items = tuple(records.view(row) for row in rows[:ACCOUNT_PAGE_LIMIT])
            following = items[-1].account_id if len(rows) > ACCOUNT_PAGE_LIMIT else None
        return AccountPage(items, following)

    @protect
    def create_account(
        self,
        identity: SessionIdentity,
        command: NewAccount,
        *,
        now: datetime,
        audit: AuditContext,
    ) -> AccountView:
        """由管理员新建启用账号并强制首次改口令。

        Args:
            identity: 管理员会话身份；事务内重验，不能从客户端声明操作者。
            command: 合法登录名、显示名、Role 和初始 SecretStr，不可空。
            now: aware 当前时刻，精度微秒。
            audit: 管理员建号请求的 AuditContext，必填；必须带服务器请求编号，来源 IP 未知时允许 None。

        Returns:
            新 AccountView，status=enabled、must_change_password=True，内部编号自动分配且不复用。

        Raises:
            AccountInputError: 字段、角色或 now 无效。
            AuthenticationError: 写事务内重新检查会话失效、过期或账号不可用。
            AuthorizationError: 当前角色不是管理员。
            PasswordChangeRequiredError: 尚未完成强制改口令。
            ConflictError: 登录名已存在或 SQLite 写锁/约束冲突。
            InputError: 数据库/UTC 列损坏；不修复存量数据。
            ExternalError: 数据库打开、提交或清理 I/O 失败，或 Argon2 名额排队超过 1 秒；失败不提交。
            DefectError: 建号 audit 缺失服务器编号或其类型/IP 非法，或初始哈希、账号插入、响应快照构造错误。
            TypeError: 调用 create_account 时遗漏必填关键字参数 audit，函数体尚未执行。

        Side Effects:
            输入、audit 和只读管理员预检通过，关闭读事务并开始申请初始口令哈希名额时算开始执行；保存预检操作人快照。
            Argon2 在事务外完成后，BEGIN IMMEDIATE 内再验管理员，并尝试创建启用、首次必须改密的账号；不为目标签发会话。
            CREATE_ACCOUNT 成功日志与新账号同事务提交，before={}，after 只含账号白名单；日志写入失败必须撤销账号创建。
            开始后的重名/锁/约束 ConflictError、存储 InputError/ExternalError 或哈希/SQL DefectError，退出原工作单元后单独补记失败。
            新建失败的对象编号始终为空，即使 flush 曾分配编号也不能保留；名字固定“新账号”，after={}，不复制原始命令或口令。
            初始字段或上下文错误、管理员预检失败，以及写事务重验抛出的 AuthenticationError、AuthorizationError、PasswordChangeRequiredError 不记日志。
            失败补记只尝试一次；补记错误给原建号异常加 AUDIT_APPEND_FAILED，交 API 边界 ERROR，不能替换原失败。

        Time Semantics:
            创建与日志采用同一个 aware now 的 UTC 微秒，回拨不拒绝建号；会话核验负经过时长按 0。
            Argon2 入场最多排队 1 秒且不持事务，完成后业务写锁最多 5000 毫秒；失败补记锁用 AUDIT_SHORT_LOCK_TIMEOUT_MS=100 毫秒。
            建号事务先结束再补记，所有阶段都不自动重试，不在补记时另读墙钟。
        """
        validate_context(audit)
        moment = records.utc(now)
        command = records.new_account(command)
        with session_scope(self.engine, read_only=True) as session:
            before_actor = sessions.authorize(session, identity, moment, admin=True)
        before_event = audit_log.make_event(
            OperationType.CREATE_ACCOUNT, audit_log.actor(before_actor), None, audit, moment
        )
        with audit_log.attempt(self.engine, before_event, started=True):
            encoded = self.passwords.hash(command.credentials.password)
            with session_scope(self.engine) as session:
                actor = sessions.authorize(session, identity, moment, admin=True)
                audit_event = audit_log.make_event(
                    OperationType.CREATE_ACCOUNT, audit_log.actor(actor), None, audit, moment
                )
                row = records.make_row(
                    command, encoded, ActorRef(actor.account_id, actor.display_name), moment, True
                )
                session.add(row)
                session.flush()
                result = records.view(row)
                audit_log.finish(session, audit_event, row)
        return result

    @protect
    def set_role(
        self,
        identity: SessionIdentity,
        account_id: int,
        role: Role,
        *,
        now: datetime,
        audit: AuditContext,
    ) -> AccountView:
        """修改账号角色并撤销该账号全部会话。

        Args:
            identity: 当前管理员会话身份，在写锁内重验。
            account_id: 目标内部编号，非 bool 整数，1 至 2^63-1。
            role: Role 声明的两个值之一，不可空。
            now: aware 当前时刻，精度微秒。
            audit: 本次角色修改入口传入的上下文，必填；记录修改者请求的服务器编号和可空来源 IP。

        Returns:
            更新后的 AccountView；role 与当前相同时返回原快照，不改时间/审计或会话。

        Raises:
            AccountInputError: 目标编号、枚举或 now 无效。
            AuthenticationError: 写事务内重新检查会话失效、过期或账号不可用。
            AuthorizationError: 当前角色不是管理员。
            PasswordChangeRequiredError: 尚未完成强制改口令。
            AccountNotFoundError: 目标已删除。
            ConflictError: 变更会使启用管理员数量变为零，或 SQLite 锁/约束冲突。
            InputError: 数据库/UTC 列损坏；不修复存量数据。
            ExternalError: 数据库打开、提交、回滚或关闭的 I/O 故障；清理失败语义同 session_scope。
            DefectError: 角色变更 audit 不符合请求来源契约，或角色/会话更新 SQL、账号映射错误；不泄漏会话凭据。
            TypeError: 调用 set_role 时遗漏必填关键字参数 audit，函数体尚未执行。

        Side Effects:
            先在只读事务核验输入、audit、管理员和目标，保留两人的快照；此时不判断最后管理员约束。
            管理员预检通过后，成功进入 BEGIN IMMEDIATE 即算开始执行，随后重验权限、目标及最后管理员数量。
            同角色只返回现有快照；实际修改时 SET_ROLE 的 before/after 仅含 role，与角色赋值、会话撤销原子提交。
            最后管理员 ConflictError、写事务中目标消失的 AccountNotFoundError，及已入事务后的存储/SQL失败均回滚，再补一条失败日志。
            失败对象使用预检确认的原账号编号与名字，after={}，不能把降级尝试写成已成功的角色变更。
            字段/audit 错误、只读预检目标缺失、未获业务写锁或任何身份/角色/强制改密拒绝不写操作日志；相同角色也不记。
            补记失败保留原角色变更异常，只附安全标记由 API 最外层报告；不复制会话摘要。

        Time Semantics:
            会话有效性用注入 now，负经过时长视为 0；变更时间取 max(已存 updated_at, UTC now)，日志保留原 now 微秒。
            初始只读及业务写锁单次预算 5000 毫秒；只有成功进入写事务才跨过本方法的执行边界。
            角色失败补记在回滚后以 AUDIT_SHORT_LOCK_TIMEOUT_MS=100 毫秒尝试一次；本方法不调用 Argon2，也不因回拨报冲突。
        """
        validate_context(audit)
        moment = records.utc(now)
        key = records.identifier(account_id)
        if not isinstance(cast(object, role), Role):
            failure = problem(AccountInputError, "角色不合法", field="role")
            raise failure
        with session_scope(self.engine, read_only=True) as session:
            before_actor = sessions.authorize(session, identity, moment, admin=True)
            before_target = records.target(session, key)
        before_event = audit_log.make_event(
            OperationType.SET_ROLE, audit_log.actor(before_actor), before_target, audit, moment
        )
        with (
            audit_log.attempt(self.engine, before_event) as execution,
            session_scope(self.engine) as session,
        ):
            execution.started = True
            actor = sessions.authorize(session, identity, moment, admin=True)
            row = records.target(session, key)
            execution.started = row.role != role.value
            if row.role != role.value:
                audit_event = audit_log.make_event(
                    OperationType.SET_ROLE, audit_log.actor(actor), row, audit, moment
                )
                if role is Role.MEMBER:
                    records.keep_admin(session, row)
                row.role = role.value
                records.stamp(row, ActorRef(actor.account_id, actor.display_name), moment)
                sessions.revoke_all(session, key)
                audit_log.finish(session, audit_event, row)
            result = records.view(row)
        return result

    @protect
    def set_status(
        self,
        identity: SessionIdentity,
        account_id: int,
        status: AccountStatus,
        *,
        now: datetime,
        audit: AuditContext,
    ) -> AccountView:
        """启用或停用账号并保证最后管理员仍可用。

        Args:
            identity: 当前管理员会话身份，在写锁内重验。
            account_id: 目标内部编号，非 bool 整数，1 至 2^63-1。
            status: AccountStatus 声明的两个值之一，不可空。
            now: aware 当前时刻，精度微秒。
            audit: 启用或停用请求对应的 AuditContext，必填；来源地址可空，服务器请求编号必须有效。

        Returns:
            更新后的 AccountView；status 与当前相同时返回原快照，不改时间/审计或会话。

        Raises:
            AccountInputError: 目标编号、枚举或 now 无效。
            AuthenticationError: 写事务内重新检查会话失效、过期或账号不可用。
            AuthorizationError: 当前角色不是管理员。
            PasswordChangeRequiredError: 尚未完成强制改口令。
            AccountNotFoundError: 目标已删除。
            ConflictError: 变更会使启用管理员数量变为零，或 SQLite 锁/约束冲突。
            InputError: 数据库/UTC 列损坏；不修复存量数据。
            ExternalError: 数据库打开、提交、回滚或关闭的 I/O 故障；清理失败语义同 session_scope。
            DefectError: 启停上下文类型、来源地址、请求编号非法，或启停/撤销会话的引擎、SQL、映射错误。
            TypeError: 调用 set_status 时遗漏必填关键字参数 audit，函数体尚未执行。

        Side Effects:
            校验参数和 audit 后，在只读工作单元确认管理员、目标及快照，最后管理员数量留到持锁后判定。
            成功取得业务写事务就算开始执行；在锁内重验权限，再检查启停条件，不因最后管理员冲突而退回“未开始”。
            状态不变不写日志、时间或会话；有变化按目标状态记 ENABLE_ACCOUNT 或 DISABLE_ACCOUNT，明细只包含前后 status。
            停用、撤销目标会话和成功日志共同提交；启用不恢复会话或清 G2，管理撤销不另记显式登出。
            持锁后停用最后管理员的 ConflictError、目标并发删除的 AccountNotFoundError 或数据库写入/提交故障，整体回滚后补记失败。
            参数和上下文不合法、管理员/目标预检拒绝、业务 BEGIN 未取得锁、重验身份权限失败均不补记；失败事件 after 为空。
            补记故障不能把原启停失败变成别的错误，只让入口凭 AUDIT_APPEND_FAILED 额外记 ERROR。

        Time Semantics:
            UTC now 决定本次启停事件时间，账号修改时间不倒退，已有 G2 截止不随回拨调整；无变化不更新时间。
            只读预检结束后申请最多 5000 毫秒的业务写锁；失败事件追加使用独立连接的 AUDIT_SHORT_LOCK_TIMEOUT_MS=100 毫秒上限。
            两个写事务不重叠，启停与补记均无重试；调用期间不读取第二个业务时刻。
        """
        validate_context(audit)
        moment = records.utc(now)
        key = records.identifier(account_id)
        if not isinstance(cast(object, status), AccountStatus):
            failure = problem(AccountInputError, "状态不合法", field="status")
            raise failure
        with session_scope(self.engine, read_only=True) as session:
            before_actor = sessions.authorize(session, identity, moment, admin=True)
            before_target = records.target(session, key)
        before_event = audit_log.make_event(
            (
                OperationType.DISABLE_ACCOUNT
                if status is AccountStatus.DISABLED
                else OperationType.ENABLE_ACCOUNT
            ),
            audit_log.actor(before_actor),
            before_target,
            audit,
            moment,
        )
        with (
            audit_log.attempt(self.engine, before_event) as execution,
            session_scope(self.engine) as session,
        ):
            execution.started = True
            actor = sessions.authorize(session, identity, moment, admin=True)
            row = records.target(session, key)
            execution.started = row.status != status.value
            if row.status != status.value:
                kind = (
                    OperationType.DISABLE_ACCOUNT
                    if status is AccountStatus.DISABLED
                    else OperationType.ENABLE_ACCOUNT
                )
                audit_event = audit_log.make_event(kind, audit_log.actor(actor), row, audit, moment)
                if status is AccountStatus.DISABLED:
                    records.keep_admin(session, row)
                    sessions.revoke_all(session, key)
                row.status = status.value
                records.stamp(row, ActorRef(actor.account_id, actor.display_name), moment)
                audit_log.finish(session, audit_event, row)
            result = records.view(row)
        return result

    @protect
    def reset_password(
        self,
        identity: SessionIdentity,
        account_id: int,
        password: SecretStr,
        *,
        now: datetime,
        audit: AuditContext,
    ) -> AccountView:
        """由管理员重置目标口令并强制其下次改口令。

        Args:
            identity: 管理员身份，事务内重验。
            account_id: 目标正整数编号，1 至 2^63-1，不接受 bool。
            password: 新 SecretStr，10-128 个 Unicode 码点，无组合要求，不可空。
            now: aware 当前时刻，精度微秒。
            audit: 管理员重置口令请求的来源与服务器编号，必填；允许 IP 未知，不接受空请求编号。

        Returns:
            更新后的 AccountView，must_change_password=True，不返回或新建会话。

        Raises:
            AccountInputError: 编号、口令或 now 无效。
            AuthenticationError: 写事务内重新检查会话失效、过期或账号不可用。
            AuthorizationError: 当前角色不是管理员。
            PasswordChangeRequiredError: 尚未完成强制改口令。
            AccountNotFoundError: 目标不存在。
            InputError: 数据库/UTC 列损坏；不修复存量数据。
            ConflictError: SQLite 写锁等待约 5 秒或约束冲突；无自动重试。
            ExternalError: 数据库打开、提交或清理 I/O 失败，或 Argon2 名额排队超过 1 秒；失败不提交。
            DefectError: 管理员重置 audit 不合法，或新哈希计算、保存及会话撤销发生程序错误；禁止携带口令原文。
            TypeError: 调用 reset_password 时遗漏必填关键字参数 audit，函数体尚未执行。

        Side Effects:
            只读核验管理员与目标并保存快照，参数及 audit 合法后关闭读事务；开始申请新哈希名额即算执行。
            写事务内只重新核验当前管理员和同一目标编号，保存预先算好的哈希、强制改密标记、修改人、清 G2 并撤销全部目标会话。
            RESET_PASSWORD 的成功日志只保存 must_change_password 前后值，与这些改动原子提交；重置自己也不签发替代会话。
            开始后的 Argon2 ExternalError/DefectError、锁或约束 ConflictError、目标消失 AccountNotFoundError，以及数据库故障都在回滚/关闭后补失败日志。
            目标旧哈希并发变化不要求核验旧口令；失败快照来自预检目标，after={}，任何哈希及新口令都不得落日志。
            输入或 audit 校验、初始管理员/目标预检失败不记；写事务内身份失效、角色不足或必须改密的拒绝也不记。
            独立补记若失败，原重置异常继续返回，固定标记由 API 边界记录，不把补记异常链带出去。

        Time Semantics:
            用 aware now 转 UTC 核验身份、记录重置时刻；更新账号取 max(已存, now)，回拨不构成冲突。
            新口令哈希入场最多等 1 秒，释放名额后业务 BEGIN 最多等 5000 毫秒；任何哈希计算都不占数据库事务。
            重置失败补记的锁等待限 AUDIT_SHORT_LOCK_TIMEOUT_MS=100 毫秒，不重复哈希或自动重试，显式清 G2 不重算旧等待期。
        """
        validate_context(audit)
        moment = records.utc(now)
        key = records.identifier(account_id)
        password_text(password)
        with session_scope(self.engine, read_only=True) as session:
            before_actor = sessions.authorize(session, identity, moment, admin=True)
            before_target = records.target(session, key)
        before_event = audit_log.make_event(
            OperationType.RESET_PASSWORD,
            audit_log.actor(before_actor),
            before_target,
            audit,
            moment,
        )
        with audit_log.attempt(self.engine, before_event, started=True):
            encoded = self.passwords.hash(password)
            with session_scope(self.engine) as session:
                actor = sessions.authorize(session, identity, moment, admin=True)
                row = records.target(session, key)
                audit_event = audit_log.make_event(
                    OperationType.RESET_PASSWORD, audit_log.actor(actor), row, audit, moment
                )
                row.password_hash = encoded
                row.must_change_password = True
                row.failed_attempts, row.blocked_until = 0, None
                records.stamp(row, ActorRef(actor.account_id, actor.display_name), moment)
                sessions.revoke_all(session, key)
                result = records.view(row)
                audit_log.finish(session, audit_event, row)
        return result

    @protect
    def delete_account(
        self,
        identity: SessionIdentity,
        account_id: int,
        *,
        now: datetime,
        audit: AuditContext,
    ) -> None:
        """永久删除账号及其全部会话，保留历史操作者快照。

        Args:
            identity: 当前管理员身份，事务内重验。
            account_id: 目标正整数编号，1 至 2^63-1，不接受 bool。
            now: aware 当前时刻，精度微秒。
            audit: 删除请求入口已提取的 AuditContext，必填；来源 IP 可以缺失，请求编号不能省略或伪造。

        Returns:
            无；成功后同名可重建但必须得到新的内部编号。

        Raises:
            AccountInputError: 编号或 now 无效。
            AuthenticationError: 写事务内重新检查会话失效、过期或账号不可用。
            AuthorizationError: 当前角色不是管理员。
            PasswordChangeRequiredError: 尚未完成强制改口令。
            AccountNotFoundError: 目标不存在，不伪造删除成功。
            ConflictError: 删除最后一个启用管理员或 SQLite 锁/约束冲突。
            InputError: 数据库/UTC 列损坏；不修复存量数据。
            ExternalError: 数据库打开、提交、回滚或关闭的 I/O 故障；清理失败语义同 session_scope。
            DefectError: 删除入口 audit 的类型/IP/编号无效，或账号/会话删除 SQL 与映射错误；不提供内部凭据。
            TypeError: 调用 delete_account 时遗漏必填关键字参数 audit，函数体尚未执行。

        Side Effects:
            在只读事务中核验管理员、目标、参数和 audit，捕获操作人与对象的原编号及名字；不预先判定最后管理员数量。
            管理员预检通过并取得 BEGIN IMMEDIATE 时算开始执行，在锁内复核身份、对象及最后管理员条件。
            DELETE_ACCOUNT 成功日志的 before 为删除前账号白名单、after={}，与账号及其所有会话的删除一起提交；删除自己仍保留快照。
            删除最后管理员的 ConflictError、事务内目标已消失的 AccountNotFoundError，以及进入写事务后的存储/映射故障均回滚并单独补失败事件。
            初始编号/audit 错误、只读预检目标不存在、未取得写锁或任一次身份/权限重验拒绝不追加操作日志；不能假装删除成功。
            失败日志保留预检对象编号以指向原账号，绝不按名字关联后来重建的账号；补记失败仅附安全标记，原删除错误不变。

        Time Semantics:
            只用注入 now 的 UTC 微秒核验操作者和标记删除事件，不为已删除账号写修改时间；负经过时长按 0。
            只读预检和删除事务各沿用单次 5000 毫秒锁上限，未取得删除锁不补记操作。
            已进入删除事务的失败先回滚，再以 AUDIT_SHORT_LOCK_TIMEOUT_MS=100 毫秒追加失败记录；不做哈希、重试或二次取时。
        """
        validate_context(audit)
        moment = records.utc(now)
        key = records.identifier(account_id)
        with session_scope(self.engine, read_only=True) as session:
            before_actor = sessions.authorize(session, identity, moment, admin=True)
            before_target = records.target(session, key)
        before_event = audit_log.make_event(
            OperationType.DELETE_ACCOUNT,
            audit_log.actor(before_actor),
            before_target,
            audit,
            moment,
        )
        with (
            audit_log.attempt(self.engine, before_event) as execution,
            session_scope(self.engine) as session,
        ):
            execution.started = True
            actor = sessions.authorize(session, identity, moment, admin=True)
            row = records.target(session, key)
            audit_event = audit_log.make_event(
                OperationType.DELETE_ACCOUNT, audit_log.actor(actor), row, audit, moment
            )
            records.keep_admin(session, row)
            sessions.revoke_all(session, key)
            session.delete(row)
            audit_log.finish(session, audit_event, None)

    @protect
    def create_first_admin(
        self, command: NewAccount, *, now: datetime, audit: AuditContext
    ) -> AccountView:
        """仅在没有任何管理员时通过本地运维创建首个管理员。

        Args:
            command: 合法新账号信息；role 必须为 ADMINISTRATOR，不接受成员。
            now: aware 当前时刻，精度微秒。
            audit: 运维入口必须显式传 OPS_AUDIT_CONTEXT；来源 IP 和请求编号均为空，不接受其他上下文值。

        Returns:
            AccountView，启用、must_change_password=False；首次口令由本人交互输入，不发会话。

        Raises:
            AccountInputError: 字段、角色或 now 无效。
            ConflictError: 已存在任意管理员（含停用），或登录名重复、锁/约束冲突。
            InputError: 数据库/UTC 列损坏；不修复存量数据。
            ExternalError: 数据库打开、提交或清理 I/O 失败，或 Argon2 名额排队超过 1 秒；失败不提交。
            DefectError: 运维上下文不是合法的双空 AuditContext，或首号哈希、引擎、SQL、快照构造错误。
            TypeError: 调用 create_first_admin 时遗漏必填关键字参数 audit，函数体尚未执行。

        Side Effects:
            先校验 command、时间及显式 OPS_AUDIT_CONTEXT，在只读事务确认没有任何管理员；已有管理员的预检拒绝不写操作日志。
            交互已由运维入口完成，读事务关闭后开始申请初始哈希名额才算开始；哈希完成后持写锁再次检查无管理员及登录名唯一。
            创建启用且不强制改密的首号，并追加 CREATE_FIRST_ADMIN，操作人固定 ActorRef(None,"运维")；不创建会话。
            新账号与成功日志一次提交，before={}、after 为账号白名单；哈希资源失败、并发另一首号/重名/锁冲突及存储故障均需回滚或关闭后补记失败。
            失败对象编号必须为空，不能保留回滚过程中分配的号；事件名字固定“新账号”，明细不包含交互口令或哈希。
            漏传 audit 在调用绑定时失败，非法运维上下文或其他输入校验失败均不记；独立补记失败只给原错误加安全标记，由运维命令最外层记 ERROR。

        Time Semantics:
            首号创建和操作日志统一使用运维注入的 aware now，转换 UTC 后保留微秒，不读取系统业务时钟。
            密码交互在本服务调用前结束；哈希名额最多排队 1 秒，之后创建事务获锁最多 5000 毫秒。
            原事务结束后失败日志最多等 AUDIT_SHORT_LOCK_TIMEOUT_MS=100 毫秒；不因时间回拨拒绝首号，也不自动重试并发创建。
        """
        validate_context(audit, ops=True)
        moment = records.utc(now)
        command = records.new_account(command)
        if command.role is not Role.ADMINISTRATOR:
            failure = problem(AccountInputError, "首个账号必须为管理员", field="role")
            raise failure
        with session_scope(self.engine, read_only=True) as session:
            records.require_no_admin(session)
        before_event = audit_log.make_event(
            OperationType.CREATE_FIRST_ADMIN, OPS_ACTOR, None, audit, moment
        )
        with audit_log.attempt(self.engine, before_event, started=True):
            encoded = self.passwords.hash(command.credentials.password)
            with session_scope(self.engine) as session:
                records.require_no_admin(session)
                audit_event = audit_log.make_event(
                    OperationType.CREATE_FIRST_ADMIN, OPS_ACTOR, None, audit, moment
                )
                row = records.make_row(command, encoded, OPS_ACTOR, moment, False)
                session.add(row)
                session.flush()
                result = records.view(row)
                audit_log.finish(session, audit_event, row)
        return result

    @protect
    def reset_password_from_ops(
        self,
        login_name: str,
        password: SecretStr,
        *,
        now: datetime,
        audit: AuditContext,
    ) -> AccountView:
        """由可信本地运维重置口令，以恢复唯一管理员的访问。

        Args:
            login_name: 已有账号的严格登录名，不修剪、不改大小写。
            password: 新 SecretStr，10-128 个码点，由 ops 交互读取。
            now: aware 当前时刻，精度微秒。
            audit: 必须明确传入具名 OPS_AUDIT_CONTEXT，表示此本地恢复命令没有来源 IP 或请求编号。

        Returns:
            更新后的 AccountView，必须改口令；不自动启用账号或改变角色，不发会话。

        Raises:
            AccountInputError: 登录名、口令或 now 无效。
            AccountNotFoundError: 本地指定的账号不存在；仅运维可得此结论。
            InputError: 数据库/UTC 列损坏；不修复存量数据。
            ConflictError: SQLite 写锁等待约 5 秒或约束冲突；无自动重试。
            ExternalError: 数据库打开、提交或清理 I/O 失败，或 Argon2 名额排队超过 1 秒；失败不提交。
            DefectError: 运维恢复的 audit 类型错误或携带非空 IP/请求编号，或恢复哈希、存储映射及 SQL 程序错误。
            TypeError: 调用 reset_password_from_ops 时遗漏必填关键字参数 audit，函数体尚未执行。

        Side Effects:
            只接受已校验的本地运维上下文；按登录名只读确认原账号编号并保存名字快照，未知目标在预检阶段拒绝、不记日志。
            关闭读事务后申请新哈希名额时算开始执行；持写锁只重读原编号与登录名，不能把同名新账号当成目标。
            成功保存预计算哈希、置必须改密、清 G2、撤销会话，并与 RESET_PASSWORD_FROM_OPS 日志原子提交；不改变启停状态或角色。
            操作人固定 ActorRef(None,"运维")，成功明细只含 must_change_password；新口令和旧哈希不进入记录。
            预检后原账号被删除/同名重建的 AccountNotFoundError、哈希资源/程序故障、写锁冲突或存储失败，关闭/回滚原事务后补一条失败操作，after={}。
            输入字段、时间或 OPS_AUDIT_CONTEXT 校验失败不补记；补记失败由运维入口凭固定标记额外报 ERROR，原重置错误与目标身份保持不变。

        Time Semantics:
            运维入口传入的 aware now 转为 UTC，重置日志用其微秒值，目标修改时间取 max(已存, now)。
            确认原目标的读事务关闭后才能最多排队 1 秒计算哈希；业务写锁最多 5000 毫秒，清 G2 属于本次显式恢复动作。
            失败补记最多等 AUDIT_SHORT_LOCK_TIMEOUT_MS=100 毫秒，须在原写事务退出后开始；回拨不报冲突，不再次按登录名寻找替代目标。
        """
        validate_context(audit, ops=True)
        moment = records.utc(now)
        name = records.login_name(login_name)
        password_text(password)
        with session_scope(self.engine, read_only=True) as session:
            previous = session.scalar(select(AccountRow).where(AccountRow.login_name == name))
            if previous is None:
                failure = problem(AccountNotFoundError, "账号不存在")
                raise failure
            key = previous.account_id
        before_event = audit_log.make_event(
            OperationType.RESET_PASSWORD_FROM_OPS, OPS_ACTOR, previous, audit, moment
        )
        with audit_log.attempt(self.engine, before_event, started=True):
            encoded = self.passwords.hash(password)
            with session_scope(self.engine) as session:
                row = records.target(session, key)
                if row.login_name != name:
                    failure = problem(AccountNotFoundError, "账号不存在")
                    raise failure
                audit_event = audit_log.make_event(
                    OperationType.RESET_PASSWORD_FROM_OPS,
                    OPS_ACTOR,
                    row,
                    audit,
                    moment,
                )
                row.password_hash = encoded
                row.must_change_password = True
                row.failed_attempts, row.blocked_until = 0, None
                records.stamp(row, OPS_ACTOR, moment)
                sessions.revoke_all(session, key)
                result = records.view(row)
                audit_log.finish(session, audit_event, row)
        return result


def _refresh_identity(
    engine: Engine, digest: str, now: datetime, previous: SessionIdentity, *, audit: AuditContext
) -> SessionIdentity:
    """刷新和过期删除均使用独立短锁；只有入场忙可跳过，过期身份始终拒绝。"""
    expired = now - previous.last_seen_at >= SESSION_IDLE_TIMEOUT
    context = session_scope_with_lock_timeout(engine, busy_timeout_ms=SESSION_TOUCH_LOCK_TIMEOUT_MS)
    entered = False
    result: SessionIdentity | None = None
    try:
        with context as session:
            entered = True
            account, saved = sessions.load(session, digest)
            elapsed = now - saved.last_seen_at
            if elapsed >= SESSION_IDLE_TIMEOUT:
                session.delete(saved)
                append_login(
                    session,
                    LoginEvent(
                        now,
                        ActorRef(account.account_id, account.display_name),
                        account.login_name,
                        LoginKind.SESSION_EXPIRED,
                        LoginResult.SUCCESS,
                        audit,
                    ),
                )
            elif elapsed >= SESSION_TOUCH_INTERVAL:
                saved.last_seen_at = max(saved.last_seen_at, now)
                result = sessions.identity(account, saved, True)
            else:
                result = sessions.identity(account, saved)
    except ConflictError as error:
        if not entered and _begin_was_busy(error):
            if expired:
                # 删除与日志都未发生，下次访问重试；拒绝过期身份不能依赖这次是否拿到锁。
                raise sessions.authentication_error() from None
            return previous
        raise
    if result is None:
        failure = sessions.authentication_error()
        raise failure
    return result


def _begin_was_busy(error: BaseException) -> bool:
    """仅识别驱动的忙码；有清理失败说明时不能伪装为可忽略的获锁失败。"""
    current: BaseException | None = error
    busy = False
    for _ in range(8):
        if current is None:
            break
        if getattr(current, "__notes__", ()):
            return False
        code = getattr(current, "sqlite_errorcode", None)
        if isinstance(code, int) and code & 0xFF in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED):
            busy = True
        nested = getattr(current, "orig", None) or current.__cause__
        current = nested if isinstance(nested, BaseException) else None
    return busy


def existing_account_ids(session: Session, identifiers: frozenset[int]) -> frozenset[int]:
    """给日志领域提供同快照的账号存在性，不以名字关联历史。

    Args:
        session: 日志查询使用的同一个受管只读事务，不可空。
        identifiers: 0 至 2*AUDIT_PAGE_LIMIT 个正整数编号，1 至 2^63-1，不含 bool。

    Returns:
        输入集合中仍存在的编号；停用账号也算存在，空输入返回空集合，不合成运维编号。

    Raises:
        AuditInputError: 编号集合类型、数量或值非法。
        InputError: 数据库损坏。
        ConflictError: 账号读取锁冲突。
        ExternalError: 账号读取 I/O 失败。
        DefectError: Session、SQL 或映射错误。

    Side Effects:
        无（只读账号编号），不读取口令/会话，不打开新事务，不覆盖历史名字。

    Time Semantics:
        与日志处于同一读快照，避免删号发生在两次查询之间导致错标。
        单次锁等待最多 5000 毫秒，无时钟读取或重试。
    """
    if (
        not isinstance(cast(object, identifiers), frozenset)
        or len(identifiers) > 2 * AUDIT_PAGE_LIMIT
    ):
        failure = audit_validation.invalid("identifiers")
        raise failure
    for identifier in identifiers:
        audit_validation.identifier(identifier)
    with audit_storage(session):
        if not session.info["rdp_read_only"]:
            raise DefectError()
        if not identifiers:
            return frozenset()
        return frozenset(
            session.scalars(
                select(AccountRow.account_id).where(AccountRow.account_id.in_(identifiers))
            )
        )


@protect
def authorize_job_actor(
    session: Session, identity: SessionIdentity, *, now: datetime, admin: bool = False
) -> ActorRef:
    """在作业业务事务内重验登录身份并返回当前操作者快照。

    Args:
        session: 已开启的受管只读或BEGIN IMMEDIATE写Session，不并发使用、不在本函数提交。
        identity: 入口认证的SessionIdentity，仅作会话定位，不信任其中缓存的角色或账号状态。
        now: 入口注入的aware时刻，统一UTC微秒；非法值归DefectError，不归用户输入错误。

        admin: True 时要求事务内当前账号为管理员，默认 False 允许成员。

    Returns:
        当前启用且完成强制改密的账号编号和显示名ActorRef；admin=False时成员/管理员均允许，True时要求管理员；不要求原作业提交人。

    Raises:
        AuthenticationError: 会话已撤销/过期或账号停用/删除，拒绝过时身份。
        PasswordChangeRequiredError: 当前账号仍须改口令。
        AuthorizationError: admin=True 且当前账号不是管理员。
        InputError: 账号/会话行或数据库损坏。
        ConflictError: 查询遇数据库锁冲突。
        ExternalError: 数据库读取I/O失败。
        DefectError: 非受管Session、非法注入时钟或SQL/映射错误。

    Side Effects:
        只读调用者事务中的会话/账号；复用账号模块内部认证规则，不刷新活动、不删除过期会话、不记作业审计。
        不返回ORM或秘密，不向jobs暴露下划线模块；写作业与审计由调用方继续同一事务。

    Time Semantics:
        使用调用者唯一请求时刻，空闲过期沿用第6张规则，回拨按经过零处理；
        事务已取得锁，无额外申请、重试或口令计算。
    """
    try:
        moment = ensure_utc(now)
    except (AttributeError, TypeError, ValueError, OverflowError):
        raise DefectError() from None
    with audit_storage(session):
        account = sessions.authorize(session, identity, moment, admin=admin)
        return ActorRef(account.account_id, account.display_name)
