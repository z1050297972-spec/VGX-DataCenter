"""预览布局生成（领域层，M5-04），只把 RobotProfile 事实转换为 Lichtblick JSON。

通道、消息类型和端口集中在同目录 preview_channels.json，前端和第 03 张 relay 共用，
避免各语言各写一份约定。资源读取用标准库；布局是查看器专有格式，按已验证原型构造。
"""

import json
from importlib.resources import files
from typing import TypedDict, cast

from pydantic import JsonValue

from rdp.collection.profile_models import JointGroup, JointSource, RobotProfile


class PreviewChannels(TypedDict):
    """M5-04 平台与 relay 共享的固定协议约定。

    Attributes:
        port: 机器人预览 WebSocket 端口，固定 8765。
        camera_topic: 相机话题模板，name 取 Profile 相机名。
        joint_topic: 关节话题模板，name 取组名，source 为 obs 或 target。
        video_schema: H.264 换壳后的消息类型。
        image_schema: JPEG 消息类型。
        joint_schema: 位置曲线消息类型。
    """

    port: int
    camera_topic: str
    joint_topic: str
    video_schema: str
    image_schema: str
    joint_schema: str


# 此包内受评审的静态资源同时供 TypeScript 直接导入；不读取外部配置或机器人。
PREVIEW_CHANNELS = cast(
    PreviewChannels,
    json.loads(
        files("rdp.collection").joinpath("preview_channels.json").read_text(encoding="utf-8")
    ),
)
# 原型显示最近 15 秒，接收时间用于趋势对比，不能用于控制误差测量（ADR 0007）。
FOLLOWING_VIEW_WIDTH_S = 15


def build_preview_layout(profile: RobotProfile) -> dict[str, JsonValue]:
    """按型号事实生成相机和关节位置面板布局。

    Args:
        profile: 已经校验的 RobotProfile；关节维数为正整数，单位可未知。

    Returns:
        可直接由 Lichtblick 1.30.0 layoutUrl 导入的裸 JSON，面板顺序为相机再关节。
        每个非双目右目的相机一个 Image；只为观测及已知目标均采用 JointState.position 的组生成 Plot。
        无目标或目标未知时只画观测；默认启用每组索引 0，其他索引保留为关闭。
        已知单位的轴标签写 position (单位)，未知单位写“单位未确认”；没有面板时 layout 为 null。

    Raises:
        无。

    Side Effects:
        无；不改 Profile，不读取文件、数据库或机器人。

    Time Semantics:
        曲线统一使用 receiveTime，因为目标 header 时间不可信；窗口为最近 15 秒。
        布局不重采样或对齐消息，不声称目标与观测具有控制级同步精度。
    """
    panels: dict[str, JsonValue] = {}
    for camera in profile.camera:
        # M5-04 补充：右目仍保留在 Profile 供其他用途读取，默认预览只显示左目。
        if camera.stereo_eye == "right":
            continue
        panels[f"Image!{camera.name}"] = {
            "lichtblickPanelTitle": camera.name,
            "imageMode": {
                "imageTopic": PREVIEW_CHANNELS["camera_topic"].format(name=camera.name),
                "synchronize": False,
                "flipHorizontal": False,
                "flipVertical": False,
                "rotation": 0,
            },
            "topics": {},
        }
    for group in profile.joint_group:
        if group.observation.extract != "JointState.position":
            continue
        # 底盘目标是速度，不能把它与观测位置并列成一组误导曲线；按本票整个组排除。
        if isinstance(group.target, JointSource) and group.target.extract != "JointState.position":
            continue
        panels[f"Plot!{group.name}"] = _plot(group)
    return {
        "configById": panels,
        "globalVariables": {},
        "userNodes": {},
        "playbackConfig": {"speed": 1},
        "layout": _mosaic(list(panels)),
    }


def _plot(group: JointGroup) -> dict[str, JsonValue]:
    """生成可手动开启全部关节的路径；不猜未知目标来源或单位。"""
    count = len(group.joints) if group.joints is not None else cast(int, group.joint_count)
    sources = ("obs", "target") if isinstance(group.target, JointSource) else ("obs",)
    paths: list[JsonValue] = [
        {
            "value": PREVIEW_CHANNELS["joint_topic"].format(name=group.name, source=source)
            + f".position[{index}]",
            "enabled": index == 0,
            "timestampMethod": "receiveTime",
            "label": f"{'观测' if source == 'obs' else '目标'} position[{index}]",
            "showLine": True,
        }
        for index in range(count)
        for source in sources
    ]
    return {
        "lichtblickPanelTitle": group.name,
        "paths": paths,
        "showLegend": True,
        "legendDisplay": "top",
        "showPlotValuesInLegend": True,
        "showXAxisLabels": True,
        "showYAxisLabels": True,
        "isSynced": True,
        "xAxisVal": "timestamp",
        "followingViewWidth": FOLLOWING_VIEW_WIDTH_S,
        "yAxisLabel": f"position ({group.unit})" if group.unit is not None else "单位未确认",
        "xAxisLabel": "接收时间（秒）",
    }


def _mosaic(identifiers: list[str], *, vertical: bool = True) -> JsonValue:
    """均匀二分面板并交替切分方向，保持 Profile 顺序且避免长链递归。"""
    if not identifiers:
        return None
    if len(identifiers) == 1:
        return identifiers[0]
    midpoint = len(identifiers) // 2
    return {
        "direction": "column" if vertical else "row",
        "splitPercentage": 50,
        "first": _mosaic(identifiers[:midpoint], vertical=not vertical),
        "second": _mosaic(identifiers[midpoint:], vertical=not vertical),
    }
