"""M5-08 就绪条件的只读脚本与机器结果（作业领域内部模块）。

复用标准库 shlex/re 和已有有界进程边界；只生成封闭检查命令，不接收任意命令，
不修复或重启机器人。行协议只传条件序号和状态，不回传进程、地址表或 SSH 原始输出。
"""

import re
import shlex
import subprocess

from rdp.collection.profile_models import ReadinessCondition, RobotProfile
from rdp.infra.diagnostics import (
    DefectError,
    Diagnostic,
    DiagnosticCategory,
    DiagnosticLevel,
    DiagnosticObject,
    ExternalError,
)
from rdp.jobs.execution import ExecutionContext
from rdp.jobs.robot_connection._process import run
from rdp.jobs.robot_connection._ros_scripts import copy_discovery_xml

# M5-11：为 ROS 发现留出等待时间，全部条件合用一次 SSH，总期限为 20 秒。
READINESS_TIMEOUT_S = 20.0
# M5-11 实测默认 spin 时间会漏节点；等待发现 3 秒，ROS 命令总计最多 8 秒。
ROS_NODE_TIMEOUT_S = 8
ROS_NODE_SPIN_TIME_S = 3


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
            stdin=_script(profile),
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
                    actual=f"就绪检查执行失败、超过 {READINESS_TIMEOUT_S:g} 秒期限或结果不完整",
                    expected="在期限内收到全部条件的机器结果",
                    consequence="本次检查失败，不能确认软件栈就绪",
                    next_step="检查机器人 SSH 服务和只读检查命令后重新检查连接",
                ),
            )
        ) from error


def _script(profile: RobotProfile) -> bytes:
    """值只作为 shell 字面量；脚本走 stdin，避免 pgrep 匹配到执行脚本的 shell。"""
    lines = ["set -o pipefail"]
    conditions = profile.ros.readiness
    if any(condition.check == "ros_node_visible" for condition in conditions):
        lines.append(_node_list(profile))
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
            case "ros_node_visible":
                # 不能把 /HDAS_bridge 或查询失败前的部分输出当成 /HDAS 已报到。
                command = "printf '%s\\n' \"$nodes\" | grep -Fx -- " + value
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


def _node_list(profile: RobotProfile) -> str:
    """所有节点条件共用一次隔离查询，失败丢弃部分结果，退出清理全部临时文件。"""
    join = profile.ros.join
    # 模型已经校验节点检查必须有 join；这里不另造降级环境。
    if join is None:
        raise DefectError()
    launch = "\n".join(
        (
            "set -e -o pipefail",
            "# 在 source 前隔离 ROS 输出并禁止字节码，避免写入 HOME 或厂商目录。",
            'export ROS_HOME="$1/ros_home" ROS_LOG_DIR="$1/ros_log"',
            "export PYTHONDONTWRITEBYTECODE=1",
            'mkdir -p -- "$ROS_HOME" "$ROS_LOG_DIR"',
            "source " + shlex.quote(join.setup_script) + " >/dev/null",
            "xml_source=" + shlex.quote(join.fastdds_profiles_file),
            'xml_destination="$1/fastdds_local.xml"',
            "discovery=" + shlex.quote(join.discovery_address),
            copy_discovery_xml(),
            'export FASTRTPS_DEFAULT_PROFILES_FILE="$xml_destination"',
            "export ROS_LOCALHOST_ONLY=" + shlex.quote(str(int(join.localhost_only))),
            "unset ROS_DOMAIN_ID"
            if profile.ros.domain_id is None
            else "export ROS_DOMAIN_ID=" + shlex.quote(str(profile.ros.domain_id)),
            "# 禁用 daemon，给新参与者足够发现时间；失败或超时由外层统一判为不满足。",
            f"exec timeout {ROS_NODE_TIMEOUT_S} ros2 node list --no-daemon --spin-time {ROS_NODE_SPIN_TIME_S}",
        )
    )
    return (
        "# 临时目录由本次脚本独占，XML、ROS 缓存和日志一起回收，不动厂商文件。\n"
        "readiness_tmp=$(mktemp -d) || exit 1\n"
        "trap 'rm -rf -- \"$readiness_tmp\"' EXIT\n"
        "trap 'exit 1' HUP INT TERM\n"
        'nodes=$(env -i HOME="$HOME" USER="$USER" LANG=C.UTF-8 PATH=/usr/bin:/bin '
        "bash -c " + shlex.quote(launch) + " -- \"$readiness_tmp\" 2>/dev/null) || nodes=''\n"
    )


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
