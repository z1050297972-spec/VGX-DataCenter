"""账号领域事务服务（06 G1-G3），每个方法拥有自己的工作单元，不向外泄漏 Session。

复用 session_scope：写事务先 BEGIN IMMEDIATE，再重读会话、角色和最后管理员计数。
登录失败是必须提交的状态：在事务内记录结果，正常退出提交后才抛 401/429；
其他失败回滚。认证与业务读事务分开，绝不把 get_read_session 升级为写会话。
不写任何日志；口令库异常先在 security 边界脱敏，数据库只允许 hide_parameters 引擎。
所有 Argon2 名额申请、排队、核验和哈希都在数据库事务之外；只读快照退出后才开始计算，
计算完成并释放名额后才进入 BEGIN IMMEDIATE。写事务内只重验状态并保存已算好的结果，禁止调用 PasswordCodec。
"""

from datetime import datetime

from pydantic import SecretStr
from sqlalchemy import Engine

from rdp.accounts.security import PasswordCodec
from rdp.accounts.types import (
    AccountPage,
    AccountStatus,
    AccountView,
    Credentials,
    NewAccount,
    PasswordChange,
    Role,
    SessionGrant,
    SessionIdentity,
)


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
        raise NotImplementedError

    def login(self, credentials: Credentials, *, now: datetime) -> SessionGrant:
        """验证登录并签发新的服务端会话。

        Args:
            credentials: Credentials，登录名和口令符合 policy 的严格边界；不允许 None。
            now: 请求开始时刻，aware datetime，精度微秒；所有等待与活动时刻均由它计算。

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
            DefectError: 引擎、SQL、映射、熵源或 Argon2 程序错误，不带秘密异常链。

        Side Effects:
            先在只读会话中取得账号编号、password_hash、启停状态及原始 G2 二元组（failed_attempts, blocked_until），
            退出并关闭只读会话后才申请 Argon2 名额。未知/停用账号仅做一次 dummy verify，返回统一 401，不计数、不建行；
            初始 G2 已在等待则直接 429，不申请名额、不做哈希。过期待重置的 G2 在只读阶段只计算，不写回。
            有效快照在事务外 verify；成功所需的重哈希也在此完成，释放名额后再 BEGIN IMMEDIATE。
            写事务重读同一账号：已删除/停用则 401；当前已在等待则 429；否则哈希或原始 G2 状态变了则 409。
            这些变化拒绝均不写计数/哈希/会话，丢弃算好的结果，不自动重试；不会将旧口令的验证结果用于新哈希。
            三项仍一致才应用结果：失败前四次提交递增计数后 401，第五次保存 now+60 秒并在提交后 429；
            已过期的等待从零重新计数。成功清 G2，只有当前哈希仍等于快照才写入预先算好的替代哈希，再创建会话。
            新会话 activity_refreshed=False；重哈希/G2 不改账号审计时间。每账号最多 32 会话，按创建时间及摘要淘汰最旧。
            提交失败不签发 SessionGrant；容量超时发生在写事务之前，不留部分变化。

        Time Semantics:
            仅使用注入 aware now 的 UTC 微秒；负经过时长按 0，既有等待截止不因回拨改变。
            从 blocked_until-60 秒算经过时长；剩余秒向上取整为 1-60，截止相等时允许尝试。
            只读查询结束后最多排队 1 秒再运算；Argon2 不持有任何数据库事务或写锁，完成后才等待写锁约 5 秒。
            原始 G2 快照比较包含已过期但尚未清零的状态，不能仅比较“当前是否等待”；整个操作不自动重试。
        """
        raise NotImplementedError

    def authenticate(self, token: SecretStr | None, *, now: datetime) -> SessionIdentity:
        """核验当前会话并按最小间隔持久化活动时间。

        Args:
            token: cookie 的 SecretStr；None 表示缺失，不可把原文放诊断；合法时为规范 43 位令牌。
            now: 当前请求的 aware 时刻，精度微秒，不能来自客户端。

        Returns:
            当前启用账号的 SessionIdentity；每次重读角色和 must_change_password，不缓存权限。
            只有本次实际提交活动更新才 activity_refreshed=True；未到间隔、BUSY 跳过或并发请求已刷新均为 False。

        Raises:
            AccountInputError: now 无时区或 UTC 换算溢出。
            AuthenticationError: 缺失/非法/未知令牌、账号已删/停用，或 max(0, now-last_seen_at) >= 7 天。
            InputError: 数据库或 UTC 列损坏。
            ConflictError: 初始只读认证查询、过期删除或刷新中非获锁阶段的数据库锁/约束冲突；
                仅有效会话的活动刷新在 BEGIN IMMEDIATE 获锁失败时按下述尽力而为处理，不抛 409。
            ExternalError: 数据库读写、提交或清理 I/O 失败，不按有效身份放行。
            DefectError: 摘要、SQL、映射或引擎配置错误，安全诊断不含令牌。

        Side Effects:
            先用独立只读事务核验摘要，找到后 hmac.compare_digest 复核；不碰业务查询 Session。
            未满 60 秒只读返回。需刷新时通过 infra.db.connection.session_scope_with_lock_timeout，
            在独立连接上以 SESSION_TOUCH_LOCK_TIMEOUT_MS=100 毫秒的 busy_timeout 开始短写事务，
            再重读身份和过期条件后更新 max(已存 last_seen_at, now)。不得修改共享引擎或其他工作单元的超时。
            只有该刷新事务入场因 SQLITE_BUSY/SQLITE_LOCKED 未取得写锁时，关闭并放弃刷新，返回此前已核验的身份，
            activity_refreshed=False，本请求继续且不续 cookie；不能把其他写入/提交错误当作这项豁免。
            取得锁后发现并发撤销/停用则拒绝，不复活会话；并发请求已经刷新时不再写、不再续 cookie。
            过期会话删除先提交再抛 401；删除失败不能放行。没有绝对有效期或定时清理入口。
            到期始终按已持久化 last_seen_at；写入正常时可提前不足 60 秒，连续 BUSY 则遗漏活动可能更长，
            即使一直请求也可能到旧截止而过期，不在内存或 cookie 中伪造已落库的续期。

        Time Semantics:
            只读注入的 aware now，转换 UTC 保留微秒；max(0, now-last_seen_at) 用于刷新和到期判断。
            回拨不报错、不改旧活动时间或到期基准；更新只取 max(已存, now)。不读系统时钟，不做 Argon2。
            初始查询及过期删除仍沿用普通约 5 秒锁预算；仅活动刷新 BEGIN 的忙等待为 100 毫秒，
            PRAGMA 必须在 BEGIN 前设置，不能等已获写锁后才改。获锁超时跳过，不再重试或退回 5 秒等待；
            这不承诺连接初始化、磁盘 I/O 或 SQL 运算的总耗时上限。
        """
        raise NotImplementedError

    def logout(self, identity: SessionIdentity, *, now: datetime) -> None:
        """撤销当前会话，保留同账号其他会话。

        Args:
            identity: 已通过鉴权的身份；只取其摘要定位会话，不信任旧快照权限。
            now: aware 当前时刻，精度微秒。

        Returns:
            无；删除不存在的目标会话也视为成功，供同一已鉴权请求安全重入。

        Raises:
            AccountInputError: now 无时区或 UTC 换算溢出。
            InputError: 数据库损坏。
            ConflictError: 当前会话删除的 SQLite 写锁或约束冲突。
            ExternalError: 删除、提交、回滚或关闭连接的 I/O 故障。
            DefectError: 引擎、SQL 或映射程序错误。

        Side Effects:
            独立写事务只删除 identity 指定的摘要行；行已不存在也提交成功，不修改其他会话或账号。
            提交后入口才能清 cookie；失败回滚，不宣称服务端已登出，不记录令牌或日志。

        Time Semantics:
            now 只做 aware/UTC 输入校验，本操作不根据时刻延长会话、计算 G2 或更改审计时间。
            回拨不阻止撤销；SQLite 单次写锁等待约 5 秒，无 Argon2、时钟读取或重试。
        """
        raise NotImplementedError

    def change_password(
        self, identity: SessionIdentity, change: PasswordChange, *, now: datetime
    ) -> SessionGrant:
        """校验当前口令后改自己的口令并轮换全部会话。

        Args:
            identity: 当前会话身份，不接受目标账号编号；允许 must_change_password=True。
            change: 当前和新口令的 SecretStr，均 10-128 个码点；不允许新旧相同。
            now: aware 当前时刻，精度微秒。

        Returns:
            新 SessionGrant；must_change_password=False，只保留本次新会话。

        Raises:
            AccountInputError: 字段类型/长度、新旧口令相同，或领域直接调用的 now 无效、等待截止加时溢出。
            CurrentPasswordError: AccountInputError 的 400 子类；状态快照一致且当前口令错误，诊断“当前口令不正确”，保留会话。
            AuthenticationError: 只读阶段或写事务重验发现当前会话失效/撤销、账号不存在/停用；不包含单纯旧口令错误。
            LoginWaitError: 初始或重读状态处于 G2 等待，或本次提交第五次旧口令错误；不清 cookie。
            InputError: 数据库/UTC 列或已存口令编码损坏。
            ConflictError: 会话仍有效且账号启用、不在等待，但口令哈希或原始 G2 状态已变化，请用户重试；以及 SQLite 写锁/约束冲突。
            ExternalError: 数据库 I/O/清理失败或事务外 Argon2 入场排队超时，不计失败。
            DefectError: SQL、映射、熵源或 Argon2 程序错误，不附秘密异常链。

        Side Effects:
            先在只读会话核验当前会话并读取同一账号的 password_hash、启停状态和原始 G2 二元组；
            允许强制改密账号，初始等待中直接 429，不做哈希。退出只读会话后才核验当前口令；新旧原文用 compare_digest 比较。
            当前口令正确时在事务外算好新口令哈希；verify 产生的旧口令按需重哈希结果不写入，本次只保存新口令的哈希。
            所有 Argon2 排队/运算结束并释放名额后才 BEGIN IMMEDIATE；重新核验当前会话仍有效、账号仍启用，
            并比较 password_hash 和原始（failed_attempts, blocked_until）与快照一致。
            会话撤销/账号不可用返回 401；已在等待返回 429；其余哈希/G2 变化返回 409，均不应用旧结果、不改计数或会话。
            只有快照一致才提交：旧口令错误前四次保存计数后抛 CurrentPasswordError（400），第五次保存等待后 429；
            这两类不撤销当前会话、不清 cookie。正确时原子保存新哈希、清强制标记/G2、修改人快照、撤销全部旧会话并新建当前会话。
            成功提交后才设置新 cookie；计算失败或提交失败不留下部分密码/会话变更，不自动重试。

        Time Semantics:
            使用 aware now 的 UTC 微秒；负会话经过时长取 0，既有 G2 截止不因回拨重设。
            G2 截止相等可尝试，原始快照状态必须在写锁内逐项复核；不能把并发变化当一次错口令。
            只读事务先结束，再分别进行旧口令核验和新口令哈希，每次入场最多排队 1 秒；所有名额在写事务前释放。
            修改时间取 max(已存, now)，新会话用 now；短写事务获锁约 5 秒，无重试。
        """
        raise NotImplementedError

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
        raise NotImplementedError

    def create_account(
        self, identity: SessionIdentity, command: NewAccount, *, now: datetime
    ) -> AccountView:
        """由管理员新建启用账号并强制首次改口令。

        Args:
            identity: 管理员会话身份；事务内重验，不能从客户端声明操作者。
            command: 合法登录名、显示名、Role 和初始 SecretStr，不可空。
            now: aware 当前时刻，精度微秒。

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
            DefectError: 引擎/SQL/映射或哈希程序错误；不附原文、哈希、令牌或 cookie。

        Side Effects:
            先只读核验管理员身份/强制改密状态并校验输入，退出读事务后在事务外算好初始口令哈希。
            释放 Argon2 名额后才 BEGIN IMMEDIATE，重验操作者会话/角色并检查登录名唯一性；写事务不申请名额、不做哈希。
            创建启用账号，保存已算好的哈希、must_change_password=True 和管理员的创建/修改人快照，不为目标建会话。
            角色/会话变化、重名或提交失败全部拒绝，不留半条记录；预先计算的哈希丢弃，不记录秘密。

        Time Semantics:
            创建和初始修改时间使用 aware now 的 UTC 微秒；重验操作者的负会话经过时长按 0。
            初始口令哈希在所有读事务结束后最多排队 1 秒，完成后才进入最长约 5 秒获锁的短写事务。
            回拨不拒绝创建，不读墙钟，无 G2 更新或自动重试。
        """
        raise NotImplementedError

    def set_role(
        self, identity: SessionIdentity, account_id: int, role: Role, *, now: datetime
    ) -> AccountView:
        """修改账号角色并撤销该账号全部会话。

        Args:
            identity: 当前管理员会话身份，在写锁内重验。
            account_id: 目标内部编号，非 bool 整数，1 至 2^63-1。
            role: Role 声明的两个值之一，不可空。
            now: aware 当前时刻，精度微秒。

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
            DefectError: 引擎、SQL 或映射错误；诊断不带令牌或 cookie。

        Side Effects:
            在 BEGIN IMMEDIATE 内重读操作者、目标和启用管理员数量，避免并发绕过最后管理员约束。
            角色相同只返回原快照，不改审计或会话；实际改变时更新当前管理员快照和修改时刻，同事务撤销目标全部会话。
            允许管理员改变自己且需保留另一名启用管理员；成功后当前会话下一请求为 401。失败全回滚，不记录日志。

        Time Semantics:
            now 转 UTC 后用于目标修改时间，取 max(目标已存 updated_at, now)，不倒退。
            重验会话负经过时长按 0，回拨不抛冲突；同角色不改时间。仅同步 SQL，写锁单次约 5 秒，无 Argon2 或重试。
        """
        raise NotImplementedError

    def set_status(
        self, identity: SessionIdentity, account_id: int, status: AccountStatus, *, now: datetime
    ) -> AccountView:
        """启用或停用账号并保证最后管理员仍可用。

        Args:
            identity: 当前管理员会话身份，在写锁内重验。
            account_id: 目标内部编号，非 bool 整数，1 至 2^63-1。
            status: AccountStatus 声明的两个值之一，不可空。
            now: aware 当前时刻，精度微秒。

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
            DefectError: 引擎、SQL 或映射错误；诊断不带令牌或 cookie。

        Side Effects:
            BEGIN IMMEDIATE 后重验操作者、目标和启用管理员数量；状态相同不改时间或会话。
            实际变更保存当前管理员快照；停用同事务删除目标全部会话，启用不恢复旧会话、不清 G2。
            可停用自己但不能是最后启用管理员；成功后当前会话下一请求 401。失败整体回滚，不留下部分状态变更。

        Time Semantics:
            使用 aware now 的 UTC 微秒，修改时间取 max(已存 updated_at, now)。
            操作者会话的负经过时长按 0；回拨不报错，也不延长 G2 截止。写锁单次约 5 秒，无 Argon2 或额外重试。
        """
        raise NotImplementedError

    def reset_password(
        self, identity: SessionIdentity, account_id: int, password: SecretStr, *, now: datetime
    ) -> AccountView:
        """由管理员重置目标口令并强制其下次改口令。

        Args:
            identity: 管理员身份，事务内重验。
            account_id: 目标正整数编号，1 至 2^63-1，不接受 bool。
            password: 新 SecretStr，10-128 个 Unicode 码点，无组合要求，不可空。
            now: aware 当前时刻，精度微秒。

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
            DefectError: 引擎/SQL/映射或哈希程序错误；不附原文、哈希、令牌或 cookie。

        Side Effects:
            先用只读会话核验管理员和目标，关闭只读会话后在事务外算好新口令哈希，释放 Argon2 名额。
            再进入写事务，重验管理员会话/角色及同一目标编号仍存在；保存预先算好的哈希、must_change_password=True、
            修改人快照、清 G2 并删目标全部会话，包括重置自己；不在事务中申请名额或做 Argon2，不发替代会话。
            本操作是显式管理员重置，目标旧哈希变化不要求重新验证旧口令；当前事务按重验后的权限提交。
            容量超时在写入前失败；权限变化、目标消失或提交故障全回滚，不出现只改口令却保留旧会话。

        Time Semantics:
            aware now 转 UTC，修改时间取 max(已存, now)，会话负经过时长按 0；回拨不报错。
            新口令哈希最多排队 1 秒且不占任何数据库事务；运算完成后才等 SQLite 写锁约 5 秒。
            G2 清零来自本次明确重置，无自动重试。
        """
        raise NotImplementedError

    def delete_account(self, identity: SessionIdentity, account_id: int, *, now: datetime) -> None:
        """永久删除账号及其全部会话，保留历史操作者快照。

        Args:
            identity: 当前管理员身份，事务内重验。
            account_id: 目标正整数编号，1 至 2^63-1，不接受 bool。
            now: aware 当前时刻，精度微秒。

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
            DefectError: 引擎、SQL 或映射错误；诊断不带令牌或 cookie。

        Side Effects:
            写锁内重新检查当前管理员、目标和启用管理员数量，同事务删除目标会话及账号。
            其他记录的操作者编号/名字快照不变，已提交删除的内部编号不复用；删除自己须有另一启用管理员，
            成功后当前会话下一请求 401。失败全回滚，账号和会话都保留，不记录日志。

        Time Semantics:
            aware now 只用于操作者会话有效性检查，UTC 换算后负经过时长按 0，回拨不拒绝删除。
            本操作不更新已删除账号的修改时间、不读墙钟；SQLite 写锁等待约 5 秒，无 Argon2 或重试。
        """
        raise NotImplementedError

    def create_first_admin(self, command: NewAccount, *, now: datetime) -> AccountView:
        """仅在没有任何管理员时通过本地运维创建首个管理员。

        Args:
            command: 合法新账号信息；role 必须为 ADMINISTRATOR，不接受成员。
            now: aware 当前时刻，精度微秒。

        Returns:
            AccountView，启用、must_change_password=False；首次口令由本人交互输入，不发会话。

        Raises:
            AccountInputError: 字段、角色或 now 无效。
            ConflictError: 已存在任意管理员（含停用），或登录名重复、锁/约束冲突。
            InputError: 数据库/UTC 列损坏；不修复存量数据。
            ExternalError: 数据库打开、提交或清理 I/O 失败，或 Argon2 名额排队超过 1 秒；失败不提交。
            DefectError: 引擎/SQL/映射或哈希程序错误；不附原文、哈希、令牌或 cookie。

        Side Effects:
            输入校验和只读预检完成后关闭会话，在事务外算好初始口令哈希；运维交互及 Argon2 排队/运算均不持写锁。
            之后 BEGIN IMMEDIATE 再检查无任何管理员（含停用）和登录名唯一，保存已算好的哈希和启用首号。
            本人交互输入口令，must_change_password=False；创建/修改人 ActorRef(None,"运维")，不签发会话。
            并发只有一个成功；重读已有管理员则 ConflictError，不用预检结果越过约束；哈希丢弃，失败无部分账号。

        Time Semantics:
            使用调用方 aware now 的 UTC 微秒作为创建和初始修改时刻；交互在本函数调用前完成。
            只读预检退出后最多排队 1 秒计算哈希，释放名额后才申请约 5 秒预算的写锁，不自动重试。
        """
        raise NotImplementedError

    def reset_password_from_ops(
        self, login_name: str, password: SecretStr, *, now: datetime
    ) -> AccountView:
        """由可信本地运维重置口令，以恢复唯一管理员的访问。

        Args:
            login_name: 已有账号的严格登录名，不修剪、不改大小写。
            password: 新 SecretStr，10-128 个码点，由 ops 交互读取。
            now: aware 当前时刻，精度微秒。

        Returns:
            更新后的 AccountView，必须改口令；不自动启用账号或改变角色，不发会话。

        Raises:
            AccountInputError: 登录名、口令或 now 无效。
            AccountNotFoundError: 本地指定的账号不存在；仅运维可得此结论。
            InputError: 数据库/UTC 列损坏；不修复存量数据。
            ConflictError: SQLite 写锁等待约 5 秒或约束冲突；无自动重试。
            ExternalError: 数据库打开、提交或清理 I/O 失败，或 Argon2 名额排队超过 1 秒；失败不提交。
            DefectError: 引擎/SQL/映射或哈希程序错误；不附原文、哈希、令牌或 cookie。

        Side Effects:
            按严格登录名在只读会话确认目标账号编号，退出会话后在事务外算好新口令哈希并释放名额。
            再用写事务重读同一账号编号和登录名；已删除或同名重建为另一个编号时按 AccountNotFoundError 拒绝，不重置新账号。
            保存预先算好的哈希、置必须改密、清 G2、删全部会话并记录修改人为运维；不改变角色/启停状态、不签发会话。
            不在写事务做 Argon2 或申请名额。不存在目标、容量超时或提交故障均不留下部分重置。

        Time Semantics:
            使用调用方 aware now 的 UTC 微秒，修改时间取 max(已存, now)，回拨不报错。
            只读确认退出后最多排队 1 秒计算哈希；释放名额后再申请 SQLite 写锁约 5 秒。
            G2 因显式重置清空，不重新计算等待，不自动重试。
        """
        raise NotImplementedError
