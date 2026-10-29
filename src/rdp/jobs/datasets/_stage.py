"""第一段持锁后的读取流程；只组合公开读取和L12共同采集，不访问存储根。"""

from collections.abc import Callable
from itertools import chain
from pathlib import Path

from rdp.infra.diagnostics import ExternalError
from rdp.jobs.datasets import _fingerprints
from rdp.jobs.datasets._issues import finding, input_error
from rdp.jobs.datasets.catalog import REQUIRED_DOCUMENTS
from rdp.jobs.datasets.fingerprint import DatasetFingerprint
from rdp.jobs.datasets.panel import aggregate_findings, inspect_entry, inspect_views
from rdp.jobs.datasets.reading import discover_entries, read_entry
from rdp.jobs.datasets.scan_types import DatasetObservation, IndexedDataset
from rdp.jobs.datasets.types import EntrySnapshot, FindingGroup, JsonDocument


def observe(
    root: Path,
    requested: str | None,
    baseline: tuple[IndexedDataset, ...],
    checkpoint: Callable[[], None],
) -> tuple[tuple[DatasetObservation, ...], tuple[FindingGroup, ...]]:
    """全量发现后按编号筛选，旧入口集合也参加消失与变更判断。"""
    catalog = discover_entries(root)
    entries: list[EntrySnapshot] = []
    for location in catalog.entries:
        checkpoint()
        try:
            entries.append(read_entry(root, location, checkpoint=checkpoint))
        except ExternalError:
            issue = finding(str(location.path), "NAV_UNREADABLE", "入口目录无法读取")
            docs = tuple(
                JsonDocument(name, None, None, None, (issue,)) for name in REQUIRED_DOCUMENTS
            )
            entries.append(EntrySnapshot(location, docs, None, (), (), (), False, None, (issue,)))
    captured = _fingerprints.collect(root, checkpoint)
    groups: dict[str, list[EntrySnapshot]] = {}
    for entry in entries:
        key = entry.dataset_id or "entry:" + str(entry.location.path)
        if requested is None or entry.dataset_id == requested:
            groups.setdefault(key, []).append(entry)
    previous = {item.dataset_id or "entry:" + item.entry_paths[0]: item for item in baseline}
    if requested is not None and requested not in groups and requested not in previous:
        raise input_error(requested, "导航及索引均没有此数据集")
    result: list[DatasetObservation] = []
    for key in sorted(groups.keys() | previous.keys()):
        selected = tuple(groups.get(key, ()))
        prior = previous.get(key)
        dataset_id = selected[0].dataset_id if selected else prior.dataset_id if prior else None
        known = prior.entry_paths if prior else tuple(str(item.location.path) for item in selected)
        fp = _fingerprints.select(root, dataset_id, known, captured, checkpoint)
        if not _matches(selected, fp):
            fp = fp.model_copy(update={"verifiable": False})
        issues = aggregate_findings(
            chain(
                (issue for item in selected for issue in (*item.findings, *inspect_entry(item))),
                inspect_views(selected),
            )
        )
        failed = tuple(
            str(item.location.path)
            for item in selected
            if any(doc.payload is None for doc in item.documents)
        )
        result.append(DatasetObservation(dataset_id, selected, fp, issues, failed))
    return tuple(result), aggregate_findings(catalog.findings)


def _matches(entries: tuple[EntrySnapshot, ...], fingerprint: DatasetFingerprint) -> bool:
    """解析字节必须等于指纹字节，禁止旧投影配新指纹获得提交资格。"""
    observed = {
        entry.path: {doc.name: doc.sha256 for doc in entry.json_files}
        for entry in fingerprint.entries
    }
    return all(
        all(
            doc.sha256 == observed.get(str(entry.location.path), {}).get(doc.name)
            for doc in entry.documents
        )
        for entry in entries
    )
