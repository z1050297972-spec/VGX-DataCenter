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


class CleaningSyncRules(_FrozenModel):
    """报告生成时生效的对齐规则；毫秒值仅用于展示，不改变纳秒对齐计算。

    Attributes:
        default_tolerance_ms: 工具配置的默认话题容差，单位毫秒。
        max_frame_gap: 最大相邻基准帧间隔，相对于标准帧间隔的倍数。
        max_frame_gap_ms: max_frame_gap 按报告顶层 fps 换算的毫秒值。
        min_episode_frames: 最短保留段的基准帧数，非负整数。
    """

    default_tolerance_ms: float
    max_frame_gap: float
    max_frame_gap_ms: float
    min_episode_frames: int


class CleaningSourceRules(_FrozenModel):
    """单个来源话题的规则快照；未配置的阈值和限位显式保存为 null。

    Attributes:
        topic: 清洗规则中的来源话题名。
        static_threshold: 静止阈值，单位与来源数值一致；None 表示不检查。
        jump_threshold: 跳变阈值，单位与来源数值一致；None 表示不检查。
        limits: 按维度排列的下限、上限对，单位与来源数值一致；None 表示未配置。
    """

    topic: str
    static_threshold: float | None
    jump_threshold: float | None
    limits: tuple[tuple[float, float], ...] | None


class CleaningCheckRules(_FrozenModel):
    """报告生成时生效的质量检查规则，不依赖前端维护默认数值。

    Attributes:
        static_feature: 静止检查使用的向量特征名。
        long_static_s: 连续静止最短时长，单位秒。
        jump_feature: 跳变检查使用的向量特征名。
        frozen_s: 相机冻结最短时长，单位秒。
        sample_interval_s: 亮度抽样间隔，单位秒。
        dark_below: 黑屏亮度阈值，0 至 255，严格小于时命中。
        bright_above: 过曝亮度阈值，0 至 255，严格大于时命中。
        sources: 按清洗规则原顺序的来源阈值，可为空。
        severe_checks: 默认剔除 episode 的严重检查规则码，顺序由检查模块定义。
    """

    static_feature: str
    long_static_s: float
    jump_feature: str
    frozen_s: float
    sample_interval_s: float
    dark_below: float
    bright_above: float
    sources: tuple[CleaningSourceRules, ...]
    severe_checks: tuple[str, ...]


class CleaningRuleSnapshot(_FrozenModel):
    """完整规则说明快照；fps 和 reference_topic 只保留在报告顶层。"""

    sync: CleaningSyncRules
    checks: CleaningCheckRules


class CleaningReport(_FrozenModel):
    """版本一报告；Pydantic 的 JSON 方法用于存库，规则指纹取文件原始字节。"""

    schema_version: Literal[1] = 1
    tool_config_sha256: str
    rules_sha256: str
    fps: int
    reference_topic: str
    rules: CleaningRuleSnapshot
    files: tuple[FileReport, ...]
    episodes: tuple[EpisodeReport, ...]
    summary: CleaningSummary
    # 目录软链接等展开警告不属于某个文件，不能在展开后悄悄丢失。
    warnings: tuple[Diagnostic, ...] = ()
