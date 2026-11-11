"""转换执行（领域层，M4-03）；复用工具登记、bwrap和受管进程，只写新暂存目录。

本模块只编排六阶段，不实现MCAP/LeRobot转换算法，也不负责入库。
"""

import json
import math
import shutil
from collections.abc import Callable
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from threading import Event

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import Engine

from rdp.infra.config import StorageRootConfig, ToolsConfig
from rdp.infra.db.connection import session_scope
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
from rdp.jobs.cleaning._config import load_configs
from rdp.jobs.conversion._cleaning import (
    CleaningRuntime,
    check_files,
    check_output,
    finish_cleaning,
    preview_selection,
)
from rdp.jobs.conversion._cleaning_selection import Selection
from rdp.jobs.conversion.parameters import ConversionParameters, selected_inputs, tool_parameters
from rdp.jobs.execution import ExecutionContext
from rdp.jobs.processes import ToolCommand, run_terminal_process
from rdp.jobs.registry import StorageUse
from rdp.jobs.sandbox import SandboxSpec, sandbox_argv
from rdp.jobs.storage import check_storage_before_job
from rdp.jobs.terminal import create_terminal_parser
from rdp.jobs.types import ConversionResult, JobProgress
from rdp.tools.registry import RegisteredTool, load_tool_registry

# M4-03约定，单次verify或convert最多12小时；取消仍走框架的秒级检查与回收。
CONVERSION_TIMEOUT_S = 12 * 60 * 60.0
# 收尾只读小型元信息，上限1MiB，防止损坏文件造成无界内存。
OUTPUT_INFO_MAX_BYTES = 1024 * 1024
# 六阶段名称是M4.5-03的展示契约，不由工具输出自由改名。
CONVERSION_STAGES = ("核对工具", "核对输入", "扫描", "转换", "剔除", "收尾")


def _sandbox(argv: tuple[str, ...], spec: SandboxSpec, roots: tuple[Path, ...]) -> tuple[str, ...]:
    """生产必须经bwrap，不因程序缺失或隔离失败退回宿主执行。"""
    return sandbox_argv(argv, spec, readonly_roots=roots)


@dataclass(frozen=True)
class ConversionDependencies:
    """worker独占的转换依赖；Web只登记类型，不持有此执行对象。

    Attributes:
        engine: 受管数据库引擎，读取成功预览并重新核对输入索引。
        tools: 登记包和工具库绝对路径。
        roots: 已登记存储根，按配置顺序选第一个可写根。
        sandbox: 生产默认为bwrap；测试可注入不隔离的假工具执行边界。
        storage: worker的有界存储检查器；清理仅依赖类型声明时可为None。
    """

    engine: Engine
    tools: ToolsConfig
    roots: tuple[StorageRootConfig, ...]
    sandbox: Callable[[tuple[str, ...], SandboxSpec, tuple[Path, ...]], tuple[str, ...]] = _sandbox
    storage: StorageAccessChecker | None = field(default=None, kw_only=True)


class _OutputInfo(BaseModel):
    """工具产物的三项收尾字段，其余格式信息由入库检查解释。"""

    model_config = ConfigDict(extra="ignore")
    total_episodes: int = Field(strict=True, ge=0)
    total_frames: int = Field(strict=True, ge=0)
    codebase_version: str = Field(min_length=1)


