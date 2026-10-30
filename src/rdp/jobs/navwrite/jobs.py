"""写入底座的作业类型与预览作业入口（worker 写入侧，领域层，M1-07，ADR 0005、0009）。

本票登记两个通用作业类型，具体的建链、新增数据集、改指向、数据来源标注各自在 M1-08、09、10
加预览作业，用本模块的 run_preview 保存结果，再统一提交 nav_write_apply：

- `nav_write_apply`（写导航层）：参数只有预览作业编号。写导航层，恢复方式"标记中断"，
  JobDefinition.writes_navigation=True，所以"导航层恢复失败"标记在时它只排队、不开始。
- `nav_revert_preview`（预览撤回）：参数是被撤回的作业编号。只读，不拿写锁，恢复方式"重跑"，
  产出一份 operation=revert_change 的预览，然后同样提交 nav_write_apply。

"预览是只读 worker 作业"（M1-07 工单）：预览要访问存储根（L1、L3、L19），而 Web 不访问存储根。
自己写作业而不用现成队列的理由同 ADR 0005：已有 M0 的作业框架，本模块只加类型。
"""

from collections.abc import Callable
from dataclasses import dataclass
from functools import partial
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from rdp.infra.diagnostics import DefectError
from rdp.jobs.execution import ExecutionContext
from rdp.jobs.navwrite.changes import plan_revert, read_change_record
from rdp.jobs.navwrite.errors import nav_input_error
from rdp.jobs.navwrite.models import NavPreview, NavWritePlan, PlanReport
from rdp.jobs.navwrite.pipeline import NavWriteDependencies, run_write_plan
from rdp.jobs.navwrite.policy import NAV_APPLY_TYPE as NAV_APPLY_TYPE
from rdp.jobs.navwrite.previews import preview_path, write_preview
from rdp.jobs.registry import JobDefinition
from rdp.jobs.types import ExecutionMode, RecoveryMode

# 稳定的作业类型键，写进持久化的作业记录，不复用历史含义。
NAV_APPLY_NAME = "写导航层"
NAV_REVERT_PREVIEW_TYPE = "nav_revert_preview"
NAV_REVERT_PREVIEW_NAME = "预览撤回"


class NavApplyParameters(BaseModel):
    """写入作业的参数：只指向一份预览，计划本身不通过参数传递。

    Attributes:
        model_config: 冻结，拒绝多余字段，不回显不可信输入。
        preview_job_id: 预览作业编号，严格整数 ≥ 1；该作业必须已成功结束并留有预览文件。
            作业参数上限 16 KiB，装不下一份计划，所以只带编号。
    """

    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)
    preview_job_id: int = Field(strict=True, ge=1)


class NavRevertPreviewParameters(BaseModel):
    """撤回预览作业的参数。

    Attributes:
        model_config: 冻结，拒绝多余字段，不回显不可信输入。
        target_job_id: 被撤回的写入作业编号，严格整数 ≥ 1；它必须有 COMMITTED 的变更记录。
    """

    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)
    target_job_id: int = Field(strict=True, ge=1)


@dataclass(frozen=True)
class PreviewBuild:
    """具体预览作业的 builder 交回的东西。

    Attributes:
        plan: 要执行的计划，plan.state 必须是 capture_preview_state 记下的、每个指纹 verifiable。
        report: 给人看的报告，由 plan 推出，不独立重算规则。
        parameters: 要回显的参数（已校验、无秘密）。
    """

    plan: NavWritePlan
    report: PlanReport
    parameters: dict[str, JsonValue]


type PreviewBuilder = Callable[[Callable[[], None]], PreviewBuild]


def run_preview(
    context: ExecutionContext, dependencies: NavWriteDependencies, builder: PreviewBuilder
) -> NavPreview:
    """预览作业的公共收尾：调用 builder、检查可验证、把结果存成文件。

    Args:
        context: 预览作业的执行上下文；预览不拿导航层写锁。
        dependencies: 写入依赖。
        builder: 具体操作的预览生成函数，接收有界检查点（取消和停止检查），返回 PreviewBuild。

    Returns:
        已写入 nav-previews/<作业编号>.json.gz 的 NavPreview；作业编号即 context.job_id。

    Raises:
        InputError: builder 判定输入不合格（诊断由 builder 给出）；或计划的任何指纹 verifiable=False，
            此时无法在执行前证明"没变"，拒绝生成预览。
        ExternalError: 访问存储根失败（离线或超时按外部失败，ADR 0006）或写预览文件失败。
        JobCancelledError: 检查点收到取消；已写的预览文件不留（先写临时文件）。
        WorkerStoppingError: worker 停止；RESTART 恢复方式会重新计算。
        DefectError: builder 返回的计划不满足模型约束。

    Side Effects:
        读导航层与存储根（只读），写 nav-previews。不拿写锁、不写导航层。同一作业重跑时先删旧的预览文件。

    Time Semantics:
        正常 1 到 2 秒，与 ADR 0005 估计的单条建链耗时一致；访问存储根的超时取登记值，超时按离线。
        预览状态不是原子快照，写入作业会在写锁下重新核对（规范 2.3）。
    """
    paths = dependencies.paths
    preview_path(paths, context.job_id).unlink(missing_ok=True)  # 重跑：先删上一次的结果
    build = builder(context.reporter.check_cancelled)
    unverifiable = [f.dataset_id for f in build.plan.state.datasets if not f.verifiable]
    if unverifiable:
        problem = nav_input_error(
            "NAV_PREVIEW_JOB",
            "计划里有不可验证的指纹，执行前无法证明导航层没变，拒绝生成预览",
            objects=tuple((f"dataset_{n}", str(d)) for n, d in enumerate(unverifiable[:5], 1)),
        )
        raise problem
    preview = NavPreview(
        preview_job_id=context.job_id,
        created_at=context.clock.now(),
        parameters=build.parameters,
        plan=build.plan,
        report=build.report,
    )
    context.reporter.check_cancelled()  # 写文件之前最后一次响应取消；之后的写入是原子的
    write_preview(paths, preview)
    return preview


