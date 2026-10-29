"""个人布局的数据库边界；不写审计、不接收客户端账号编号，不随索引重建删除。"""

from pydantic import TypeAdapter, ValidationError
from sqlalchemy import inspect
from sqlalchemy.orm import Session

from rdp.infra.db.validation import invalid_field
from rdp.infra.diagnostics import DiagnosticCategory, ExternalError
from rdp.jobs.dataset_browser.errors import DatasetQueryError
from rdp.jobs.dataset_browser.preference_models import DatasetLayoutPreferenceRow
from rdp.jobs.dataset_browser.schemas import Layout, LayoutResponse

_LAYOUT = TypeAdapter(Layout)


def read(session: Session, account_id: int) -> LayoutResponse:
    """无行与非法记录不同，默认值只用于确实没有保存过的账号。"""
    require_table(session)
    row = session.get(DatasetLayoutPreferenceRow, account_id)
    if row is None:
        return LayoutResponse(layout="A", updated_at=None)
    try:
        return LayoutResponse.model_validate({"layout": row.layout, "updated_at": row.updated_at})
    except ValidationError as error:
        raise invalid_field("layout", "已保存的布局和UTC时刻必须有效") from error


def require_table(session: Session) -> None:
    """迁移未提供布局表是依赖不可用，不能把SQLite缺表错误变成默认布局或程序缺陷。"""
    if not inspect(session.connection()).has_table(DatasetLayoutPreferenceRow.__tablename__):
        diagnostics = invalid_field("dataset_layout_preferences", "必须先完成0008迁移").diagnostics
        raise ExternalError(
            tuple(
                item.model_copy(update={"category": DiagnosticCategory.EXTERNAL})
                for item in diagnostics
            )
        )


def choice(value: Layout) -> Layout:
    """领域直接调用同样复用布局类型校验，不把客户端错误留到SQL约束变成冲突。"""
    try:
        return _LAYOUT.validate_python(value, strict=True)
    except ValidationError as error:
        raise DatasetQueryError(invalid_field("layout", "布局必须为A、B或C").diagnostics) from error
