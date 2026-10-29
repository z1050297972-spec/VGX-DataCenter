"""统计大小的索引读写（领域层，M1-02），不访问存储根，不获取导航写锁。"""

from datetime import datetime
from pathlib import Path

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from rdp.infra.diagnostics import (
    DIAGNOSTIC_SAMPLE_LIMIT,
    Diagnostic,
    DiagnosticCategory,
    DiagnosticLevel,
    DiagnosticObject,
)
from rdp.jobs.datasets._sizing_types import SizeDataset, SizeEntry, SizeLink, SizeValue
from rdp.jobs.datasets.index import read_index_baseline
from rdp.jobs.datasets.models import DatasetRow, EntryRow, FindingRow, LinkRow


def snapshot(session: Session, dataset_id: str | None, nav_root: Path) -> tuple[SizeDataset, ...]:
    """先读索引身份，再复制相关入口和链接，不让ORM实例越过事务。"""
    result: list[SizeDataset] = []
    for dataset in read_index_baseline(session, dataset_id, nav_root=nav_root):
        if dataset.dataset_id is None:
            continue
        entries: list[SizeEntry] = []
        for entry in session.scalars(
            select(EntryRow)
            .where(EntryRow.dataset_id == dataset.dataset_id)
            .order_by(EntryRow.path)
        ):
            links = tuple(
                SizeLink(row.ordinal, row.source_path, row.observed_target)
                for row in session.scalars(
                    select(LinkRow)
                    .where(LinkRow.entry_path == entry.path)
                    .order_by(LinkRow.ordinal)
                )
            )
            entries.append(SizeEntry(entry.path, entry.view == "task", links))
        result.append(SizeDataset(dataset.dataset_id, dataset.fingerprint, tuple(entries)))
    return tuple(result)


def publish(
    session: Session, dataset: SizeDataset, values: dict[tuple[str, int], SizeValue], now: datetime
) -> None:
    """一次事务发布该数据集全部入口，数据集大小只取规范入口。"""
    current = session.get(DatasetRow, dataset.dataset_id)
    if current is None or current.fingerprint != dataset.fingerprint.model_dump(mode="json"):
        raise OSError("索引在统计期间变化")
    for entry in dataset.entries:
        selected = [values[(entry.path, link.ordinal)] for link in entry.links]
        size = sum(value.size_bytes for value in selected)
        session.execute(
            update(EntryRow)
            .where(EntryRow.path == entry.path)
            .values(
                size_bytes=size,
                size_checked_at=now,
                aria2_count=sum(value.aria2_count for value in selected),
                incomplete_count=sum(value.incomplete_count for value in selected),
            )
        )
        if entry.canonical and sum(item.canonical for item in dataset.entries) == 1:
            session.execute(
                update(DatasetRow)
                .where(DatasetRow.dataset_id == dataset.dataset_id)
                .values(size_bytes=size, size_checked_at=now)
            )
        for link in entry.links:
            session.execute(
                update(LinkRow)
                .where(LinkRow.entry_path == entry.path, LinkRow.ordinal == link.ordinal)
                .values(
                    size_bytes=values[(entry.path, link.ordinal)].size_bytes, size_checked_at=now
                )
            )

    _incomplete(session, dataset, values)


def _incomplete(
    session: Session, dataset: SizeDataset, values: dict[tuple[str, int], SizeValue]
) -> None:
    """一个数据集只按规范入口计发现，不能把两个视图重复计成两次下载。"""
    owner = "dataset:" + dataset.dataset_id
    session.execute(
        delete(FindingRow).where(
            FindingRow.owner_key == owner, FindingRow.rule == "DOWNLOAD_INCOMPLETE"
        )
    )
    canonical = tuple(entry for entry in dataset.entries if entry.canonical)
    if len(canonical) != 1:
        return
    selected = [values[(canonical[0].path, link.ordinal)] for link in canonical[0].links]
    total = sum(value.aria2_count + value.incomplete_count for value in selected)
    row = session.get(DatasetRow, dataset.dataset_id)
    if not total or row is None:
        return
    samples: list[dict[str, object]] = []
    for value in selected:
        for path in value.samples:
            if len(samples) < DIAGNOSTIC_SAMPLE_LIMIT:
                samples.append(
                    Diagnostic(
                        level=DiagnosticLevel.WARNING,
                        category=DiagnosticCategory.INPUT,
                        stage="统计大小",
                        source="平台",
                        objects=(
                            DiagnosticObject(key="dataset_id", value=dataset.dataset_id),
                            DiagnosticObject(key="path", value=str(path)),
                        ),
                        rule="DOWNLOAD_INCOMPLETE",
                        actual="发现.aria2或.incomplete文件",
                        expected="下载完成且无残留控制文件",
                        consequence="仅提示，统计值包含当前文件大小",
                        next_step="核对下载状态，必要时重新下载或清理",
                    ).model_dump(mode="json")
                )
    session.add(
        FindingRow(
            owner_key=owner,
            group="storage",
            severity="notice",
            rule="DOWNLOAD_INCOMPLETE",
            scan_id=row.scan_id,
            total=total,
            samples=samples,
        )
    )
