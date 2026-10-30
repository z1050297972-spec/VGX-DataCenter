"""编辑计划的差异投影（M1.5-02）；由实际文件前后像生成，包含副本重建，不重新决定写入。

标准库 JSON 保持字段顺序；只列有界样例但计数完整，避免大子任务报告撑满页面。
"""

import json
from collections.abc import Callable, Iterator

from rdp.jobs.datasets.types import JsonValue
from rdp.jobs.navwrite.models import ListedChange, WriteFileStep
from rdp.jobs.navwrite.policy import PREVIEW_LISTED_CHANGE_LIMIT

# 差异正文是预览片段；大说明只展示前4096码点，完整内容保存在同一计划后像中。
_MAX_FRAGMENT_CHARS = 4096


def differences(
    steps: list[WriteFileStep], originals: dict[str, bytes], checkpoint: Callable[[], None]
) -> tuple[tuple[ListedChange, ...], int]:
    """比较计划中真正要写的前后像，递归保留字段顺序和完整计数。"""
    listed: list[ListedChange] = []
    total = 0
    for step in steps:
        before: JsonValue = json.loads(originals[step.path])
        after: JsonValue = json.loads(step.after_content)
        for path, old, new in _walk(before, after, (), checkpoint):
            total += 1
            if len(listed) < PREVIEW_LISTED_CHANGE_LIMIT:
                listed.append(
                    ListedChange(
                        file=step.path,
                        json_path="/".join(map(str, path)),
                        before=_fragment(old),
                        after=_fragment(new),
                    )
                )
    return tuple(listed), total


def _walk(
    before: JsonValue, after: JsonValue, path: tuple[str | int, ...], checkpoint: Callable[[], None]
) -> Iterator[tuple[tuple[str | int, ...], JsonValue, JsonValue]]:
    """对象递归到字段；文字数组按字段整体比较，保留多选顺序。"""
    checkpoint()
    if before == after:
        return
    if isinstance(before, dict) and isinstance(after, dict):
        for key in dict.fromkeys((*before, *after)):
            # 缺失与显式null必须区分，否则L10补写version:null会从预览中消失。
            yield from _walk(
                before.get(key, "（字段不存在）"),
                after.get(key, "（字段不存在）"),
                (*path, key),
                checkpoint,
            )
    elif (
        isinstance(before, list)
        and isinstance(after, list)
        and any(isinstance(item, dict) for item in (*before, *after))
    ):
        for index in range(max(len(before), len(after))):
            yield from _walk(
                before[index] if index < len(before) else None,
                after[index] if index < len(after) else None,
                (*path, index),
                checkpoint,
            )
    else:
        yield path, before, after


def _fragment(value: JsonValue) -> str:
    """保留JSON类型；截取时明确提示，不能把片段冒充完整值。"""
    text = json.dumps(value, ensure_ascii=False)
    return (
        text
        if len(text) <= _MAX_FRAGMENT_CHARS
        else text[:_MAX_FRAGMENT_CHARS] + "…（预览片段已截取）"
    )
