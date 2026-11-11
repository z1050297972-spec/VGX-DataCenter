"""M5-12 数据流判定（领域层）：复用 Profile 和通道定义，不执行 SSH 或修改预览进程。

标准库负责结果组织，已有 Pydantic 校验不可信探测载荷；频率只描述本次窗口。
"""

import math
from dataclasses import dataclass
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, TypeAdapter

from rdp.collection.preview import PREVIEW_CHANNELS
from rdp.collection.profile_models import JointSource, RobotProfile

# M5-12：源话题达到标称频率的 50% 即通过，不能拿转发限频作为标称。
MIN_RATE_RATIO = 0.5


@dataclass(frozen=True)
class DataflowResult:
    """单条路由在本次探测窗口内的结论。

    Attributes:
        channel: 配置中的完整通道名，非空。
        actual_hz: 原始消息计数除以实际窗口秒数，有限非负 Hz。
        nominal_hz: Profile 的有限正标称 Hz，None 表示未知。
        status: 通过、警告、失败或提示；目标无数据只能提示。
    """

    channel: str
    actual_hz: float
    nominal_hz: float | None
    status: Literal["通过", "警告", "失败", "提示"]


class _Probe(BaseModel):
    """仅接收完整窗口和非负整数计数，拒绝布尔值与非有限时长。"""

    model_config = ConfigDict(extra="forbid")
    window_s: float = Field(strict=True, gt=0, allow_inf_nan=False)
    counts: dict[str, Annotated[int, Field(strict=True, ge=0)]]


class _Route(BaseModel):
    """只提取配置中的通道身份，其余路由事实由配置生成器负责。"""

    channel: str = Field(strict=True, min_length=1)


def evaluate_dataflow(
    profile: RobotProfile, routes: JsonValue, probe_output: str
) -> tuple[DataflowResult, ...]:
    """校验探测协议并按 Profile 的标称频率逐路判定数据流。

    Args:
        profile: 生成本次配置所用的已校验型号事实快照。
        routes: build_relay_config 返回的 routes 列表，通道唯一且均能对应 Profile。
        probe_output: 恰好一行 RDP_VIZ_PROBE JSON，可带末尾换行；计数为非负整数，
            window_s 为单调时钟测得的有限正秒数，计数键必须和路由完全一致。

    Returns:
        按路由顺序返回每路一条结果；空路由返回空元组。标称未知时有数据即通过。

    Raises:
        ValueError: 协议格式、窗口、计数、路由键或 Profile 对应关系不合法。

    Side Effects:
        无；不写日志、不读取机器人或时钟。

    Time Semantics:
        频率是本次窗口内的原始消息数除以实际秒数，不使用消息时间戳或转发限频。
        目标无数据不判失败，包含 may_be_silent 为 false 的来源（M5-12、0014）。
    """
    lines = probe_output.splitlines()
    if len(lines) != 1 or not lines[0].startswith("RDP_VIZ_PROBE "):
        raise ValueError("探测输出必须是一行结果")
    probe = _Probe.model_validate_json(lines[0].removeprefix("RDP_VIZ_PROBE "))
    parsed_routes = TypeAdapter(list[_Route]).validate_python(routes)
    channels = [route.channel for route in parsed_routes]
    if len(set(channels)) != len(channels) or set(channels) != probe.counts.keys():
        raise ValueError("探测通道和路由不一致")
    sources = _sources(profile)
    results: list[DataflowResult] = []
    for channel in channels:
        if channel not in sources:
            raise ValueError("路由没有对应的 Profile 来源")
        nominal, target = sources[channel]
        try:
            actual = probe.counts[channel] / probe.window_s
        except OverflowError as error:
            raise ValueError("探测计数超出可计算范围") from error
        if not math.isfinite(actual):
            raise ValueError("探测频率不是有限数值")
        # 0014 实测目标在无人操作时静默；M5-12 明确覆盖 may_be_silent=false 的旧事实。
        if actual == 0:
            status = "提示" if target else "失败"
        elif nominal is None or actual >= nominal * MIN_RATE_RATIO:
            status = "通过"
        else:
            status = "警告"
        results.append(DataflowResult(channel, actual, nominal, status))
    return tuple(results)


def _sources(profile: RobotProfile) -> dict[str, tuple[float | None, bool]]:
    """通过共享通道模板连接事实；不从消息类型或话题字符串猜目标身份。"""
    sources = {
        PREVIEW_CHANNELS["camera_topic"].format(name=camera.name): (camera.rate_hz, False)
        for camera in profile.camera
    }
    for group in profile.joint_group:
        for name, source in (("obs", group.observation), ("target", group.target)):
            if isinstance(source, JointSource):
                channel = PREVIEW_CHANNELS["joint_topic"].format(name=group.name, source=name)
                sources[channel] = (source.rate_hz, name == "target")
    return sources
