"""M4.5 清洗转换编排辅助；预览约束、产物核对和回执共用同一选择，不重算清洗规则。"""

import hashlib
import json
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import Engine

from rdp.infra.config import ToolsConfig
from rdp.infra.db.connection import session_scope
from rdp.infra.diagnostics import (
    Diagnostic,
    DiagnosticCategory,
    DiagnosticLevel,
    DiagnosticObject,
    ExternalError,
    InputError,
)
from rdp.jobs.cleaning._config import ToolConfig
from rdp.jobs.cleaning.records import CleaningPreview, read_preview
from rdp.jobs.conversion._check_data import safe
from rdp.jobs.conversion._cleaning_selection import Selection, select
from rdp.jobs.conversion._encoder import encoder_parameters
from rdp.jobs.conversion._process import CHECK_TIMEOUT_S
from rdp.jobs.conversion.lerobot import (
    ENV_DIRECTORY,
    PROBE_TIMEOUT_S,
    environment_argv,
    inspect_environment,
)
from rdp.jobs.conversion.parameters import ConversionParameters
from rdp.jobs.errors import JobNotFoundError
from rdp.jobs.execution import ExecutionContext
from rdp.jobs.processes import ToolCommand
from rdp.jobs.records import find_job
from rdp.jobs.sandbox import SandboxSpec
from rdp.tools.registry import RegisteredTool

# 删除可重编码全部视频，工单给定与转换一致的 12 小时上限。
DELETE_TIMEOUT_S = 12 * 60 * 60.0


def preview_selection(
    engine: Engine, parameters: ConversionParameters, tool: RegisteredTool, settings: ToolsConfig
) -> tuple[CleaningPreview, Selection]:
    """先验证预览身份和三个指纹；失败发生在任何暂存写入之前。"""
    identifier = parameters.cleaning_preview_job_id
    if identifier is None:
        raise InputError((problem("转换必须从清洗预览发起"),))
    try:
        with session_scope(engine, read_only=True) as session:
            preview = read_preview(session, identifier)
            original = find_job(session, identifier)
    except JobNotFoundError as error:
        raise InputError((problem("预览不存在，请重新清洗预览"),)) from error
    manifest = tool.manifest
    if manifest is None:
        raise InputError((problem("工具清单无效，请重新清洗预览"),))
    configuration = next(
        (item for item in tool.configurations if item.robot_model == parameters.robot_model), None
    )
    try:
        package = settings.registry_dir / tool.name
        rules = package / manifest.cleaning[parameters.robot_model]
        if not rules.resolve().is_relative_to(package.resolve()):
            raise InputError((problem("清洗规则路径越界，请重新清洗预览"),))
        rules_sha = hashlib.sha256(rules.read_bytes()).hexdigest()
    except (OSError, KeyError) as error:
        raise InputError((problem("规则不可读取，请重新清洗预览"),)) from error
    if (
        (preview.dataset_id, preview.robot_model, preview.tool_name)
        != (parameters.dataset_id, parameters.robot_model, tool.name)
        or original.parameters.get("source_ids") != parameters.source_ids
        or preview.binary_sha256 != manifest.program.sha256
        or configuration is None
        or preview.config_sha256 != configuration.sha256
        or preview.rules_sha256 != rules_sha
    ):
        raise InputError((problem("预览身份、工具、配置或规则已变化，请重新清洗预览"),))
    selection = select(preview, parameters)
    if selection.excluded_indices and settings.lerobot_python is None:
        raise InputError((problem("未配置 LeRobot 环境"),))
    return preview, selection


def check_files(selection: Selection, abandoned: Callable[[], bool]) -> None:
    """仅 stat 未剔除文件；由调用方的有界存储访问包装，绝不打开 MCAP。"""
    for item in selection.files:
        if abandoned():
            return
        try:
            stat = Path(item.path).stat()
        except OSError as error:
            raise InputError(
                (problem("输入文件不可读取，请重新清洗预览", path=item.path),)
            ) from error
        if (stat.st_size, stat.st_mtime_ns) != (item.size_bytes, item.mtime_ns):
            raise InputError(
                (problem("输入文件大小或 mtime 已变化，请重新清洗预览", path=item.path),)
            )


def check_output(
    context: ExecutionContext, stage: Path, output: Path, expected: tuple[int, ...]
) -> None:
    """受管平台子进程复用入库元数据读取器；超时可取消，不在 worker 主线程读 NAS。"""
    # 工具也能写暂存目录；逐层拒绝链接并只新建，防止平台跟随工具留下的链接写出沙箱。
    try:
        expectation = safe(stage, f"cleaning-{output.name}-expected.json")
        result = safe(stage, f"cleaning-{output.name}-check.json")
        with expectation.open("x") as stream:
            json.dump(expected, stream)
    except (OSError, ValueError) as error:
        raise ExternalError(
            (problem(f"无法准备产物核对：{error}", path=str(output), mismatch=True),)
        ) from error
    context.run_process(
        ToolCommand(
            "清洗产物核对",
            (
                sys.executable,
                "-m",
                "rdp.jobs.conversion._cleaning_child",
                str(output),
                str(expectation),
                str(result),
            ),
            stage,
            CHECK_TIMEOUT_S,
        )
    )
    mismatch = json.loads(result.read_text())["mismatch"]
    if mismatch is not None:
        raise ExternalError((problem(str(mismatch), path=str(output), mismatch=True),))


