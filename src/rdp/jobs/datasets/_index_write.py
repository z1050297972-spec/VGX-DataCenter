"""已核对计划的SQL执行；全部写入由外层单事务提交，不读导航或存储根。"""

from typing import cast

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from rdp.infra.diagnostics import DefectError
from rdp.jobs.datasets.models import (
    DatasetRow,
    DatasetScanRow,
    DocumentRow,
    EntryRow,
    FindingRow,
    LinkRow,
    ScanRootRow,
    SourceRow,
)
from rdp.jobs.datasets.scan_types import DatasetObservation, IndexReplacement, ScanPublication
from rdp.jobs.datasets.types import EntrySnapshot, FindingGroup, View


def apply(session: Session, plan: IndexReplacement) -> ScanPublication:
    """先发布新代次、再替换指定归属；任一flush失败均由外层回滚。"""
    used = session.info.setdefault("dataset_plans", set())
    if not isinstance(used, set) or id(plan) in used:
        raise DefectError()
    cast(set[int], used).add(id(plan))
    previous_roots = tuple(
        session.scalars(select(ScanRootRow).order_by(ScanRootRow.scan_id.desc()))
    )
    session.execute(update(DatasetScanRow).values(is_current=False))
    nav = plan.navigation
    scan = DatasetScanRow(
        job_id=nav.job_id,
        scope="all" if nav.requested_dataset_id is None else "dataset",
        requested_dataset_id=nav.requested_dataset_id,
        started_at=nav.started_at,
        navigation_finished_at=nav.finished_at,
        committed_at=plan.committed_at,
        navigation_elapsed_s=nav.elapsed_s,
        lock_held_s=nav.lock_held_s,
        storage_stage=plan.storage.stage.value,
        is_current=True,
    )
    session.add(scan)
    session.flush()
    _roots(session, plan, scan.scan_id, previous_roots)
    for identity in plan.deleted_dataset_ids:
        session.execute(delete(DatasetRow).where(DatasetRow.dataset_id == identity))
        session.execute(delete(FindingRow).where(FindingRow.owner_key == "dataset:" + identity))
    for path in plan.deleted_entry_paths:
        session.execute(delete(EntryRow).where(EntryRow.path == path))
        session.execute(delete(FindingRow).where(FindingRow.owner_key == "entry:" + path))
    for observation in plan.accepted:
        _dataset(session, observation, scan.scan_id)
    if nav.requested_dataset_id is None:
        _findings(session, "global", nav.global_findings, scan.scan_id, clear=True)
    _findings(session, "global", plan.notices, scan.scan_id, clear=False)
    storage_count = _storage_values(session, plan)
    session.flush()
    _cleanup(session)
    entries = sum(len(item.entries) for item in nav.datasets)
    failed = sum(len(item.failed_entry_paths) for item in nav.datasets)
    count = sum(group.diagnostics.total for item in plan.accepted for group in item.findings)
    count += sum(group.diagnostics.total for group in nav.global_findings + plan.notices)
    return ScanPublication(
        scan.scan_id,
        sum(item.dataset_id is not None for item in plan.accepted),
        entries,
        failed,
        len(plan.skipped),
        count + storage_count,
        len(plan.skipped) + plan.storage.warning_count,
    )


def _roots(
    session: Session, plan: IndexReplacement, scan_id: int, previous: tuple[ScanRootRow, ...]
) -> None:
    """未检查的根只沿用身份相同的旧观察，不能用同名新挂载冒充在线。"""
    observed = {item.name: item for item in plan.storage.roots}
    for root in plan.navigation.registered_roots:
        current = observed.get(root.name)
        old = next(
            (
                item
                for item in previous
                if (item.name, item.path, item.uuid, item.nfs_export)
                == (root.name, str(root.path), root.uuid, root.nfs_export)
            ),
            None,
        )
        session.add(
            ScanRootRow(
                scan_id=scan_id,
                name=root.name,
                path=str(root.path),
                uuid=root.uuid,
                nfs_export=root.nfs_export,
                writable=root.writable,
                online=current.online if current else old.online if old else None,
                reason=current.reason.value
                if current and current.reason
                else old.reason
                if old and current is None
                else None,
                checked_at=current.checked_at if current else old.checked_at if old else None,
            )
        )


