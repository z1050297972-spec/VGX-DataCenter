"""以真实 G2 CLI 报告为基准验证适配器；损坏用例只修改要拒绝的字段。"""

# ruff: noqa: S101  # 理由：显式手动验收用断言核对结果，不作为生产输入校验。

import copy
import json
import subprocess
from pathlib import Path
from typing import Any

import pytest
from _g2_real_support import TOOL, archives

from rdp.infra.diagnostics import ExternalError
from rdp.jobs.cleaning._agibot import load_snapshot
from rdp.jobs.cleaning._g2 import read_report


def test_real_cli_summary_and_strict_result_validation(tmp_path: Path) -> None:
    """事件只含路径计数；真实结果可映射，错误路径/配置/空元信息/负数/重复集/未知字段均拒绝。

    Args:
        tmp_path: 本次演练的临时目录或导航夹具。

    Returns:
        验收结果；测试函数无返回值。

    Raises:
        AssertionError: 真实 CLI、报告、产物或平台行为不满足验收契约。

    Side Effects:
        仅在演练临时目录写输入、报告、DB 和产物，调用真实工具。

    Time Semantics:
        按同步作业顺序运行，工具超时沿用平台受管进程预算。
    """
    paths = archives(tmp_path / "input")
    config = Path(__file__).parents[2] / "tools/agibot2lerobot-g2/configs/agibot_g2.toml"
    rules = config.parent.parent / "cleaning/agibot_g2.toml"
    result = tmp_path / "result.json"
    process = subprocess.run(  # noqa: S603  # 理由：固定真实 CLI，仅消费临时归档并写临时报告。
        [
            str(TOOL / "bin/agibot2lerobot-g2"),
            "--events",
            "-",
            "preview",
            "--report-only",
            "-c",
            str(config),
            "--rules",
            str(rules),
            "--result",
            str(result),
            *map(str, paths),
        ],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert process.returncode == 0, process.stderr
    event = json.loads(process.stdout.splitlines()[-1])
    assert event["ok"] and event["result"] == {
        "report_file": str(result),
        "archives": 2,
        "episodes": 4,
        "archives_with_problems": 0,
        "episodes_with_problems": 1,
        "issues": 0,
    }
    raw: dict[str, Any] = json.loads(result.read_text())
    sources = tuple((str(index), path) for index, path in enumerate(paths))
    snapshot = load_snapshot(config, rules)
    report = read_report(result, sources, snapshot, (config, "0.1.0"), lambda: None)
    assert report.episodes[0].fatal_issues
    for change in (
        "path",
        "config",
        "missing_metadata",
        "negative_frames",
        "duplicate",
        "bool_index",
        "unknown",
    ):
        corrupted = copy.deepcopy(raw)
        _corrupt(corrupted, change)
        result.write_text(json.dumps(corrupted))
        with pytest.raises(ExternalError):
            read_report(result, sources, snapshot, (config, "0.1.0"), lambda: None)


def _corrupt(raw: dict[str, Any], change: str) -> None:
    """单一字段损坏用于检验拒绝路径，不改写任何成功路径的 CLI 报告。"""
    if change == "path":
        raw["archives"][0]["path"] = "/not-selected.tar.gz"
    elif change == "config":
        raw["config_sha256"] = "0" * 64
    elif change == "missing_metadata":
        raw["archives"][0]["mtime_ns"] = None
    elif change == "negative_frames":
        raw["archives"][0]["episodes"][0]["frames"] = -1
    elif change == "duplicate":
        raw["archives"][0]["episodes"].append(raw["archives"][0]["episodes"][0])
    elif change == "bool_index":
        raw["archives"][0]["episodes"][0]["episode_index"] = True
    else:
        raw["archives"][0]["unexpected"] = 1
