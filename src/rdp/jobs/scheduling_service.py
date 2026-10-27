"""调度页只读服务（领域层，09）；只查询数据库与入口注入的静态配置，不访问 worker 资源池。"""

from sqlalchemy import Engine

from rdp.jobs.scheduling_types import SchedulingCatalog, SchedulingSnapshot
from rdp.jobs.service import JobRequest


class SchedulingService:
    """任意登录账号可读的调度聚合，不持有跨请求 Session。"""

    def __init__(self, engine: Engine, catalog: SchedulingCatalog) -> None:
        """绑定调度页面的数据库及入口配置。

        Args:
            engine: 已迁移受管引擎，生命周期归 Web 入口。
            catalog: 已验证的上限、GPU 列表、定时规则和本地时区；Web 不自行寻找配置。

        Returns:
            无；不立即建立数据库连接。

        Raises:
            DefectError: 非受管引擎或配置类型/登记不一致。

        Side Effects:
            仅保存只读依赖；不创建资源池、锁、执行线程或外部进程。

        Time Semantics:
            启动时构造，配置变更重启生效；请求时刻由 snapshot 的 request 注入。
        """
        raise NotImplementedError

    def snapshot(self, request: JobRequest) -> SchedulingSnapshot:
        """读取同一数据库快照下的类型容量、GPU、写锁和每日计划。

        Args:
            request: 任意账号身份、唯一 aware 请求时刻和审计来源；事务内重验会话及强制改密。

        Returns:
            按类型键、卡号、规则名分别排序的快照，空登记/无卡/无历史分别为空集合或 None。
            类型数量用 running/cancelling 聚合，包括尚在恢复的记录；终态历史卡号不计占用。
            GPU 可用/移出池状态、核对诊断及持锁者全部由 worker 保存的数据库副本决定，心跳离线时仍保留最后观察并明确 worker_online=False。
            上次结果直接读 JobRecord，不自行从诊断样例计算；下次时刻用本机时区，返回 UTC。

        Raises:
            AuthenticationError: 会话过期、撤销、账号停用或删除。
            PasswordChangeRequiredError: 账号需要先改口令。
            InputError: 数据库或存量去重/作业记录损坏。
            ConflictError: 只读快照锁竞争。
            ExternalError: 数据库查询或清理 I/O 失败，不伪装空闲资源。
            DefectError: 多个有效持锁者、同卡多个活跃占用、非法时钟或查询映射错误。

        Side Effects:
            无；只读作业、心跳及定时表，身份重验沿用 authorize_job_actor。
            聚合不加载全部队列；每规则只读最近行和有界未来日期窗，不查看日志文件、GPU 或 worker 内存；从 worker_gpu_checks 读卡的核对结果，
            按 instance_id 与当前心跳关联，不把旧实例结果冒充新实例；未匹配为 UNKNOWN。
            配置已移除的 GPU 不列为可用卡；已移除类型不列入当前类型容量，历史仍可在作业列表查询。

        Time Semantics:
            一个普通只读事务，锁最多 BUSY_TIMEOUT_MS；checked_at 用请求时刻，日历计算不另读系统时间。
            展示允许短锁跳过造成暂时落后；不以 UTC 墙钟回拨修改数据库历史。
        """
        raise NotImplementedError