def execute_apply(dependencies: NavWriteDependencies | None, context: ExecutionContext) -> None:
    """nav_write_apply 的执行函数：读取预览并交给 run_write_plan。

    Args:
        dependencies: worker 的写入依赖；Web 侧登记传 None，执行时缺依赖属于程序缺陷。
        context: 参数为 NavApplyParameters 的执行上下文，mode 只允许 FRESH（中断后不自动续跑）。

    Returns:
        无；作业结果由框架按计数计算：成功为成功，导航层已退回为失败。

    Raises:
        DefectError: 缺依赖、参数类型或 mode 不对。
        InputError: 同 run_write_plan。
        ConflictError: 同 run_write_plan。
        ExternalError: 同 run_write_plan。
        JobCancelledError: 同 run_write_plan。
        WorkerStoppingError: 同 run_write_plan。

    Side Effects:
        同 run_write_plan；提交人身份从作业记录读取，写入变更记录和操作日志。

    Time Semantics:
        同 run_write_plan。恢复方式为标记中断：worker 中断后由 recover_navigation_writes 退回，
        不会自动重新执行。
    """
    if dependencies is None or not isinstance(context.parameters, NavApplyParameters):
        raise DefectError()
    if context.mode is not ExecutionMode.FRESH:
        raise DefectError()
    run_write_plan(context, dependencies, context.parameters.preview_job_id)


def execute_revert_preview(
    dependencies: NavWriteDependencies | None, context: ExecutionContext
) -> None:
    """nav_revert_preview 的执行函数：读变更记录、核对现状、保存反向计划的预览。

    Args:
        dependencies: worker 的写入依赖；Web 侧登记传 None。
        context: 参数为 NavRevertPreviewParameters 的执行上下文，mode 允许 FRESH 和 RESTART。

    Returns:
        无；预览保存在 nav-previews/<作业编号>.json.gz。

    Raises:
        DefectError: 缺依赖、参数类型或 mode 不对。
        InputError: 被撤回作业没有 COMMITTED 的变更记录。
        ConflictError: 当前状态不等于 #N 的后像，诊断列出变了的地方和改过它的作业。
        ExternalError: 读导航层或状态目录失败。
        JobCancelledError: 检查点收到取消。
        WorkerStoppingError: worker 停止。

    Side Effects:
        经 run_preview 调用 plan_revert 并保存预览；只读导航层，不拿写锁。

    Time Semantics:
        同 run_preview。无论操作日志是否已按保留期（30 天）清掉，只要变更记录在就能预览（场景三）。
    """
    if dependencies is None or not isinstance(context.parameters, NavRevertPreviewParameters):
        raise DefectError()
    if context.mode not in (ExecutionMode.FRESH, ExecutionMode.RESTART):
        raise DefectError()
    target = context.parameters.target_job_id

    def build(checkpoint: Callable[[], None]) -> PreviewBuild:
        record = read_change_record(dependencies.paths, target)
        plan, report = plan_revert(
            Path(dependencies.rescan.nav_root), dependencies.paths, record, checkpoint=checkpoint
        )
        return PreviewBuild(plan, report, {"target_job_id": target})

    run_preview(context, dependencies, build)


def build_navwrite_definitions(
    dependencies: NavWriteDependencies | None,
) -> tuple[JobDefinition, ...]:
    """构造本票的两个作业类型定义，供 production_registry 加入登记表。

    Args:
        dependencies: worker 传完整依赖；Web 传 None，只能校验提交参数，不能执行。

    Returns:
        (nav_write_apply, nav_revert_preview)：前者 RecoveryMode.INTERRUPT、writes_navigation=True；
        后者 RecoveryMode.RESTART、writes_navigation=False。两者并发 1、无 GPU、storage 声明为空
        （写入只碰导航层和状态目录，预览按数据集降级检查存储根，与重新扫描相同）。

    Raises:
        DefectError: 依赖的引擎不受管或 nav_root 不是绝对路径。

    Side Effects:
        只构造定义，不执行、不读配置或存储根。

    Time Semantics:
        Web 与 worker 各在启动登记期构造一次；参数模型和恢复方式不受提交人覆盖。
    """
    if dependencies is not None and (
        not dependencies.rescan.engine.get_execution_options().get("rdp_managed")
        or not dependencies.rescan.nav_root.is_absolute()
    ):
        raise DefectError()
    return (
        JobDefinition(
            NAV_APPLY_TYPE,
            NAV_APPLY_NAME,
            NavApplyParameters,
            RecoveryMode.INTERRUPT,
            partial(execute_apply, dependencies),
            writes_navigation=True,
        ),
        JobDefinition(
            NAV_REVERT_PREVIEW_TYPE,
            NAV_REVERT_PREVIEW_NAME,
            NavRevertPreviewParameters,
            RecoveryMode.RESTART,
            partial(execute_revert_preview, dependencies),
        ),
    )
