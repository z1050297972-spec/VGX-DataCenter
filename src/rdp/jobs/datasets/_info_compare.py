"""领域层的导航顶层字段与原文件比对（M1.5-15、ADR0006），只产生提示、不读写文件。

字符串规范化使用标准库，诊断复用现有构造器；比对规则属于本项目契约，无需新依赖。
"""

from rdp.jobs.datasets._panel_issue import difference
from rdp.jobs.datasets.panel import NavigationRule
from rdp.jobs.datasets.scan_types import SourceCheck
from rdp.jobs.datasets.types import EntrySnapshot, Finding, PanelGroup


def compare(
    entry: EntrySnapshot,
    source: SourceCheck,
    *,
    robot_model: object,
    fps: object,
) -> tuple[Finding, ...]:
    """比较规范入口顶层标注与已读取的 LeRobot 元信息，返回提示级发现。

    Args:
        entry: 规范入口的快照，仅用于诊断身份；调用方保证数据块为 LeRobot 且可用。
        source: 已读取的 LeRobot 数据块观察，含零起序号、robot_type 和 fps；
            fps 为有限正数，单位帧/秒，两个元信息值为 None 时各自不比。
        robot_model: 数据集信息.json 顶层原值；缺失、非文本或空白文本不比。
        fps: 数据集信息.json 顶层原值，单位帧/秒；缺失或非正整数不比。

    Returns:
        按型号、FPS 顺序返回差异提示；相同或未标注时为空，不产生需处理级发现。
        型号去首尾空白并忽略大小写；原文件 FPS 沿用索引的正数半入取整规则。

    Raises:
        无。

    Side Effects:
        无；不改输入、导航文件、原数据或作业成败计数。

    Time Semantics:
        只比较同轮扫描已读到的值，不访问磁盘或时钟，不等待或重试。
    """
    findings: list[Finding] = []
    if (
        isinstance(robot_model, str)
        and robot_model.strip()
        and source.robot_type is not None
        and robot_model.strip().casefold() != source.robot_type.strip().casefold()
    ):
        findings.append(
            difference(
                entry,
                NavigationRule.INFO_ROBOT_MODEL_DIFFERS,
                (
                    f"sources[{source.ordinal}].meta/info.json.robot_type",
                    robot_model,
                    source.robot_type,
                ),
                group=PanelGroup.DISK,
                notice=True,
            )
        )
    if isinstance(fps, int) and not isinstance(fps, bool) and fps > 0 and source.fps is not None:
        # 与已有索引的 fps_rounded 一致，正数半入；不用银行家舍入或直接截断。
        rounded_fps = int(source.fps + 0.5)
        if fps != rounded_fps:
            findings.append(
                difference(
                    entry,
                    NavigationRule.INFO_FPS_DIFFERS,
                    (f"sources[{source.ordinal}].meta/info.json.fps", fps, rounded_fps),
                    group=PanelGroup.DISK,
                    notice=True,
                )
            )
    return tuple(findings)
