"""AgiBot 工具结果到清洗报告的适配（领域层，M4.6-03），不运行工具或保存预览。

用 Pydantic 和 tomllib 解析外部契约，复用已有阈值模型与诊断；不重做工具的数值检查。
"""

import hashlib
import os
import stat
import tomllib
from collections.abc import Callable
from pathlib import Path
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from rdp.infra.diagnostics import (
    DIAGNOSTIC_SAMPLE_LIMIT,
    Diagnostic,
    DiagnosticCategory,
    DiagnosticLevel,
    DiagnosticObject,
    ExternalError,
    InputError,
)
from rdp.jobs.cleaning._checks import CHECK_MESSAGES, SEVERE_CHECKS, quality_issue
from rdp.jobs.cleaning._config import ConfigFloat, FrozenConfig, JumpRule, SourceRule, StaticRule
from rdp.jobs.cleaning._io import diagnostic, read_config_bytes
from rdp.jobs.cleaning.models import (
    CleaningCheckRules,
    CleaningReport,
    CleaningRuleSnapshot,
    CleaningSourceRules,
    CleaningSummary,
    EpisodeReport,
    FileReport,
    IssueDetails,
    TimeRange,
)

# 工单规定结果最多 256 MiB；只多读一字节判超限，避免工具输出造成无界读取。
MAX_RESULT_BYTES = 256 * 1024 * 1024
type NonnegativeInt = Annotated[int, Field(ge=0)]
type Seconds = Annotated[float, Field(ge=0)]


class ResultModel(BaseModel):
    """外部 JSON 的各层都拒绝未知键、类型强转和非有限数。"""

    model_config = ConfigDict(
        extra="forbid", strict=True, allow_inf_nan=False, hide_input_in_errors=True
    )


class _RobotConfig(ResultModel):
    """工具实际使用的配置身份，摘要须与登记包原始字节相符。"""

    path: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class _Proprio(ResultModel):
    """本体感知位置只校验结构，不打开其路径；未归档文件没有偏移。"""

    path: str
    offset: NonnegativeInt | None
    size: NonnegativeInt


class _Issue(ResultModel):
    """工具只上报数值事实，严重程度由平台统一赋予。"""

    check: str
    feature: str
    count: NonnegativeInt
    first_time_s: Seconds
    ranges: tuple[tuple[Seconds, Seconds], ...] = Field(max_length=DIAGNOSTIC_SAMPLE_LIMIT)


class _Episode(ResultModel):
    """一集的体检和数值结果，目录边界在报告映射前核对。"""

    episode_id: str = Field(pattern=r"^[0-9]+$")
    observation_dir: str
    observation_mtime_ns: NonnegativeInt | None
    proprio: _Proprio | None
    size_bytes: NonnegativeInt
    frames: NonnegativeInt
    problems: tuple[str, ...]
    issues: tuple[_Issue, ...]
    # preview_task 对没有 task_info 标注的集返回 null；体检问题仍由 problems 表达。
    task: str | None


class _Result(ResultModel):
    """版本一预览结果；不从未声明字段猜测帧数或配置。"""

    # Literal[1] 会按相等关系接受 JSON true；严格整数同时限制为 1 才符合版本契约。
    schema_version: int = Field(strict=True, ge=1, le=1)
    tool_version: str
    # CLI/Layout 全程使用数字字符串标识任务，不能按 int 接收或隐式转换。
    task_id: str = Field(pattern=r"^[0-9]+$")
    task_name: str
    dataset_name: str
    fps: int = Field(gt=0)
    robot_config: _RobotConfig
    feature_names: dict[str, tuple[str, ...]]
    episodes: tuple[_Episode, ...]


class _SourceRule(SourceRule):
    """来源字段与限位复用 MCAP 模型，阈值按工具 checks._number 允许零。"""

    topic: str = Field(alias="field")
    static_threshold: ConfigFloat | None = Field(default=None, ge=0, allow_inf_nan=False)
    jump_threshold: ConfigFloat | None = Field(default=None, ge=0, allow_inf_nan=False)


class _StaticRule(StaticRule):
    """按工具 checks.parse_rules 补齐 3 秒缺省值；显式零秒同样有效。"""

    long_static_s: ConfigFloat = Field(default=3.0, ge=0, allow_inf_nan=False)


class _Rules(FrozenConfig):
    """仅解析 README 声明的规则，既不读取 HDF5 也不推断图像规则。"""

    schema_version: int = Field(strict=True, ge=1, le=1)
    static: _StaticRule
    jump: JumpRule
    source: tuple[_SourceRule, ...] = ()


def load_snapshot(config: Path, rules: Path) -> tuple[str, str, CleaningRuleSnapshot]:
    """在工具启动前读取登记配置指纹和规则快照；规则不可读属于输入问题。"""
    config_bytes, rules_bytes = read_config_bytes(config), read_config_bytes(rules)
    try:
        parsed = _Rules.model_validate(tomllib.loads(rules_bytes.decode("utf-8")))
    except ValueError as error:
        raise InputError(
            (diagnostic("cleaning.config_invalid", str(error), path=rules),)
        ) from error
    return (
        hashlib.sha256(config_bytes).hexdigest(),
        hashlib.sha256(rules_bytes).hexdigest(),
        CleaningRuleSnapshot(
            sync=None,
            checks=CleaningCheckRules(
                static_feature=parsed.static.feature,
                long_static_s=parsed.static.long_static_s,
                jump_feature=parsed.jump.feature,
                frozen_s=None,
                sample_interval_s=None,
                dark_below=None,
                bright_above=None,
                sources=tuple(
                    CleaningSourceRules(**source.model_dump()) for source in parsed.source
                ),
                severe_checks=SEVERE_CHECKS,
            ),
        ),
    )


