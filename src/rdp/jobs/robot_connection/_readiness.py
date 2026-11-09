"""M5-08 就绪条件的只读脚本与机器结果（作业领域内部模块）。

复用标准库 shlex/re 和已有有界进程边界；只生成封闭检查命令，不接收任意命令，
不修复或重启机器人。行协议只传条件序号和状态，不回传进程、地址表或 SSH 原始输出。
"""

import re
import shlex
import subprocess

from rdp.collection.profile_models import ReadinessCondition, RobotProfile
from rdp.infra.diagnostics import (
    Diagnostic,
    DiagnosticCategory,
    DiagnosticLevel,
    DiagnosticObject,
    ExternalError,
)
from rdp.jobs.execution import ExecutionContext
from rdp.jobs.robot_connection._process import run

# M5-08：全部条件合用一次 SSH，包含发送脚本与读取结果在内限时 10 秒。
READINESS_TIMEOUT_S = 10.0


def check(
    context: ExecutionContext,
    profile: RobotProfile,
    robot_id: int,
    ssh_argv: tuple[str, ...],
) -> tuple[Diagnostic, ...]:
    """执行一次只读脚本，返回未满足条件的诊断；传输和协议失败不伪装成条件满足。"""
    try:
        result = run(
            (*ssh_argv, "bash", "-s"),
            READINESS_TIMEOUT_S,
            context,
            stdin=_script(profile.ros.readiness),
        )
        context.reporter.tool_exit(result.returncode)
        if result.returncode != 0:
            raise OSError("就绪检查 SSH 执行失败")
        # 直接比较协议字节，拒绝原始输出时异常链也不能带出远程文本。
        states = result.stdout.splitlines()
        conditions = profile.ros.readiness
        if len(states) != len(conditions):
            raise ValueError("就绪结果数量不符")
        diagnostics: list[Diagnostic] = []
        for index, (condition, state) in enumerate(zip(conditions, states, strict=True)):
            allowed = ("info",) if condition.check == "run_on_robot" else ("pass", "fail")
            if state not in (f"{index}:{status}".encode("ascii") for status in allowed):
                raise ValueError("就绪结果格式不符")
            if state == f"{index}:fail".encode("ascii"):
                diagnostics.append(_condition_diagnostic(robot_id, profile, index, condition))
        return tuple(diagnostics)
    except (OSError, subprocess.SubprocessError, ValueError) as error:
        raise ExternalError(
            (
                Diagnostic(
                    level=DiagnosticLevel.ERROR,
                    category=DiagnosticCategory.EXTERNAL,
                    stage="第 3 层 就绪",
                    source="平台",
                    objects=(DiagnosticObject(key="robot_id", value=str(robot_id)),),
                    rule="robot_readiness.execution",
                    actual="就绪检查执行失败、超过 10 秒期限或结果不完整",
                    expected="在期限内收到全部条件的机器结果",
                    consequence="本次检查失败，不能确认软件栈就绪",
                    next_step="检查机器人 SSH 服务和只读检查命令后重新检查连接",
                ),
            )
        ) from error


def _script(conditions: list[ReadinessCondition]) -> bytes:
    """值只作为 shell 字面量；脚本走 stdin，避免 pgrep 匹配到执行脚本的 shell。"""
    lines = ["set -o pipefail"]
    for index, condition in enumerate(conditions):
        if condition.check == "run_on_robot":
            lines.append(f"printf '%s\\n' '{index}:info'")
            continue
        value = shlex.quote(str(condition.value))
        match condition.check:
            case "address_present":
                # 按地址字段去掉前缀长度后精确比较，不能把相邻地址误报为存在。
                command = (
                    "ip -br addr | awk '{for (i=3; i<=NF; i++) "
                    '{split($i, a, "/"); print a[1]}}\' | grep -Fx -- ' + value
                )
            case "udp_port_listening":
                # ss -Huln 的第 4 列为本地端点；只取最后的端口，不把对端算成监听。
                command = (
                    "ss -Huln | awk '{sub(/^.*:/, \"\", $4); print $4}' | grep -Fx -- " + value
                )
            case "process_running":
                # pgrep 使用 ERE；先转义正则元字符，再引用 shell 参数，保持固定文本语义。
                command = "pgrep -f -- " + shlex.quote(re.escape(str(condition.value)))
        lines.extend(
            (
                f"if {command} >/dev/null; then",
                f"  printf '%s\\n' '{index}:pass'",
                "else",
                f"  printf '%s\\n' '{index}:fail'",
                "fi",
            )
        )
    return ("\n".join(lines) + "\n").encode("utf-8")


def _condition_diagnostic(
    robot_id: int, profile: RobotProfile, index: int, condition: ReadinessCondition
) -> Diagnostic:
    """每条未满足条件带独立规则身份和原始 reason；不加入远程原始输出。"""
    warning = condition.level == "warning"
    return Diagnostic(
        level=DiagnosticLevel.WARNING if warning else DiagnosticLevel.ERROR,
        category=DiagnosticCategory.EXTERNAL,
        stage="第 3 层 就绪",
        source="平台",
        objects=(
            DiagnosticObject(key="robot_id", value=str(robot_id)),
            DiagnosticObject(key="profile", value=profile.profile),
            DiagnosticObject(key="condition", value=str(index + 1)),
        ),
        rule=f"robot_readiness.{profile.profile}.{index + 1}.{condition.check}",
        actual=f"{condition.check} 条件不满足",
        expected=f"满足 {condition.check} 就绪条件",
        consequence="检查继续，保留就绪警告" if warning else "本次检查失败，软件栈未就绪",
        next_step=condition.reason,
    )
