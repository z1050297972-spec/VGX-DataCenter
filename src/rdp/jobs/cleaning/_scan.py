"""一遍读取 MCAP，保留紧凑时间戳、数值和摘要；文件原文不进入报告缓存。

数值解码复用 mcap-ros2-support，字段遍历遵循 Rust SourceState 的 schema 顺序。
维度表跨文件共享，和 Converter.sources 的生命周期一致；关键帧门每文件重新建立。
"""

import hashlib
import math
import os
import struct
from array import array
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import BinaryIO, cast

from mcap.exceptions import McapError
from mcap.records import Channel, McapRecord, Message, Schema
from mcap_ros2.decoder import DecoderFactory
from PIL import Image
from zstandard import ZstdError

from rdp.infra.diagnostics import Diagnostic, InputError
from rdp.jobs.cleaning._config import CleaningRules, Source, ToolConfig, VectorFeature, VideoFeature
from rdp.jobs.cleaning._h264 import KeyframeGate, has_b_slice
from rdp.jobs.cleaning._io import diagnostic, open_readonly
from rdp.jobs.cleaning._media import Cdr, brightness, has_header, image_payload
from rdp.jobs.cleaning._records import BoundedReader, records

# 本机内存 30 GB，紧凑缓存及匹配预算放宽到 1 GiB，另为排序工作区留余量。
# 按 R1 Lite 约 1400 条有效消息/秒折算，1000 万条约可覆盖 2 小时的单个录制文件。
MAX_CACHE_BYTES = 1024 * 1024 * 1024
MAX_MESSAGES = 10_000_000
# verify.rs 留 0.5% 频率余量，避免将 29.998 Hz 当成丢帧。
MIN_RATE_RATIO = 0.995


@dataclass
class Values:
    """一个 topic/field 的有效消息数值。

    Attributes:
        dimension: 每条消息维度，非负整数。
        data: 按有效消息物理顺序拼接的 float64 数组，单位来自来源配置。
    """

    dimension: int
    data: array[float] = field(default_factory=lambda: array("d"))


@dataclass
class TopicData:
    """单文件单话题的紧凑缓存及扫描计数。

    Attributes:
        stamps: 有效 header.stamp，纳秒；扫描后稳定排序。
        order: 排序后位置到物理有效消息序号的映射。
        values: 按 field 区分的数值缓存，空字典表示无向量引用。
        digests: 每有效图像 16 字节摘要，H.264 用零占位。
        brightness: 每有效图像的抽样亮度，未抽样用 NaN，不输出到报告。
        gate: 每文件重新等首个 IDR。
        message_count: 文件内消息总数，包含零 stamp。
        pre_keyframe: 首个 IDR 前排除数。
        h264: 是否遇到 H.264 消息。
        last_sample_ns: 上次抽样时间；None 表示尚未抽样。
    """

    stamps: array[int] = field(default_factory=lambda: array("q"))
    order: array[int] = field(default_factory=lambda: array("Q"))
    values: dict[str, Values] = field(default_factory=dict)
    digests: bytearray = field(default_factory=bytearray)
    brightness: array[float] = field(default_factory=lambda: array("d"))
    gate: KeyframeGate = field(default_factory=KeyframeGate)
    message_count: int = 0
    pre_keyframe: int = 0
    h264: bool = False
    last_sample_ns: int | None = None


@dataclass
class Scan:
    """单文件扫描结果；失败也保留已知元数据及诊断。

    Attributes:
        path: 输入绝对路径。
        topics: 按配置话题排列的缓存。
        size_bytes: 文件字节数；无法 stat 时为 None。
        mtime_ns: 文件修改时间，UNIX 纳秒；无法 stat 时为 None。
        fatal: 致命问题，按发现顺序。
        warnings: 非致命诊断，按发现顺序。
        cache_bytes: 已保存紧凑数据及 schema 大小，字节。
        messages: 已保存的有效消息数。
    """

    path: Path
    topics: dict[str, TopicData]
    size_bytes: int | None = None
    mtime_ns: int | None = None
    fatal: list[Diagnostic] = field(default_factory=list)
    warnings: list[Diagnostic] = field(default_factory=list)
    cache_bytes: int = 0
    messages: int = 0


