"""M5-12 数据流探测执行边界：复用有界 SSH，纯判定留在 collection，不启停服务。"""

import subprocess
from collections import Counter

from pydantic import JsonValue

from rdp.collection.preview_dataflow import DataflowResult, evaluate_dataflow
from rdp.collection.profile_models import RobotProfile
from rdp.infra.diagnostics import Diagnostic, DiagnosticCategory, DiagnosticLevel, DiagnosticObject
from rdp.jobs.execution import ExecutionContext
from rdp.jobs.robot_connection import _preview_scripts as scripts
from rdp.jobs.robot_connection._process import run
from rdp.jobs.robot_connection._session import ConnectionParameters

# M5-12：包含 2 秒发现预热、5 秒计数及 SSH/ROS 启动余量，整段最多 20 秒。
PROBE_TIMEOUT_S = 20.0


def check(
    context: ExecutionContext,
    ssh: tuple[str, ...],
    package_id: str,
    profile: RobotProfile,
    routes: JsonValue,
) -> tuple[str, tuple[Diagnostic, ...]]:
    """执行探测并返回摘要与诊断；探测失败降为警告，取消仍向上传播。"""
    robot_id = ConnectionParameters.model_validate(context.parameters).robot_id
    try:
        result = run(
            (*ssh, "bash", "-s"),
            PROBE_TIMEOUT_S,
            context,
            stdin=scripts.probe(package_id, profile).encode(),
        )
        context.reporter.tool_exit(result.returncode)
        if result.returncode != 0:
            raise ValueError("探测进程失败")
        results = evaluate_dataflow(profile, routes, result.stdout.decode("utf-8"))
    except (OSError, subprocess.SubprocessError, ValueError):
        # 原始 SSH/ROS 输出不落平台日志；它可能包含环境信息或凭据。
        diagnostic = _diagnostic(
            robot_id,
            DiagnosticLevel.WARNING,
            "数据流检查没做成",
            "预览照常可用，但本次没有确认数据流",
            "看机器人上 ~/rdp_viz/log/probe.log",
        )
        return "检查没做成", (diagnostic,)
    diagnostics: list[Diagnostic] = []
    for item in results:
        nominal = "标称未知" if item.nominal_hz is None else f"标称 {item.nominal_hz:g} Hz"
        context.log.write_line(
            f"数据流 {item.channel} {item.actual_hz:g} Hz（{nominal}）{item.status}",
            now=context.clock.now(),
        )
        if item.status in ("警告", "失败"):
            diagnostics.append(_route_diagnostic(robot_id, item, nominal))
    counts = Counter(item.status for item in results)
    summary = "，".join(
        f"{counts[status]} 路{status}"
        for status in ("通过", "警告", "失败", "提示")
        if counts[status]
    )
    return summary or "0 路通过", tuple(diagnostics)


def _route_diagnostic(robot_id: int, item: DataflowResult, nominal: str) -> Diagnostic:
    """把纯判定转成可操作诊断，静默目标不进入本函数。"""
    if item.status == "失败":
        return _diagnostic(
            robot_id,
            DiagnosticLevel.ERROR,
            f"{item.channel} 5 秒内 0 条",
            "预览程序已开启并保持运行，但这一路没有数据",
            "先点检查连接看就绪条件；接通主臂网线、确认厂商栈在跑；不需要预览时点停止预览",
        )
    return _diagnostic(
        robot_id,
        DiagnosticLevel.WARNING,
        f"{item.channel} 实测 {item.actual_hz:g} Hz，{nominal}",
        "预览保持运行，但这一路频率不足",
        "画面或曲线可能卡顿；检查机器人负载和厂商节点",
    )


def _diagnostic(
    robot_id: int,
    level: DiagnosticLevel,
    actual: str,
    consequence: str,
    next_step: str,
) -> Diagnostic:
    """沿用统一诊断结构，只报告可信通道身份与已校验的数值。"""
    return Diagnostic(
        level=level,
        category=DiagnosticCategory.EXTERNAL,
        stage="数据流",
        source="平台",
        objects=(DiagnosticObject(key="robot_id", value=str(robot_id)),),
        rule="robot_preview.dataflow",
        actual=actual,
        expected="观测和相机有数据，已知标称的路由达到标称频率的 50%；目标允许静默",
        consequence=consequence,
        next_step=next_step,
    )
