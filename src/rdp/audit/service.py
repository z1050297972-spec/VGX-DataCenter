"""需要独立工作单元的日志领域契约（07），不调度、不鉴权、不打印运行日志。

成功追加在 records 里共享业务 Session；这里仅承接失败补记、匿名失败和保留期清除。
只用已批准 session_scope/session_scope_with_lock_timeout，避免嵌套 SQLite 写锁。
"""

from datetime import datetime

from sqlalchemy import Engine

from rdp.audit.types import LoginEvent, OperationEvent, PurgeResult


def append_failed_operation(engine: Engine, event: OperationEvent) -> None:
    """在已回滚业务之外用短写事务追加执行后的失败操作。

    Args:
        engine: 受管 SQLite 引擎，业务 Session 已回滚并关闭，不可空。
        event: result=FAILURE 且 failure_category 非空的事件；after 必须为空，
            actor/target 来自执行前已确认快照，不含异常原文；未开始执行的拒绝不得调用。

    Returns:
        无；返回表示恰好一条失败日志已提交。

    Raises:
        AuditInputError: 失败操作的业务字段不合法或传入成功结果。
        InputError: 数据库损坏。
        ConflictError: 短锁超时或插入约束冲突。
        ExternalError: 写入、提交或清理 I/O 失败。
        DefectError: 失败操作的 AuditContext 类型、来源 IP 或请求编号非法，以及引擎或 SQL/映射错误。

    Side Effects:
        独立事务追加一行，失败则回滚，不保留虚假成功日志。
        调用者必须保留原业务异常：补记失败仅给原异常增加固定 AUDIT_APPEND_FAILED 安全标记，
        不替换原异常/类别/诊断、不附第二异常原文；由 API/ops/worker 最外层按 6.3 记 ERROR。
        不在领域层打印日志；不捕获 KeyboardInterrupt/SystemExit 等控制流假装成功。

    Time Semantics:
        事件沿用原业务注入时刻，不读系统时钟；回拨不报冲突。
        独立连接 BEGIN 的等待上限 AUDIT_SHORT_LOCK_TIMEOUT_MS=100 毫秒，一次尝试，无重试；
        只限制锁等待，SQLite 磁盘 I/O 无硬实时总耗时保证。
    """
    raise NotImplementedError


def append_missing_login(engine: Engine, event: LoginEvent) -> None:
    """单独提交未知账号的失败登录，避免保存可能误填的口令原文（H2）。

    Args:
        engine: 受管引擎，初始只读查询和 dummy verify 已结束，无活动写事务。
        event: LOGIN/ACCOUNT_MISSING，account/login_name/request_id 均为空，仅带时刻和来源 IP。

    Returns:
        无；提交一条不关联任何账号的登录记录。

    Raises:
        AuditInputError: 事件包含账号身份，或结果/类型不符合未知账号失败要求。
        InputError: 数据库损坏。
        ConflictError: 100 毫秒内无法取得写锁或插入约束冲突。
        ExternalError: 写入/提交/回滚/清理 I/O 失败。
        DefectError: 匿名登录的 AuditContext 非法或请求编号未按 H2 清空，或引擎、SQL、映射错误。

    Side Effects:
        只追加登录日志，不创建账号、不更新 G2、不签发会话；失败不留半行。
        账号服务保留原 AuthenticationError；本追加失败只附安全标记，由入口单独记 ERROR。

    Time Semantics:
        UTC 微秒来自 event，不读时钟；BEGIN 最多等 AUDIT_SHORT_LOCK_TIMEOUT_MS，无重试。
        dummy verify 在进入事务前已释放 Argon2 名额，不把密码计算放进写锁。
    """
    raise NotImplementedError


def append_failed_login(engine: Engine, event: LoginEvent) -> None:
    """在原登录事务回滚后记录执行故障，不伪造口令或账号判定结果。

    Args:
        engine: 原只读/写事务已退出并关闭的受管 SQLite 引擎。
        event: LOGIN/FAILURE 且四类失败类别必填；已确认账号使用快照，未确认身份的
            account/login_name/request_id 均为空，只保留安全类别、时刻、类型和 IP。

    Returns:
        无；恰好一条独立提交的失败登录日志，不修改 G2 或签发会话。

    Raises:
        AuditInputError: 事件不是执行故障，或身份、失败类别、事件时刻不合格。
        InputError: 数据库损坏。
        ConflictError: 短锁超时或插入约束冲突。
        ExternalError: 写入、提交或清理 I/O 失败。
        DefectError: 故障登录上下文非法、未确认身份却保留请求编号，或引擎/SQL/映射错误。

    Side Effects:
        独立短事务追加登录日志；失败回滚，不留下部分事件。
        账号服务保留原故障，补记错误仅增加 AUDIT_APPEND_FAILED 固定标记，穿过账号脱敏边界后
        由 API 入口记 ERROR；不得递归补记日志写入失败或附加第二异常原文。

    Time Semantics:
        UTC 微秒沿用原请求时间，回拨不修改事件；独立连接 BEGIN 最多等待 100 毫秒，一次尝试，无重试。
    """
    raise NotImplementedError


class AuditMaintenance:
    """第 9 张定时作业可调用的保留期清除服务，不提供单条删除。

    Attributes:
        engine: 受管 SQLite 引擎，不可空；由调用者持有生命周期。
    """

    engine: Engine

    def __init__(self, engine: Engine) -> None:
        """绑定日志维护使用的数据库引擎。

        Args:
            engine: create_database_engine 创建的 SQLite 引擎，不可空。

        Returns:
            无；构造不连接数据库、不激活表或安排定时任务。

        Raises:
            DefectError: 非受管 SQLite 引擎。

        Side Effects:
            无。

        Time Semantics:
            同步构造，无时钟、等待或重试。
        """
        raise NotImplementedError

    def purge_expired(self, now: datetime) -> PurgeResult:
        """原子清除严格超过共同保留期的两种日志。

        Args:
            now: 注入的 aware 当前时刻，转换 UTC 并保留微秒；不能取客户端日期。

        Returns:
            提交后的两种删除计数、实际保留期 N 和 cutoff=now-timedelta(days=N)。
            只删 occurred_at < cutoff；恰好 N 天、较新及未来记录都保留，无匹配返回零计数。

        Raises:
            AuditInputError: now 非 aware、UTC 换算或减 N 天溢出；不执行删除。
            InputError: 数据库或设置值损坏，禁止悄悄改用默认值。
            ConflictError: 写锁超时或删除约束冲突。
            ExternalError: 删除、提交、回滚或关闭 I/O 失败。
            DefectError: 引擎/SQL/映射错误。

        Side Effects:
            一个 BEGIN IMMEDIATE 内读取最新保留期（无行取 30），删除两表过期行并一次提交。
            任一表失败两表一起回滚；不删设置、不写递归的清除操作日志、不改报错表或作业记录。
            不按批次部分提交、不使用 offset 或上次清除时刻水位，不安排定时调用。

        Time Semantics:
            UTC 的一天固定 24 小时，独立于本机时区和 DST。每次完全按传入 now 重算截止；
            回拨时截止随之提前，未来记录不被误删；下一次仍扫描整个截止范围，不漏掉回拨后插入的旧记录。
            已清除的记录无法恢复，不声称跨时钟回拨保留已删除内容；不把负经过时长当冲突。
            SQLite BEGIN 最多等 5000 毫秒，无自动重试；不承诺磁盘 I/O 的硬实时上限。
        """
        raise NotImplementedError
