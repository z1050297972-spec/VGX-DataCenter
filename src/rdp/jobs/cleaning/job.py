"""清洗预览执行（领域层，M4.5-02）；只读工具、索引和输入，报告交终态事务保存。

MCAP 复用第 01 张入口，AgiBot 在只读沙箱运行预览工具；只写工具缓存和成功报告。
"""

from collections.abc import Callable
from dataclasses import dataclass, field, replace
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
from rdp.jobs.cleaning import _g2, build_cleaning_report
from rdp.jobs.cleaning._agibot import load_snapshot, read_report
from rdp.jobs.cleaning._alpha_snapshot import task_snapshot
from rdp.jobs.cleaning._io import collect_inputs
from rdp.jobs.cleaning.models import CleaningReport
from rdp.jobs.cleaning.parameters import CleaningPreviewParameters, tool_parameters
from rdp.jobs.cleaning.records import CleaningPreview, save_preview
from rdp.jobs.conversion.parameters import selected_inputs
from rdp.jobs.execution import ExecutionContext
from rdp.jobs.processes import ToolCommand, run_terminal_process
from rdp.jobs.registry import StorageUse
from rdp.jobs.sandbox import SandboxSpec, sandbox_argv
from rdp.jobs.storage import check_storage_before_job
from rdp.jobs.terminal import TerminalParser, TerminalUpdate, create_terminal_parser
from rdp.jobs.tool_cache import result_file, tool_cache_dir
from rdp.jobs.tool_environment import offline_tool_argv
from rdp.jobs.types import JobProgress, ProgressPart
from rdp.tools.registry import RegisteredTool, load_tool_registry

# M4.5-02 固定四阶段；文件序号放分项中，阶段名不随文件变化。
PREVIEW_STAGES = ("核对工具", "核对输入", "读取文件", "生成报告")
# M4.6-03：预览最多运行 12 小时，取消和进程回收沿用受管终端的秒级检查。
PREVIEW_TIMEOUT_S = 12 * 60 * 60.0


def _sandbox(argv: tuple[str, ...], spec: SandboxSpec, roots: tuple[Path, ...]) -> tuple[str, ...]:
    """生产始终使用 bwrap，工具缓存之外没有持久可写目录。"""
    return sandbox_argv(argv, spec, readonly_roots=roots)


