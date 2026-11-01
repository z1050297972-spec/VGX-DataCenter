"""创建操作的只读预览作业入口（worker 领域层，M1-08、ADR 0005/0006）。

只负责参数/执行上下文交接，调用 create_builders 后由 run_preview 保存同一份计划。
实际执行统一交给第 07 张 nav_write_apply，日志、回滚、恢复与索引更新不在此实现。
"""

import logging
from functools import partial

from rdp.accounts.types import Role
from rdp.infra.db.connection import session_scope
from rdp.infra.diagnostics import DefectError
from rdp.infra.timeutil import ensure_utc
from rdp.jobs.execution import ExecutionContext
from rdp.jobs.navwrite.create_builders import build_dataset_preview, build_link_preview
from rdp.jobs.navwrite.create_models import (
    DATASET_PREVIEW_TYPE,
    LINK_PREVIEW_TYPE,
    DatasetPreviewParameters,
    LinkPreviewParameters,
)
from rdp.jobs.navwrite.jobs import run_preview
from rdp.jobs.navwrite.pipeline import NavWriteDependencies
from rdp.jobs.navwrite.provenance import ActorStamp
from rdp.jobs.records import find_job
from rdp.jobs.registry import JobDefinition
from rdp.jobs.types import ExecutionMode, JobProgress, RecoveryMode

logger = logging.getLogger(__name__)


def execute_link_preview(
    dependencies: NavWriteDependencies | None, context: ExecutionContext
) -> None:
    """执行建链预览并持久保存可确认的计划。

    Args:
        dependencies: worker 完整依赖；Web 登记时为 None，执行时不可缺少。
        context: LinkPreviewParameters 上下文，只允许 FRESH/RESTART，编号为本次预览编号。

    Returns:
        无；run_preview 保存 nav-previews/<作业编号>.json.gz，作业结果由框架计算。

    Raises:
        InputError: build_link_preview 拒绝输入或 run_preview 发现指纹不可验证。
        ConflictError: builder 观察到导航读取期间发生变化。
        ExternalError: 目标访问失败、离线/超时或预览文件保存失败。
        JobCancelledError: 检查点检出取消，不发布半份预览。
        WorkerStoppingError: worker 停止，下次 RESTART 从头读取。
        DefectError: 缺依赖、参数/执行模式不匹配或计划模型违约。

    Side Effects:
        经 run_preview 调用 build_link_preview，只读导航和存储；保存预览到状态目录。
        RESTART 复用 run_preview 删除旧结果，不拿导航写锁、不写导航或存储根。

    Time Semantics:
        有界检查点响应取消与停止；目标超时来自根登记。前端轮询既有作业接口，
        仅 completed 且成功的预览可确认；不把文件提前出现当作作业已成功。
    """
    if (
        dependencies is None
        or not isinstance(context.parameters, LinkPreviewParameters)
        or context.mode not in (ExecutionMode.FRESH, ExecutionMode.RESTART)
    ):
        raise DefectError()
    parameters = context.parameters
    preview = run_preview(
        context,
        dependencies,
        lambda checkpoint: build_link_preview(
            dependencies.rescan, parameters, checkpoint=checkpoint
        ),
    )
    _finished(context, preview.report.file_count, preview.report.link_count)


