"""worker 一侧的装配：把写导航层的依赖和两个框架回调接到 worker 上（M1-07，ADR 0005 修订）。

rdp.ops 的运行时装配不能直接 import 原子写、恢复、流水线三个模块（import-linter 合约），
所以装配放在这里，由 ops 只 import 本模块的两个函数。Web 一侧不调用本模块。
"""

from collections.abc import Callable
from pathlib import Path

from sqlalchemy import Engine

from rdp.infra.db.connection import session_scope
from rdp.infra.state import StatePaths
from rdp.jobs.datasets.rescan import RescanDependencies
from rdp.jobs.navwrite.marker import is_navigation_write_blocked
from rdp.jobs.navwrite.pipeline import NavWriteDependencies
from rdp.jobs.navwrite.recovery import RecoveryDependencies, recover_navigation_writes
from rdp.jobs.registry import production_registry
from rdp.jobs.service import JobService
from rdp.jobs.types import JobClock


def build_nav_write_dependencies(
    rescan: RescanDependencies, paths: StatePaths
) -> NavWriteDependencies:
    """装配 worker 的写入底座依赖。

    Args:
        rescan: worker 的扫描依赖，写入后的索引更新复用它。
        paths: 已初始化的状态布局。

    Returns:
        NavWriteDependencies；内部服务经生产类型登记表校验和提交统计或自动同步作业，
        不在提交服务中运行执行器；worker 使用完整依赖的登记表执行。

    Raises:
        DefectError: 引擎不受管。

    Side Effects:
        无（只构造对象，不读文件、不提交作业）。

    Time Semantics:
        worker 启动时调用一次。
    """
    service = JobService(rescan.engine, production_registry(rescan))
    return NavWriteDependencies(rescan=rescan, paths=paths, service=service)


def build_navigation_callbacks(
    engine: Engine, paths: StatePaths, nav_root: Path, clock: JobClock
) -> tuple[Callable[[], None], Callable[[], bool]]:
    """构造 ExecutorDependencies 的两个回调：启动恢复、领取前读标记。

    Args:
        engine: 受管 SQLite 引擎。
        paths: 已初始化的状态布局。
        nav_root: 导航层根目录绝对路径。
        clock: 注入时钟，用于恢复时写操作日志和标记。

    Returns:
        (recover_navigation, navigation_blocked)：前者在 worker 旧作业判为中断之后、第一次领取之前
        调用一次；后者每轮领取前只读数据库，返回恢复失败标记是否存在。

    Raises:
        DefectError: 引擎不受管。

    Side Effects:
        无（只构造闭包；回调被调用时才读写数据库和导航层）。

    Time Semantics:
        recover_navigation 不拿导航层写锁（此时没有别的写者）；navigation_blocked 约每秒调用一次。
    """
    dependencies = RecoveryDependencies(engine, paths, nav_root, clock)

    def recover() -> None:
        recover_navigation_writes(dependencies, checkpoint=_no_checkpoint)

    def blocked() -> bool:
        with session_scope(engine, read_only=True) as session:
            return is_navigation_write_blocked(session)

    return recover, blocked


def _no_checkpoint() -> None:
    """启动恢复阶段没有取消点；停止由主循环在恢复之后处理。"""
