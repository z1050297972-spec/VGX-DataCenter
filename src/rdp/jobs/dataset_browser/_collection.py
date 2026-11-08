"""采集筛选与详情投影；只读本次事务的索引和登记表，不访问导航或数据盘。"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from rdp.collection.information import CollectionInformation
from rdp.collection.models import MethodRow, PurposeRow, RegistryRow, RobotRow
from rdp.jobs.dataset_browser._index import Index
from rdp.jobs.dataset_browser.schemas import (
    CollectionMethod,
    CollectionRobot,
    CollectionTerm,
    DatasetCollection,
    FilterOption,
)
from rdp.jobs.datasets.vocabulary import UNLABELED


def _options(
    values: tuple[tuple[str, ...], ...], labels: dict[str, str]
) -> tuple[FilterOption, ...]:
    """每数据集一次计数，登记项保留零计数，未知编号追加，未标注固定最后。"""
    counts: dict[str, int] = {}
    for row in values:
        for code in set(row):
            counts[code] = counts.get(code, 0) + 1
    codes = tuple(labels) + tuple(sorted(counts.keys() - labels.keys(), key=int))
    return tuple(
        FilterOption(
            value=code, label=labels.get(code, f"未知编号 {code}"), count=counts.get(code, 0)
        )
        for code in codes
    ) + (FilterOption(value=UNLABELED, label="无采集信息", count=sum(not row for row in values)),)


def options(session: Session, index: Index) -> dict[str, tuple[FilterOption, ...]]:
    """候选用当前登记名称，计数只来自唯一规范副本的采集索引。"""
    values = tuple(index.collections.get(row.dataset_id) for row in index.datasets)
    result = {
        "collection_statuses": _options(
            tuple((value.status,) if value else () for value in values),
            {"planned": "计划中", "collecting": "采集中", "done": "已完成"},
        )
    }
    for key, model, groups in (
        (
            "collection_methods",
            MethodRow,
            tuple(
                (str(value.method_id),) if value and value.method_id is not None else ()
                for value in values
            ),
        ),
        (
            "collection_purposes",
            PurposeRow,
            tuple(
                (str(value.purpose_id),) if value and value.purpose_id is not None else ()
                for value in values
            ),
        ),
        (
            "collection_robots",
            RobotRow,
            tuple(tuple(map(str, value.robot_ids)) if value else () for value in values),
        ),
    ):
        labels = {
            str(row.id): row.name for row in session.scalars(select(model).order_by(model.id))
        }
        result[key] = _options(groups, labels)
    return result


def _term(session: Session, model: type[RegistryRow], identifier: int) -> dict[str, object]:
    """缺号时保留身份，不能以空对象冒充未填写。"""
    row = session.get(model, identifier)
    return dict(
        id=identifier, name=row.name if row else None, status=row.status if row else "missing"
    )


def detail(session: Session, value: CollectionInformation | None) -> DatasetCollection | None:
    """详情按编号取当前名称和状态，未知编号明确标 missing。"""
    if value is None:
        return None
    method = None
    if value.method_id is not None:
        row = session.get(MethodRow, value.method_id)
        method = CollectionMethod.model_validate(
            _term(session, MethodRow, value.method_id)
            | {"data_origin": row.data_origin if row else None}
        )
    purpose = (
        None
        if value.purpose_id is None
        else CollectionTerm.model_validate(_term(session, PurposeRow, value.purpose_id))
    )
    robots: list[CollectionRobot] = []
    for identifier in value.robot_ids:
        fields = _term(session, RobotRow, identifier)
        fields["robot_id"] = fields.pop("id")
        robots.append(CollectionRobot.model_validate(fields))
    return DatasetCollection(
        status=value.status, method=method, purpose=purpose, robots=tuple(robots)
    )
