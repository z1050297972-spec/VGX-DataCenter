"""用 tomllib/Pydantic 读取登记配置；校验和容差归并严格对应 config.rs。

视频参数只保存不执行；对齐和清洗的业务约束由本模块集中表达。
"""

import hashlib
import math
import tomllib
from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from rdp.infra.diagnostics import InputError
from rdp.jobs.cleaning._io import diagnostic, read_config_bytes

# TOML 的整数可用于 Rust f64，但字符串和 bool 不可；严格浮点保留这一边界。
type ConfigFloat = Annotated[float, Field(strict=True)]


class FrozenConfig(BaseModel):
    """拒绝未知键和隐式字符串转换，允许 TOML 数组转为不可变元组。"""

    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)


class SyncConfig(FrozenConfig):
    """工具的纳秒对齐参数；默认值取自 config.rs。"""

    reference_topic: str
    max_dt_ms: ConfigFloat
    max_frame_gap: ConfigFloat = Field(default=1.5, gt=1)
    min_episode_frames: int = Field(default=1, ge=0, le=2**64 - 1, strict=True)


class VideoConfig(FrozenConfig):
    """只接受工具声明的视频键，清洗不使用编码器选项。"""

    vcodec: str = "libsvtav1"
    pix_fmt: str = "yuv420p"
    g: int | None = Field(default=2, ge=0, le=2**32 - 1, strict=True)
    crf: JsonValue = 30
    preset: JsonValue = None
    fast_decode: int = Field(default=0, ge=0, le=2**32 - 1, strict=True)

    @model_validator(mode="after")
    def _default_preset(self) -> Self:
        """对应 Config.load：只有 libsvtav1 且未指定 preset 才补 12。"""
        if self.preset is None and self.vcodec == "libsvtav1":
            object.__setattr__(self, "preset", 12)
        return self


class Source(FrozenConfig):
    """向量来源；fill 的维度在读取消息前已经确定。"""

    topic: str
    field: str
    names: tuple[str, ...] = ()
    max_dt_ms: ConfigFloat | None = None
    optional: bool = Field(default=False, strict=True)
    fill: tuple[ConfigFloat, ...] | None = None

    @model_validator(mode="after")
    def _validate_fill(self) -> Self:
        """对应工具 optional/fill 成对、非空及 names 维度检查。"""
        if self.optional != (self.fill is not None):
            raise ValueError("optional 与 fill 必须同时设置")
        if self.fill is not None:
            if not self.fill:
                raise ValueError("fill 不能为空")
            if self.names and len(self.names) != len(self.fill):
                raise ValueError("names 和 fill 维度必须一致")
        return self


class VideoFeature(FrozenConfig):
    """单相机映射。"""

    name: str
    type: Literal["video"]
    topic: str
    max_dt_ms: ConfigFloat | None = None


class VectorFeature(FrozenConfig):
    """按 sources 顺序拼接的向量特征。"""

    name: str
    type: Literal["vector"]
    sources: tuple[Source, ...] = Field(min_length=1)


class ToolConfig(FrozenConfig):
    """工具配置；features 保持文件中首次出现的顺序。"""

    robot_type: str | None = None
    fps: int = Field(gt=0, le=2**32 - 1, strict=True)
    task: str | None = None
    sync: SyncConfig
    video: VideoConfig = VideoConfig()
    features: tuple[Annotated[VideoFeature | VectorFeature, Field(discriminator="type")], ...] = (
        Field(alias="feature", min_length=1)
    )

    @model_validator(mode="after")
    def _validate_config(self) -> Self:
        """按工具校验最终使用的话题和容差，不额外限制未生效的默认容差。"""
        if len({f.name for f in self.features}) != len(self.features):
            raise ValueError("feature 名不能重复")
        if self.sync.reference_topic not in self.topics():
            raise ValueError("基准话题必须被 feature 引用")
        if self.is_optional_topic(self.sync.reference_topic):
            raise ValueError("基准话题不能是可选话题")
        if any(not tol > 0 for _, tol in self.topic_tolerances()):
            raise ValueError("每个话题的容差必须大于零")
        return self

    def topics(self) -> tuple[str, ...]:
        """按 feature/source 顺序返回所有引用，和工具一样保留重复话题。"""
        return tuple(topic for topic, _, _ in self._references())

    def is_optional_topic(self, topic: str) -> bool:
        """只有被引用且全部引用为 optional source 才允许整文件缺失。"""
        references = [optional for name, _, optional in self._references() if name == topic]
        return bool(references) and all(references)

    def topic_tolerances(self) -> tuple[tuple[str, float], ...]:
        """按首次引用顺序返回每话题最严格的容差，单位毫秒。"""
        result: dict[str, float] = {}
        for topic, tolerance, _ in self._references():
            value = self.sync.max_dt_ms if tolerance is None else tolerance
            result[topic] = min(result.get(topic, value), value)
        return tuple(result.items())

    def _references(self) -> tuple[tuple[str, float | None, bool], ...]:
        """统一三个话题查询方法的引用遍历顺序。"""
        result: list[tuple[str, float | None, bool]] = []
        for feature in self.features:
            if isinstance(feature, VideoFeature):
                result.append((feature.topic, feature.max_dt_ms, False))
            else:
                result.extend((s.topic, s.max_dt_ms, s.optional) for s in feature.sources)
        return tuple(result)