def read_report(
    result_path: Path,
    source: tuple[str, Path],
    snapshot: tuple[str, str, CleaningRuleSnapshot],
    checkpoint: Callable[[], None],
) -> CleaningReport:
    """有界读取普通结果文件并严格校验，映射期间逐集响应取消。"""
    try:
        parsed = _Result.model_validate_json(read_result_bytes(result_path))
        if parsed.robot_config.sha256 != snapshot[0]:
            raise ValueError("工具结果的配置 sha256 与登记配置不符")
        files: list[FileReport] = []
        episodes: list[EpisodeReport] = []
        root = source[1].resolve()
        for index, episode in enumerate(
            sorted(parsed.episodes, key=lambda item: int(item.episode_id))
        ):
            checkpoint()
            _validate_episode(episode, root)
            files.append(_file_report(episode, index, source[0]))
            if not episode.problems:
                episodes.append(_episode_report(episode, index, parsed.fps))
        frames = sum(episode.frame_count for episode in episodes)
        return CleaningReport(
            source_format="agibot_native",
            tool_config_sha256=snapshot[0],
            rules_sha256=snapshot[1],
            fps=parsed.fps,
            reference_topic=None,
            rules=snapshot[2],
            files=tuple(files),
            episodes=tuple(episodes),
            summary=CleaningSummary(
                files=len(files),
                excluded_files=sum(file.default_excluded for file in files),
                episodes=len(episodes),
                excluded_episodes=sum(episode.default_action == "exclude" for episode in episodes),
                reference_frames=frames,
                kept_frames=frames,
            ),
        )
    except (OSError, ValueError) as error:
        raise ExternalError((invalid_result(result_path, str(error)),)) from error


def read_result_bytes(path: Path) -> bytes:
    """拒绝链接和非普通文件，防止外部工具把结果重定向到数据或阻塞设备。"""
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    with os.fdopen(descriptor, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_RESULT_BYTES:
            raise ValueError("预览结果必须是至多 256 MiB 的普通文件")
        content = stream.read(MAX_RESULT_BYTES + 1)
    if len(content) > MAX_RESULT_BYTES:
        raise ValueError("预览结果超过 256 MiB")
    return content


def _validate_episode(episode: _Episode, root: Path) -> None:
    """解析目录链接后核对边界，所有集的未知检查都拒绝，包括已体检失败的集。"""
    path = Path(episode.observation_dir)
    resolved = path.resolve()
    if not path.is_absolute() or resolved == root or not resolved.is_relative_to(root):
        raise ValueError(f"episode 目录越出所选任务观测目录：{path}")
    for issue in episode.issues:
        if issue.check not in CHECK_MESSAGES:
            raise ValueError(f"未知检查规则：{issue.check}")
        if any(start > end for start, end in issue.ranges):
            raise ValueError("检查区间起点不得晚于终点")


def _file_report(episode: _Episode, index: int, source_id: str) -> FileReport:
    """每集映射成一个文件；体检失败只剔除该集，不阻止其他集生成预览。"""
    return FileReport(
        file_index=index,
        source_id=source_id,
        path=episode.observation_dir,
        episode_id=episode.episode_id,
        size_bytes=episode.size_bytes,
        mtime_ns=episode.observation_mtime_ns,
        fatal_issues=tuple(
            diagnostic(
                "cleaning.agibot_episode_unusable", problem, path=Path(episode.observation_dir)
            )
            for problem in episode.problems
        ),
        warnings=(),
        reference_frames=episode.frames,
        kept_frames=episode.frames,
        bad_frames=0,
        gaps=0,
        short_segments=0,
        short_frames=0,
        topics=(),
        default_excluded=bool(episode.problems),
    )


def _episode_report(episode: _Episode, index: int, fps: int) -> EpisodeReport:
    """可转集映射为单段，工具时间是相对帧索引的秒数，不套用 MCAP stamp 对齐。"""
    issues = tuple(
        quality_issue(
            issue.check,
            CHECK_MESSAGES[issue.check],
            IssueDetails(
                count=issue.count,
                first_time_s=issue.first_time_s,
                feature=issue.feature,
                ranges=tuple(TimeRange(start_s=start, end_s=end) for start, end in issue.ranges),
            ),
            Path(episode.observation_dir),
            0,
        )
        for issue in episode.issues
    )
    return EpisodeReport(
        file_index=index,
        segment_index=0,
        start_frame=0,
        end_frame=episode.frames,
        frame_count=episode.frames,
        duration_s=episode.frames / fps,
        stamp_span_s=episode.frames / fps,
        start_time_s=0,
        issues=issues,
        default_action="exclude" if any(issue.severity == "severe" for issue in issues) else "keep",
    )


def invalid_result(path: Path, actual: str) -> Diagnostic:
    """外部工具结果不合格时不保存任何部分报告。"""
    return Diagnostic(
        level=DiagnosticLevel.ERROR,
        category=DiagnosticCategory.EXTERNAL,
        stage="生成报告",
        source="平台",
        objects=(DiagnosticObject(key="path", value=str(path)),),
        rule="cleaning.tool_preview_invalid",
        actual=actual,
        expected="版本一预览结果，配置指纹一致、检查已知且集目录位于所选数据块内",
        consequence="清洗预览失败，未保存报告",
        next_step="核对工具版本和登记配置后重新预览",
    )
