"""G2 v2.1 归档报告适配（领域层，08 票）；严格消费真实 CLI，不读归档内容。

复用 Pydantic、现有规则快照与诊断映射；G2 的归档/源集身份在此单独校验，
不把 Alpha 的目录快照或 MCAP 的时间对齐规则套到归档上。
"""

import re
import stat
import tomllib
from collections.abc import Callable
from pathlib import Path
from typing import Literal

from pydantic import Field

from rdp.infra.diagnostics import ExternalError, InputError
from rdp.jobs.cleaning._agibot import (
    NonnegativeInt,
    ResultModel,
    Seconds,
    invalid_result,
    read_result_bytes,
)
from rdp.jobs.cleaning._checks import CHECK_MESSAGES, quality_issue
from rdp.jobs.cleaning._io import diagnostic, read_config_bytes
from rdp.jobs.cleaning.models import (
    CleaningReport,
    CleaningRuleSnapshot,
    CleaningSummary,
    EpisodeIssue,
    EpisodeReport,
    FileReport,
    IssueDetails,
    TimeRange,
)


class _Issue(ResultModel):
    """工具只执行这五种数值检查，不接受图像检查或未知特征。"""

    check: Literal["non_finite", "joint_limit", "action_jump", "entire_static", "long_static"]
    feature: Literal["observation.state", "action"]
    count: int = Field(gt=0)
    first_time_s: Seconds
    ranges: tuple[tuple[Seconds, Seconds], ...] = Field(max_length=10)


class _Episode(ResultModel):
    """源集号可不连续；task 缺失时只允许伴随质量问题。"""

    episode_index: NonnegativeInt
    frames: NonnegativeInt
    task: str | tuple[str, ...] | None
    problems: tuple[str, ...]
    issues: tuple[_Issue, ...]


class _Archive(ResultModel):
    """不能 stat 的坏归档允许空元信息，但必须记录归档问题。"""

    path: str
    size_bytes: NonnegativeInt | None
    mtime_ns: NonnegativeInt | None
    problems: tuple[str, ...]
    episodes: tuple[_Episode, ...]
    passes: int = Field(ge=1, le=2)


class _Result(ResultModel):
    """真实 G2 schema_version=1 的全部字段，不容忍多余或伪造字段。"""

    schema_version: int = Field(ge=1, le=1)
    tool_version: str
    fps: int = Field(gt=0)
    robot_type: str
    config_sha256: str
    feature_names: dict[str, tuple[str, ...]]
    archives: tuple[_Archive, ...]


def validate_paths(paths: tuple[Path, ...], *, filesystem: bool = False) -> None:
    """提交时只验证索引路径；worker 在线检查后再拒绝链接、设备及硬链接重复。"""
    try:
        if not paths or len(set(paths)) != len(paths) or len({p.parent for p in paths}) != 1:
            raise ValueError("必须选择同一 task_<数字> 目录下不重复的归档")
        identities: set[tuple[int, int]] = set()
        for path in paths:
            if (
                not path.is_absolute()
                or ".." in path.parts
                or not path.name.endswith(".tar.gz")
                or re.fullmatch(r"task_[0-9]+", path.parent.name) is None
            ):
                raise ValueError("direct_path 必须是 task_<数字> 下的 .tar.gz 文件")
            if filesystem:
                # 检查祖先后才 stat 叶子，避免中间链接跳出已登记存储根。
                for parent in reversed((path, *path.parents)):
                    if parent.is_symlink():
                        raise ValueError("G2 输入路径不能包含符号链接")
                info = path.stat(follow_symlinks=False)
                identity = (info.st_dev, info.st_ino)
                if not stat.S_ISREG(info.st_mode) or identity in identities:
                    raise ValueError("G2 输入必须为不同的普通归档文件")
                identities.add(identity)
    except (OSError, ValueError) as error:
        raise InputError(
            (diagnostic("cleaning.g2_inputs", str(error), path=paths[0] if paths else Path("/")),)
        ) from error


