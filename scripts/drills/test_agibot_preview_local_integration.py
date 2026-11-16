"""显式启用的真实工具契约验证；只读本机缓存样本，结果和缓存仅写 pytest 临时目录。

只允许手动用项目 Python 的 -I -B 模式启动 pytest，显式传入本文件。
普通检查不访问工具目录或样本；不下载数据、不安装依赖、不访问真实数据盘。
"""

import json
import os
import subprocess
from pathlib import Path
from typing import cast

import pytest
from agibot_alpha_support import SAMPLE_ROOT as _SAMPLE_ROOT
from agibot_alpha_support import TOOL_ROOT as _TOOL_ROOT
from agibot_alpha_support import check_sample_boundary, require

from rdp.jobs.cleaning._agibot import load_snapshot, read_report

# 两集本地样本的工具体检需要启动进程池，给五分钟上限，不使用无限等待。
_TOOL_TIMEOUT_S = 300


def _run_tool(tmp_path: Path, *, unannotated: bool) -> Path:
    """用真实 CLI 写结果；-I 隔离环境路径，-B 阻止在只读工具目录生成字节码。"""
    check_sample_boundary()
    launcher = tmp_path / "launch_preview.py"
    # -I 忽略 PYTHONPATH，因此只显式加入已授权的工具包；main guard 允许真实 spawn 进程池。
    launcher.write_text(
        "import runpy, sys\n"
        f"sys.path.insert(0, {str(_TOOL_ROOT)!r})\n"
        'if __name__ == "__main__":\n'
        '    runpy.run_module("agibot2lerobot", run_name="__main__")\n'
    )
    source_args = ["--task-dir", str(_SAMPLE_ROOT / "observations/327")]
    if unannotated:
        # 仅复制标注到临时目录并保留一集，观测和 h5 仍只读 src；不用越界的目录软链接。
        rows = cast(
            list[dict[str, object]],
            json.loads((_SAMPLE_ROOT / "task_info/task_327.json").read_text()),
        )
        metadata = tmp_path / "metadata/task_info"
        metadata.mkdir(parents=True)
        (metadata / "task_327.json").write_text(
            json.dumps([row for row in rows if str(row["episode_id"]) == "649806"])
        )
        source_args = [
            "--raw-root",
            str(metadata.parent),
            "--task-id",
            "327",
            "--extracted-root",
            str(_SAMPLE_ROOT),
        ]
    result = tmp_path / "preview.json"
    command = [
        str(_TOOL_ROOT / ".venv/bin/python"),
        "-I",
        "-B",
        str(launcher),
        "--events",
        "/dev/stderr",
        "preview",
        *source_args,
        "-c",
        str(_TOOL_ROOT / "configs/agibot_g1.toml"),
        "--rules",
        str(_TOOL_ROOT / "configs/agibot_g1.cleaning.toml"),
        "--index-cache",
        str(tmp_path / "index-cache"),
        "--result",
        str(result),
        "--no-archive-proprio",
        "--workers",
        "1",
    ]
    completed = subprocess.run(  # noqa: S603  # 理由：固定已授权工具、隔离解释器和本地样本参数，不经 shell。
        command,
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
        timeout=_TOOL_TIMEOUT_S,
        env=os.environ | {"HF_HUB_OFFLINE": "1", "HF_HOME": str(tmp_path / "hf-home")},
    )
    require(completed.returncode == 0, completed.stderr)
    return result


@pytest.mark.parametrize("unannotated", [False, True], ids=["local-sample", "unannotated-episode"])
def test_real_tool_result_roundtrip(tmp_path: Path, unannotated: bool) -> None:
    """真实工具 JSON 原样通过平台解析，包括数字字符串 ID 和未标注集的 null。

    Args:
        tmp_path: pytest 创建的本次独占临时目录。
        unannotated: 为真时仅在临时标注副本中删除一集标注。

    Returns:
        无；结果通过断言检查。

    Raises:
        AssertionError: 路径越界、工具失败或解析结果违反真实样本契约。
        TimeoutExpired: 工具运行超过 300 秒。

    Side Effects:
        只读授权的工具和本地样本；报告、标注副本和缓存仅写临时目录。

    Time Semantics:
        手动即时验证；每个场景至多等待工具 300 秒，不重试。
    """
    result = _run_tool(tmp_path, unannotated=unannotated)
    payload = cast(dict[str, object], json.loads(result.read_text()))
    require(payload["task_id"] == "327", "真实任务 ID 必须是数字字符串")
    snapshot = load_snapshot(
        _TOOL_ROOT / "configs/agibot_g1.toml", _TOOL_ROOT / "configs/agibot_g1.cleaning.toml"
    )
    report = read_report(
        result, ("local-sample", _SAMPLE_ROOT / "observations/327"), snapshot, lambda: None
    )
    require(report.source_format == "agibot_native", "源格式不匹配")
    require(report.fps == 30, "样本帧率不匹配")
    require(report.summary.episodes == (1 if unannotated else 2), "可转集数不匹配")
    require(report.summary.kept_frames == (910 if unannotated else 1826), "帧数不匹配")
    if unannotated:
        episodes = cast(list[dict[str, object]], payload["episodes"])
        require(
            next(row for row in episodes if row["episode_id"] == "650435")["task"] is None,
            "未标注集 task 应为 null",
        )
        file = next(file for file in report.files if file.episode_id == "650435")
        require(file.default_excluded, "未标注集应默认剔除")
        require(any("task_info" in issue.actual for issue in file.fatal_issues), "应解释标注缺失")
        require(
            all(episode.file_index != file.file_index for episode in report.episodes),
            "不可转集不能有段",
        )