class Scanner:
    """扫描上下文；回调只由读取循环调用，不落入数据异常捕获范围。"""

    def __init__(
        self, config: ToolConfig, rules: CleaningRules, dimensions: dict[tuple[str, str], int]
    ) -> None:
        """复用跨文件维度表，预先归并同一话题的来源引用。"""
        self.config = config
        self.rules = rules
        self.dimensions = dimensions
        self.source_rules = {rule.topic: rule for rule in rules.source}
        self.video_topics = {f.topic for f in config.features if isinstance(f, VideoFeature)}
        self.sources: dict[str, list[Source]] = {}
        for feature in config.features:
            if isinstance(feature, VectorFeature):
                for source in feature.sources:
                    self.sources.setdefault(source.topic, []).append(source)
        self.schemas: dict[int, Schema] = {}
        self.channels: dict[int, Channel] = {}
        self.decoders = DecoderFactory()
        self.header_cache: dict[int, bool] = {}

    def scan(
        self, path: Path, checkpoint: Callable[[], None], progress: Callable[[int], None]
    ) -> Scan:
        """只读打开一遍；数据错误转文件诊断，调用方取消和进度异常原样传播。"""
        result = Scan(path, {topic: TopicData() for topic in self.config.topics()})
        stream = _open_stream(result)
        if stream is None:
            return result
        with stream:
            iterator = records(cast(BinaryIO, stream))
            while True:
                checkpoint()
                record = _next_record(iterator, result)
                progress(stream.tell())
                if record is None:
                    break
                self._consume(record, result)
                if result.fatal:
                    break
        if not result.fatal:
            self._finish(result, checkpoint)
        return result

    def _consume(self, record: McapRecord, result: Scan) -> None:
        """只在 SDK/消息解码边界转译错误，不吞掉取消异常。"""
        topic: str | None = None
        try:
            if isinstance(record, Schema):
                if record.id not in self.schemas:
                    _reserve(result, len(record.data))
                self.schemas[record.id] = record
            elif isinstance(record, Channel):
                self.channels[record.id] = record
            elif isinstance(record, Message):
                channel = self.channels[record.channel_id]
                topic = channel.topic
                if topic in result.topics:
                    self._message(record, channel, result)
        except InputError as error:
            result.fatal.extend(error.diagnostics)
        except (
            ValueError,
            McapError,
            struct.error,
            KeyError,
            AttributeError,
            TypeError,
            OSError,
            IndexError,
            OverflowError,
            Image.DecompressionBombError,
        ) as error:
            result.fatal.append(
                diagnostic(
                    "cleaning.message",
                    str(error) or type(error).__name__,
                    path=result.path,
                    topic=topic,
                )
            )

    def _message(self, message: Message, channel: Channel, result: Scan) -> None:
        """先判断 Header 和视频门，再存有效 stamp 对应的数据。"""
        topic = channel.topic
        target = result.topics[topic]
        target.message_count += 1
        schema = self.schemas[channel.schema_id]
        if schema.id not in self.header_cache:
            self.header_cache[schema.id] = has_header(schema)
        if not self.header_cache[schema.id] or channel.message_encoding != "cdr":
            raise ValueError("消息没有 Header 或编码不是 cdr")
        reader = Cdr(message.data)
        stamp = reader.header()
        if topic in self.video_topics:
            stamp = self._image(schema.name, reader, (target, stamp), result)
        if topic in self.sources:
            self._vector(message, schema, (topic, stamp), result)
        if stamp != 0:
            _reserve(result, 16)
            result.messages += 1
            if result.messages > MAX_MESSAGES:
                raise InputError(
                    (
                        diagnostic(
                            "cleaning.message_limit",
                            "单文件有效消息超过 1000 万条安全上限",
                            path=result.path,
                            topic=topic,
                        ),
                    )
                )
            target.stamps.append(stamp)

    def _image(
        self, schema_name: str, reader: Cdr, item: tuple[TopicData, int], result: Scan
    ) -> int:
        """每条图片算摘要，仅到达抽样间隔时解码；视频只检查 IDR/B slice。"""
        target, stamp = item
        payload = image_payload(schema_name, reader)
        digest, light = bytes(16), math.nan
        if payload.kind == "h264":
            target.h264 = True
            if has_b_slice(payload.data):
                raise ValueError("H.264 码流含 B slice")
            if not target.gate.accept(payload.data):
                target.pre_keyframe += 1
                return 0
        else:
            digest = hashlib.blake2b(payload.data, digest_size=16).digest()
            due = target.last_sample_ns is None or (
                stamp - target.last_sample_ns >= self.rules.image.sample_interval_s * 1e9
            )
            if stamp != 0 and due:
                light = brightness(payload)
                target.last_sample_ns = stamp
        if stamp != 0:
            _reserve(result, 24)
            target.digests.extend(digest)
            target.brightness.append(light)
        return stamp

    def _vector(
        self, message: Message, schema: Schema, item: tuple[str, int], result: Scan
    ) -> None:
        """一次解码供同话题所有来源使用，维度检查包含零 stamp 消息。"""
        topic, stamp = item
        decoder = self.decoders.decoder_for("cdr", schema)
        if decoder is None:
            raise ValueError("没有可用的 ROS2 解码器")
        decoded: object = decoder(message.data)
        extracted: dict[str, list[float]] = {}
        for source in self.sources[topic]:
            if source.field not in extracted:
                extracted[source.field] = _extract(decoded, source.field)
            values = extracted[source.field]
            self._dimension(source, len(values))
        for name, values in extracted.items():
            series = result.topics[topic].values.setdefault(name, Values(len(values)))
            if stamp != 0:
                _reserve(result, len(values) * 8)
                series.data.extend(values)

    def _dimension(self, source: Source, dimension: int) -> None:
        """先验 fill/names 维度和首次推断维度都不能随消息、文件改变。"""
        expected = self.dimensions.get((source.topic, source.field))
        if source.fill is not None and len(source.fill) != dimension:
            raise ValueError("向量维度与 fill 不符")
        if source.names and len(source.names) != dimension:
            raise ValueError("向量维度与 names 不符")
        if expected is not None and dimension != expected:
            raise ValueError(f"向量维度变化：{expected} -> {dimension}")
        rule = self.source_rules.get(source.topic)
        if rule is not None and rule.limits is not None and len(rule.limits) != dimension:
            raise ValueError("限位维度与来源向量不一致")
        self.dimensions[source.topic, source.field] = dimension

    def _finish(self, result: Scan, checkpoint: Callable[[], None]) -> None:
        """消息物理顺序用于警告，之后稳定排序供匹配使用。"""
        for topic, data in result.topics.items():
            checkpoint()
            if data.message_count == 0 and not self.config.is_optional_topic(topic):
                result.fatal.append(
                    diagnostic(
                        "cleaning.missing_topic",
                        "非可选话题没有消息",
                        path=result.path,
                        topic=topic,
                    )
                )
            if data.h264 and not data.gate.started:
                result.fatal.append(
                    diagnostic(
                        "cleaning.no_keyframe", "H.264 没有关键帧", path=result.path, topic=topic
                    )
                )
            _topic_warnings(result, topic, self.config)
            data.order = array("Q", sorted(range(len(data.stamps)), key=data.stamps.__getitem__))
            data.stamps = array("q", (data.stamps[i] for i in data.order))


