"""提交资格纯判断；不同或无法验证的指纹保留旧索引，消失须有两次明确观察。"""

from dataclasses import replace
from datetime import datetime

from rdp.infra.diagnostics import DefectError
from rdp.jobs import _storage
from rdp.jobs.datasets._issues import finding
from rdp.jobs.datasets.fingerprint import DatasetFingerprint, FileState
from rdp.jobs.datasets.panel import aggregate_findings
from rdp.jobs.datasets.scan_types import (
    DatasetObservation,
    IndexReplacement,
    NavigationScan,
    StorageScan,
)


def plan(
    navigation: NavigationScan,
    storage: StorageScan,
    current: tuple[DatasetFingerprint, ...],
    now: datetime,
) -> IndexReplacement:
    """先验证范围，再分别列出替换、删除和跳过，不触碰数据库。"""
    now = _storage.moment(now)
    if len(current) != len(navigation.datasets):
        raise DefectError()
    accepted: list[DatasetObservation] = []
    skipped: list[DatasetObservation] = []
    removed: list[str] = []
    removed_entries: list[str] = []
    old_paths = {path for item in navigation.baseline for path in item.entry_paths}
    for item, fresh in zip(navigation.datasets, current, strict=True):
        if fresh.dataset_id != item.dataset_id or fresh.nav_root != item.fingerprint.nav_root:
            raise DefectError()
        if item.fingerprint.verifiable and fresh.verifiable and item.fingerprint == fresh:
            if not item.entries and all(
                entry.state is FileState.MISSING for entry in fresh.entries
            ):
                if item.dataset_id is not None:
                    removed.append(item.dataset_id)
                else:
                    removed_entries.extend(entry.path for entry in fresh.entries)
            else:
                accepted.append(item)
        else:
            skipped.append(item)
            # 初次不可读仅记录位置占位，不覆盖之前可用的入口；不授权第二段字段。
            if _new_observation(item, navigation, old_paths):
                placeholders = tuple(
                    replace(entry, links=(), sources=(), dataset_roots=(), recorded_size_bytes=None)
                    for entry in item.entries
                )
                accepted.append(replace(item, entries=placeholders))
    notices = aggregate_findings(
        finding(
            item.dataset_id or item.fingerprint.entries[0].path,
            "DATASET_CHANGED",
            "导航状态变化或无法验证，保留旧索引",
            notice=True,
        )
        for item in skipped
    )
    return IndexReplacement(
        navigation,
        storage,
        tuple(accepted),
        tuple(removed),
        tuple(removed_entries),
        tuple(skipped),
        notices,
        now,
    )


def _new_observation(
    item: DatasetObservation, navigation: NavigationScan, old_paths: set[str]
) -> bool:
    """只有没有旧编号及旧入口的观察才可建立损坏占位，不能覆盖已有可用记录。"""
    previous = {entry.dataset_id for entry in navigation.baseline if entry.dataset_id is not None}
    return (
        bool(item.entries)
        and item.dataset_id not in previous
        and all(str(entry.location.path) not in old_paths for entry in item.entries)
    )