def _dataset(session: Session, item: DatasetObservation, scan_id: int) -> None:
    """规范副本唯一才取其数据集属性；重复或缺失时保留全部入口供面板处理。"""
    if not item.entries:
        return
    old_entries = {
        row.path: row
        for row in session.scalars(
            select(EntryRow).where(
                EntryRow.path.in_([str(entry.location.path) for entry in item.entries])
            )
        )
    }
    for row in old_entries.values():
        session.expunge(row)
    canonical = tuple(entry for entry in item.entries if entry.location.view is View.TASK)
    selected = canonical[0] if len(canonical) == 1 else None
    if item.dataset_id is not None:
        old = session.get(DatasetRow, item.dataset_id)
        same = selected is not None and _same_links(session, selected, item)
        values = DatasetRow(
            dataset_id=item.dataset_id,
            name=selected.location.dataset_name
            if selected
            else item.entries[0].location.dataset_name,
            canonical_entry_path=str(selected.location.path) if selected else None,
            scan_id=scan_id,
            fingerprint=item.fingerprint.model_dump(mode="json"),
            data_origin=selected.data_origin if selected else "unknown",
            scene=selected.scene if selected else None,
            tasks=list(selected.tasks) if selected else [],
            robot_model=selected.robot_model if selected else None,
            recorded_size_bytes=selected.recorded_size_bytes if selected else None,
            size_bytes=old.size_bytes if old and same else None,
            size_checked_at=old.size_checked_at if old and same else None,
        )
        session.merge(values)
        session.flush()
        new_paths = [str(entry.location.path) for entry in item.entries]
        session.execute(
            delete(EntryRow).where(
                EntryRow.dataset_id == item.dataset_id, EntryRow.path.not_in(new_paths)
            )
        )
    for entry in item.entries:
        _entry(session, entry, item, scan_id, old_entries.get(str(entry.location.path)))
    owner = (
        "dataset:" + item.dataset_id
        if item.dataset_id
        else "entry:" + str(item.entries[0].location.path)
    )
    _findings(session, owner, item.findings, scan_id, clear=True)


def _same_links(session: Session, entry: EntrySnapshot, observation: DatasetObservation) -> bool:
    """统计与磁盘观察只能复用于相同目标，不能仅用入口路径判断。"""
    links = tuple(
        session.scalars(
            select(LinkRow)
            .where(LinkRow.entry_path == str(entry.location.path))
            .order_by(LinkRow.ordinal)
        )
    )
    fingerprint = next(
        item for item in observation.fingerprint.entries if item.path == str(entry.location.path)
    )
    actual = {link.name: link.target for link in fingerprint.links}
    return tuple((row.name, row.source_path, row.observed_target) for row in links) == tuple(
        (row.name, row.source_path, actual.get(row.name)) for row in entry.links
    )


def _entry(
    session: Session,
    entry: EntrySnapshot,
    item: DatasetObservation,
    scan_id: int,
    old: EntryRow | None,
) -> None:
    """删除与重建在同事务，统计保留需先比较旧链接；不会出现可见的空入口。"""
    path = str(entry.location.path)
    same = old is not None and _same_links(session, entry, item)
    old_links = tuple(session.scalars(select(LinkRow).where(LinkRow.entry_path == path)))
    old_sources = tuple(session.scalars(select(SourceRow).where(SourceRow.entry_path == path)))
    for row in (*old_links, *old_sources):
        session.expunge(row)
    session.execute(delete(EntryRow).where(EntryRow.path == path))
    fp = next(part for part in item.fingerprint.entries if part.path == path)
    session.add(
        EntryRow(
            path=path,
            dataset_id=item.dataset_id,
            scan_id=scan_id,
            view=entry.location.view.value,
            format=entry.location.format,
            version=entry.location.version,
            name=entry.location.dataset_name,
            dataset_roots=list(entry.dataset_roots),
            provenance_present=entry.provenance_present,
            fingerprint=fp.model_dump(mode="json"),
            recorded_size_bytes=entry.recorded_size_bytes,
            size_bytes=old.size_bytes if old and same else None,
            size_checked_at=old.size_checked_at if old and same else None,
            aria2_count=old.aria2_count if old and same else None,
            incomplete_count=old.incomplete_count if old and same else None,
        )
    )
    session.flush()
    for doc in entry.documents:
        session.add(
            DocumentRow(
                entry_path=path,
                name=doc.name,
                payload=doc.payload,
                schema_version=doc.schema_version,
                sha256=doc.sha256,
            )
        )
    actual = {link.name: link.target for link in fp.links}
    for ordinal, link in enumerate(entry.links):
        prior = next(
            (
                row
                for row in old_links
                if (row.name, row.source_path, row.observed_target)
                == (link.name, link.source_path, actual.get(link.name))
            ),
            None,
        )
        session.add(
            LinkRow(
                entry_path=path,
                ordinal=ordinal,
                name=link.name,
                source_path=link.source_path,
                source_type=link.source_type,
                derived_entry_path=link.entry_path,
                observed_target=actual.get(link.name),
                storage_root_name=prior.storage_root_name if prior else None,
                status=prior.status if prior else "unchecked",
                checked_at=prior.checked_at if prior else None,
                size_bytes=prior.size_bytes if prior else None,
                size_checked_at=prior.size_checked_at if prior else None,
            )
        )
    for ordinal, source in enumerate(entry.sources):
        prior_source = next(
            (
                row
                for row in old_sources
                if (row.source_id, row.direct_path) == (source.source_id, source.direct_path)
            ),
            None,
        )
        _source(session, entry, ordinal, prior_source)


