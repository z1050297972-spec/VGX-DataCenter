"""详情的血缘索引查询；名称和按任务入口取当前索引，未知编号保留为 null。"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from rdp.jobs.dataset_browser.schemas import DatasetLineage, LineageDownstream, LineageUpstream
from rdp.jobs.datasets.lineage_models import DatasetLineageRow
from rdp.jobs.datasets.models import DatasetRow


def detail(session: Session, dataset_id: str | None) -> DatasetLineage:
    """同一读事务里展开上游并反查下游，重复输入仍按文件序号逐项保留。"""
    if dataset_id is None:
        return DatasetLineage(upstream=(), downstream=())
    upstream = session.execute(
        select(DatasetLineageRow, DatasetRow)
        .outerjoin(DatasetRow, DatasetRow.dataset_id == DatasetLineageRow.input_dataset_id)
        .where(DatasetLineageRow.dataset_id == dataset_id)
        .order_by(DatasetLineageRow.ordinal)
    )
    up = tuple(
        LineageUpstream(
            record_id=relation.record_id,
            dataset_id=relation.input_dataset_id,
            name=dataset.name if dataset else None,
            entry_path=dataset.canonical_entry_path if dataset else None,
            note=relation.note,
            removable=relation.removable,
        )
        for relation, dataset in upstream
    )
    downstream = session.execute(
        select(DatasetLineageRow, DatasetRow)
        .outerjoin(DatasetRow, DatasetRow.dataset_id == DatasetLineageRow.dataset_id)
        .where(
            DatasetLineageRow.input_dataset_id == dataset_id,
            DatasetLineageRow.dataset_id != dataset_id,
        )
        .order_by(DatasetLineageRow.dataset_id, DatasetLineageRow.ordinal)
    )
    return DatasetLineage(
        upstream=up,
        # worker 一条记录可引用同一数据集的多个 source_id；下游按记录显示一次。
        downstream=tuple(
            {
                (relation.dataset_id, relation.record_id): LineageDownstream(
                    record_id=relation.record_id,
                    dataset_id=relation.dataset_id,
                    name=dataset.name if dataset else None,
                    entry_path=dataset.canonical_entry_path if dataset else None,
                    note=relation.note,
                )
                for relation, dataset in downstream
            }.values()
        ),
    )
