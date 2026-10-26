"""作业提交、取消、重提与查询服务（08）；Web 只访问数据库和受限日志尾，不执行作业。

依赖accounts只使用service.authorize_job_actor、existing_account_ids及公开types/models；不导入下划线模块，复用第6张鉴权规则，
不缓存角色。依赖 audit 使写操作与操作日志原子提交；执行前拒绝不记日志，执行后失败
回滚再按第 7 张短事务补记，补记失败附固定标记交 API 边界报告，不在本层打日志。
"""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import Engine

from rdp.accounts.types import SessionIdentity
from rdp.audit.types import AuditContext
from rdp.jobs.registry import JobRegistry
from rdp.jobs.types import JobPage, JobQuery, JobRecord, WorkerHeartbeat


@dataclass(frozen=True)
class JobRequest:
    """入口必须显式提供的身份和审计上下文，不接受前端声明操作者。

    Attributes:
        identity: 已认证 SessionIdentity；服务在业务事务中重新核验会话、启停和强制改密。
        now: 本请求唯一 aware 时刻，转换 UTC 微秒；非法注入值为 DefectError。
        audit: ASGI 来源及服务器请求编号，必填；无 client 的 IP 可空，request_id 不可空。
    """

    identity: SessionIdentity
    now: datetime
    audit: AuditContext


