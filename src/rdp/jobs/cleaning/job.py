"""清洗预览执行（领域层，M4.5-02）；只读工具、索引和输入，报告交终态事务保存。

复用登记、存储检查和第 01 张入口；不创建暂存、转换产物或导航层记录。
"""

from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError
from sqlalchemy import Engine

from rdp.infra.config import StorageRootConfig, ToolsConfig
from rdp.infra.db.connection import session_scope
from rdp.infra.db.validation import invalid_field
from rdp.infra.diagnostics import (
    DefectError,
    Diagnostic,
    DiagnosticCategory,
    DiagnosticLevel,
    DiagnosticObject,
    ExternalError,
    InputError,
)
from rdp.infra.storage import StorageAccessChecker
from rdp.infra.timeutil import ensure_utc
from rdp.jobs.cleaning import build_cleaning_report
from rdp.jobs.cleaning._io import collect_inputs
from rdp.jobs.cleaning.parameters import CleaningPreviewParameters, tool_parameters
from rdp.jobs.cleaning.records import CleaningPreview, save_preview
from rdp.jobs.conversion.parameters import selected_inputs
from rdp.jobs.execution import ExecutionContext
from rdp.jobs.registry import StorageUse
from rdp.jobs.storage import check_storage_before_job
from rdp.jobs.types import JobProgress, ProgressPart
from rdp.tools.registry import RegisteredTool, load_tool_registry

# M4.5-02 固定四阶段；文件序号放分项中，阶段名不随文件变化。
PREVIEW_STAGES = ("核对工具", "核对输入", "读取文件", "生成报告")


@dataclass(frozen=True)
class CleaningDependencies:
    """仅 worker 持有的只读预览能力。

    Attributes:
        engine: 已迁移数据库，用短事务重读索引。
        tools: 登记包与工具库绝对路径。
        roots: 全部已登记根，不要求存在可写根。
        storage: 有界在线检查器，测试根也须显式提供。
    """

    engine: Engine
    tools: ToolsConfig
    roots: tuple[StorageRootConfig, ...]
    storage: StorageAccessChecker


@dataclass(frozen=True)
class CleaningPreviewExecutor:
    """绑定登记工具，执行状态均留在当前调用，允许不同作业并发。

    Attributes:
        tool_name: 启动登记的工具名。
        dependencies: worker 能力；Web 为 None，不能执行。
    """

    tool_name: str
    dependencies: CleaningDependencies | None

    def execute(self, context: ExecutionContext) -> None:
        """重新核对工具与只读输入，生成完整清洗报告并登记成功写入。

        Args:
            context: 当前运行作业，参数为 CleaningPreviewParameters，提供取消和 UTC 时钟。

        Returns:
            无；四阶段进度交 reporter，报告交成功终态事务。

        Raises:
            DefectError: 缺少 worker 能力或参数类型错误。
            InputError: 工具不可用、型号规则失效、输入越界或清洗配置无效。
            ExternalError: 工具登记读取失败或输入根离线，后者保留存储检查诊断。
            JobCancelledError: 检查点发现取消，不保存部分报告。
            WorkerStoppingError: worker 停止，由框架在恢复时标为中断。

        Side Effects:
            只读输入、工具和数据库索引；生成报告仅暂存在内存，成功终态同事务新增报告。
            不写任何存储根或导航层，不创建暂存目录，不启动转换工具。

        Time Semantics:
            四阶段依次执行，每条 MCAP 记录及运算批次响应取消；存储检查受已有超时预算约束。
            生成时刻来自注入时钟并规范为 UTC；文件处理沿用第 01 张 header.stamp 语义。
        """
        deps = self.dependencies
        if deps is None or not isinstance(context.parameters, CleaningPreviewParameters):
            raise DefectError()
        _stage(context, 1)
        tool = _checked_tool(self.tool_name, deps.tools)
        manifest = tool.manifest
        if manifest is None:
            raise DefectError()
        try:
            parameters = tool_parameters(manifest).model_validate(context.parameters.model_dump())
        except ValidationError as error:
            raise InputError(
                invalid_field("robot_model", "当前工具已登记的清洗型号").diagnostics
            ) from error
        _stage(context, 2)
        inputs = _prepare_paths(context, deps, parameters)
        files, warnings = collect_inputs(inputs, context.reporter.check_cancelled)
        # 目录内文件软链接也必须检查，否则仅约束顶层目录仍能读出登记根。
        input_roots = {_root_for(path, deps.roots).name for _, path in inputs}
        file_roots = {_root_for(path, deps.roots).name for _, path in files}
        # 文件软链接允许指向另一个登记根，但那个根也要先过在线检查。
        check_storage_before_job(
            tuple(
                StorageUse(root.name)
                for root in deps.roots
                if root.name in file_roots - input_roots
            ),
            checker=deps.storage,
            checkpoint=context.reporter.check_cancelled,
        )
        _stage(context, 3)
        reading = _ReadingProgress(context)
        package = deps.tools.registry_dir / tool.name
        report = build_cleaning_report(
            files,
            package / manifest.models[parameters.robot_model],
            package / manifest.cleaning[parameters.robot_model],
            checkpoint=context.reporter.check_cancelled,
            progress=reading.bytes_read,
            file_progress=reading.start_file,
        )
        report = report.model_copy(update={"warnings": (*warnings, *report.warnings)})
        _stage(context, 4, files=report.summary.files)
        preview = CleaningPreview(
            job_id=context.job_id,
            dataset_id=parameters.dataset_id,
            tool_name=tool.name,
            robot_model=parameters.robot_model,
            binary_sha256=manifest.program.sha256,
            config_sha256=report.tool_config_sha256,
            rules_sha256=report.rules_sha256,
            created_at=ensure_utc(context.clock.now()),
            report=report,
        )
        context.save_on_success(lambda session: save_preview(session, preview))


