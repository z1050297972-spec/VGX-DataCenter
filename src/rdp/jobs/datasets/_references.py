"""③组引用提取（领域层，11 Q14），只解释路径字段与Markdown链接，不解析14项指标。"""

import re
from collections.abc import Iterator
from dataclasses import dataclass

from rdp.jobs.datasets.types import EntrySnapshot, JsonValue

# 历史正文采用](<绝对路径>)，同时接受无空白的普通Markdown本地链接；不取展示文字。
_LOCAL_LINK = re.compile(r"\]\((?:<(/[^>]+)>|(/[^\s)]+))\)")


@dataclass(frozen=True)
class Reference:
    """一个需要存在性检查的引用。

    Attributes:
        field: JSON中的字段位置，用于诊断对象。
        path: 原始绝对路径文本，不访问、不展开用户目录。
        rule: 失效时的稳定规则码。
        notice: True表示提示；False表示需要处理。
    """

    field: str
    path: str
    rule: str
    notice: bool = True


def references(entry: EntrySnapshot) -> Iterator[Reference]:
    """只提取契约要求的引用；original_path及其他自由文本不作路径推断。"""
    for ordinal, path in enumerate(entry.dataset_roots):
        yield Reference(f"dataset_roots[{ordinal}]", path, "DATASET_ROOT_MISSING", False)
    for document in entry.documents:
        data = document.payload
        if data is None:
            continue
        yield from _document_references(document.name, data)


def _document_references(name: str, data: dict[str, JsonValue]) -> Iterator[Reference]:
    """按文件职责选取引用，避免把普通未知字段当成路径。"""
    if name == "数据集信息.json":
        yield from _information(data)
        return
    field, rule = (
        ("excluded_from_navigation", "EXCLUDED_PATH_MISSING")
        if name == "原始路径.json"
        else ("子任务", "TASK_REFERENCE_MISSING")
    )
    for location, value in _strings(data if name == "子任务.json" else data.get(field), field):
        if value.startswith("/"):
            yield Reference(location, value, rule)


def _strings(value: JsonValue, field: str) -> Iterator[tuple[str, str]]:
    """顺序遍历有限JSON树，跳过首次登记路径，不把数字拼成路径。"""
    if isinstance(value, str):
        yield field, value
    elif isinstance(value, list):
        for ordinal, child in enumerate(value):
            yield from _strings(child, f"{field}[{ordinal}]")
    elif isinstance(value, dict):
        for key, child in value.items():
            if key != "original_path":
                yield from _strings(child, f"{field}.{key}")


def _information(data: dict[str, JsonValue]) -> Iterator[Reference]:
    """只检查summary_path和14项中的本地链接；外网URL不访问。"""
    summary = data.get("summary_path")
    if isinstance(summary, str) and summary.startswith("/"):
        yield Reference("summary_path", summary, "SUMMARY_PATH_MISSING")
    for field, value in _strings(data.get("fields"), "fields"):
        if field.endswith(".value_markdown"):
            for match in _LOCAL_LINK.finditer(value):
                yield Reference(field, match[1] or match[2], "MARKDOWN_REFERENCE_MISSING")