def _reserve(result: Scan, size_bytes: int) -> None:
    """缓存达到上限时停止当前文件，不把截断结果当作正常清洗结果。"""
    result.cache_bytes += size_bytes
    if result.cache_bytes > MAX_CACHE_BYTES:
        raise InputError(
            (
                diagnostic(
                    "cleaning.cache_limit",
                    "单文件缓存超过 1 GiB 安全上限",
                    path=result.path,
                ),
            )
        )


def _extract(message: object, path: str) -> list[float]:
    """点路径只穿过结构体，展平保留 schema 字段顺序及数组顺序。"""
    target = message
    for key in path.split("."):
        if not isinstance(target, SimpleNamespace):
            raise ValueError("字段路径的中间值不是结构体")
        target = cast(object, getattr(target, key))
    values: list[float] = []
    _flatten(target, values)
    return values


def _flatten(value: object, output: list[float]) -> None:
    """对应 Value.flatten_numbers，bool 是 0/1，字符串一律拒绝。"""
    if isinstance(value, (int, float)):
        output.append(float(value))
    elif isinstance(value, (bytes, bytearray, list, tuple)):
        for child in cast(list[object], value):
            _flatten(child, output)
    elif isinstance(value, SimpleNamespace):
        for name in cast(tuple[str, ...], value.__slots__):
            _flatten(cast(object, getattr(value, name)), output)
    else:
        raise ValueError("字段含不能转换为数值的值")


