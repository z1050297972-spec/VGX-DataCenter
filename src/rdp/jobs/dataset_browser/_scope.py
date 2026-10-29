"""数据集范围校验，只读永久编号索引；不检查导航或存储路径是否存在。"""

from pydantic import TypeAdapter, ValidationError
from sqlalchemy.orm import Session

from rdp.infra.db.validation import invalid_field
from rdp.jobs.dataset_browser.errors import DatasetNotFoundError, DatasetQueryError
from rdp.jobs.dataset_browser.schemas import DatasetId
from rdp.jobs.datasets.models import DatasetRow

_IDENTIFIER = TypeAdapter(DatasetId)


def identifier(value: str) -> str:
    """复用已批准的编号类型，拒绝空白、路径分隔符及None，不回显原值。"""
    try:
        return _IDENTIFIER.validate_python(value, strict=True)
    except ValidationError as error:
        raise DatasetQueryError(invalid_field("dataset_id", "有效永久编号").diagnostics) from error


def require_dataset(session: Session, value: str | None) -> None:
    """None是明确的全量范围，其余编号必须在同一次查询事务中存在。"""
    if value is not None and session.get(DatasetRow, identifier(value)) is None:
        raise DatasetNotFoundError(invalid_field("dataset_id", "已入索引的数据集").diagnostics)
