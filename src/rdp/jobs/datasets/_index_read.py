"""索引基线的有界读取；不加载完整导航文档，数据库错误交外层受管事务分类。"""

from pathlib import Path

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from rdp.infra.diagnostics import DefectError
from rdp.jobs.datasets._issues import input_error
from rdp.jobs.datasets.catalog import MAX_SCAN_ENTRIES
from rdp.jobs.datasets.fingerprint import DatasetFingerprint, EntryFingerprint
from rdp.jobs.datasets.models import DatasetRow, EntryRow
from rdp.jobs.datasets.scan_types import IndexedDataset


def baseline(
    session: Session, requested: str | None, nav_root: Path | None
) -> tuple[IndexedDataset, ...]:
    """无法识别编号的行通过显式导航根恢复指纹范围，不用虚构根路径。"""
    query = select(DatasetRow).order_by(DatasetRow.dataset_id).limit(MAX_SCAN_ENTRIES + 1)
    if requested is not None:
        if not requested.strip():
            raise input_error("索引", "数据集编号为空")
        query = query.where(DatasetRow.dataset_id == requested)
    result: list[IndexedDataset] = []
    try:
        for row in session.scalars(query):
            fingerprint = DatasetFingerprint.model_validate(row.fingerprint)
            paths = tuple(
                session.scalars(
                    select(EntryRow.path)
                    .where(EntryRow.dataset_id == row.dataset_id)
                    .order_by(EntryRow.path)
                )
            )
            result.append(IndexedDataset(row.dataset_id, paths, fingerprint))
        if requested is None:
            for row in session.scalars(
                select(EntryRow).where(EntryRow.dataset_id.is_(None)).limit(MAX_SCAN_ENTRIES + 1)
            ):
                if nav_root is None:
                    raise DefectError()
                fingerprint = DatasetFingerprint(
                    nav_root=str(nav_root),
                    dataset_id=None,
                    entries=(EntryFingerprint.model_validate(row.fingerprint),),
                    verifiable=False,
                )
                result.append(IndexedDataset(None, (row.path,), fingerprint))
    except ValidationError as error:
        raise input_error("索引", "持久化指纹损坏") from error
    if len(result) > MAX_SCAN_ENTRIES:
        raise input_error("索引", "基线入口超过预算")
    return tuple(result)
