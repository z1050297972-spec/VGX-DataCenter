"""M4.5 LeRobot 环境登记与只读探测；复用 bwrap 和有界进程，不导入真实 LeRobot。

指纹使用平台解释器和 hashlib/tomllib；源码读取也在有界子进程内，不扫描数据集。
"""

import json
import subprocess
import sys
import tomllib
from collections.abc import Callable
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from rdp.infra.config import ToolsConfig
from rdp.jobs.conversion._process import run_bounded
from rdp.jobs.sandbox import SandboxSpec, sandbox_argv

# 探测只导入顶层包并读版本，15 秒是列表请求和执行前共用的有界预算。
PROBE_TIMEOUT_S = 15.0
# 独立于 tools 登记包，避免被枚举为转换工具。
ENV_DIRECTORY = Path(__file__).resolve().parents[4] / "envs/lerobot"
_PROBE = """import importlib.metadata, json, pathlib, sys
import lerobot
value = {"version": importlib.metadata.version("lerobot"), "package": str(pathlib.Path(lerobot.__file__).resolve().parent)}
pathlib.Path(sys.argv[1]).write_text(json.dumps(value))
print(json.dumps(value))
"""


class _Registration(BaseModel):
    """登记文件只认可版本一与工单规定的指纹范围。"""

    schema_version: Literal[1]
    version: str
    fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    fingerprint_scope: tuple[Literal["configs", "datasets", "utils"], ...]


class LeRobotEnvironment(BaseModel):
    """请求时的环境状态；未配置或失败时实际值为 null，失败不拖垮工具列表。"""

    model_config = ConfigDict(frozen=True)
    status: Literal["unconfigured", "available", "mismatch", "error"]
    expected_version: str
    actual_version: str | None = None
    expected_fingerprint: str
    actual_fingerprint: str | None = None
    message: str | None = None


def inspect_environment(
    settings: ToolsConfig,
    *,
    run: Callable[[tuple[str, ...], Path], None] | None = None,
    directory: Path | None = None,
    temporary_parent: Path | None = None,
) -> LeRobotEnvironment:
    """探测实际导入的 LeRobot 并核对已登记版本和源码指纹。

    Args:
        settings: 配置的绝对解释器路径；None 表示未配置。
        run: worker 的受管执行边界，接收命令和工作目录；None 使用列表请求的只读沙箱。
        temporary_parent: worker 的作业暂存目录；None 使用系统临时目录。
        directory: 平台登记绝对目录；None 使用随部署的 envs/lerobot，测试仅临时目录。

    Returns:
        四种状态之一，包含期望及实际版本、指纹；错误说明保留在 message。

    Raises:
        JobCancelledError: worker 检查点取消，原样传播。
        WorkerStoppingError: worker 停止，原样传播。
        ExternalError: worker 受管进程启动、超时或回收失败，原样传播。

    Side Effects:
        配置时运行只读、断网解释器，在私有临时目录写探测 JSON；退出清理该目录。
        平台读取包源码计算指纹，不安装包或修改环境。

    Time Semantics:
        每次调用重新探测；解释器探测与平台源码哈希各至多 15 秒，合计至多 30 秒，另计框架回收预算。
    """
    expected_version = "0.6.2"
    expected_fingerprint = ""
    try:
        registration = _Registration.model_validate(
            tomllib.loads(((directory or ENV_DIRECTORY) / "env.toml").read_text())
        )
        expected_version, expected_fingerprint = registration.version, registration.fingerprint
        if settings.lerobot_python is None:
            return LeRobotEnvironment(
                status="unconfigured",
                expected_version=expected_version,
                expected_fingerprint=expected_fingerprint,
                message="未配置 LeRobot 环境",
            )
        with TemporaryDirectory(prefix="rdp-lerobot-", dir=temporary_parent) as temporary:
            scratch = Path(temporary)
            target = scratch / "probe.json"
            command = environment_argv(
                settings.lerobot_python, scratch, ("-c", _PROBE, str(target))
            )
            commands = (
                command,
                environment_argv(
                    Path(sys.executable),
                    scratch,
                    (
                        str(Path(__file__).with_name("_lerobot_fingerprint.py")),
                        str(target),
                        *registration.fingerprint_scope,
                    ),
                ),
            )
            for command in commands:
                _run_probe(command, scratch, run)
            probe = json.loads(target.read_text())
            actual_version = str(probe["version"])
            fingerprint = str(probe["fingerprint"])
        matches = actual_version == expected_version and fingerprint == expected_fingerprint
        return LeRobotEnvironment(
            status="available" if matches else "mismatch",
            expected_version=expected_version,
            actual_version=actual_version,
            expected_fingerprint=expected_fingerprint,
            actual_fingerprint=fingerprint,
            message=None if matches else "LeRobot 环境已变化，需要重新登记",
        )
    except (OSError, ValueError, KeyError, subprocess.TimeoutExpired) as error:
        return LeRobotEnvironment(
            status="error",
            expected_version=expected_version,
            expected_fingerprint=expected_fingerprint,
            message=f"LeRobot 环境探测失败：{error}",
        )


def environment_argv(python: Path, scratch: Path, arguments: tuple[str, ...]) -> tuple[str, ...]:
    """为 LeRobot 构造隔离解释器与离线缓存环境。

    Args:
        python: 部署登记的绝对解释器路径。
        scratch: 本次执行的私有可写目录，绝对路径。
        arguments: 探测代码或平台脚本参数，不经 shell。

    Returns:
        env、解释器和参数元组；调用方必须再包入 bwrap。

    Raises:
        无。

    Side Effects:
        无；只构造参数，不创建缓存目录。

    Time Semantics:
        无时钟依赖，超时由调用方受管进程提供。
    """
    # -I 会忽略 PYTHON* 环境变量，额外 -B 才能真正禁止写 pyc。
    return (
        "/usr/bin/env",
        "HF_HUB_OFFLINE=1",
        "PYTHONDONTWRITEBYTECODE=1",
        f"HF_HOME={scratch / 'hf-home'}",
        str(python),
        "-I",
        "-B",
        *arguments,
    )


def _run_probe(
    command: tuple[str, ...], scratch: Path, run: Callable[[tuple[str, ...], Path], None] | None
) -> None:
    """两次探测共用同一只读沙箱设置；worker 还共用取消与作业日志。"""
    if run is not None:
        run(command, scratch)
        return
    sandboxed = sandbox_argv(command, SandboxSpec((scratch,)), readonly_roots=())
    _, stderr, code = run_bounded(sandboxed, timeout_s=PROBE_TIMEOUT_S)
    if code:
        raise ValueError("LeRobot 探测失败：" + stderr.decode(errors="replace")[-4096:])