class StaticRule(FrozenConfig):
    """静止特征及连续静止最短秒数。"""

    feature: str
    long_static_s: ConfigFloat = Field(gt=0, allow_inf_nan=False)


class JumpRule(FrozenConfig):
    """跳变检查的向量特征名。"""

    feature: str


class ImageRule(FrozenConfig):
    """图像抽样规则；亮度范围 0-255，阈值为严格不等式。"""

    frozen_s: ConfigFloat = Field(gt=0, allow_inf_nan=False)
    sample_interval_s: ConfigFloat = Field(gt=0, allow_inf_nan=False)
    dark_below: ConfigFloat = Field(gt=0, le=255, allow_inf_nan=False)
    bright_above: ConfigFloat = Field(gt=0, le=255, allow_inf_nan=False)


class SourceRule(FrozenConfig):
    """按来源话题提供阈值；限位允许负数，每维下限必须不大于上限。"""

    topic: str
    static_threshold: ConfigFloat | None = Field(default=None, gt=0, allow_inf_nan=False)
    jump_threshold: ConfigFloat | None = Field(default=None, gt=0, allow_inf_nan=False)
    limits: tuple[tuple[ConfigFloat, ConfigFloat], ...] | None = None

    @model_validator(mode="after")
    def _validate_limits(self) -> Self:
        """限位不使用正数约束，因为关节合法下限可以为负数。"""
        if self.limits is not None and any(
            not math.isfinite(low) or not math.isfinite(high) or low > high
            for low, high in self.limits
        ):
            raise ValueError("限位必须是有限且有序的上下限")
        return self


class CleaningRules(FrozenConfig):
    """版本一清洗规则；不存在的阈值不检查。"""

    schema_version: Literal[1]
    static: StaticRule
    jump: JumpRule
    image: ImageRule
    source: tuple[SourceRule, ...] = ()

    def validate_topics(self, config: ToolConfig) -> None:
        """确保检查特征为向量、阈值话题存在且不重复。"""
        vectors = {f.name for f in config.features if isinstance(f, VectorFeature)}
        if self.static.feature not in vectors or self.jump.feature not in vectors:
            raise ValueError("静止和跳变检查必须引用 vector feature")
        topics = [s.topic for s in self.source]
        if len(set(topics)) != len(topics) or not set(topics).issubset(config.topics()):
            raise ValueError("规则话题必须存在于工具配置中且不重复")
        self._validate_fill_limits(config)

    def _validate_fill_limits(self, config: ToolConfig) -> None:
        """缺失 optional 不会解码消息，因此 fill 对应限位的维度必须在配置阶段检查。"""
        rules = {rule.topic: rule for rule in self.source}
        for feature in config.features:
            if not isinstance(feature, VectorFeature):
                continue
            for source in feature.sources:
                rule = rules.get(source.topic)
                if (
                    source.fill is not None
                    and rule is not None
                    and rule.limits is not None
                    and len(source.fill) != len(rule.limits)
                ):
                    raise ValueError("限位维度与可选来源 fill 不一致")


def load_configs(tool_path: Path, rules_path: Path) -> tuple[ToolConfig, CleaningRules, str, str]:
    """只读两份 TOML，按原始字节计算指纹；解析失败转为统一输入诊断。"""
    tool_bytes = read_config_bytes(tool_path)
    rules_bytes = read_config_bytes(rules_path)
    tool = _parse_config(tool_bytes, tool_path, ToolConfig)
    rules = _parse_config(rules_bytes, rules_path, CleaningRules)
    try:
        rules.validate_topics(tool)
    except ValueError as error:
        raise InputError((diagnostic("cleaning.config", str(error), path=rules_path),)) from error
    return (
        tool,
        rules,
        hashlib.sha256(tool_bytes).hexdigest(),
        hashlib.sha256(rules_bytes).hexdigest(),
    )


def _parse_config[T: FrozenConfig](data: bytes, path: Path, model: type[T]) -> T:
    """在知道配置文件身份的边界转译解析错误，不回显配置原始载荷。"""
    try:
        return model.model_validate(tomllib.loads(data.decode("utf-8")))
    except ValueError as error:
        raise InputError((diagnostic("cleaning.config", str(error), path=path),)) from error
