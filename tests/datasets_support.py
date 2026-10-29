"""数据集测试的公共输入，只用临时导航和明确的公开接口。"""

import json
from collections.abc import Callable
from pathlib import Path, PurePosixPath
from typing import Any

from nav_manifest import FakeNavigation

from rdp.jobs.datasets.reading import discover_entries, parse_document
from rdp.jobs.datasets.types import EntryLocation, JsonDocument, View

LOCATION = EntryLocation(PurePosixPath("按任务/example"), View.TASK, None, None, "example")


def document(data: dict[str, Any], name: str = "子任务.json") -> JsonDocument:
    """从独立的JSON输入调用公开解析接口，不生成期望结果。"""
    return parse_document(LOCATION, name, json.dumps(data, ensure_ascii=False).encode())


def checkpoint() -> None:
    """无取消请求的同步检查点，不访问真实时钟或部署。"""


def edit_json(path: Path, change: Callable[[dict[str, Any]], None]) -> None:
    """只改测试临时JSON，原始样本和其他测试输入保持独立。"""
    data = json.loads(path.read_text())
    change(data)
    path.write_text(json.dumps(data, ensure_ascii=False))


def location(nav: FakeNavigation) -> EntryLocation:
    """通过公开目录发现选取固定libero样本，不访问规划文件。"""
    return next(
        item
        for item in discover_entries(nav.nav_root).entries
        if item.dataset_name == "libero_10" and item.view is View.TASK
    )


def fingerprint(nav: FakeNavigation):
    """固定数据集的公开指纹调用，期望变化由各测试独立变更输入决定。"""
    from rdp.jobs.datasets.fingerprint import fingerprint_dataset

    return fingerprint_dataset(
        nav.nav_root, "dataset-14", known_entry_paths=(), checkpoint=checkpoint
    )
