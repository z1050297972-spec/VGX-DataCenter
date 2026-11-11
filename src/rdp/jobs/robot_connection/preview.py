"""M5-09 人工启停预览作业（领域层）；复用连接会话，不自动重启、不修改厂商配置。

标准库完成打包和传输，远程只执行随平台发布的 bash 脚本；原始 SSH 输出不落日志。
"""

import subprocess
from typing import Literal

from rdp.collection.preview import PREVIEW_CHANNELS
from rdp.collection.preview_config import build_relay_config
from rdp.collection.profile_models import RobotProfile
from rdp.infra import viz_relay
from rdp.infra.diagnostics import (
    DefectError,
    Diagnostic,
    DiagnosticCategory,
    DiagnosticLevel,
    DiagnosticObject,
    ExternalError,
)
from rdp.jobs.execution import ExecutionContext
from rdp.jobs.registry import JobDefinition
from rdp.jobs.robot_connection import _preview_dataflow as dataflow
from rdp.jobs.robot_connection import _preview_scripts as scripts
from rdp.jobs.robot_connection._process import run
from rdp.jobs.robot_connection._session import ConnectionDependencies, ConnectionParameters, connect
from rdp.jobs.types import JobProgress, RecoveryMode

# 第 09 张各段含 SSH 的单调期限；脚本内锁 5 秒、READY 20 秒、TERM 宽限 5 秒。
QUERY_TIMEOUT_S = 10.0
INSTALL_TIMEOUT_S = 180.0
START_TIMEOUT_S = 30.0
STOP_TIMEOUT_S = 15.0


def build_preview_definitions(
    dependencies: ConnectionDependencies | None,
) -> tuple[JobDefinition, ...]:
    """登记只接受 robot_id 的人工预览启停作业。

    Args:
        dependencies: worker 的连接和本地包能力；Web 传 None，仅能提交作业。

    Returns:
        robot_preview_start、robot_preview_stop 两个默认并发 1、interrupt 恢复类型。

    Raises:
        无。

    Side Effects:
        只构造定义；不读取文件、不生成密钥、不连接机器人。

    Time Semantics:
        启动期登记；中断不自动恢复，避免无人确认时重新开启预览。
    """

    def start(context: ExecutionContext) -> None:
        if dependencies is None:
            raise DefectError()
        _execute(context, dependencies, "start")

    def stop(context: ExecutionContext) -> None:
        if dependencies is None:
            raise DefectError()
        _execute(context, dependencies, "stop")

    return (
        JobDefinition(
            "robot_preview_start",
            "开启机器人预览",
            ConnectionParameters,
            RecoveryMode.INTERRUPT,
            start,
        ),
        JobDefinition(
            "robot_preview_stop",
            "停止机器人预览",
            ConnectionParameters,
            RecoveryMode.INTERRUPT,
            stop,
        ),
    )


def _execute(
    context: ExecutionContext,
    dependencies: ConnectionDependencies,
    action: Literal["start", "stop"],
) -> None:
    """先按当前登记连接；停止不查就绪，开启在就绪通过后才读取和上传包。"""
    try:
        connected = connect(context, dependencies, readiness=action == "start")
    except ExternalError as error:
        if action == "stop":
            raise ExternalError(
                tuple(
                    d.model_copy(update={"consequence": "停止失败；预览程序可能还在机器人上运行"})
                    for d in error.diagnostics
                )
            ) from error
        raise
    _, _, ssh, _ = connected
    if action == "stop":
        _progress(context, "网络：通过；登录：通过；停止：进行中", done=2, total=3)
        result = _remote(context, ssh, scripts.stop(), STOP_TIMEOUT_S, "停止")
        state = "已停止" if result == "RDP_CONTROL stopped" else "本来就没在运行"
        _progress(context, f"网络：通过；登录：通过；停止：{state}", done=3, total=3)
        return
    _start(context, dependencies, connected)