@dataclass(frozen=True)
class ConversionExecutor:
    """绑定单工具身份及worker能力，不缓存跨作业的工具指纹结果。

    Attributes:
        tool_name: 登记包名称，启动时生成作业类型时固定。
        dependencies: worker依赖；Web为None，不能运行。
    """

    tool_name: str
    dependencies: ConversionDependencies | None

    def execute(self, context: ExecutionContext) -> None:
        """核对工具和输入后转换到新暂存区，并保存回执与产物摘要。

        Args:
            context: 当前已领取作业，参数为ConversionParameters，GPU由调度器分配。

        Returns:
            无；进度、episode/帧数、版本和产物位置通过reporter保存。

        Raises:
            DefectError: 缺少worker依赖或参数类型不正确。
            InputError: 工具不可用、参数失效、缺少预览、预览指纹或输入已变、环境未登记或变化、路径越界。
            ExternalError: 无可写根、输入大小统计失败、空间不足、子进程失败或超时，
                或产物/回执读写失败；空间不足诊断包含输入、估算产物、预留和可用字节。
            JobCancelledError: 取消后进程组已回收，暂存目录保留。
            WorkerStoppingError: worker停止，交框架在重启时标记中断。

        Side Effects:
            只在首个登记可写根新建暂存/转换/作业编号，沙箱只允许写该目录。
            输出 out；需要剔除时另产出 cleaned，成功结果指向最终产物并写转换回执.json；失败、取消或中断保留已有产物，不写导航层。
            空间预检只读输入元数据和可写根容量；不足时不建暂存目录、不启动工具。

        Time Semantics:
            六阶段依次推进；verify、convert 和剔除各至多12小时，产物核对至多300秒；
            LeRobot 导入和指纹探测各至多15秒，TERM宽限10秒并有界回收。
            起止时间由作业时钟规范化为UTC，阶段间检查取消，不重试转换。
            第2阶段在线检查后预检空间；容量访问和遍历停滞受storage的秒级预算约束，
            等待可取消；容量只反映当前观察，不保证转换途中一直够用。
        """
        if self.dependencies is None or not isinstance(context.parameters, ConversionParameters):
            raise DefectError()
        deps = self.dependencies
        started = ensure_utc(context.clock.now())
        _stage(context, 1)
        tool = _checked_tool(self.tool_name, deps.tools)
        manifest = tool.manifest
        if manifest is None or tool.program_path is None:
            raise DefectError()
        try:
            parameters = tool_parameters(manifest).model_validate(context.parameters.model_dump())
        except ValidationError as error:
            raise InputError((_diagnostic("型号或输出版本不再适用于当前工具清单"),)) from error
        _stage(context, 2)
        preview, selection = preview_selection(deps.engine, parameters, tool, deps.tools)
        inputs, stage = _prepare_paths(context, deps, parameters, selection)
        context.reporter.artifact(str(stage))
        configuration = next(
            item for item in tool.configurations if item.robot_model == parameters.robot_model
        )
        config = deps.tools.registry_dir / tool.name / configuration.filename
        substitutions = {
            "config": str(config),
            "output": str(stage / "out"),
            "format": parameters.output_format or manifest.io.output_versions[0],
        }
        verify = _command(tool, manifest.command.verify, inputs, substitutions)
        convert = _command(tool, manifest.command.convert, inputs, substitutions)
        readonly = tuple(root.path for root in deps.roots if not root.writable)
        spec = SandboxSpec((stage,))
        context.run_process(
            ToolCommand(
                tool.name,
                deps.sandbox(verify, spec, readonly),
                stage,
                CONVERSION_TIMEOUT_S,
                failure_stdout=True,
            )
        )
        _stage(context, 3)
        run_terminal_process(
            ToolCommand(
                tool.name, deps.sandbox(convert, spec, readonly), stage, CONVERSION_TIMEOUT_S
            ),
            context.reporter,
            context.log,
            context.clock,
            gpu_index=context.gpu_index,
            parser=create_terminal_parser(
                manifest.runtime.progress, stage_count=len(CONVERSION_STAGES), first_stage=3
            ),
        )
        # 无法解析进度也不能跳过固定阶段；成败始终由退出码和产物决定。
        progress = context.reporter.snapshot().progress
        if progress is None or progress.stage_index < 4:
            _stage(context, 4)
        check_output(
            context, stage, stage / "out", tuple(item.frame_count for item in selection.episodes)
        )
        _stage(context, 5)
        tool_config, _, _, _ = load_configs(
            config, deps.tools.registry_dir / tool.name / manifest.cleaning[parameters.robot_model]
        )
        output, cleaning = finish_cleaning(
            context,
            stage,
            preview,
            selection,
            CleaningRuntime(deps.tools, deps.sandbox, readonly, tool_config),
        )
        _stage(context, 6)
        receipt: dict[str, object] = {
            "job_id": context.job_id,
            "tool": {
                "name": tool.name,
                "version": manifest.tool.version,
                "binary_sha256": manifest.program.sha256,
                "source_commit": manifest.tool.source_commit,
                "source_note": manifest.tool.source_note,
            },
            "configuration": asdict(configuration),
            "commands": {"verify": verify, "convert": convert},
            "inputs": [
                {"dataset_id": parameters.dataset_id, "source_id": source_id, "path": str(path)}
                for source_id, path in ((item.source_id, item.path) for item in selection.files)
            ],
            "started_at": started.isoformat(),
            "ended_at": ensure_utc(context.clock.now()).isoformat(),
            "exit_code": 0,
            "cleaning": cleaning,
        }
        _finish(context, stage, output, receipt)


def _checked_tool(name: str, settings: ToolsConfig) -> RegisteredTool:
    """第一阶段重新核对工具；不可读登记是外部失败，坏指纹是输入问题。"""
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
            (_diagnostic(f"无法读取工具登记：{error}", DiagnosticCategory.EXTERNAL),)
        ) from error
    if tool is None:
        raise InputError((_diagnostic("工具未登记"),))
    if tool.status != "可用":
        raise InputError(
            tuple(
                item.model_copy(update={"next_step": item.next_step + "；请重新清洗预览"})
                for item in tool.diagnostics
            )
        )
    return tool


