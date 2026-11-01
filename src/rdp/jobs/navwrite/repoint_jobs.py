"""改指向的作业登记；只读预览统一交第 07 张保存，确认后由 nav_write_apply 执行。"""

from functools import partial

from rdp.accounts.types import Role
from rdp.infra.diagnostics import DefectError
from rdp.jobs.execution import ExecutionContext
from rdp.jobs.navwrite.jobs import run_preview
from rdp.jobs.navwrite.pipeline import NavWriteDependencies
from rdp.jobs.navwrite.repoint import build_repoint_preview
from rdp.jobs.navwrite.repoint_models import REPOINT_PREVIEW_TYPE, RepointParameters
from rdp.jobs.registry import JobDefinition
from rdp.jobs.types import ExecutionMode, RecoveryMode


def build_repoint_definition(dependencies: NavWriteDependencies | None) -> JobDefinition:
    """登记只读的改指向预览类型。

    Args:
        dependencies: worker 注入写入依赖，Web 传 None，仅登记参数校验能力。

    Returns:
        nav_repoint_preview，RESTART、并发 1、不写导航层、无 GPU 及静态存储声明。

    Raises:
        无。

    Side Effects:
        无；只返回定义，不启动作业或读取路径。

    Time Semantics:
        Web/worker 启动时各登记一次；失败重跑从头读取状态。
    """
    return JobDefinition(
        REPOINT_PREVIEW_TYPE,
        "预览改指向",
        RepointParameters,
        RecoveryMode.RESTART,
        partial(_execute, dependencies),
        submission_role=Role.MEMBER,
    )


def _execute(dependencies: NavWriteDependencies | None, context: ExecutionContext) -> None:
    """验证执行上下文，复用只读预览公共收尾；缺 worker 依赖属于程序缺陷。"""
    if (
        dependencies is None
        or not isinstance(context.parameters, RepointParameters)
        or context.mode not in (ExecutionMode.FRESH, ExecutionMode.RESTART)
    ):
        raise DefectError()
    parameters = context.parameters
    run_preview(
        context,
        dependencies,
        lambda checkpoint: build_repoint_preview(
            dependencies.rescan, parameters, checkpoint=checkpoint
        ),
    )