def _start(
    context: ExecutionContext,
    dependencies: ConnectionDependencies,
    connected: tuple[RobotProfile | None, str, tuple[str, ...], int],
) -> None:
    """就绪通过后才生成包、查询差异、安装并等待 READY。"""
    profile, address, ssh, warnings = connected
    robot_id = ConnectionParameters.model_validate(context.parameters).robot_id
    if profile is None or profile.ros.join is None:
        raise ExternalError(
            (
                _diagnostic(
                    robot_id,
                    "配置",
                    "型号没有 ros.join，不能开启预览",
                    "补充该型号的新参与者 ROS 环境事实",
                ),
            )
        )
    wheel = dependencies.paths.root / "viz_relay/wheels" / viz_relay.WHEEL_FILENAME
    if not wheel.is_file():
        raise ExternalError(
            (
                _diagnostic(
                    robot_id,
                    "安装",
                    "工作站没有预览 wheel",
                    f"rdp install-viz-relay-wheel /本地路径/{viz_relay.WHEEL_FILENAME}",
                ),
            )
        )
    config = build_relay_config(profile, address)
    try:
        package_id, archive = scripts.bundle(dependencies.relay_source, config)
    except OSError as error:
        raise DefectError(
            (
                _diagnostic(
                    robot_id,
                    "配置",
                    "平台缺少转发程序文件或无法读取",
                    "检查平台部署中的 robot_side/viz_relay 程序包",
                    category=DiagnosticCategory.DEFECT,
                ),
            )
        ) from error
    query = _remote(context, ssh, scripts.query(package_id), QUERY_TIMEOUT_S, "查询")
    states = query.split()
    if len(states) != 4 or states[0] != "RDP_QUERY" or any(s not in ("0", "1") for s in states[1:]):
        raise ExternalError(
            (
                _diagnostic(
                    robot_id, "查询", "机器人安装查询结果不完整", "检查机器人 Python 和 SSH 后重试"
                ),
            )
        )
    has_wheel, has_site, has_package = (s == "1" for s in states[1:])
    prefix = "网络：通过；登录：通过；就绪：" + ("有警告" if warnings else "通过")
    _progress(context, prefix + "；安装：进行中", done=3, total=6, warnings=warnings)
    try:
        wheel_data = None if has_wheel else wheel.read_bytes()
    except OSError as error:
        raise ExternalError(
            (_diagnostic(robot_id, "安装", "工作站 wheel 读取失败", "检查平台状态目录权限"),)
        ) from error
    _remote(
        context,
        ssh,
        scripts.install(
            package_id, archive, wheel_data, needs_package=not has_package, profile=profile
        ),
        INSTALL_TIMEOUT_S,
        "安装",
    )
    installed = "已是最新" if has_wheel and has_site and has_package else "已安装"
    _progress(
        context, prefix + f"；安装：{installed}；启动：进行中", done=4, total=6, warnings=warnings
    )
    result = _remote(
        context,
        ssh,
        scripts.start(package_id, profile, PREVIEW_CHANNELS["port"]),
        START_TIMEOUT_S,
        "启动",
    )
    if result == "RDP_CONTROL old_package":
        warnings += 1
        context.reporter.diagnostic(
            _diagnostic(
                robot_id,
                "启动",
                "已在运行的包与本次不同",
                "先停止再开启才会更新",
            ).model_copy(
                update={"level": DiagnosticLevel.WARNING, "consequence": "继续使用当前预览进程"}
            )
        )
    state = "已开启" if result == "RDP_CONTROL started" else "已在运行"
    host = f"[{address}]" if ":" in address else address
    prefix += f"；安装：{installed}；启动：{state}"
    _progress(context, prefix + "；数据流：进行中", done=5, total=6, warnings=warnings)
    # 必须在启动确认后检查；无数据只影响作业结果，不回滚已开启的服务。
    summary, diagnostics = dataflow.check(context, ssh, package_id, profile, config["routes"])
    _finish_dataflow(
        context,
        prefix + f"；数据流：{summary}；ws://{host}:{PREVIEW_CHANNELS['port']}",
        diagnostics,
        warnings,
    )


def _finish_dataflow(
    context: ExecutionContext, summary: str, diagnostics: tuple[Diagnostic, ...], warnings: int
) -> None:
    """先保存完整摘要和警告，再让执行器记录失败；不回收已启动的预览。"""
    errors = tuple(d for d in diagnostics if d.level == DiagnosticLevel.ERROR)
    for diagnostic in diagnostics:
        if diagnostic.level == DiagnosticLevel.WARNING:
            context.reporter.diagnostic(diagnostic)
            warnings += 1
    _progress(context, summary, done=6, total=6, warnings=warnings)
    if errors:
        raise ExternalError(errors)


