"""扫描事务内替换血缘投影；所有记录共用同一输入投影，不按记录人或来源种类过滤。"""

from sqlalchemy import delete
from sqlalchemy.orm import Session

from rdp.jobs.datasets.lineage_models import DatasetLineageRow
from rdp.jobs.datasets.types import EntrySnapshot


def replace(session: Session, dataset_id: str, entry: EntrySnapshot | None) -> None:
    """只投影唯一规范入口，删除旧关联和新增关联由扫描发布事务一起提交。"""
    session.execute(delete(DatasetLineageRow).where(DatasetLineageRow.dataset_id == dataset_id))
    if entry is None:
        return
    session.add_all(
        [
            DatasetLineageRow(
                dataset_id=dataset_id,
                ordinal=ordinal,
                record_id=value.record_id,
                input_dataset_id=value.dataset_id,
                note=value.note,
                removable=value.removable,
            )
            for ordinal, value in enumerate(entry.lineage)
        ]
    )
