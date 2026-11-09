"""对保留段做数值与抽样图像检查，不改变工具的对齐计划。

阈值来自规则文件，数值展平及匹配只复用扫描结果。缺失 optional 的 fill 参与非有限值和
限位检查，但不参与静止/跳变。所有时间取原始基准 stamp，区间明细只保留前十条。
"""

import math
from array import array
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass

from rdp.infra.diagnostics import DIAGNOSTIC_SAMPLE_LIMIT, Diagnostic, DiagnosticObject
from rdp.jobs.cleaning._config import (
    CleaningRules,
    Source,
    SourceRule,
    ToolConfig,
    VectorFeature,
)
from rdp.jobs.cleaning._io import diagnostic
from rdp.jobs.cleaning._scan import Scan, TopicData, Values
from rdp.jobs.cleaning._sync import CHECKPOINT_FRAMES, TopicMatch
from rdp.jobs.cleaning.models import EpisodeIssue, IssueDetails, TimeRange


@dataclass(frozen=True)
class SegmentContext:
    """段内检查共用的显式上下文。

    Attributes:
        scan: 当前文件的扫描缓存。
        reference: 排序后的基准时间，纳秒。
        segment: 基准帧下标范围，左闭右开。
        matches: 各非缺失话题的匹配，不含缺失 optional。
        checkpoint: 调用方取消函数，异常原样传播。
    """

    scan: Scan
    reference: array[int]
    segment: range
    matches: dict[str, TopicMatch]
    checkpoint: Callable[[], None]

    def seconds(self, frame: int) -> float:
        """从段首有效基准 stamp 起算秒数。"""
        return (self.reference[frame] - self.reference[self.segment.start]) / 1e9


@dataclass(frozen=True)
class SourceView:
    """来源的匹配视图，不构造全段的 Python 数值矩阵。

    Attributes:
        source: 工具配置来源。
        topic: 对应话题缓存。
        match: 有效消息匹配；None 表示使用 fill。
        rule: 该话题阈值；None 表示未设阈值。
    """

    source: Source
    topic: TopicData
    match: TopicMatch | None
    rule: SourceRule | None

    def at(self, frame: int) -> Sequence[float]:
        """按排序匹配下标回到物理消息位置，取数值或配置的 fill。"""
        if self.match is None:
            return self.source.fill or ()
        series: Values = self.topic.values[self.source.field]
        row = self.topic.order[self.match.matched[frame]]
        start = row * series.dimension
        return series.data[start : start + series.dimension]


def check_segment(
    context: SegmentContext, config: ToolConfig, rules: CleaningRules
) -> tuple[EpisodeIssue, ...]:
    """每个 vector feature 检查非有限值和限位，仅指定 feature 检查静止/跳变。"""
    issues: list[EpisodeIssue] = []
    for feature in config.features:
        context.checkpoint()
        if not isinstance(feature, VectorFeature):
            continue
        views = _views(feature, context, rules)
        issues.extend(_vector_events(feature.name, views, context, rules))
        if feature.name == rules.static.feature:
            issues.extend(_static(views, context, rules))
    for topic, data in context.scan.topics.items():
        if data.digests and not data.h264 and topic in context.matches:
            issues.extend(_images(topic, context, rules))
    return tuple(issues)


def _views(
    feature: VectorFeature, context: SegmentContext, rules: CleaningRules
) -> list[SourceView]:
    """按来源顺序构造只读数值视图，保留每个来源自己的 fill。"""
    by_topic = {rule.topic: rule for rule in rules.source}
    return [
        SourceView(
            source,
            context.scan.topics[source.topic],
            context.matches.get(source.topic),
            by_topic.get(source.topic),
        )
        for source in feature.sources
    ]


def _frames(context: SegmentContext) -> Iterator[int]:
    """计算期间按批次响应取消，不让长段检查阻塞作业取消。"""
    for frame in context.segment:
        if (frame - context.segment.start) % CHECKPOINT_FRAMES == 0:
            context.checkpoint()
        yield frame