@dataclass(frozen=True)
class CleaningRuntime:
    """删除阶段的环境及沙箱边界。

    Attributes:
        settings: 已登记工具与解释器配置。
        sandbox: 与转换一致的沙箱参数构造器。
        readonly: 全部只读存储根绝对路径。
        config: 转换命令所用登记配置经清洗解析器校验后的对象。
    """

    settings: ToolsConfig
    sandbox: Callable[[tuple[str, ...], SandboxSpec, tuple[Path, ...]], tuple[str, ...]]
    readonly: tuple[Path, ...]
    config: ToolConfig


def finish_cleaning(
    context: ExecutionContext,
    stage: Path,
    preview: CleaningPreview,
    selection: Selection,
    runtime: CleaningRuntime,
) -> tuple[Path, dict[str, object]]:
    """产物核对后才允许删除；回执记录的是实际换算编号与实际执行环境。"""
    settings, sandbox, readonly = runtime.settings, runtime.sandbox, runtime.readonly
    output = stage / "out"
    retained_files = {item.file_index for item in selection.files}
    receipt: dict[str, object] = {
        "cleaning_preview_job_id": preview.job_id,
        "rules_sha256": preview.rules_sha256,
        "config_sha256": preview.config_sha256,
        "excluded_files": [
            {
                "file_index": item.file_index,
                "path": item.path,
                "reason": "；".join(issue.actual for issue in item.fatal_issues) or "用户选择剔除",
            }
            for item in preview.report.files
            if item.file_index not in retained_files
        ],
        "excluded_episodes": [
            {
                "file_index": selection.episodes[index].file_index,
                "segment_index": selection.episodes[index].segment_index,
                "episode_index": index,
                "reason": "；".join(issue.message for issue in selection.episodes[index].issues)
                or "用户选择剔除",
            }
            for index in selection.excluded_indices
        ],
        "lerobot_version": None,
        "lerobot_fingerprint": None,
        "command": None,
        "encoder": None,
    }
    if not selection.excluded_indices:
        return output, receipt

    def run(command: tuple[str, ...], scratch: Path) -> None:
        context.run_process(
            ToolCommand(
                "LeRobot 环境探测",
                sandbox(command, SandboxSpec((stage,)), readonly),
                scratch,
                PROBE_TIMEOUT_S,
            )
        )

    environment = inspect_environment(settings, run=run, temporary_parent=stage)
    if environment.status != "available":
        raise InputError((problem(environment.message or "LeRobot 环境探测失败"),))
    python = settings.lerobot_python
    if python is None:
        raise InputError((problem("未配置 LeRobot 环境"),))
    cleaned = stage / "cleaned"
    encoder = encoder_parameters(runtime.config)
    command = environment_argv(
        python,
        stage,
        (
            str(ENV_DIRECTORY / "delete_episodes.py"),
            str(output),
            str(cleaned),
            "--encoder",
            json.dumps(encoder, ensure_ascii=False),
            *(str(index) for index in selection.excluded_indices),
        ),
    )
    context.run_process(
        ToolCommand(
            "LeRobot 剔除",
            sandbox(command, SandboxSpec((stage,)), readonly),
            stage,
            DELETE_TIMEOUT_S,
        )
    )
    excluded_indices = set(selection.excluded_indices)
    kept = tuple(
        item.frame_count
        for index, item in enumerate(selection.episodes)
        if index not in excluded_indices
    )
    check_output(context, stage, cleaned, kept)
    receipt.update(
        lerobot_version=environment.actual_version,
        lerobot_fingerprint=environment.actual_fingerprint,
        command=command,
        encoder=encoder,
    )
    return cleaned, receipt


def problem(actual: str, *, path: str | None = None, mismatch: bool = False) -> Diagnostic:
    """清洗输入过期和工具产物不一致分属输入与外部失败，均明确不入库。"""
    return Diagnostic(
        level=DiagnosticLevel.ERROR,
        category=DiagnosticCategory.EXTERNAL if mismatch else DiagnosticCategory.INPUT,
        stage="转换" if mismatch else "核对输入",
        source="平台",
        objects=() if path is None else (DiagnosticObject(key="path", value=path),),
        rule="cleaning.output_mismatch" if mismatch else "cleaning.preview_check",
        actual=actual,
        expected="产物 episode 和帧数逐项符合预览"
        if mismatch
        else "预览身份、指纹和输入文件与当前一致",
        consequence="转换失败，不剔除、不入库，暂存保留" if mismatch else "转换停止，不入库",
        next_step="检查工具与预览差异" if mismatch else "请重新清洗预览",
    )
