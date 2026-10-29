"""从已存扫描发现生成面板；完整总数与有限样例分开聚合，不执行任何磁盘检查。"""

from dataclasses import replace

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from rdp.infra.db.validation import invalid_field
from rdp.infra.diagnostics import (
    DIAGNOSTIC_SAMPLE_LIMIT,
    Diagnostic,
    DiagnosticLevel,
    aggregate_diagnostics,
)
from rdp.jobs.dataset_browser.schemas import DatasetPanelResponse, IndexedStorageRoot
from rdp.jobs.datasets.catalog import MAX_ENTRY_MEMBERS
from rdp.jobs.datasets.models import DatasetScanRow, FindingRow, ScanRootRow
from rdp.jobs.datasets.types import FindingGroup, PanelGroup, PanelSeverity


def snapshot(session: Session, dataset_id: str | None) -> DatasetPanelResponse:
    """单事务读取发现与最近发布代次的根状态；无扫描时返回空面板和空时间。"""
    query = select(FindingRow).order_by(
        FindingRow.owner_key, FindingRow.group, FindingRow.severity, FindingRow.rule
    )
    if dataset_id is not None:
        query = query.where(FindingRow.owner_key == "dataset:" + dataset_id)
    rows = tuple(session.scalars(query.limit(MAX_ENTRY_MEMBERS + 1)))
    if len(rows) > MAX_ENTRY_MEMBERS:
        raise invalid_field("findings", "发现行数不得超过查询预算")
    scan = session.scalar(select(DatasetScanRow).where(DatasetScanRow.is_current.is_(True)))
    roots = (
        ()
        if scan is None
        else tuple(
            session.scalars(
                select(ScanRootRow)
                .where(ScanRootRow.scan_id == scan.scan_id)
                .order_by(ScanRootRow.name)
            )
        )
    )
    try:
        return DatasetPanelResponse(
            findings=merge(rows),
            storage_roots=tuple(
                IndexedStorageRoot.model_validate(
                    {
                        "name": row.name,
                        "path": row.path,
                        "online": row.online,
                        "reason": row.reason,
                        "checked_at": row.checked_at,
                    }
                )
                for row in roots
            ),
            indexed_at=scan.committed_at if scan else None,
        )
    except ValidationError as error:
        raise invalid_field("panel", "发现和根状态必须满足索引契约") from error


def merge(rows: tuple[FindingRow, ...]) -> tuple[FindingGroup, ...]:
    """按四组/两级/来源/规则合并已聚合记录，不用样例长度替代原始总数。"""
    groups: dict[tuple[PanelGroup, PanelSeverity, str, str], tuple[int, list[Diagnostic]]] = {}
    for row in rows:
        group, severity, samples = decode(row)
        key = (group, severity, samples[0].source, row.rule)
        total, retained = groups.get(key, (0, []))
        retained = sorted(retained + list(samples), key=sample_key)[:DIAGNOSTIC_SAMPLE_LIMIT]
        groups[key] = total + row.total, retained
    order = {value: number for number, value in enumerate(PanelGroup)}
    severity_order = {value: number for number, value in enumerate(PanelSeverity)}
    result: list[FindingGroup] = []
    for key in sorted(
        groups, key=lambda key: (order[key[0]], severity_order[key[1]], key[2], key[3])
    ):
        total, samples = groups[key]
        errors = total if key[1] is PanelSeverity.ACTION_REQUIRED else 0
        # 沿用统一诊断聚合器生成形状，再恢复索引中没有被样例截断的真实总数。
        diagnostics = replace(
            aggregate_diagnostics(samples)[0],
            total=total,
            error_count=errors,
            warning_count=total - errors,
        )
        result.append(FindingGroup(key[0], key[1], diagnostics))
    return tuple(result)


def decode(row: FindingRow) -> tuple[PanelGroup, PanelSeverity, tuple[Diagnostic, ...]]:
    """损坏记录不能静默成为空面板；一个聚合行必须只有一个来源/规则/级别。"""
    try:
        group, severity = PanelGroup(row.group), PanelSeverity(row.severity)
        samples = tuple(Diagnostic.model_validate(sample) for sample in row.samples)
        level = (
            DiagnosticLevel.ERROR
            if severity is PanelSeverity.ACTION_REQUIRED
            else DiagnosticLevel.WARNING
        )
        if (
            not samples
            or not 0 < len(samples) <= min(row.total, DIAGNOSTIC_SAMPLE_LIMIT)
            or len({sample.source for sample in samples}) != 1
            or any(sample.rule != row.rule or sample.level is not level for sample in samples)
        ):
            raise ValueError("发现聚合行不一致")
        return group, severity, samples
    except (ValueError, TypeError) as error:
        raise invalid_field("dataset_findings", "索引发现及总数必须一致且样例有界") from error


def sample_key(sample: Diagnostic) -> tuple[str, tuple[tuple[str, str], ...]]:
    """优先按入口路径排序，再用完整对象身份稳定消除相同路径的歧义。"""
    return next((item.value for item in sample.objects if item.key == "entry_path"), ""), tuple(
        (item.key, item.value) for item in sample.objects
    )