def _vector_events(
    feature: str, views: list[SourceView], context: SegmentContext, rules: CleaningRules
) -> list[EpisodeIssue]:
    """按帧聚合非有限值、跳变与限位；同帧多维命中只计一次。"""
    counts = {"non_finite": 0, "action_jump": 0, "joint_limit": 0}
    first: dict[str, float] = {}
    previous: list[Sequence[float]] | None = None
    for frame in _frames(context):
        values = [view.at(frame) for view in views]
        flags = {
            "non_finite": any(not math.isfinite(v) for row in values for v in row),
            "joint_limit": any(
                _outside_limits(view, row) for view, row in zip(views, values, strict=True)
            ),
            "action_jump": feature == rules.jump.feature
            and previous is not None
            and _jumped(views, previous, values),
        }
        for check, found in flags.items():
            if found:
                counts[check] += 1
                first.setdefault(check, context.seconds(frame))
        previous = values
    descriptions = {
        "non_finite": "向量特征存在 NaN 或无穷值",
        "action_jump": "动作相邻帧变化超过来源阈值",
        "joint_limit": "关节数值超出配置限位",
    }
    return [
        _issue(
            check,
            descriptions[check],
            IssueDetails(count=count, first_time_s=first[check], feature=feature),
            context,
        )
        for check, count in counts.items()
        if count
    ]


def _outside_limits(view: SourceView, values: Sequence[float]) -> bool:
    """仅有 limits 时检查，NaN 交给非有限值规则，不把它重复计为超限。"""
    if view.rule is None or view.rule.limits is None:
        return False
    return any(
        value < low or value > high
        for value, (low, high) in zip(values, view.rule.limits, strict=True)
    )


def _jumped(
    views: list[SourceView], previous: list[Sequence[float]], current: list[Sequence[float]]
) -> bool:
    """仅实测来源且配置了跳变阈值的维度参与，恰好等于阈值不提示。"""
    for view, before, after in zip(views, previous, current, strict=True):
        if view.match is None or view.rule is None or view.rule.jump_threshold is None:
            continue
        if any(abs(a - b) > view.rule.jump_threshold for a, b in zip(after, before, strict=True)):
            return True
    return False


def _static(
    views: list[SourceView], context: SegmentContext, rules: CleaningRules
) -> list[EpisodeIssue]:
    """整段极差和逐帧静止分开判定；没有可检查的维度时不作真空肯定。"""
    selected = [
        v
        for v in views
        if v.match is not None and v.rule is not None and v.rule.static_threshold is not None
    ]
    thresholds = [
        v.rule.static_threshold
        for v in selected
        if v.rule is not None and v.rule.static_threshold is not None
        for _ in v.at(context.segment.start)
    ]
    if not thresholds:
        return []
    low = [math.inf] * len(thresholds)
    high = [-math.inf] * len(thresholds)
    all_finite = True
    previous: list[float] | None = None
    runs: list[TimeRange] = []
    run_start = context.segment.start
    count = 0
    for frame in _frames(context):
        values = [x for v in selected for x in v.at(frame)]
        all_finite = all_finite and all(math.isfinite(x) for x in values)
        low = [min(a, b) for a, b in zip(low, values, strict=True)]
        high = [max(a, b) for a, b in zip(high, values, strict=True)]
        if previous is not None and not all(
            abs(a - b) < threshold
            for a, b, threshold in zip(values, previous, thresholds, strict=True)
        ):
            count += _record_run(context, (run_start, frame - 1), rules.static.long_static_s, runs)
            run_start = frame
        previous = values
    count += _record_run(
        context, (run_start, context.segment.stop - 1), rules.static.long_static_s, runs
    )
    issues: list[EpisodeIssue] = []
    if all_finite and all(b - a < t for a, b, t in zip(low, high, thresholds, strict=True)):
        issues.append(
            _issue(
                "entire_static",
                "整段所有受检状态维度的极差均小于静止阈值",
                IssueDetails(
                    count=len(context.segment), first_time_s=0, feature=rules.static.feature
                ),
                context,
            )
        )
    if count:
        issues.append(
            _issue(
                "long_static",
                "状态连续静止达到配置时长",
                IssueDetails(
                    count=count,
                    first_time_s=runs[0].start_s,
                    ranges=tuple(runs),
                    feature=rules.static.feature,
                ),
                context,
            )
        )
    return issues