class JobService:
    """短事务领域服务，不持有 Session、线程或可变请求状态。"""

    def __init__(self, engine: Engine, registry: JobRegistry) -> None:
        """绑定受管数据库与入口私有的类型登记表。

        Args:
            engine: 已迁移到 0004 的受管 SQLite Engine，生命周期归入口。
            registry: 启动时已登记完成的 JobRegistry，Web 和 worker 各自构造。

        Returns:
            无；保存依赖，不连接数据库。

        Raises:
            DefectError: 非受管引擎、非 JobRegistry 或不可用依赖。

        Side Effects:
            无；不迁移、不创建状态目录、不执行示例作业。

        Time Semantics:
            构造无等待；调用方法各开自己的短事务，不跨请求共享会话。
        """
        raise NotImplementedError

    def submit(
        self, request: JobRequest, type_name: str, parameters: dict[str, object]
    ) -> JobRecord:
        """任何登录账号提交一个经类型模型校验的作业。

        Args:
            request: 必填身份、唯一请求时刻和审计来源；不要求管理员。
            type_name: 当前登记的稳定英文键。
            parameters: 不可信 JSON 对象，至多 JOB_PARAMETERS_MAX_BYTES，按当前模型严格校验。

        Returns:
            已提交的 queued 记录，提交人为事务内当前账号；参数保留模型的 JSON 值和默认值。

        Raises:
            AuthenticationError: 事务内会话已撤销/过期或账号停用、删除。
            PasswordChangeRequiredError: 当前账号必须先改口令。
            JobInputError: 未登记类型、非法参数、额外字段或编码后超长；不回显原值。
            InputError: 数据库损坏。
            ConflictError: 写锁、约束或作业编号耗尽。
            ExternalError: 作业或审计写入/提交/清理失败。
            DefectError: 注入时刻/审计上下文、类型定义、SQL 或序列化错误。

        Side Effects:
            事务外先校验参数，写事务内重验身份；insert_job 与提交作业操作日志同事务提交。
            对象 kind=job，object_id 为编号文本，object_name 为“显示名 #编号”（最多 61 码点）。
            明细 v1 仅含 job_id、job_type、job_state；before 为空，after 为已提交值，无参数。
            校验或权限拒绝不记日志；开始写入后失败整体回滚，短锁补记失败日志，补记失败不覆盖原错误。

        Time Semantics:
            request.now 用于作业及审计，UTC 微秒；BUSY_TIMEOUT_MS 普通锁预算，补记最多
            AUDIT_SHORT_LOCK_TIMEOUT_MS，无重试，外部计算不放在写事务。
        """
        raise NotImplementedError

    def cancel(self, request: JobRequest, job_id: int) -> JobRecord:
        """请求取消任意账号提交的作业，取消身份记为当前账号。

        Args:
            request: 当前已登录且完成改密的身份与审计上下文，不按提交人限制。
            job_id: 严格正整数，最大 2^63-1。

        Returns:
            queued→cancelled 或 running→cancelling 的已提交记录；后者表示请求已登记，未承诺工具已退出。

        Raises:
            AuthenticationError: 事务内重验时身份失效。
            PasswordChangeRequiredError: 当前账号必须先改口令。
            JobInputError: 编号格式/范围非法。
            JobNotFoundError: 原作业不存在。
            ConflictError: 已是 cancelling 或终态、条件 UPDATE 竞争失败，或写锁冲突。
            InputError: 数据库损坏。
            ExternalError: 状态/审计写入、提交或清理 I/O 失败。
            DefectError: 上下文非法、状态机或映射错误。

        Side Effects:
            先取得BEGIN IMMEDIATE写锁，再重验身份并读当前作业状态，transition_job仍使用WHERE state=:expected；
            worker先领取提交时本次读到running，成功转cancelling并记录当前账号取消，不能用事务外旧queued返回冲突。
            取消先提交时 worker 的 queued→running 失败且不执行。合法取消与操作日志原子提交，
            明细 before/after 带 job_id/job_type/job_state，对象为 job，不删除任何产物。
            已取消/正在取消/已完成/已中断及竞争败方均在执行前拒绝，不补记失败日志；
            真正开始更新后的存储失败按第 7 张补记，after 为空。

        Time Semantics:
            用请求 UTC 时刻；排队取消当次完成，运行中由主循环最多约一秒发现并在阶段边界停止。
            普通事务锁预算 BUSY_TIMEOUT_MS；补记 AUDIT_SHORT_LOCK_TIMEOUT_MS，无自动重试。
        """
        raise NotImplementedError

    def resubmit(self, request: JobRequest, job_id: int) -> JobRecord:
        """从终态作业复制参数，作为当前账号的新提交。

        Args:
            request: 点重新提交按钮的账号上下文，不要求原提交人或管理员。
            job_id: 原作业正编号，必须为 completed/cancelled/interrupted。

        Returns:
            新 queued 记录，新编号及提交时间，resubmitted_from 指向原记录；旧记录不变。

        Raises:
            AuthenticationError: 重验时会话或账号无效。
            PasswordChangeRequiredError: 账号须先改口令。
            JobNotFoundError: 原记录不存在。
            JobInputError: 编号非法、原类型已移除或原参数按当前模型无效；不回显原参数。
            ConflictError: 原记录非终态、写锁/约束冲突。
            InputError: 存量 JSON 或数据库损坏。
            ExternalError: 新记录/审计事务失败。
            DefectError: 时钟、上下文或映射错误。

        Side Effects:
            当前模型只验证兼容性，不向原参数补默认值或改写原值；成功复制原 JSON 新增一行。
            操作类型仍为提交作业，明细 after 加 resubmitted_from，页面显示“重新提交自 #N”。
            参数不入审计；权限、参数、非终态拒绝不记日志；执行失败回滚并按提交规则补记。

        Time Semantics:
            request.now 为新提交时间，旧开始/结束时间不复制；写锁最多 BUSY_TIMEOUT_MS，
            补记短锁，不调用 worker 或等待原作业。
        """
        raise NotImplementedError

    def get(self, request: JobRequest, job_id: int) -> JobRecord:
        """向任意登录账号返回作业详情及提交人当前删除标记。

        Args:
            request: 身份及 UTC 请求时刻，只读事务仍重验会话和强制改密。
            job_id: 正整数作业编号。

        Returns:
            完整永久记录；账号已删除时保留历史名字并设置 submitter_deleted=True。

        Raises:
            AuthenticationError: 会话或账号失效。
            PasswordChangeRequiredError: 尚未完成强制改密。
            JobInputError: 编号非法。
            JobNotFoundError: 指定作业不存在。
            InputError: 持久化 JSON/数据库损坏。
            ConflictError: 读取锁冲突。
            ExternalError: 读取或清理失败。
            DefectError: 时钟/存量状态不一致或查询程序错误。

        Side Effects:
            无；同一只读快照查询作业及账号是否存在，不读取整份日志或修改历史名字。

        Time Semantics:
            请求时刻只用于身份核验，数据库时刻保留 UTC 微秒；读锁沿用 BUSY_TIMEOUT_MS，无轮询。
        """
        raise NotImplementedError

    def list(self, request: JobRequest, query: JobQuery) -> JobPage:
        """按状态和稳定游标查询所有提交人的作业。

        Args:
            request: 任意登录账号上下文；不按角色或提交人缩小范围。
            query: 状态可空、limit 1-100、游标最长 512 字符；非法游标不回退首页。

        Returns:
            仅job_id DESC的有界页；自增编号就是提交顺序，submitted_at仅作展示；游标绑定状态、limit、首页最大编号，
            后续新增不插入既有翻页。状态会改变，跨页不承诺冻结整个队列；允许空页。

        Raises:
            AuthenticationError: 查询事务身份无效。
            PasswordChangeRequiredError: 强制改密未完成。
            JobInputError: 状态、分页、游标编码/版本/筛选绑定非法。
            InputError: 数据库或行内容损坏。
            ConflictError: 查询锁冲突。
            ExternalError: 读取 I/O 或关闭失败。
            DefectError: 注入时钟、查询映射或状态/结果不一致。

        Side Effects:
            无；最多读取 limit+1 行及当前页账号存在性，不全量加载作业，不记查看操作日志。

        Time Semantics:
            墙钟回拨不禁止查询未来提交记录；只读锁最多 BUSY_TIMEOUT_MS，无自动重试。
        """
        raise NotImplementedError

    def heartbeat(self, request: JobRequest) -> WorkerHeartbeat | None:
        """读取最近 worker 心跳，供入口计算在线状态。

        Args:
            request: 任意已认证账号上下文，仍检查会话有效和强制改密。

        Returns:
            单行心跳快照；从未启动过 worker 时 None，不用伪造进程号或时刻。

        Raises:
            AuthenticationError: 会话失效。
            PasswordChangeRequiredError: 必须改口令。
            InputError: 数据库损坏。
            ConflictError: 心跳读取锁冲突。
            ExternalError: 查询失败，不将故障伪装成离线。
            DefectError: 非法时钟、心跳字段或 SQL 映射错误。

        Side Effects:
            无；只读心跳，不探测 PID、不触碰 worker 锁或运行日志。

        Time Semantics:
            heartbeat_online 使用 request.now 与存储的 UTC 时刻比较；不跨进程比较 monotonic。
        """
        raise NotImplementedError
