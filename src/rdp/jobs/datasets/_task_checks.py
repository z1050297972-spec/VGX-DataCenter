"""子任务跨视图子集核对；仅比较导航声明，不执行子任务功能或查询任何引用路径。"""

from rdp.jobs.datasets import _json
from rdp.jobs.datasets._panel_issue import difference
from rdp.jobs.datasets.panel import NavigationRule
from rdp.jobs.datasets.types import EntrySnapshot, Finding, JsonObject, JsonValue, PanelGroup


def compare(
    entry: EntrySnapshot,
    original: JsonObject,
    current: JsonObject,
    canonical_ids: frozenset[str] | None,
) -> tuple[Finding, ...]:
    """task_key只在当前数据集内配对，不把跨数据集同名任务当成重复编号。"""
    from rdp.jobs.datasets._view_checks import comparable_content

    try:
        known = {
            str(item["task_key"]): item for item in _json.objects(original.get("tasks"), "tasks")
        }
        tasks = _json.objects(current.get("tasks"), "tasks")
        result: list[Finding] = []
        seen: set[str] = set()
        for task in tasks:
            identity = _json.text(task.get("task_key"), "task_key")
            if identity not in known:
                result.append(
                    difference(
                        entry,
                        NavigationRule.TASK_SUBSET_MISMATCH,
                        ("tasks.task_key", identity, "规范副本已有的任务编号"),
                        group=PanelGroup.VIEWS,
                    )
                )
            elif identity in seen or comparable_content(task) != comparable_content(
                _selected_task(entry, known[identity], canonical_ids)
            ):
                result.append(
                    difference(
                        entry,
                        NavigationRule.TASK_CONTENT_MISMATCH,
                        (
                            "tasks." + identity,
                            "非位置字段不同或任务编号重复",
                            "同一任务内容一致且编号唯一",
                        ),
                        group=PanelGroup.VIEWS,
                    )
                )
            seen.add(identity)
        return tuple(result)
    except (ValueError, KeyError):
        return (
            difference(
                entry,
                NavigationRule.TASK_CONTENT_MISMATCH,
                ("tasks", "任务结构无法按编号比较", "tasks为带task_key的对象数组"),
                group=PanelGroup.VIEWS,
            ),
        )


def _selected_task(
    entry: EntrySnapshot, task: JsonObject, canonical_ids: frozenset[str] | None
) -> JsonObject:
    """按格式入选块筛规范任务引用；跨数据集引用仍保留，来源文件不可用时不猜筛选范围。"""
    allowed = {source.source_id for source in entry.sources}
    manifest = next(doc.payload for doc in entry.documents if doc.name == "原始路径.json")
    if manifest is None or canonical_ids is None:
        return task
    selected: list[JsonValue] = [
        source
        for source in _json.objects(task.get("sources"), "tasks.sources")
        if str(source.get("source_id")) in allowed
        or str(source.get("source_id")) not in canonical_ids
    ]
    result: JsonObject = dict(task)
    result["sources"] = selected
    return result