def _open_stream(result: Scan) -> BoundedReader | None:
    """打开失败或 stat 失败都成为当前文件致命诊断。"""
    try:
        descriptor = open_readonly(result.path, result.warnings)
        raw = os.fdopen(descriptor, "rb", buffering=0)
        with_raw = BoundedReader(raw)
        metadata = os.fstat(descriptor)
        result.size_bytes, result.mtime_ns = metadata.st_size, metadata.st_mtime_ns
        return with_raw
    except OSError as error:
        result.fatal.append(diagnostic("cleaning.file_read", str(error), path=result.path))
        return None


def _next_record(iterator: Iterator[McapRecord], result: Scan) -> McapRecord | None:
    """SDK 和压缩库边界的损坏文件异常转诊断；这里不执行调用方回调。"""
    try:
        return next(iterator)
    except StopIteration:
        return None
    except (
        McapError,
        OSError,
        ValueError,
        EOFError,
        struct.error,
        RuntimeError,
        ZstdError,
    ) as error:
        result.fatal.append(
            diagnostic("cleaning.file_read", str(error) or type(error).__name__, path=result.path)
        )
        return None


def _topic_warnings(result: Scan, topic: str, config: ToolConfig) -> None:
    """工具 verify 仅警告的事件各计一次聚合诊断，不逐消息增长。"""
    data = result.topics[topic]
    stamps = data.stamps
    findings: list[tuple[str, str]] = []
    if not stamps and config.is_optional_topic(topic):
        findings.append(("optional_fill", "可选话题没有有效 stamp，本文件全部使用 fill"))
    if data.pre_keyframe:
        findings.append(("pre_keyframe", f"关键帧前排除 {data.pre_keyframe} 条消息"))
    backwards = sum(stamps[i] < stamps[i - 1] for i in range(1, len(stamps)))
    duplicates = sum(stamps[i] == stamps[i - 1] for i in range(1, len(stamps)))
    if backwards:
        findings.append(("out_of_order", f"物理消息顺序有 {backwards} 处时间戳回退"))
    if duplicates:
        findings.append(("duplicate", f"相邻消息有 {duplicates} 处重复时间戳"))
    if len(stamps) >= 2 and (span := max(stamps) - min(stamps)) > 0:
        hz = (len(stamps) - 1) * 1e9 / span
        if hz < config.fps * MIN_RATE_RATIO:
            findings.append(("low_rate", f"平均频率 {hz:.3f} Hz 低于目标 fps * 0.995"))
    result.warnings.extend(
        diagnostic(f"cleaning.{rule}", actual, path=result.path, topic=topic, fatal=False)
        for rule, actual in findings
    )
