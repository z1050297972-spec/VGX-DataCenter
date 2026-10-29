"""两个视图的纯索引树聚合，数量按永久编号去重、大小按入口求和。"""

from pathlib import PurePosixPath

from rdp.infra.db.validation import invalid_field
from rdp.jobs.dataset_browser.schemas import DatasetTreeNode, EntrySummary, TreeSize
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
