"""跨视图②组及规范入口唯一性；按数据集局部身份比较，不扫描存储路径。"""

from collections import Counter

from rdp.infra.diagnostics import DefectError
from rdp.jobs.datasets import _json, _task_checks
from rdp.jobs.datasets._panel_issue import difference
from rdp.jobs.datasets.panel import NavigationRule
from rdp.jobs.datasets.types import EntrySnapshot, Finding, JsonObject, JsonValue, PanelGroup, View


def check(entries: tuple[EntrySnapshot, ...]) -> tuple[Finding, ...]:
    """先确定规范副本是否存在，不能用一个格式切片冒充完整数据集。"""
    if (
        len({str(entry.location.path) for entry in entries}) != len(entries)
        or len({entry.dataset_id for entry in entries}) > 1
    ):
        raise DefectError()
    if not entries or entries[0].dataset_id is None:
        # 身份不可识别时无法证明另一视图缺失，读取层已经报告该文件的问题。
        return ()
    canonical = [entry for entry in entries if entry.location.view is View.TASK]
    if not canonical:
        return tuple(
            difference(
                entry,
                NavigationRule.CANONICAL_MISSING,
                ("按任务入口", "只有按格式入口", "同编号存在按任务入口"),
            )
            for entry in entries
        )
    if len(canonical) > 1:
        paths = tuple(str(entry.location.path) for entry in canonical)
        return tuple(
            difference(
                entry,
                NavigationRule.DUPLICATE_TASK_ID,
                ("dataset_id", paths, "同一编号恰有一个规范入口"),
            )
            for entry in canonical[1:]
        )
    reference = canonical[0]
    issues = (
        _duplicate_sources(reference)
        + _duplicate_tasks(reference)
        + tuple(
            issue
            for entry in entries
            if entry.location.view is View.FORMAT
            for issue in _compare(reference, entry)
        )
    )
    return tuple(
        sorted(
            issues,
            key=lambda item: (
                item.diagnostic.rule,
                item.diagnostic.objects[0].value,
                item.diagnostic.objects[-1].value,
            ),
        )
    )


def _payload(entry: EntrySnapshot, name: str) -> JsonObject | None:
    """文件不可用以None传递，不能用空对象制造跨视图一致或连锁差异。"""
    return next(doc.payload for doc in entry.documents if doc.name == name)


def _compare(canonical: EntrySnapshot, entry: EntrySnapshot) -> tuple[Finding, ...]:
    """信息正文按对象内容比较，键序不重要，Markdown原文和数组顺序保留。"""
    issues: list[Finding] = []
    original = _payload(canonical, "数据集信息.json")
    current = _payload(entry, "数据集信息.json")
    if original is not None and current is not None:
        left = original | {"schema_version": original.get("schema_version", 1)}
        right = current | {"schema_version": current.get("schema_version", 1)}
        if left != right:
            issues.append(
                difference(
                    entry,
                    NavigationRule.INFORMATION_MISMATCH,
                    ("数据集信息.json", "与规范副本内容不同", "与规范副本一致"),
                    group=PanelGroup.VIEWS,
                )
            )
    original_manifest = _payload(canonical, "原始路径.json")
    current_manifest = _payload(entry, "原始路径.json")
    if original_manifest is not None and current_manifest is not None:
        for field in ("dataset_name", "dataset_roots"):
            if original_manifest[field] != current_manifest[field]:
                issues.append(
                    difference(
                        entry,
                        NavigationRule.DATASET_HEADER_MISMATCH,
                        (
                            "原始路径.json." + field,
                            current_manifest[field],
                            original_manifest[field],
                        ),
                        group=PanelGroup.VIEWS,
                    )
                )
        issues.extend(_sources(entry, original_manifest, current_manifest))
    original_tasks = _payload(canonical, "子任务.json")
    current_tasks = _payload(entry, "子任务.json")
    if original_tasks is not None and current_tasks is not None:
        canonical_ids = (
            frozenset(source.source_id for source in canonical.sources)
            if original_manifest is not None
            else None
        )
        issues.extend(_task_checks.compare(entry, original_tasks, current_tasks, canonical_ids))
    return tuple(issues)


def _sources(
    entry: EntrySnapshot, original: JsonObject, current: JsonObject
) -> tuple[Finding, ...]:
    """格式入口的数据块只能引用规范副本的source_id，允许规范副本有更多数据块。"""
    original_items = _json.objects(original["sources"], "sources")
    known = {str(item["source_id"]): item for item in original_items}
    result: list[Finding] = []
    seen: set[str] = set()
    for item in _json.objects(current["sources"], "sources"):
        identity = str(item["source_id"])
        if identity not in known:
            result.append(
                difference(
                    entry,
                    NavigationRule.SOURCE_SUBSET_MISMATCH,
                    ("sources.source_id", identity, "规范副本登记的数据块编号"),
                    group=PanelGroup.VIEWS,
                )
            )
        elif identity in seen or comparable_content(item) != comparable_content(known[identity]):
            result.append(
                difference(
                    entry,
                    NavigationRule.SOURCE_CONTENT_MISMATCH,
                    ("sources." + identity, "非位置字段不同或编号重复", "同一编号内容一致且不重复"),
                    group=PanelGroup.VIEWS,
                )
            )
        seen.add(identity)
    return tuple(result)


def comparable_content(value: JsonValue) -> JsonValue:
    """只排除位置路径，递归保留未知内容；省略version等价于null，不忽略数据块格式。"""
    if isinstance(value, dict):
        return {
            key: comparable_content(item) for key, item in value.items() if key != "entry_path"
        } | {"version": comparable_content(value.get("version"))}
    if isinstance(value, list):
        return [comparable_content(item) for item in value]
    return value


def _duplicate_sources(entry: EntrySnapshot) -> tuple[Finding, ...]:
    """规范副本也必须保持永久编号唯一，不能以字典最后一项冒充唯一事实。"""
    counts = Counter(source.source_id for source in entry.sources)
    return tuple(
        difference(
            entry,
            NavigationRule.SOURCE_CONTENT_MISMATCH,
            ("sources." + identity, f"同编号登记{count}次", "每个source_id登记一次"),
            group=PanelGroup.VIEWS,
        )
        for identity, count in sorted(counts.items())
        if count > 1
    )


def _duplicate_tasks(entry: EntrySnapshot) -> tuple[Finding, ...]:
    """规范入口task_key重复时报告原对象，不让配对字典静默覆盖其中一项。"""
    payload = _payload(entry, "子任务.json")
    if payload is None:
        return ()
    try:
        tasks = _json.objects(payload.get("tasks"), "tasks")
    except ValueError:
        return ()
    counts = Counter(
        str(task["task_key"]) for task in tasks if isinstance(task.get("task_key"), str)
    )
    return tuple(
        difference(
            entry,
            NavigationRule.TASK_CONTENT_MISMATCH,
            ("tasks." + identity, f"同编号登记{count}次", "本数据集每个task_key登记一次"),
            group=PanelGroup.VIEWS,
        )
        for identity, count in sorted(counts.items())
        if count > 1
    )