@dataclass(frozen=True)
class CleaningDependencies:
    """仅 worker 持有的只读预览能力。

    Attributes:
        engine: 已迁移数据库，用短事务重读索引。
        tools: 登记包与工具库绝对路径。
        roots: 全部已登记根，不要求存在可写根。
        storage: 有界在线检查器，测试根也须显式提供。
        sandbox: 默认 bwrap；测试可显式注入仅运行临时假工具的边界。
    """

    engine: Engine
    tools: ToolsConfig
    roots: tuple[StorageRootConfig, ...]
    storage: StorageAccessChecker
    sandbox: Callable[[tuple[str, ...], SandboxSpec, tuple[Path, ...]], tuple[str, ...]] = field(
        default=_sandbox, kw_only=True
    )


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
            ExternalError: 工具登记读取失败、输入根离线、预览工具失败、结果不合格或缓存操作失败。
            JobCancelledError: 检查点发现取消，不保存部分报告。
            WorkerStoppingError: worker 停止，由框架在恢复时标为中断。

        Side Effects:
            只读输入、工具和数据库索引；报告在成功终态同事务新增，不写存储根或导航层。
            有 preview 命令时在沙箱启动预览工具，仅缓存目录可写；索引缓存保留，
            结果文件在成功、失败和取消时均清理，删除失败报外部问题并保留文件。

        Time Semantics:
            四阶段依次执行，每条 MCAP 记录及运算批次响应取消；存储检查受已有超时预算约束。
            生成时刻来自注入时钟并规范为 UTC；文件处理沿用第 01 张 header.stamp 语义。
            工具预览至多 12 小时，回收后再读结果；AgiBot 段时长为帧数除以 FPS。
        """
        deps = self.dependencies
        if deps is None or not isinstance(context.parameters, CleaningPreviewParameters):
            raise DefectError()
        _stage(context, 1)
        tool = _checked_tool(self.tool_name, deps.tools)
        manifest = tool.manifest
        fingerprint = tool.fingerprint
        if manifest is None or fingerprint is None:
            raise DefectError()
        try:
            parameters = tool_parameters(manifest).model_validate(context.parameters.model_dump())
        except ValidationError as error:
            raise InputError(
                invalid_field("robot_model", "当前工具已登记的清洗型号").diagnostics
            ) from error
        _stage(context, 2)
        inputs = _prepare_paths(
            context,
            deps,
            parameters,
            input_format=manifest.io.input_format,
            task_directory=manifest.io.input_format == "agibot_native",
        )
        package = deps.tools.registry_dir / tool.name
        config_paths = (
            package / manifest.models[parameters.robot_model],
            package / manifest.cleaning[parameters.robot_model],
        )
        report = (
            _tool_report(context, deps, tool, inputs, config_paths)
            if manifest.command.preview is not None
            else _mcap_report(context, deps, inputs, config_paths)
        )
        _stage(context, 4, files=report.summary.files)
        preview = CleaningPreview(
            job_id=context.job_id,
            dataset_id=parameters.dataset_id,
            tool_name=tool.name,
            robot_model=parameters.robot_model,
            binary_sha256=fingerprint,
            config_sha256=report.tool_config_sha256,
            rules_sha256=report.rules_sha256,
            created_at=ensure_utc(context.clock.now()),
            report=report,
        )
        context.save_on_success(lambda session: save_preview(session, preview))


def _mcap_report(
    context: ExecutionContext,
    deps: CleaningDependencies,
    inputs: tuple[tuple[str, Path], ...],
    config_paths: tuple[Path, Path],
) -> CleaningReport:
    """保留 MCAP 的展开、链接边界与在线检查，不经过外部工具预览。"""
    files, warnings = collect_inputs(inputs, context.reporter.check_cancelled)
    # 目录内文件软链接也必须检查，指向另一个登记根的文件还要补在线检查。
    input_roots = {_root_for(path, deps.roots).name for _, path in inputs}
    file_roots = {_root_for(path, deps.roots).name for _, path in files}
    check_storage_before_job(
        tuple(
            StorageUse(root.name) for root in deps.roots if root.name in file_roots - input_roots
        ),
        checker=deps.storage,
        checkpoint=context.reporter.check_cancelled,
    )
    _stage(context, 3)
    reading = _ReadingProgress(context)
    report = build_cleaning_report(
        files,
        *config_paths,
        checkpoint=context.reporter.check_cancelled,
        progress=reading.bytes_read,
        file_progress=reading.start_file,
    )
    return report.model_copy(update={"warnings": (*warnings, *report.warnings)})


def _tool_report(
    context: ExecutionContext,
    deps: CleaningDependencies,
    tool: RegisteredTool,
    sources: tuple[tuple[str, Path], ...],
    config_paths: tuple[Path, Path],
) -> CleaningReport:
    """在缓存目录内运行工具并读取结果，进程回收后所有退出路径都清除结果文件。"""
    manifest = tool.manifest
    if manifest is None or manifest.command.preview is None or tool.program_path is None:
        raise DefectError()
    snapshot = load_snapshot(*config_paths)
    g2 = manifest.runtime.progress == "agibot2lerobot-g2-events"
    source = sources[0]
    try:
        before_alpha = {} if g2 else task_snapshot(source[1], context.reporter.check_cancelled)
        before_g2 = (
            tuple((path.stat().st_size, path.stat().st_mtime_ns) for _, path in sources)
            if g2
            else ()
        )
    except (OSError, ValueError) as error:
        raise InputError(
            invalid_field("source_ids", f"无法建立输入快照：{error}").diagnostics
        ) from error
    cache = tool_cache_dir(deps.tools, tool.name)
    result = result_file(cache, context.job_id)
    substitutions = {
        "config": str(config_paths[0]),
        "rules": str(config_paths[1]),
        "cache": str(cache),
        "result": str(result),
        "inputs": str(source[1]),
    }
    argv = (
        str(tool.program_path),
        *(
            value
            for arg in manifest.command.preview
            for value in (
                tuple(str(path) for _, path in sources)
                if arg == "{inputs}"
                else (arg.format_map(substitutions),)
            )
        ),
    )
    readonly = tuple(root.path for root in deps.roots if not root.writable)
    try:
        _stage(context, 3)
        run_terminal_process(
            ToolCommand(
                tool.name,
                deps.sandbox(offline_tool_argv(cache, argv), SandboxSpec((cache,)), readonly),
                cache,
                PREVIEW_TIMEOUT_S,
            ),
            context.reporter,
            context.log,
            context.clock,
            gpu_index=context.gpu_index,
            parser=_PreviewParser(
                create_terminal_parser(manifest.runtime.progress, stage_count=4, first_stage=3)
            ),
        )
        _stage(context, 4)
        report = (
            _g2.read_report(
                result,
                sources,
                snapshot,
                (config_paths[0], manifest.tool.version),
                context.reporter.check_cancelled,
            )
            if g2
            else read_report(result, source, snapshot, context.reporter.check_cancelled)
        )
        try:
            if g2:
                after = tuple((path.stat().st_size, path.stat().st_mtime_ns) for _, path in sources)
                if before_g2 != after or any(
                    not item.fatal_issues
                    and (item.size_bytes, item.mtime_ns) != after[item.file_index]
                    for item in report.files
                ):
                    raise ValueError("G2 归档在预览期间变化")
            else:
                after_alpha = task_snapshot(source[1], context.reporter.check_cancelled)
                if before_alpha != after_alpha:
                    raise ValueError("Alpha 输入文件集合或元信息在预览期间变化")
                paths = {item.path for item in report.files}
                # 工具按标注、本体感知和观测的联合集号出报告；缺观测 fatal 行没有快照，
                # 但已有观测必须完整且唯一，可转行不能借缺目录绕过后续输入复核。
                if (
                    len(paths) != len(report.files)
                    or len({item.episode_id for item in report.files}) != len(report.files)
                    or not before_alpha.keys() <= paths
                    or any(
                        item.path not in before_alpha and not item.fatal_issues
                        for item in report.files
                    )
                ):
                    raise ValueError("Alpha 报告集身份重复、遗漏已有观测或可转集缺少输入快照")
                report = report.model_copy(
                    update={
                        "files": tuple(
                            item.model_copy(
                                update={"alpha_input_snapshot": before_alpha.get(item.path)}
                            )
                            for item in report.files
                        )
                    }
                )
        except (OSError, ValueError) as error:
            raise InputError(
                invalid_field("source_ids", f"请重新预览：{error}").diagnostics
            ) from error
        return report
    finally:
        # 复用缓存边界的普通文件核对和相对目录描述符删除，不跟随工具生成的链接。
        result_file(cache, context.job_id)


@dataclass
class _PreviewParser:
    """保留工具进度事实，只把通用扫描阶段名适配为清洗固定的读取阶段。

    Attributes:
        parser: 本次运行独占的工具解析器。
    """

    parser: TerminalParser

    def feed(self, chunk: bytes) -> TerminalUpdate:
        """按原顺序解析终端输出，不改变日志内容。"""
        return self._rename(self.parser.feed(chunk))

    def finish(self) -> TerminalUpdate:
        """工具退出时保留末次进度，报告阶段只由平台进入。"""
        return self._rename(self.parser.finish())

    def _rename(self, update: TerminalUpdate) -> TerminalUpdate:
        """外部进度不能提前占用生成报告阶段。"""
        if update.progress is None:
            return update
        return replace(
            update,
            progress=update.progress.model_copy(
                update={"stage_index": 3, "stage_name": PREVIEW_STAGES[2]}
            ),
        )


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
    context: ExecutionContext,
    deps: CleaningDependencies,
    parameters: CleaningPreviewParameters,
    *,
    input_format: str,
    task_directory: bool = False,
) -> tuple[tuple[str, Path], ...]:
    """重读索引后仅检查所选根，不要求可写根或预留空间。"""
    with session_scope(deps.engine, read_only=True) as session:
        inputs = selected_inputs(session, parameters, input_format=input_format)
    if task_directory:
        _check_task_directory(inputs, deps.roots)
        # Alpha 的标注和本体感知是同数据集兄弟目录，也必须在已登记存储根内。
        _root_for(inputs[0].parent.parent, deps.roots)
    names = {_root_for(path, deps.roots).name for path in inputs}
    check_storage_before_job(
        tuple(StorageUse(root.name) for root in deps.roots if root.name in names),
        checker=deps.storage,
        checkpoint=context.reporter.check_cancelled,
    )
    if input_format == "archives":
        _g2.validate_paths(inputs, filesystem=True)
    if task_directory and not inputs[0].is_dir():
        raise InputError(invalid_field("source_ids", "请选择一个已解压的任务观测目录").diagnostics)
    return tuple(zip(parameters.source_ids, inputs, strict=True))


def _check_task_directory(inputs: tuple[Path, ...], roots: tuple[StorageRootConfig, ...]) -> None:
    """在运行工具前拒绝多选、归档及越界路径，任务编号只接受 ASCII 数字。"""
    try:
        if len(inputs) != 1:
            raise ValueError("必须恰好选择一个数据块")
        path = inputs[0]
        if (
            path.parent.name != "observations"
            or not path.name.isascii()
            or not path.name.isdecimal()
        ):
            raise ValueError("输入不是任务观测目录")
        _root_for(path, roots)
    except (ValueError, InputError) as error:
        raise InputError(
            invalid_field("source_ids", "请选择一个已解压的任务观测目录").diagnostics
        ) from error


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
