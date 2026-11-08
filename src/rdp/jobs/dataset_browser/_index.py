"""查询用索引快照与元信息投影；只读SQL，绝不打开索引内保存的路径。"""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from rdp.collection.index_models import DatasetCollectionRobotRow, DatasetCollectionRow
from rdp.collection.information import MAX_COLLECTION_ROBOTS, CollectionInformation
from rdp.infra.db.validation import invalid_field
from rdp.jobs.datasets.catalog import MAX_ENTRY_MEMBERS, MAX_SCAN_ENTRIES
from rdp.jobs.datasets.models import DatasetRow, DatasetScanRow, EntryRow, SourceRow


@dataclass(frozen=True)
class Index:
    """单个事务中读取的有界行集合，关闭会话后只使用已加载标量。

    Attributes:
        datasets: 至多MAX_SCAN_ENTRIES条永久编号索引，允许空。
        entries: 至多MAX_SCAN_ENTRIES条入口，按路径排序，包含损坏身份占位。
        sources: 至多MAX_ENTRY_MEMBERS条元信息观察，不加载JSON全文。
        collections: 数据集编号到有效采集投影，机器人去重并保留导航顺序。
        scans: 被索引引用及当前发布的扫描时刻，UTC；不读取挂载状态。
    """

    datasets: tuple[DatasetRow, ...]
    entries: tuple[EntryRow, ...]
    sources: tuple[SourceRow, ...]
    scans: tuple[DatasetScanRow, ...]
    collections: dict[str, CollectionInformation]


def load(session: Session) -> Index:
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
    collections: dict[str, CollectionInformation] = {}
    robot_ids: dict[str, list[int]] = {}
    robots = session.scalars(
        select(DatasetCollectionRobotRow)
        .order_by(DatasetCollectionRobotRow.dataset_id, DatasetCollectionRobotRow.ordinal)
        .limit(MAX_SCAN_ENTRIES * MAX_COLLECTION_ROBOTS + 1)
    )
    for row in robots:
        robot_ids.setdefault(row.dataset_id, []).append(row.robot_id)
    for row in session.scalars(select(DatasetCollectionRow).limit(MAX_SCAN_ENTRIES + 1)):
        collections[row.dataset_id] = CollectionInformation.model_validate(
            dict(
                status=row.status,
                method_id=row.method_id,
                purpose_id=row.purpose_id,
                robot_ids=robot_ids.get(row.dataset_id, []),
            )
        )
    if (
        len(collections) > MAX_SCAN_ENTRIES
        or sum(map(len, robot_ids.values())) > MAX_SCAN_ENTRIES * MAX_COLLECTION_ROBOTS
    ):
        raise invalid_field("index", "采集投影不得超过入口预算")
    return Index(datasets, entries, sources, scans, collections)
