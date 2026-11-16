"""以真实 G2 CLI 报告为基准验证适配器；损坏用例只修改要拒绝的字段。"""

import copy
import json
from pathlib import Path
from typing import Any

import pytest
from g2_platform_support import archives, report_payload

from rdp.infra.diagnostics import ExternalError
from rdp.jobs.cleaning._agibot import load_snapshot
from rdp.jobs.cleaning._g2 import read_report


def test_fixed_cli_report_and_strict_result_validation(tmp_path: Path) -> None:
    """固定真实格式报告可映射；错误路径、配置、空元信息、负数、重复集和未知字段均拒绝。"""
    paths = archives(tmp_path / "input")
    config = Path(__file__).parents[1] / "tools/agibot2lerobot-g2/configs/agibot_g2.toml"
    rules = config.parent.parent / "cleaning/agibot_g2.toml"
    result = tmp_path / "result.json"
    raw = report_payload(paths, config)
    result.write_text(json.dumps(raw))
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
