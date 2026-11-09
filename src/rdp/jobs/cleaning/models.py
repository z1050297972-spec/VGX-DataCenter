"""清洗预览的持久化报告；只描述事实和默认处理，不执行转换或写数据库。"""

from typing import Literal

from pydantic import BaseModel, ConfigDict

from rdp.infra.diagnostics import Diagnostic


class _FrozenModel(BaseModel):
    """报告各层共用冻结及未知字段拒绝规则，集合用元组保持深层不可变。"""

    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)


class TimeRange(_FrozenModel):
    """相对 episode 第一条基准 stamp 的区间，单位秒，两个端点均包含。"""

    start_s: float
    end_s: float


class IssueDetails(_FrozenModel):
    """检查明细；count 为完整次数，ranges 为前十个区间，时间均相对段首。"""

    count: int
    first_time_s: float | None = None
    ranges: tuple[TimeRange, ...] = ()
    feature: str | None = None
    topic: str | None = None


class EpisodeIssue(_FrozenModel):
    """数值或画面检查；严重问题默认剔除 episode，提示只供人工判断。"""

    check: str
    severity: Literal["severe", "hint"]
    message: str
    details: IssueDetails
    diagnostic: Diagnostic


class TopicAlignment(_FrozenModel):
    """全文件基准帧上的对齐统计；空话题的时间差为 None，不伪造为零。"""

    topic: str
    tolerance_ms: float
    mean_abs_dt_ms: float | None
    max_abs_dt_ms: float | None
    reused_frames: int
    bad_frames: int
    missing_optional: bool
    image_check: Literal["not_applicable", "sampled", "unchecked_h264"]
    image_check_note: str | None = None


class EpisodeReport(_FrozenModel):
    """保留段身份不随剔除文件改变；基准帧范围左闭右开，下标从零起。"""

    file_index: int
    segment_index: int
    start_frame: int
    end_frame: int
    frame_count: int
    # 转换后的恒定帧率时长，与原始 stamp 跨度分别记录，避免混淆。
    duration_s: float
    stamp_span_s: float
    start_time_s: float
    issues: tuple[EpisodeIssue, ...]
    default_action: Literal["keep", "exclude"]


class FileReport(_FrozenModel):
    """展开顺序中的一个文件；元数据无法读取时大小、mtime_ns 为 None。"""

    file_index: int
    source_id: str
    path: str
    size_bytes: int | None
    mtime_ns: int | None
    fatal_issues: tuple[Diagnostic, ...]
    warnings: tuple[Diagnostic, ...]
    reference_frames: int
    kept_frames: int
    bad_frames: int
    gaps: int
    short_segments: int
    short_frames: int
    topics: tuple[TopicAlignment, ...]
    default_excluded: bool


class CleaningSummary(_FrozenModel):
    """整份报告的计数；kept_frames 是时间对齐保留数，尚未扣除数值问题段。"""

    files: int
    excluded_files: int
    episodes: int
    excluded_episodes: int
    reference_frames: int
    kept_frames: int


class CleaningReport(_FrozenModel):
    """版本一报告；Pydantic 的 JSON 方法用于存库，规则指纹取文件原始字节。"""

    schema_version: Literal[1] = 1
    tool_config_sha256: str
    rules_sha256: str
    fps: int
    reference_topic: str
    files: tuple[FileReport, ...]
    episodes: tuple[EpisodeReport, ...]
    summary: CleaningSummary
    # 目录软链接等展开警告不属于某个文件，不能在展开后悄悄丢失。
    warnings: tuple[Diagnostic, ...] = ()
