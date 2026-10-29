"""查询用索引快照与元信息投影；只读SQL，绝不打开索引内保存的路径。"""

from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from rdp.infra.db.validation import invalid_field
from rdp.infra.diagnostics import DefectError
from rdp.jobs.dataset_browser.schemas import RobotModelOption
from rdp.jobs.datasets.catalog import MAX_ENTRY_MEMBERS, MAX_SCAN_ENTRIES
from rdp.jobs.datasets.models import DatasetRow, DatasetScanRow, EntryRow, SourceRow


@dataclass(frozen=True)
class Index:
    """单个事务中读取的有界行集合，关闭会话后只使用已加载标量。

    Attributes:
        datasets: 至多MAX_SCAN_ENTRIES条永久编号索引，允许空。
        entries: 至多MAX_SCAN_ENTRIES条入口，按路径排序，包含损坏身份占位。
        sources: 至多MAX_ENTRY_MEMBERS条元信息观察，不加载JSON全文。
        scans: 被索引引用及当前发布的扫描时刻，UTC；不读取挂载状态。
        models: 注入目录的唯一型号及标签映射，按编号排序，允许空。
    """

    datasets: tuple[DatasetRow, ...]
    entries: tuple[EntryRow, ...]
    sources: tuple[SourceRow, ...]
    scans: tuple[DatasetScanRow, ...]
    models: tuple[RobotModelOption, ...]


def load(session: Session, reader: Callable[[Session], tuple[RobotModelOption, ...]]) -> Index:
    """索引总入口及元信息都有上界，拒绝悄悄截断统计。"""
    datasets = tuple(session.scalars(select(DatasetRow).limit(MAX_SCAN_ENTRIES + 1)))
    entries = tuple(
        session.scalars(select(EntryRow).order_by(EntryRow.path).limit(MAX_SCAN_ENTRIES + 1))
    )
    sources = tuple(session.scalars(select(SourceRow).limit(MAX_ENTRY_MEMBERS + 1)))
    scans = tuple(session.scalars(select(DatasetScanRow).limit(MAX_SCAN_ENTRIES + 2)))
    if (
        len(entries) > MAX_SCAN_ENTRIES
        or len(datasets) > MAX_SCAN_ENTRIES
        or len(sources) > MAX_ENTRY_MEMBERS
    ):
        raise invalid_field("index", "索引查询数量不得超过既有入口/成员预算")
    models = reader(session)
    identifiers: set[str] = set()
    labels: set[str] = set()
    for model in models:
        if model.model_id in identifiers or labels.intersection(model.robot_types):
            raise DefectError()
        identifiers.add(model.model_id)
        labels.update(model.robot_types)
    return Index(
        datasets, entries, sources, scans, tuple(sorted(models, key=lambda item: item.model_id))
    )


def metadata(
    index: Index, dataset: DatasetRow
) -> tuple[tuple[str | None, ...], tuple[int | None, ...], tuple[str, ...]]:
    """筛选只用规范入口的meta索引；规范入口不可确定时取格式入口的并集。"""
    paths = (
        {dataset.canonical_entry_path}
        if dataset.canonical_entry_path
        else {
            entry.path
            for entry in index.entries
            if entry.dataset_id == dataset.dataset_id and entry.view == "format"
        }
    )
    rows = [row for row in index.sources if row.entry_path in paths]
    labels = {
        row.robot_type
        if row.format == "lerobot"
        and row.meta_checked_at is not None
        and row.robot_type != "unknown"
        else None
        for row in rows
    } or {None}
    fps = {
        row.fps_rounded if row.format == "lerobot" and row.meta_checked_at is not None else None
        for row in rows
    } or {None}
    models = tuple(
        model.model_id for model in index.models if labels.intersection(model.robot_types)
    )
    return (
        tuple(sorted(labels, key=lambda value: (value is None, value or ""))),
        tuple(sorted(fps, key=lambda value: (value is None, value or 0))),
        models,
    )
