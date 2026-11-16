"""M4.6-02 离线工具参数契约；仅构造命令，不执行工具或解释器。"""

from pathlib import Path

from rdp.jobs.conversion.lerobot import environment_argv
from rdp.jobs.tool_environment import offline_tool_argv


def test_offline_tool_argv(tmp_path: Path) -> None:
    """验收4：环境前缀精确匹配离线约定，带空格的命令参数原样保留。"""
    argv = ("/tool/bin/agibot2lerobot", "--config", "with spaces.toml")
    assert offline_tool_argv(tmp_path, argv) == (
        "/usr/bin/env",
        "HF_HUB_OFFLINE=1",
        "PYTHONDONTWRITEBYTECODE=1",
        f"HF_HOME={tmp_path}/hf-home",
        *argv,
    )
    assert not (tmp_path / "hf-home").exists()


def test_lerobot_environment_keeps_isolated_interpreter_flags(tmp_path: Path) -> None:
    """验收4：LeRobot 复用环境包装后仍带 -I 和 -B，保留原有隔离及禁止 pyc 行为。"""
    assert environment_argv(Path("/tool/python"), tmp_path, ("-c", "pass")) == (
        "/usr/bin/env",
        "HF_HUB_OFFLINE=1",
        "PYTHONDONTWRITEBYTECODE=1",
        f"HF_HOME={tmp_path}/hf-home",
        "/tool/python",
        "-I",
        "-B",
        "-c",
        "pass",
    )