def _checked_tool(name: str, settings: ToolsConfig) -> RegisteredTool:
    """执行时重载登记和程序指纹；不运行程序来探测状态。"""
    try:
        tool = next(
            (
                item
                for item in load_tool_registry(settings.registry_dir, settings.library_root).items
                if item.name == name
            ),
            None,
        )
    except OSError as error:
        raise ExternalError(
            (
                Diagnostic(
                    level=DiagnosticLevel.ERROR,
                    category=DiagnosticCategory.EXTERNAL,
                    stage="核对工具",
                    source="平台",
                    objects=(DiagnosticObject(key="tool", value=name),),
                    rule="cleaning.registry_read",
                    actual=f"工具登记读取失败：{type(error).__name__}",
                    expected="可读取的工具登记",
                    consequence="清洗预览失败，未生成报告",
                    next_step="检查登记目录及读取权限后重新提交",
                ),
            )
        ) from error
    if tool is None:
        raise InputError(invalid_field("tool", "已登记的清洗工具").diagnostics)
    if tool.status != "可用":
        raise InputError(tool.diagnostics)
    return tool


def _root_for(path: Path, roots: tuple[StorageRootConfig, ...]) -> StorageRootConfig:
    """复用转换路径约束，拒绝绝对路径以外及解析后越界的输入。"""
    resolved = path.resolve()
    root = next(
        (
            root
            for root in roots
            if path.is_absolute() and resolved.is_relative_to(root.path.resolve())
        ),
        None,
    )
    if root is None:
        raise InputError(invalid_field("source_ids", "已登记存储根内的输入路径").diagnostics)
    return root


def _prepare_paths(
    context: ExecutionContext, deps: CleaningDependencies, parameters: CleaningPreviewParameters
) -> tuple[tuple[str, Path], ...]:
    """重读索引后仅检查所选根，不要求可写根或预留空间。"""
    with session_scope(deps.engine, read_only=True) as session:
        inputs = selected_inputs(session, parameters)
    names = {_root_for(path, deps.roots).name for path in inputs}
    check_storage_before_job(
        tuple(StorageUse(root.name) for root in deps.roots if root.name in names),
        checker=deps.storage,
        checkpoint=context.reporter.check_cancelled,
    )
    return tuple(zip(parameters.source_ids, inputs, strict=True))


def _stage(context: ExecutionContext, index: int, *, files: int = 0) -> None:
    """阶段边界先响应取消，文件质量问题保留在报告，不误作预览执行失败。"""
    context.reporter.check_cancelled()
    context.reporter.report(
        JobProgress(
            stage_index=index,
            stage_count=len(PREVIEW_STAGES),
            stage_name=PREVIEW_STAGES[index - 1],
            done=0,
            total=None,
            unit="项",
            warning_count=0,
            failed_items=0,
            total_items=files,
        )
    )


class _ReadingProgress:
    """单次读取的进度适配，直接使用第 01 张通知，不由累计字节猜文件序号。"""

    def __init__(self, context: ExecutionContext) -> None:
        """保存本次作业上下文，不共享可变状态。"""
        self.context = context
        self.index = self.count = self.done = 0
        self.total: int | None = None

    def start_file(self, index: int, count: int, total: int | None) -> None:
        """文件开始时更新序号和总字节，累计已读字节不归零。"""
        self.index, self.count, self.total = index, count, total
        self.bytes_read(self.done)

    def bytes_read(self, done: int) -> None:
        """实际读取量超过预检大小时取消百分比分母，避免报告虚假的完整比例。"""
        self.done = done
        if self.total is not None and done > self.total:
            self.total = None
        self.context.reporter.report(
            JobProgress(
                stage_index=3,
                stage_count=4,
                stage_name=PREVIEW_STAGES[2],
                done=done,
                total=self.total,
                unit="字节",
                warning_count=0,
                failed_items=0,
                total_items=0,
                parts=(
                    ProgressPart(
                        name=f"第 {self.index}/{self.count} 个文件",
                        done=self.index - 1,
                        total=self.count,
                        unit="文件",
                    ),
                ),
            )
        )
