"""把扫描、对齐计划和检查结果组合为冻结报告，逐文件释放消息缓存。"""

import time
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path

from rdp.infra.diagnostics import Diagnostic, InputError
from rdp.jobs.cleaning._checks import SEVERE_CHECKS, SegmentContext, check_segment
from rdp.jobs.cleaning._config import CleaningRules, ToolConfig
from rdp.jobs.cleaning._io import diagnostic
from rdp.jobs.cleaning._scan import MAX_CACHE_BYTES, Scan, Scanner
from rdp.jobs.cleaning._sync import SyncPlan, TopicInput, TopicMatch, plan
from rdp.jobs.cleaning.models import (
    CleaningCheckRules,
    CleaningReport,
    CleaningRuleSnapshot,
    CleaningSourceRules,
    CleaningSummary,
    CleaningSyncRules,
    EpisodeReport,
    FileReport,
    TopicAlignment,
)

# 报告必须整体序列化存库；限制条目数避免小段极多时报告本身无限增长。
MAX_REPORT_EPISODES = 10_000
# 规范 6.7：进度通知最多每秒一次，用 monotonic 计算间隔。
PROGRESS_INTERVAL_S = 1.0


class ReportBuilder:
    """一次调用的状态，不共享全局缓存或取消标志。"""

    def __init__(
        self,
        config: ToolConfig,
        rules: CleaningRules,
        checkpoint: Callable[[], None],
        progress: Callable[[int], None],
        file_progress: Callable[[int, int, int | None], None] | None = None,
    ) -> None:
        """保存调用方回调，文件编号由展开顺序唯一确定。"""
        self.config = config
        self.rules = rules
        self.checkpoint = checkpoint
        self.progress = progress
        self.file_progress = file_progress
        self.dimensions: dict[tuple[str, str], int] = {}
        self.completed_bytes = 0
        self.file_read_bytes = 0
        self.last_progress_s = -float("inf")

    def build(
        self, files: list[tuple[str, Path]], warnings: list[Diagnostic], hashes: tuple[str, str]
    ) -> CleaningReport:
        """每文件独立预览；坏文件不终止后续文件，报告仅保存统计和段级问题。"""
        reports: list[FileReport] = []
        episodes: list[EpisodeReport] = []
        total_bytes = None
        if self.file_progress is not None:
            # 文件读取失败仍交扫描生成文件级诊断，不能因进度统计提前终止整份报告。
            with suppress(OSError):
                total_bytes = sum(path.stat().st_size for _, path in files)
        for index, (source_id, path) in enumerate(files):
            self.checkpoint()
            if self.file_progress is not None:
                self.file_progress(index + 1, len(files), total_bytes)
            self.file_read_bytes = 0
            # 致命文件不锁定后续文件的维度，用户排除该文件后转换也不会读取它。
            dimensions = dict(self.dimensions)
            scan = Scanner(self.config, self.rules, dimensions).scan(
                path, self.checkpoint, self._progress
            )
            self.completed_bytes += self.file_read_bytes
            aligned, matches = self._align(scan)
            current = self._episodes(index, scan, aligned, matches)
            if not scan.fatal and current:
                self.dimensions = dimensions
            reports.append(self._file_report((index, source_id), scan, aligned, matches))
            episodes.extend(current)
            # 下个文件开始解码前释放上一个文件的数组及匹配工作区，峰值不叠加。
            del scan, aligned, matches
            if len(episodes) > MAX_REPORT_EPISODES:
                raise InputError(
                    (diagnostic("cleaning.report_limit", "报告超过 10000 个 episode", path=path),)
                )
        summary = CleaningSummary(
            files=len(reports),
            excluded_files=sum(f.default_excluded for f in reports),
            episodes=len(episodes),
            excluded_episodes=sum(e.default_action == "exclude" for e in episodes),
            reference_frames=sum(f.reference_frames for f in reports),
            kept_frames=sum(f.kept_frames for f in reports),
        )
        return CleaningReport(
            tool_config_sha256=hashes[0],
            rules_sha256=hashes[1],
            fps=self.config.fps,
            reference_topic=self.config.sync.reference_topic,
            rules=self._rules_snapshot(),
            files=tuple(reports),
            episodes=tuple(episodes),
            summary=summary,
            warnings=tuple(warnings),
        )

    def _rules_snapshot(self) -> CleaningRuleSnapshot:
        """只投影本次已解析配置，确保报告说明与实际检查使用同一份值。"""
        sync = self.config.sync
        rules = self.rules
        return CleaningRuleSnapshot(
            sync=CleaningSyncRules(
                default_tolerance_ms=sync.max_dt_ms,
                max_frame_gap=sync.max_frame_gap,
                # fps 是帧/秒；乘 1000 把帧间隔从秒换算成供规则说明使用的毫秒。
                max_frame_gap_ms=sync.max_frame_gap * 1000 / self.config.fps,
                min_episode_frames=sync.min_episode_frames,
            ),
            checks=CleaningCheckRules(
                static_feature=rules.static.feature,
                long_static_s=rules.static.long_static_s,
                jump_feature=rules.jump.feature,
                frozen_s=rules.image.frozen_s,
                sample_interval_s=rules.image.sample_interval_s,
                dark_below=rules.image.dark_below,
                bright_above=rules.image.bright_above,
                sources=tuple(
                    CleaningSourceRules(
                        topic=source.topic,
                        static_threshold=source.static_threshold,
                        jump_threshold=source.jump_threshold,
                        limits=source.limits,
                    )
                    for source in rules.source
                ),
                severe_checks=SEVERE_CHECKS,
            ),
        )

    def _progress(self, file_bytes: int) -> None:
        """累计已读取字节；回调发生在数据异常转换范围之外。"""
        self.file_read_bytes = file_bytes
        now = time.monotonic()
        if now - self.last_progress_s >= PROGRESS_INTERVAL_S:
            self.progress(self.completed_bytes + file_bytes)
            self.last_progress_s = now

    def _align(self, scan: Scan) -> tuple[SyncPlan | None, dict[str, TopicMatch]]:
        """对应 plan_for_config：排除缺失 optional，先校验基准再计算纳秒容差。"""
        if scan.fatal:
            return None, {}
        reference = scan.topics[self.config.sync.reference_topic].stamps
        if len(reference) < 2:
            scan.fatal.append(
                diagnostic("cleaning.reference", "基准有效 stamp 不足 2 个", path=scan.path)
            )
            return None, {}
        topics = [
            (topic, tol)
            for topic, tol in self.config.topic_tolerances()
            if scan.topics[topic].stamps or not self.config.is_optional_topic(topic)
        ]
        if scan.cache_bytes + len(reference) * len(topics) * 16 > MAX_CACHE_BYTES:
            scan.fatal.append(
                diagnostic(
                    "cleaning.alignment_limit",
                    "匹配数组和缓存超过 1 GiB 安全上限",
                    path=scan.path,
                )
            )
            return None, {}
        inputs = [TopicInput(scan.topics[topic].stamps, int(tol * 1e6)) for topic, tol in topics]
        # frame_ns 先除再乘，保持 Rust f64 运算顺序与截断位置。
        options = (
            int(self.config.sync.max_frame_gap * (1e9 / self.config.fps)),
            self.config.sync.min_episode_frames,
        )
        aligned = plan(reference, inputs, options, self.checkpoint)
        matches = {topic: match for (topic, _), match in zip(topics, aligned.topics, strict=True)}
        return aligned, matches

    def _episodes(
        self, file_index: int, scan: Scan, aligned: SyncPlan | None, matches: dict[str, TopicMatch]
    ) -> list[EpisodeReport]:
        """只对保留段检查，身份用文件内的保留段序号，不存全局编号。"""
        if aligned is None:
            return []
        reference = scan.topics[self.config.sync.reference_topic].stamps
        result: list[EpisodeReport] = []
        for segment_index, segment in enumerate(aligned.segments):
            self.checkpoint()
            context = SegmentContext(scan, reference, segment, matches, self.checkpoint)
            issues = check_segment(context, self.config, self.rules)
            result.append(
                EpisodeReport(
                    file_index=file_index,
                    segment_index=segment_index,
                    start_frame=segment.start,
                    end_frame=segment.stop,
                    frame_count=len(segment),
                    duration_s=len(segment) / self.config.fps,
                    stamp_span_s=(reference[segment.stop - 1] - reference[segment.start]) / 1e9,
                    start_time_s=(reference[segment.start] - reference[0]) / 1e9,
                    issues=issues,
                    default_action="exclude"
                    if any(i.severity == "severe" for i in issues)
                    else "keep",
                )
            )
            if len(result) > MAX_REPORT_EPISODES:
                raise InputError(
                    (
                        diagnostic(
                            "cleaning.report_limit", "报告超过 10000 个 episode", path=scan.path
                        ),
                    )
                )
        return result

    def _file_report(
        self,
        identity: tuple[int, str],
        scan: Scan,
        aligned: SyncPlan | None,
        matches: dict[str, TopicMatch],
    ) -> FileReport:
        """统计口径集中在一处，保留帧数不扣除默认剔除的质量问题段。"""
        reference = scan.topics[self.config.sync.reference_topic].stamps
        return FileReport(
            file_index=identity[0],
            source_id=identity[1],
            path=str(scan.path),
            size_bytes=scan.size_bytes,
            mtime_ns=scan.mtime_ns,
            fatal_issues=tuple(scan.fatal),
            warnings=tuple(scan.warnings),
            reference_frames=len(reference),
            kept_frames=sum(len(s) for s in aligned.segments) if aligned else 0,
            bad_frames=sum(aligned.bad) if aligned else 0,
            gaps=aligned.gaps if aligned else 0,
            short_segments=len(aligned.short_segments) if aligned else 0,
            short_frames=sum(len(s) for s in aligned.short_segments) if aligned else 0,
            topics=tuple(
                self._topic_report(topic, tol, scan, matches.get(topic))
                for topic, tol in self.config.topic_tolerances()
            ),
            default_excluded=bool(scan.fatal) or aligned is None or not aligned.segments,
        )

    def _topic_report(
        self, topic: str, tolerance_ms: float, scan: Scan, match: TopicMatch | None
    ) -> TopicAlignment:
        """复用次数统计相邻两基准帧，不因坏帧和短段过滤改变 verify 口径。"""
        data = scan.topics[topic]
        deltas = match.abs_dt if match else ()
        picked = match.matched if match else ()
        return TopicAlignment(
            topic=topic,
            tolerance_ms=tolerance_ms,
            mean_abs_dt_ms=sum(deltas) / len(deltas) / 1e6 if deltas else None,
            max_abs_dt_ms=max(deltas) / 1e6 if deltas else None,
            reused_frames=sum(picked[i] == picked[i - 1] for i in range(1, len(picked))),
            bad_frames=match.bad_frames if match else 0,
            missing_optional=not data.stamps and self.config.is_optional_topic(topic),
            image_check="unchecked_h264"
            if data.h264
            else "sampled"
            if data.digests
            else "not_applicable",
            image_check_note="H.264 画面未检查" if data.h264 else None,
        )