def _record_run(
    context: SegmentContext, endpoints: tuple[int, int], minimum_s: float, samples: list[TimeRange]
) -> int:
    """始末采样之间的实际时间达到阈值才计区间；完整计数与样例上限分开。"""
    start, end = endpoints
    if (context.reference[end] - context.reference[start]) / 1e9 < minimum_s:
        return 0
    if len(samples) < DIAGNOSTIC_SAMPLE_LIMIT:
        samples.append(TimeRange(start_s=context.seconds(start), end_s=context.seconds(end)))
    return 1


def _images(topic: str, context: SegmentContext, rules: CleaningRules) -> list[EpisodeIssue]:
    """冻结按匹配帧的摘要判断，亮度按段内原始抽样判断，不重复计复用帧。"""
    data = context.scan.topics[topic]
    match = context.matches[topic]
    previous: bytes | None = None
    start = context.segment.start
    runs: list[TimeRange] = []
    count = 0
    for frame in _frames(context):
        row = data.order[match.matched[frame]]
        digest = bytes(data.digests[row * 16 : (row + 1) * 16])
        if previous is not None and digest != previous:
            count += _record_run(context, (start, frame - 1), rules.image.frozen_s, runs)
            start = frame
        previous = digest
    count += _record_run(context, (start, context.segment.stop - 1), rules.image.frozen_s, runs)
    issues = _brightness_issues(topic, context, rules)
    if count:
        issues.insert(
            0,
            _issue(
                "camera_frozen",
                "相机连续匹配到完全相同的图片内容",
                IssueDetails(
                    count=count, first_time_s=runs[0].start_s, ranges=tuple(runs), topic=topic
                ),
                context,
            ),
        )
    return issues


def _brightness_issues(
    topic: str, context: SegmentContext, rules: CleaningRules
) -> list[EpisodeIssue]:
    """只统计段起止 stamp 内的抽样消息，每个消息只算一次。"""
    data = context.scan.topics[topic]
    begin, end = (
        context.reference[context.segment.start],
        context.reference[context.segment.stop - 1],
    )
    counts = {"dark_image": 0, "bright_image": 0}
    first: dict[str, float] = {}
    for position, stamp in enumerate(data.stamps):
        if position % CHECKPOINT_FRAMES == 0:
            context.checkpoint()
        if not begin <= stamp <= end:
            continue
        value = data.brightness[data.order[position]]
        for check, found in (
            ("dark_image", value < rules.image.dark_below),
            ("bright_image", value > rules.image.bright_above),
        ):
            if found:
                counts[check] += 1
                first.setdefault(check, (stamp - begin) / 1e9)
    return [
        _issue(
            check,
            "图像抽样亮度低于黑屏阈值" if check == "dark_image" else "图像抽样亮度高于过曝阈值",
            IssueDetails(count=count, first_time_s=first[check], topic=topic),
            context,
        )
        for check, count in counts.items()
        if count
    ]


def _issue(
    check: str, message: str, details: IssueDetails, context: SegmentContext
) -> EpisodeIssue:
    """质量问题仍使用平台 Diagnostic；严重只剔除当前段，不误报整文件失败。"""
    severe = check in ("non_finite", "entire_static")
    base = diagnostic(
        f"cleaning.{check}",
        f"{message}，共 {details.count} 次",
        path=context.scan.path,
        topic=details.topic,
        fatal=severe,
    )
    extra = (DiagnosticObject(key="start_frame", value=str(context.segment.start)),)
    if details.feature is not None:
        extra += (DiagnosticObject(key="feature", value=details.feature),)
    detail = Diagnostic(
        level=base.level,
        category=base.category,
        stage=base.stage,
        source=base.source,
        objects=base.objects + extra,
        rule=base.rule,
        actual=base.actual,
        expected=base.expected,
        consequence="该 episode 默认剔除" if severe else "该 episode 默认保留，提示人工核对",
        next_step=base.next_step,
    )
    return EpisodeIssue(
        check=check,
        severity="severe" if severe else "hint",
        message=message,
        details=details,
        diagnostic=detail,
    )
