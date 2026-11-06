"""真实视图与虚拟场景树的纯索引聚合，数量按永久编号去重、大小按入口求和。"""

from pathlib import PurePosixPath

from rdp.infra.db.validation import invalid_field
from rdp.jobs.dataset_browser._classification import scene_path
from rdp.jobs.dataset_browser.schemas import (
    DatasetListItem,
    DatasetTreeNode,
    EntrySummary,
    TreeSize,
)
from rdp.jobs.datasets import vocabulary
from rdp.jobs.datasets.types import View


def aggregate(entries: tuple[EntrySummary, ...]) -> TreeSize:
    """部分未知时只显示小计，不让None变成看似精确的总数。"""
    times = [
        entry.size.size_checked_at for entry in entries if entry.size.size_checked_at is not None
    ]
    count = {
        source: sum(entry.size.display_source == source for entry in entries)
        for source in ("measured", "recorded", "unknown")
    }
    total = sum(entry.size.display_bytes or 0 for entry in entries)
    return TreeSize(
        known_bytes=total,
        total_bytes=None if count["unknown"] else total,
        measured_entry_count=count["measured"],
        recorded_entry_count=count["recorded"],
        unknown_entry_count=count["unknown"],
        oldest_size_checked_at=min(times) if times else None,
        newest_size_checked_at=max(times) if times else None,
    )


def nodes(entries: tuple[EntrySummary, ...]) -> tuple[DatasetTreeNode, ...]:
    """父节点由完整路径分量构造，不通过文件系统补充空目录。"""
    groups: dict[str, list[EntrySummary]] = {"按任务": [], "按格式": []}
    leaves = {entry.entry_path: entry for entry in entries}
    for entry in entries:
        parts = PurePosixPath(entry.entry_path).parts
        for length in range(1, len(parts) + 1):
            groups.setdefault("/".join(parts[:length]), []).append(entry)
    result: list[DatasetTreeNode] = []
    for path, children in sorted(groups.items()):
        parts = PurePosixPath(path).parts
        if not parts:
            raise invalid_field("entry_path", "索引入口路径不得为空")
        leaf = leaves.get(path)
        view = View.TASK if parts[0] == "按任务" else View.FORMAT
        result.append(
            DatasetTreeNode(
                path=path,
                parent_path=str(PurePosixPath(path).parent) if len(parts) > 1 else None,
                name=PurePosixPath(path).name,
                kind="entry"
                if leaf
                else "view"
                if len(parts) == 1
                else "format"
                if len(parts) == 2
                else "version",
                view=view,
                format=children[0].format if children and len(parts) > 1 else None,
                version=children[0].version if children and len(parts) > 2 else None,
                dataset_id=leaf.dataset_id if leaf else None,
                entry_path=path if leaf else None,
                dataset_count=len(
                    {item.dataset_id for item in children if item.dataset_id is not None}
                ),
                entry_count=len(children),
                size=aggregate(tuple(children)),
            )
        )
    return tuple(result)


def scenes(
    items: tuple[DatasetListItem, ...], entries: tuple[EntrySummary, ...]
) -> tuple[DatasetTreeNode, ...]:
    """场景树每个数据集取唯一规范入口一次，避免格式副本重复计数；缺规范副本不伪造入口。"""
    selected = {entry.entry_path: entry for entry in entries}
    groups: dict[str, list[EntrySummary]] = {"按场景": []}
    names = {"按场景": "按场景"}
    leaves: dict[str, EntrySummary] = {}
    for item in items:
        entry = selected.get(item.canonical_entry_path or "")
        if entry is None:
            continue
        # 根节点每个数据集只累计一次，多个场景叶不能让根的数量和大小重复。
        groups["按场景"].append(entry)
        for scene in item.scene or (vocabulary.UNLABELED,):
            parent = scene_path(scene)
            path = parent + "/" + entry.name
            groups.setdefault(parent, []).append(entry)
            groups[path] = [entry]
            leaves[path] = entry
            # 自定义场景按原值显示，不再标注词表外（M1.5-06）。
            names[parent] = (
                vocabulary.UNLABELED_NAME
                if scene == vocabulary.UNLABELED
                else vocabulary.scene_name(scene) or scene
            )
            names[path] = entry.name
    return tuple(
        DatasetTreeNode(
            path=path,
            parent_path=path.rsplit("/", 1)[0] if "/" in path else None,
            name=names[path],
            kind="entry" if path in leaves else "view" if path == "按场景" else "scene",
            view="scene",
            format=None,
            version=None,
            dataset_id=leaves[path].dataset_id if path in leaves else None,
            entry_path=leaves[path].entry_path if path in leaves else None,
            dataset_count=len({entry.dataset_id for entry in children if entry.dataset_id}),
            entry_count=len(children),
            size=aggregate(tuple(children)),
        )
        for path, children in sorted(groups.items())
    )