def read_report(
    result_path: Path,
    sources: tuple[tuple[str, Path], ...],
    snapshot: tuple[str, str, CleaningRuleSnapshot],
    configuration: tuple[Path, str],
    checkpoint: Callable[[], None],
) -> CleaningReport:
    """读取有界结果并核对路径顺序、配置、非负统计和每个归档内的唯一源集号。"""
    try:
        parsed = _Result.model_validate_json(read_result_bytes(result_path))
        settings = tomllib.loads(read_config_bytes(configuration[0]).decode("utf-8"))
        if (
            parsed.config_sha256 != snapshot[0]
            or parsed.fps != settings.get("fps")
            or parsed.robot_type != settings.get("robot_type")
            or parsed.tool_version != configuration[1]
        ):
            raise ValueError("G2 报告的工具版本或配置身份不符")
        if tuple(item.path for item in parsed.archives) != tuple(str(path) for _, path in sources):
            raise ValueError("G2 报告归档路径或顺序与所选输入不符")
        names = parsed.feature_names
        if names and (set(names) != {"action", "observation.state"} or not all(names.values())):
            raise ValueError("G2 feature_names 缺失或含未知特征")
        files: list[FileReport] = []
        episodes: list[EpisodeReport] = []
        for index, (archive, (source_id, path)) in enumerate(
            zip(parsed.archives, sources, strict=True)
        ):
            checkpoint()
            if not archive.problems and (
                not names or archive.size_bytes is None or archive.mtime_ns is None
            ):
                raise ValueError("无归档问题时必须有输入元信息和特征名")
            seen: set[int] = set()
            for episode in sorted(archive.episodes, key=lambda item: item.episode_index):
                checkpoint()
                if episode.episode_index in seen or (
                    episode.task is None and not (archive.problems or episode.problems)
                ):
                    raise ValueError("G2 源集号重复或无问题的集缺 task")
                seen.add(episode.episode_index)
                episodes.append(_episode(episode, index, path, parsed.fps))
            frames = sum(episode.frames for episode in archive.episodes)
            files.append(
                FileReport(
                    file_index=index,
                    source_id=source_id,
                    path=str(path),
                    size_bytes=archive.size_bytes,
                    mtime_ns=archive.mtime_ns,
                    fatal_issues=tuple(
                        diagnostic("cleaning.g2_archive_unusable", p, path=path)
                        for p in archive.problems
                    ),
                    warnings=(),
                    reference_frames=frames,
                    kept_frames=frames,
                    bad_frames=0,
                    gaps=0,
                    short_segments=0,
                    short_frames=0,
                    topics=(),
                    default_excluded=bool(archive.problems),
                )
            )
        return CleaningReport(
            source_format="agibot_lerobot21",
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
                excluded_episodes=sum(e.default_action == "exclude" for e in episodes),
                reference_frames=sum(f.reference_frames for f in files),
                kept_frames=sum(
                    e.frame_count
                    for e in episodes
                    if not files[e.file_index].fatal_issues and not e.fatal_issues
                ),
            ),
        )
    except (OSError, ValueError) as error:
        raise ExternalError((invalid_result(result_path, str(error)),)) from error


def _episode(episode: _Episode, index: int, path: Path, fps: int) -> EpisodeReport:
    """原始采集跨度未知；只展示帧数/FPS，不伪造 stamp。致命问题与可调整数值问题分开。"""
    issues: list[EpisodeIssue] = []
    for issue in episode.issues:
        if any(start > end for start, end in issue.ranges):
            raise ValueError("G2 数值问题区间逆序")
        issues.append(
            quality_issue(
                issue.check,
                CHECK_MESSAGES[issue.check],
                IssueDetails(
                    count=issue.count,
                    first_time_s=issue.first_time_s,
                    feature=issue.feature,
                    ranges=tuple(
                        TimeRange(start_s=start, end_s=end) for start, end in issue.ranges
                    ),
                ),
                path,
                episode.episode_index,
            )
        )
    problems = episode.problems or (("集没有可转换帧",) if episode.frames == 0 else ())
    return EpisodeReport(
        file_index=index,
        segment_index=episode.episode_index,
        start_frame=0,
        end_frame=episode.frames,
        frame_count=episode.frames,
        duration_s=episode.frames / fps,
        stamp_span_s=None,
        start_time_s=None,
        issues=tuple(issues),
        fatal_issues=tuple(
            diagnostic("cleaning.g2_episode_unusable", p, path=path) for p in problems
        ),
        default_action="exclude"
        if problems or any(i.severity == "severe" for i in issues)
        else "keep",
    )