def execute_dataset_preview(
    dependencies: NavWriteDependencies | None, context: ExecutionContext
) -> None:
    """执行新增数据集预览，使用真实提交人生成来源印记。

    Args:
        dependencies: worker 写入底座依赖；Web 侧为 None，不获取 worker 文件访问能力。
        context: DatasetPreviewParameters 的 FRESH/RESTART 上下文；时钟返回 aware UTC。

    Returns:
        无；可确认的 NavPreview 保存在与本预览作业编号对应的压缩文件。

    Raises:
        InputError: 数据集重名、编号不可确认、第一链接/格式/来源不合约或指纹不可验证。
        ConflictError: 预览构造期间目的或最大编号变化。
        ExternalError: 根离线/超时、作业身份读取或预览落盘失败。
        JobCancelledError: 阶段间或构造中的检查点收到取消。
        WorkerStoppingError: worker 停止，自动重跑重新观察状态。
        DefectError: 缺依赖、上下文类型/模式错误、身份不是人工提交或时钟非法。

    Side Effects:
        只读作业提交人快照，用 context.clock.now 构造 ActorStamp，交 build_dataset_preview；
        run_preview 写状态目录，不创建数据集、不提前分配数据库对象或写来源文件。

    Time Semantics:
        来源印记使用本次预览 UTC 时刻；重跑生成新印记与新计划，不续用失败前的预计编号。
        预览本身无导航写锁，真正写入必须重新核对。
    """
    if (
        dependencies is None
        or not isinstance(context.parameters, DatasetPreviewParameters)
        or context.mode not in (ExecutionMode.FRESH, ExecutionMode.RESTART)
    ):
        raise DefectError()
    with session_scope(dependencies.rescan.engine, read_only=True) as session:
        actor = find_job(session, context.job_id).submitted_by
    if actor.account_id is None:
        raise DefectError()
    try:
        at = ensure_utc(context.clock.now()).strftime("%Y-%m-%dT%H:%M:%SZ")
    except (ValueError, TypeError, AttributeError, OverflowError) as error:
        raise DefectError() from error
    set_by = ActorStamp(
        kind="人工标注", account_id=actor.account_id, account_name=actor.name, at=at
    )
    parameters = context.parameters
    preview = run_preview(
        context,
        dependencies,
        lambda checkpoint: build_dataset_preview(
            dependencies.rescan, parameters, set_by, checkpoint=checkpoint
        ),
    )
    _finished(context, preview.report.file_count, preview.report.link_count)


def build_creation_definitions(
    dependencies: NavWriteDependencies | None,
) -> tuple[JobDefinition, ...]:
    """构造两个创建预览的作业定义，供生产登记表使用。

    Args:
        dependencies: worker 的完整写入依赖；Web 传 None，只登记参数校验能力。

    Returns:
        按 LINK_PREVIEW_TYPE、DATASET_PREVIEW_TYPE 顺序的两个定义，参数分别为
        LinkPreviewParameters、DatasetPreviewParameters，中文名为预览建链、预览新增数据集。
        两者 RecoveryMode.RESTART、writes_navigation=False、并发 1、无 GPU、storage 声明空；
        不新增第二种写入执行器，确认后统一提交 NAV_APPLY_TYPE。

    Raises:
        DefectError: 非空依赖引擎不受管、导航根非绝对路径或参数模型登记不合约。

    Side Effects:
        无（仅返回定义，不登记全局单例、不运行 builder、不查询存储）。

    Time Semantics:
        两个入口在启动登记期各调用一次；自动重跑次数沿用现有作业框架上限。
    """
    if dependencies is not None and (
        not dependencies.rescan.engine.get_execution_options().get("rdp_managed")
        or not dependencies.rescan.nav_root.is_absolute()
    ):
        raise DefectError()
    return (
        JobDefinition(
            LINK_PREVIEW_TYPE,
            "预览建链",
            LinkPreviewParameters,
            RecoveryMode.RESTART,
            partial(execute_link_preview, dependencies),
            submission_role=Role.MEMBER,
        ),
        JobDefinition(
            DATASET_PREVIEW_TYPE,
            "预览新增数据集",
            DatasetPreviewParameters,
            RecoveryMode.RESTART,
            partial(execute_dataset_preview, dependencies),
            submission_role=Role.MEMBER,
        ),
    )


def _finished(context: ExecutionContext, files: int, links: int) -> None:
    """完整预览发布后才上报完成，结果仍由 M0 按计数计算。"""
    context.reporter.report(
        JobProgress(
            stage_index=1,
            stage_count=1,
            stage_name="生成预览",
            done=1,
            total=1,
            unit="预览",
            total_items=1,
            failed_items=0,
            warning_count=0,
        )
    )
    logger.info("创建预览已保存 files=%s links=%s", files, links)
