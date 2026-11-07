"""索引行到列表及筛选的纯投影；不使用原文猜测meta，也不读取文件。"""

from pathlib import PurePosixPath

from rdp.infra.db.validation import invalid_field
from rdp.jobs.dataset_browser import _classification, _index
from rdp.jobs.dataset_browser.errors import DatasetQueryError
from rdp.jobs.dataset_browser.schemas import (
    DataOrigin,
    DatasetFilters,
    DatasetListItem,
    DatasetSize,
    EntrySummary,
)
from rdp.jobs.datasets.models import DatasetRow, EntryRow
from rdp.jobs.datasets.types import View
from rdp.jobs.datasets.vocabulary import UNLABELED


def size(row: DatasetRow | EntryRow | None) -> DatasetSize:
    """未知与实际零值分离，只显示统计值且保留原时刻。"""
    measured = row.size_bytes if row else None
    return DatasetSize(
        size_bytes=measured,
        size_checked_at=row.size_checked_at if row else None,
        recorded_size_bytes=None,
        display_bytes=measured,
        display_source="measured" if measured is not None else "unknown",
    )


def entry(row: EntryRow) -> EntrySummary:
    """位置与单入口大小来自同一索引行，不把数据集总量复制到格式入口。"""
    return EntrySummary(
        entry_path=row.path,
        dataset_id=row.dataset_id,
        name=row.name,
        view=View(row.view),
        format=row.format,
        version=row.version,
        size=size(row),
    )


def items(index: _index.Index) -> tuple[DatasetListItem, ...]:
    """永久编号去重，未知身份按入口独立占位。"""
    moments = {scan.scan_id: scan.committed_at for scan in index.scans}
    result: list[DatasetListItem] = []
    for dataset in index.datasets:
        result.append(
            DatasetListItem(
                dataset_id=dataset.dataset_id,
                name=dataset.name,
                canonical_entry_path=dataset.canonical_entry_path,
                entries=tuple(
                    entry(row) for row in index.entries if row.dataset_id == dataset.dataset_id
                ),
                fps=(dataset.fps,),
                data_origin=DataOrigin(dataset.data_origin),
                scene=tuple(dataset.scene),
                tasks=tuple(dataset.tasks),
                robot_model=dataset.robot_model,
                size=size(dataset) if dataset.canonical_entry_path else size(None),
                indexed_at=moments[dataset.scan_id],
            )
        )
    for row in index.entries:
        if row.dataset_id is None:
            result.append(
                DatasetListItem(
                    dataset_id=None,
                    name=row.name,
                    canonical_entry_path=None,
                    entries=(entry(row),),
                    fps=(None,),
                    data_origin=DataOrigin.UNKNOWN,
                    size=size(None),
                    indexed_at=moments[row.scan_id],
                )
            )
    return tuple(
        sorted(
            result,
            key=lambda item: (
                item.name,
                item.dataset_id or "",
                item.entries[0].entry_path if item.entries else "",
            ),
        )
    )


def matches(item: DatasetListItem, filters: DatasetFilters) -> bool:
    """不同维度取交集，五个字段仅匹配规范信息索引。"""
    fps = None if filters.fps == "unknown" else filters.fps
    model = None if filters.robot_model == UNLABELED else filters.robot_model
    return (
        (filters.robot_model is None or model == item.robot_model)
        and (filters.fps is None or fps in item.fps)
        and (filters.data_origin is None or filters.data_origin == item.data_origin)
        and (filters.scene is None or filters.scene in (item.scene or (UNLABELED,)))
        and all(task in (item.tasks or (UNLABELED,)) for task in filters.tasks)
        and (
            filters.entry_path is None
            or not filters.entry_path.startswith("按场景/")
            or any(
                PurePosixPath(_classification.scene_path(scene), item.name).is_relative_to(
                    filters.entry_path
                )
                for scene in (item.scene or (UNLABELED,))
            )
        )
        and any(entry_matches(row, filters) for row in item.entries)
    )


def entry_matches(row: EntrySummary, filters: DatasetFilters) -> bool:
    """视图/格式/版本/路径必须在同一个入口同时命中，路径按完整分量比较。"""
    return (
        (filters.view is None or filters.view == row.view)
        and (filters.format is None or filters.format == row.format)
        and (filters.version is None or filters.version == row.version)
        and (
            filters.entry_path is None
            or filters.entry_path == "按场景"
            or filters.entry_path.startswith("按场景/")
            or PurePosixPath(row.entry_path).is_relative_to(filters.entry_path)
        )
    )


def validate(filters: DatasetFilters) -> None:
    """跨字段组合不能默默匹配空集；拒绝路径规范化隐藏的穿越和空分量。"""
    if (
        filters.version is not None
        and filters.format is None
        or filters.view is View.TASK
        and filters.format is not None
    ):
        raise DatasetQueryError(
            invalid_field("filters", "版本必须附带格式，按任务不得指定格式").diagnostics
        )
    if UNLABELED in filters.tasks and len(set(filters.tasks)) > 1:
        raise DatasetQueryError(invalid_field("tasks", "未标注必须单独选择").diagnostics)
    if filters.entry_path is not None:
        path = filters.entry_path
        if (
            path.startswith("/")
            or any(part in {"", ".", ".."} for part in path.split("/"))
            or "\x00" in path
            or "\\" in path
        ):
            raise DatasetQueryError(invalid_field("entry_path", "无穿越的导航相对路径").diagnostics)