def _prepare_paths(
    context: ExecutionContext,
    deps: ConversionDependencies,
    parameters: ConversionParameters,
    selection: Selection,
) -> tuple[tuple[Path, ...], Path]:
    """重读选中输入并约束路径，在线与空间预检通过后才新建暂存目录。"""
    with session_scope(deps.engine, read_only=True) as session:
        sources = dict(
            zip(parameters.source_ids, selected_inputs(session, parameters), strict=True)
        )
    if any(
        item.source_id not in sources or not Path(item.path).is_relative_to(sources[item.source_id])
        for item in selection.files
    ):
        raise InputError((_diagnostic("输入路径与预览不再一致，请重新清洗预览"),))
    inputs = tuple(Path(item.path) for item in selection.files)
    # 根据本次输入声明存储需求，未选中的离线根不能阻挡转换。
    selected_roots: set[str] = set()
    for path in inputs:
        resolved = path.resolve()
        root = next(
            (
                root
                for root in deps.roots
                if path.is_absolute() and resolved.is_relative_to(root.path.resolve())
            ),
            None,
        )
        if root is None:
            raise InputError((_diagnostic("输入路径越出已登记存储根"),))
        selected_roots.add(root.name)
    writable = next((root for root in deps.roots if root.writable), None)
    if writable is None:
        raise ExternalError(
            (
                _diagnostic("没有登记可写存储根", DiagnosticCategory.EXTERNAL).model_copy(
                    update={"next_step": "管理员在配置文件登记可写存储根（NAS 平台区）后重新提交"}
                ),
            )
        )
    uses = tuple(
        StorageUse(root.name, write=root.name == writable.name)
        for root in deps.roots
        if root.name in selected_roots or root.name == writable.name
    )
    check_storage_before_job(
        uses, checker=deps.storage, checkpoint=context.reporter.check_cancelled
    )
    # M4-07：先确认在线再读元数据和容量；预检通过前不能建暂存或运行verify。
    if deps.storage is None:
        raise DefectError()
    failures: list[InputError] = []
    abandoned = Event()

    def access(path: Path) -> None:
        try:
            check_files(selection, abandoned.is_set)
        except InputError as error:
            # 存储边界把未知异常归缺陷；输入快照差异由主线程按原始输入类别报告。
            failures.append(error)

    try:
        check_storage_before_job(
            (StorageUse(writable.name),),
            checker=replace(deps.storage, access=access),
            checkpoint=context.reporter.check_cancelled,
        )
    finally:
        abandoned.set()
    if failures:
        raise failures[0]
    _check_space(
        context,
        deps.storage,
        writable,
        sum(item.size_bytes or 0 for item in selection.files),
        parameters,
    )
    stage = _new_staging(writable.path, context.job_id)
    return inputs, stage


def _check_space(
    context: ExecutionContext,
    checker: StorageAccessChecker | None,
    writable: StorageRootConfig,
    input_bytes: int,
    parameters: ConversionParameters,
) -> None:
    """只累计本次选中数据块，容量不足以统一外部失败阻止后续写入。"""
    if checker is None:
        raise DefectError()
    # 整数百分比向上取整避免大字节数经浮点乘法损失精度；偏置按完整字节预留。
    estimated_bytes = (input_bytes * parameters.space_ratio_percent + 99) // 100
    if parameters.excluded_episodes:
        estimated_bytes *= 2
    reserve_bytes = math.ceil(parameters.space_reserve_gib * 1024**3)
    available_bytes = _available_bytes(writable, checker, context)
    if available_bytes < estimated_bytes + reserve_bytes:
        actual = "，".join(
            f"{name} {value} 字节（{value / 1024**3:.2f} GiB）"
            for name, value in (
                ("输入", input_bytes),
                ("估算产物", estimated_bytes),
                ("预留", reserve_bytes),
                ("可用", available_bytes),
            )
        )
        actual += (
            f"，百分比 {parameters.space_ratio_percent}%，偏置 {parameters.space_reserve_gib:g} GiB"
        )
        if parameters.excluded_episodes:
            actual += "，估算产物按两倍计（工具产物 + 清洗后副本）"
        raise ExternalError(
            (
                Diagnostic(
                    level=DiagnosticLevel.ERROR,
                    category=DiagnosticCategory.EXTERNAL,
                    stage="核对输入",
                    source="平台",
                    objects=(DiagnosticObject(key="storage_root", value=writable.name),),
                    rule="conversion.insufficient_space",
                    actual=actual,
                    expected="可用空间不少于估算产物与预留之和",
                    consequence="未开始转换，未建暂存目录",
                    next_step="释放可写根空间后重新提交",
                ),
            )
        )