def _source(session: Session, entry: EntrySnapshot, ordinal: int, prior: SourceRow | None) -> None:
    """尚未执行磁盘检查时保留相同身份与目标的meta观察，其余字段明确未知。"""
    source = entry.sources[ordinal]
    session.add(
        SourceRow(
            entry_path=str(entry.location.path),
            ordinal=ordinal,
            source_id=source.source_id,
            original_path=source.original_path,
            direct_path=source.direct_path,
            derived_entry_path=source.entry_path,
            format=source.format,
            version=source.version,
            validation_status=source.validation_status,
            storage_root_name=prior.storage_root_name if prior else None,
            status=prior.status if prior else "unchecked",
            checked_at=prior.checked_at if prior else None,
            robot_type=prior.robot_type if prior else None,
            fps=prior.fps if prior else None,
            fps_rounded=prior.fps_rounded if prior else None,
            codebase_version=prior.codebase_version if prior else None,
            meta_checked_at=prior.meta_checked_at if prior else None,
        )
    )


def _findings(
    session: Session, owner: str, findings: tuple[FindingGroup, ...], scan_id: int, *, clear: bool
) -> None:
    """只替换①②组，NOT_RUN不能抹掉第02张已保存的磁盘发现。"""
    if clear:
        session.execute(
            delete(FindingRow).where(
                FindingRow.owner_key == owner, FindingRow.group.in_(("json", "views"))
            )
        )
    for group in findings:
        session.merge(
            FindingRow(
                owner_key=owner,
                group=group.group.value,
                severity=group.severity.value,
                rule=group.diagnostics.rule,
                scan_id=scan_id,
                total=group.diagnostics.total,
                samples=[sample.model_dump(mode="json") for sample in group.diagnostics.samples],
            )
        )


def _cleanup(session: Session) -> None:
    """只清已经没有索引引用的旧代次，跳过数据集依旧引用其原扫描元数据。"""
    referenced = (
        set(session.scalars(select(DatasetRow.scan_id)))
        | set(session.scalars(select(EntryRow.scan_id)))
        | set(session.scalars(select(FindingRow.scan_id)))
    )
    session.execute(
        delete(DatasetScanRow).where(
            DatasetScanRow.is_current.is_(False), DatasetScanRow.scan_id.not_in(referenced)
        )
    )


def _storage_values(session: Session, plan: IndexReplacement) -> int:
    """只把通过指纹复核的数据块观察写入索引，不覆盖跳过者。"""
    skipped_paths = {str(entry.location.path) for item in plan.skipped for entry in item.entries}
    paths = {
        str(entry.location.path) for item in plan.accepted for entry in item.entries
    } - skipped_paths
    for item in plan.storage.links:
        if item.entry_path in paths:
            session.execute(
                update(LinkRow)
                .where(LinkRow.entry_path == item.entry_path, LinkRow.ordinal == item.ordinal)
                .values(
                    storage_root_name=item.storage_root_name,
                    status=item.status.value,
                    checked_at=item.checked_at,
                )
            )
    for item in plan.storage.sources:
        if item.entry_path not in paths:
            continue
        session.execute(
            update(SourceRow)
            .where(SourceRow.entry_path == item.entry_path, SourceRow.ordinal == item.ordinal)
            .values(
                storage_root_name=item.storage_root_name,
                status=item.status.value,
                checked_at=item.checked_at,
                robot_type=item.robot_type,
                fps=item.fps,
                fps_rounded=int(item.fps + 0.5) if item.fps is not None else None,
                codebase_version=item.codebase_version,
                meta_checked_at=item.meta_checked_at,
            )
        )

    return _storage_findings(session, plan)


def _storage_findings(session: Session, plan: IndexReplacement) -> int:
    """完成第二段才替换对应发现；单数据集扫描保留全局和其他数据集发现。"""
    if plan.storage.stage.value == "not_run":
        return 0
    skipped_paths = {str(entry.location.path) for item in plan.skipped for entry in item.entries}
    owners = {
        "dataset:" + item.dataset_id
        if item.dataset_id
        else "entry:" + str(item.entries[0].location.path)
        for item in plan.accepted
        if item.entries
        and not any(str(entry.location.path) in skipped_paths for entry in item.entries)
    }
    if plan.navigation.requested_dataset_id is None:
        owners.add("global")
    session.execute(
        delete(FindingRow).where(
            FindingRow.owner_key.in_(owners),
            (FindingRow.group == "disk") | (FindingRow.rule == "STORAGE_OFFLINE"),
        )
    )
    scan_id = session.scalar(
        select(DatasetScanRow.scan_id).where(DatasetScanRow.is_current.is_(True))
    )
    if scan_id is None:
        raise DefectError()
    count = 0
    for owner, group in plan.storage.findings:
        if owner in owners:
            _findings(session, owner, (group,), scan_id, clear=False)
            count += group.diagnostics.total
    return count
