"""采集字段的预览规则：验证当前登记状态，并把默认来源纳入同一份可确认计划。"""

from sqlalchemy import Engine

from rdp.collection._references import references
from rdp.collection.information import CollectionInformation, read_collection
from rdp.collection.models import MethodRow
from rdp.infra.db.connection import session_scope
from rdp.jobs.datasets.types import JsonObject
from rdp.jobs.navwrite.errors import nav_input_error
from rdp.jobs.navwrite.field_models import FieldEditParameters


def prepare(engine: Engine, information: JsonObject, parameters: FieldEditParameters) -> None:
    """只在修改采集字段时验证新值，历史停用项按同一字段的原编号放行。"""
    edit = next(
        (
            item
            for item in parameters.changes
            if item.document == "数据集信息.json" and item.path == ("collection",)
        ),
        None,
    )
    if edit is None or not isinstance(edit.value, CollectionInformation):
        return
    previous = read_collection(information.get("collection"))
    old_ids = {field: ids for field, _, ids in references(previous)} if previous else {}
    value = edit.value
    with session_scope(engine, read_only=True) as session:
        for field, model, identifiers in references(value):
            for identifier in identifiers:
                row = session.get(model, identifier)
                if row is None:
                    raise nav_input_error(
                        "NAV_FIELDS", f"collection.{field} 引用的编号 {identifier} 不存在"
                    )
                if row.status == "retired" and identifier not in old_ids.get(field, ()):
                    raise nav_input_error(
                        "NAV_FIELDS",
                        f"collection.{field} 不能新选停用的编号 {identifier}（{row.name}）",
                    )
        # 显式提交的来源优先，包括主动改回未知；自动补值必须出现在同一份预览差异中。
        explicit_origin = any(
            item.document == "数据集信息.json" and item.path == ("data_origin",)
            for item in parameters.changes
        )
        origin = information.get("data_origin")
        empty_origin = origin is None or isinstance(origin, str) and origin.strip() in {"", "未知"}
        if value.method_id is not None and empty_origin and not explicit_origin:
            method = session.get(MethodRow, value.method_id)
            if method is not None:
                information["data_origin"] = method.data_origin