def _available_bytes(
    root: StorageRootConfig, checker: StorageAccessChecker, context: ExecutionContext
) -> int:
    """参照M2容量快照复用worker的有界检查，取消或超时后不发布迟到容量。"""
    abandoned = Event()
    outcome: list[int] = []

    def access(path: Path) -> None:
        checker.access(path)
        if abandoned.is_set():
            return
        available = shutil.disk_usage(path).free
        if not abandoned.is_set():
            outcome.append(available)

    try:
        check_storage_before_job(
            (StorageUse(root.name, write=True),),
            checker=replace(checker, access=access),
            checkpoint=context.reporter.check_cancelled,
        )
    finally:
        abandoned.set()
    return outcome[0]


def _finish(
    context: ExecutionContext, stage: Path, output: Path, receipt: dict[str, object]
) -> None:
    """产物元信息和回执都就绪后才发布成功结果，保留终端最后分项计数。"""
    try:
        info_path = output / "meta/info.json"
        if not info_path.resolve().is_relative_to(stage):
            raise InputError((_diagnostic("产物路径越出本作业暂存目录"),))
        with info_path.open("rb") as stream:
            info = _OutputInfo.model_validate_json(stream.read(OUTPUT_INFO_MAX_BYTES))
        with (stage / "转换回执.json").open("x", encoding="utf-8") as stream:
            json.dump(receipt, stream, ensure_ascii=False, indent=2)
        result = ConversionResult(**info.model_dump(), output_path=str(output))
    except (OSError, ValueError) as error:
        raise ExternalError(
            (_diagnostic(f"收尾读取产物或写回执失败：{error}", DiagnosticCategory.EXTERNAL),)
        ) from error
    progress = context.reporter.snapshot().progress
    if progress is None:
        raise DefectError()
    context.reporter.report(
        progress.model_copy(
            update={
                "done": info.total_frames,
                "total": info.total_frames,
                "unit": "帧",
                "total_items": info.total_episodes,
                "conversion": result,
            }
        )
    )
    context.reporter.artifact(str(output))
    context.reporter.artifact(str(stage / "转换回执.json"))


def _stage(context: ExecutionContext, index: int) -> None:
    """阶段切换保留分项和累计警告，避免收尾把工具进度擦掉。"""
    context.reporter.check_cancelled()
    previous = context.reporter.snapshot().progress
    progress = (
        JobProgress(
            stage_index=index,
            stage_count=len(CONVERSION_STAGES),
            stage_name=CONVERSION_STAGES[index - 1],
            done=0,
            total=None,
            unit="项",
            warning_count=0,
            failed_items=0,
            total_items=0,
        )
        if previous is None
        else previous.model_copy(
            update={
                "stage_index": index,
                "stage_name": CONVERSION_STAGES[index - 1],
                "done": 0,
                "total": None,
            }
        )
    )
    context.reporter.report(progress)


def _new_staging(root: Path, job_id: int) -> Path:
    """每层拒绝软链接，只新建作业目录；已有作业不能覆盖重跑。"""
    try:
        path = root.resolve()
        for part in ("暂存", "转换"):
            path = path / part
            if path.is_symlink():
                raise InputError((_diagnostic("暂存目录包含软链接"),))
            path.mkdir(exist_ok=True)
        path = path / str(job_id)
        path.mkdir(exist_ok=False)
        return path
    except OSError as error:
        raise ExternalError(
            (_diagnostic(f"无法新建转换暂存目录：{error}", DiagnosticCategory.EXTERNAL),)
        ) from error


def _command(
    tool: RegisteredTool,
    template: tuple[str, ...],
    inputs: tuple[Path, ...],
    substitutions: dict[str, str],
) -> tuple[str, ...]:
    """清单参数逐项填充，多输入按原顺序展开，不经过shell。"""
    return (
        str(tool.program_path),
        *(
            value
            for argument in template
            for value in (
                tuple(str(path) for path in inputs)
                if argument == "{inputs}"
                else (argument.format_map(substitutions),)
            )
        ),
    )


def _diagnostic(actual: str, category: DiagnosticCategory = DiagnosticCategory.INPUT) -> Diagnostic:
    """补转换上下文，最终错误日志由作业执行器统一记录。"""
    return Diagnostic(
        level=DiagnosticLevel.ERROR,
        category=category,
        stage="转换",
        source="平台",
        objects=(),
        rule="conversion.execution",
        actual=actual,
        expected="登记有效、路径受控且工具完整生成产物",
        consequence="转换失败，已有暂存产物保留",
        next_step="检查工具、输入与存储登记后重新提交",
    )
