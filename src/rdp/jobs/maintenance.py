"""清除作业适配（领域层，09/验收7）；复用第5/7张清除函数，不复制保留期 SQL。

报错保留期来自配置，操作/登录日志共用数据库设置；数据库事务在服务里，执行上下文只拿能力对象。
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from pydantic import BaseModel, ConfigDict
from sqlalchemy import Engine

from rdp.audit.types import PurgeResult
from rdp.jobs.execution import ExecutionContext


@dataclass(frozen=True)
class MaintenanceActions:
    """执行上下文获得的最小清除能力，不暴露引擎、Session 或保留期配置。

    Attributes:
        purge_errors: 接收注入 aware UTC 时刻，提交后返回报错删除数；绑定 MaintenanceService.purge_errors。
        purge_logs: 接收同类时刻，返回两种日志的 PurgeResult；绑定 MaintenanceService.purge_logs。
    """

    purge_errors: Callable[[datetime], int]
    purge_logs: Callable[[datetime], PurgeResult]


class PurgeParameters(BaseModel):
    """清除作业无可由提交人覆盖的参数；保留期始终取服务端配置或设置。"""

    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)


class MaintenanceService:
    """仅供 worker 清除类型使用的能力，不把 Session 暴露给类型执行函数。"""

    def __init__(self, engine: Engine, error_retention_days: int) -> None:
        """绑定报错清除配置与受管数据库。

        Args:
            engine: 已迁移引擎，生命周期归入口，不跨方法保存 Session。
            error_retention_days: 最终配置 [errors] retention_days，1 至 MAX_RETENTION_DAYS，单位 UTC 天。

        Returns:
            无；记录依赖，不读取或修改日志保留设置。

        Raises:
            DefectError: 非受管引擎、bool/非整数或越界保留期。

        Side Effects:
            不建表、不清记录、不启动定时器。

        Time Semantics:
            构造不取时钟；报错保留期是入口启动配置快照。
        """
        raise NotImplementedError

    def purge_errors(self, now: datetime) -> int:
        """用配置保留期调用 clear_expired_errors 并提交删除计数。

        Args:
            now: 注入的 aware 执行时刻，转换 UTC，不能用定时计划时刻冒充执行时刻。

        Returns:
            已提交删除的报错行数，非负；没有过期记录为零。

        Raises:
            DefectError: 注入时钟无效或转换/减保留期溢出，不能作为用户参数错误。
            InputError: 数据库损坏。
            ConflictError: 普通写锁等待用尽。
            ExternalError: DELETE/提交/关闭失败，保持下层异常链。

        Side Effects:
            一个独立事务调用现有 clear_expired_errors，失败回滚全部删除；不写递归操作日志。
            仅删严格早于 now-retention_days 的报错；不动作业或运行日志文件。

        Time Semantics:
            保留期每一天固定 86400 秒，边界恰好相等/未来记录保留；锁最多 BUSY_TIMEOUT_MS。
        """
        raise NotImplementedError

    def purge_logs(self, now: datetime) -> PurgeResult:
        """委托第 7 张服务按共同保留期原子清除两种日志。

        Args:
            now: 注入的 aware 执行时刻，统一 UTC 微秒。

        Returns:
            第 7 张已提交的 PurgeResult，保留操作/登录两种独立删除计数及实际保留期。

        Raises:
            DefectError: 注入时钟非法、时间换算溢出或服务装配缺陷。
            InputError: 数据库或保留设置损坏。
            ConflictError: 清除事务普通写锁超时。
            ExternalError: 任一表删除、提交或关闭失败，两种删除一起回滚。

        Side Effects:
            调 AuditMaintenance.purge_expired 原有入口，不在外面嵌套写事务、不拆成两个清除作业。
            不写清除自身的操作日志；提交这个作业时已经写了系统提交日志。

        Time Semantics:
            执行时读取最新共同保留期，UTC 固定天数；一次普通锁预算，不跨两表重新读取 now。
        """
        raise NotImplementedError


def execute_purge_errors(context: ExecutionContext) -> None:
    """清除过期报错并把实际删除条数写入作业摘要。

    Args:
        context: purge_errors 上下文，PurgeParameters；维护服务必须已由 worker 注入。

    Returns:
        无；事务提交后报告单阶段 done=total_items=删除数、unit=条、失败/警告为零，结果仍由框架计算。

    Raises:
        JobCancelledError: 清除前或提交后的检查点收到取消，不撤销已提交删除。
        WorkerStoppingError: 清除前/后的停止检查；恢复为 restart，重复清除幂等。
        InputError: 数据库损坏。
        ConflictError: 清除写锁冲突。
        ExternalError: 清除、进度或日志 I/O 失败。
        DefectError: 上下文、时钟、参数或计数不合法。

    Side Effects:
        调 maintenance.purge_errors(context.clock.now())；只在真实提交后上报计数，不预报待删数量。
        零条同样完成；删除后尚未上报即崩溃时，重跑摘要只记录此次实际删除数，不伪造原删除数。

    Time Semantics:
        事务前后各检查一次取消，不在 DELETE 中间打断；耗时沿用 reporter 单调计时。
    """
    raise NotImplementedError


def execute_purge_logs(context: ExecutionContext) -> None:
    """联合清除过期操作与登录日志并报告两类删除数。

    Args:
        context: purge_audit_logs 上下文，空参数模型与注入维护服务。

    Returns:
        无；摘要 progress 的 stage_name 明确两类删除数，done/total_items 为两数之和，unit=条；
        不把删除日志行误算作警告或失败，日志结尾和数据库共用此摘要。

    Raises:
        JobCancelledError: 清除前/提交后取消，已经删除的日志不恢复。
        WorkerStoppingError: 检查点停止，下一实例 restart 重跑。
        InputError: 数据库/保留设置损坏。
        ConflictError: 日志清除普通写锁冲突。
        ExternalError: 原子清除、上报或日志写入失败。
        DefectError: 非法上下文/时钟/计数，或缺少维护服务。

    Side Effects:
        只调一次 maintenance.purge_logs，提交成功后报告独立两数和总数，不拆分提交。
        若提交后崩溃，重跑只报告当次删除数；保留期不写死在定时参数里。

    Time Semantics:
        两表使用同一 aware UTC now，严格早于共同截止才删除；取消检查在原子事务外。
    """
    raise NotImplementedError
