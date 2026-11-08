"""在扫描发布事务内替换采集索引并生成未知编号提示，不修改导航或登记对象。"""

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from rdp.collection._references import references
from rdp.collection.index_models import DatasetCollectionRobotRow, DatasetCollectionRow
from rdp.jobs.datasets._issues import finding
from rdp.jobs.datasets.types import EntrySnapshot, Finding


def replace(session: Session, dataset_id: str, entry: EntrySnapshot | None) -> tuple[Finding, ...]:
    """规范副本唯一时才投影，先删除旧关联，未知编号仍保留在新索引中。"""
    session.execute(
        delete(DatasetCollectionRow).where(DatasetCollectionRow.dataset_id == dataset_id)
    )
    value = entry.collection if entry else None
    if value is None or entry is None:
        return ()
    session.add(
        DatasetCollectionRow(
            dataset_id=dataset_id,
            status=value.status,
            method_id=value.method_id,
            purpose_id=value.purpose_id,
        )
    )
    # 先写父行再写关联，SQLite 外键即时检查；关联顺序保留导航中的选择顺序。
    session.flush()
    session.add_all(
        [
            DatasetCollectionRobotRow(dataset_id=dataset_id, robot_id=identifier, ordinal=ordinal)
            for ordinal, identifier in enumerate(value.robot_ids)
        ]
    )
    issues: list[Finding] = []
    for field, model, identifiers in references(value):
        existing = set(session.scalars(select(model.id).where(model.id.in_(identifiers))))
        for identifier in identifiers:
            if identifier not in existing:
                issues.append(
                    finding(
                        str(entry.location.path),
                        "COLLECTION_UNKNOWN_REF",
                        f"collection.{field} 引用了不存在的编号 {identifier}",
                        notice=True,
                    )
                )
    return tuple(issues)
