"""作业开跑前的存储许可边界（领域层，10），不访问 HTTP，也不直接写作业终态。

复用 infra.storage 的检查和既有 ExternalError/Diagnostic，最终记录与日志由执行器收口。
先核对全部写许可，再依声明顺序只读检查根，避免只读违规时仍启动数据盘访问。
"""

from collections.abc import Callable

from rdp.infra.diagnostics import (
    DefectError,
    Diagnostic,
    DiagnosticCategory,
    DiagnosticLevel,
    DiagnosticObject,
    ExternalError,
)
from rdp.infra.storage import OFFLINE_REASON_LABELS, StorageAccessChecker
from rdp.jobs._storage_requirements import validate_storage_uses
from rdp.jobs.registry import StorageUse


def check_storage_before_job(
    uses: tuple[StorageUse, ...],
    *,
    checker: StorageAccessChecker | None,
    checkpoint: Callable[[], None],
) -> None:
    """在类型函数调用前阻止不被允许或不可访问的存储需求。

    Args:
        uses: 类型声明的不可变需求元组，名字已在启动登记核对；空元组表示不需要存储。
        checker: 必填关键字的本 worker 检查器；仅 uses 为空时允许显式 None，不默认发现系统路径。
        checkpoint: 必填关键字，执行器的同步、有界取消/停止检查；空声明不调用。

    Returns:
        无；所有根许可与访问通过才允许执行器调用类型函数，空声明立即返回。

    Raises:
        ExternalError: 任一 write=True 指向只读根、根离线或检查发生基础设施错误；
            只读违规规则 storage.read_only，离线规则 storage.offline；诊断对象含 storage_root，
            实际含只读或三个离线原因之一，期望是所需许可且在线，后果为类型函数未调用、
            未向根写入，下一步为修正登记或恢复挂载后重新提交。检查异常保留原诊断及异常链。
        DefectError: 非空需求未装配 checker、名字未登记、重复需求、字段或检查返回值非法。
        JobCancelledError: 等待期间checkpoint观察到取消，执行器按当前数据库状态结束为已取消。
        WorkerStoppingError: 等待期间checkpoint观察到停止，交执行器保留可恢复的运行记录。
        Exception: checkpoint的其他上报错误原样交执行器收口。

    Side Effects:
        非空且全部许可通过后，每根只读检查会启动一个daemon线程；空声明不读表、不读时钟、不启动线程。
        不写标记文件，不改根内容，不调用类型函数；失败交 execute_job 写统一诊断及终态。

    Time Semantics:
        新作业、续跑和重跑都在类型调用之前重新检查，不复用 Web 或上次作业结果。
        顺序检查，第一项失败立即停止；每根最多 checker.options.access_timeout_s 秒，
        不在数据库事务或导航层写锁内等待；检查前后及等待中都经checkpoint响应取消/停止，
        单次控制等待片段以StorageAccessChecker的STORAGE_CHECKPOINT_INTERVAL_S为上限。
    """
    validate_storage_uses(uses)
    if not uses:
        return
    if not isinstance(checker, StorageAccessChecker):
        raise DefectError()
    roots = {root.name: root for root in checker.mounts.roots}
    for use in uses:
        root = roots.get(use.name)
        if root is None:
            raise DefectError()
        if use.write and not root.writable:
            raise ExternalError(
                (_refusal_diagnostic(use.name, "storage.read_only", "存储根登记为只读"),)
            )
    for use in uses:
        result = checker.check(use.name, checkpoint=checkpoint)
        if not result.online:
            if result.reason is None:
                raise DefectError()
            raise ExternalError(
                (
                    _refusal_diagnostic(
                        use.name, "storage.offline", OFFLINE_REASON_LABELS[result.reason]
                    ),
                )
            )


def _refusal_diagnostic(name: str, rule: str, actual: str) -> Diagnostic:
    """作业存储拒绝只生成统一诊断，终态和日志由执行器负责。"""
    return Diagnostic(
        level=DiagnosticLevel.ERROR,
        category=DiagnosticCategory.EXTERNAL,
        stage="开跑前检查",
        source="平台",
        objects=(DiagnosticObject(key="storage_root", value=name),),
        rule=rule,
        actual=actual,
        expected="存储根在线且满足类型声明的读写许可",
        consequence="类型执行函数未调用，未向存储根写入",
        next_step="修正存储登记或恢复挂载后重新提交作业",
    )