def _remote(
    context: ExecutionContext,
    ssh: tuple[str, ...],
    script: str,
    timeout_s: float,
    stage: str,
) -> str:
    """只识别封闭协议，子进程输出不写作业日志，取消由既有边界回收 SSH 进程组。"""
    robot_id = ConnectionParameters.model_validate(context.parameters).robot_id
    try:
        result = run((*ssh, "bash", "-s"), timeout_s, context, stdin=script.encode())
    except (OSError, subprocess.SubprocessError) as error:
        raise ExternalError(
            (
                _diagnostic(
                    robot_id,
                    stage,
                    "SSH 失败或执行超过本段期限",
                    "检查机器人连接；预览程序可能还在机器人上运行",
                ),
            )
        ) from error
    context.reporter.tool_exit(result.returncode)
    output = result.stdout.decode("utf-8", errors="replace").strip()
    reasons = {
        "port_in_use": (
            "预览端口被占用",
            f"机器人上 {PREVIEW_CHANNELS['port']} 端口被别的程序占用；平台不会去停它，先查是谁在用",
        ),
        "python_version": (
            "机器人没有 Python 3.10 以上",
            "确认机器人 Python 版本后重试；平台不修改系统 Python",
        ),
        "xml_format": (
            "厂商 XML 和预期的格式不同",
            "核对厂商 XML 中的 address 格式，平台不修改厂商文件",
        ),
        "checksum": ("机器人收到的 wheel sha256 不符", "重新核对工作站离线 wheel"),
        "lock_busy": ("预览启停锁等待超过 5 秒", "等待另一项预览操作结束后重试"),
    }
    allowed = {
        "RDP_CONTROL installed",
        "RDP_CONTROL started",
        "RDP_CONTROL running",
        "RDP_CONTROL old_package",
        "RDP_CONTROL stopped",
        "RDP_CONTROL absent",
    }
    if result.returncode == 0 and (output in allowed or output.startswith("RDP_QUERY ")):
        return output
    code = output.removeprefix("RDP_CONTROL_ERROR ")
    actual, next_step = reasons.get(code, ("预览操作失败", "看机器人上 ~/rdp_viz/log/relay.log"))
    if code in (
        "config_invalid",
        "import_failed",
        "ros_init_failed",
        "ready_timeout",
        "self_test_failed",
        "install_failed",
    ):
        actual += "：" + code
        if stage == "安装":
            log = "install.log" if code == "install_failed" else "self-test.log"
            next_step = "看机器人上 ~/rdp_viz/log/" + log
    raise ExternalError((_diagnostic(robot_id, stage, actual, next_step),))


def _progress(
    context: ExecutionContext, name: str, *, done: int, total: int, warnings: int = 0
) -> None:
    """延续连接层的累计计数；后续异常由执行器中止，不能伪装部分成功。"""
    context.reporter.report(
        JobProgress(
            stage_index=1,
            stage_count=1,
            stage_name=name,
            done=done,
            total=total,
            unit="项",
            total_items=done,
            failed_items=0,
            warning_count=warnings,
        )
    )


def _diagnostic(
    robot_id: int,
    stage: str,
    actual: str,
    next_step: str,
    *,
    category: DiagnosticCategory = DiagnosticCategory.EXTERNAL,
) -> Diagnostic:
    """固定五段诊断仅带机器人编号和安全结果，不带凭据或原始 SSH 内容。"""
    return Diagnostic(
        level=DiagnosticLevel.ERROR,
        category=category,
        stage=stage,
        source="平台",
        objects=(DiagnosticObject(key="robot_id", value=str(robot_id)),),
        rule="robot_preview." + stage,
        actual=actual,
        expected="在专用用户目录安装并按人工指令启停预览",
        consequence="停止失败；预览程序可能还在机器人上运行"
        if stage == "停止"
        else "本次预览操作失败",
        next_step=next_step,
    )
