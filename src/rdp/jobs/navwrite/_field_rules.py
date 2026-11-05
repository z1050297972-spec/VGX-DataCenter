"""字段编辑的纯规则（M1.5-02）：统一可编辑白名单及分页投影，拒绝身份、路径和推导字段。

标准库容器即可表达局部修改；不引入 JSON Patch 依赖，避免把任意 JSON 路径变成写入权限。
"""

import copy
from typing import cast

from rdp.jobs.datasets.types import JsonObject, JsonValue
from rdp.jobs.datasets.vocabulary import UNLABELED
from rdp.jobs.errors import JobInputError
from rdp.jobs.navwrite.errors import nav_input_error
from rdp.jobs.navwrite.field_models import EditableField, FieldEdit, FieldValue

INFO_LABELS = (
    ("title", "标题"),
    ("robot_model", "机器人型号"),
    ("scene", "场景"),
    ("tasks", "任务"),
    ("subtask_notes", "子任务"),
)
TASK_LABELS = (("display_name", "任务名"), ("description", "描述"), ("source_ids", "关联数据块"))
SOURCE_LABELS = (
    ("source_role", "数据块用途"),
    ("validation_status", "人工核验结论"),
    ("notes", "数据块说明"),
)


def objects(document: JsonObject, key: str) -> list[JsonObject]:
    """拒绝坏数组，不跳过坏条目冒充完整表单。"""
    values = document.get(key)
    if not isinstance(values, list) or not all(isinstance(item, dict) for item in values):
        raise nav_input_error("NAV_FIELDS", f"{key} 必须是对象数组")
    return cast(list[JsonObject], values)


def page_fields(
    document: str, payload: JsonObject, offset: int, limit: int
) -> tuple[int, tuple[EditableField, ...]]:
    """只投影请求页的可编辑值，保留绝对条目下标用于后续补丁定位。"""
    fields: list[EditableField] = []
    if document == "数据集信息.json":
        if offset:
            return 1, ()
        for key, label in INFO_LABELS:
            fields.append(
                _field(
                    (key,),
                    label,
                    payload.get(key, [] if key == "tasks" else ""),
                    multiple=key == "tasks",
                )
            )
        for index, item in enumerate(objects(payload, "fields")):
            fields.append(
                _field(
                    ("fields", index, "value_markdown"),
                    f"第 {item.get('number', index + 1)} 项：{item.get('name', '')}",
                    item.get("value_markdown"),
                )
            )
        return 1, tuple(fields)
    array = "tasks" if document == "子任务.json" else "sources"
    rows = objects(payload, array)
    labels = TASK_LABELS if array == "tasks" else SOURCE_LABELS
    for index, item in enumerate(rows[offset : offset + limit], offset):
        for key, label in labels:
            value: JsonValue = item.get(key, "")
            if key == "source_ids":
                value = [
                    str(ref["source_id"])
                    for ref in objects(item, "sources")
                    if isinstance(ref.get("source_id"), str)
                ]
            fields.append(
                _field(
                    (array, index, key),
                    f"{index + 1} · {item.get('task_key', item.get('source_id', ''))} · {label}",
                    value,
                    multiple=key == "source_ids" or isinstance(value, list),
                )
            )
    if array == "sources" and offset == 0:
        fields.append(
            _field(
                ("notes",),
                "入口说明",
                payload.get("notes", []),
                multiple=isinstance(payload.get("notes", []), list),
            )
        )
    return len(rows), tuple(fields)


def apply_edit(
    payload: JsonObject, edit: FieldEdit, known: dict[str, JsonObject]
) -> tuple[JsonValue | None, JsonValue]:
    """分类去空格、任务去重保序后写入；关系编辑只接受已存在引用的 source_id。"""
    path = edit.path
    normalized = _classification_value(edit)
    value: JsonValue = list(normalized) if isinstance(normalized, tuple) else normalized
    target = payload
    key = str(path[-1])
    if len(path) == 3 and isinstance(path[1], int):
        array = str(path[0])
        rows = objects(payload, array)
        if path[1] >= len(rows):
            raise nav_input_error("NAV_FIELDS", "编辑条目不存在")
        target = rows[path[1]]
        if key == "source_ids":
            if not isinstance(value, list):
                raise nav_input_error("NAV_FIELDS", "关联数据块必须是编号数组")
            if len(set(cast(list[str], value))) != len(value) or any(
                str(identifier) not in known for identifier in value
            ):
                raise nav_input_error("NAV_FIELDS", "关联数据块必须已在规范副本中登记，且不能重复")
            before: JsonValue = [ref.get("source_id") for ref in objects(target, "sources")]
            target["sources"] = [copy.deepcopy(known[str(identifier)]) for identifier in value]
            return before, value
        if key != "notes" and not isinstance(value, str):
            raise nav_input_error("NAV_FIELDS", "说明字段必须是文字")
    before = target.get(key)
    target[key] = value
    return before, value


def _field(
    path: tuple[str | int, ...], label: str, value: JsonValue | None, *, multiple: bool = False
) -> EditableField:
    """只接受文本或文本数组；坏值必须明确报错，不能在保存时被空值覆盖。"""
    if isinstance(value, str):
        return EditableField(path=path, label=label, value=value, multiple=multiple)
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return EditableField(
            path=path, label=label, value=tuple(cast(list[str], value)), multiple=multiple
        )
    raise nav_input_error("NAV_FIELDS", "可编辑字段不是文字或文字数组")


def check_shape(edit: FieldEdit) -> None:
    """入队前校验路径、形状和分类值；形状失败交给 Pydantic，分类失败抛 JobInputError。"""
    path = edit.path
    key = str(path[-1])
    array_value = isinstance(edit.value, tuple)
    if len(path) == 1:
        allowed = (
            {name for name, _ in INFO_LABELS}
            if edit.document == "数据集信息.json"
            else {"notes"}
            if edit.document == "原始路径.json"
            else set[str]()
        )
        valid = key in allowed and (key == "notes" or array_value == (key == "tasks"))
    elif len(path) == 3 and isinstance(path[1], int):
        allowed = (
            {"value_markdown"}
            if edit.document == "数据集信息.json" and path[0] == "fields"
            else {name for name, _ in TASK_LABELS}
            if edit.document == "子任务.json" and path[0] == "tasks"
            else {name for name, _ in SOURCE_LABELS}
            if edit.document == "原始路径.json" and path[0] == "sources"
            else set[str]()
        )
        valid = key in allowed and (key == "notes" or array_value == (key == "source_ids"))
    else:
        valid = False
    if not valid:
        raise ValueError("字段路径或值类型不属于编辑范围")
    _classification_value(edit)


def _classification_value(edit: FieldEdit) -> FieldValue:
    """推荐词表允许自定义；分类值去空格，拒绝保留字及空任务，任务去重保序。"""
    if edit.document != "数据集信息.json" or edit.path not in {("scene",), ("tasks",)}:
        return edit.value
    value = edit.value
    if isinstance(value, str):
        normalized = value.strip()
        invalid = normalized == UNLABELED
    else:
        normalized = tuple(dict.fromkeys(item.strip() for item in value))
        invalid = any(not item or item == UNLABELED for item in normalized)
    if invalid:
        # 与普通形状校验一样在入队前拒绝，同时保留导航字段诊断码供调用方定位。
        raise JobInputError(
            nav_input_error(
                "NAV_FIELDS", "场景和任务不能使用未标注保留字，任务项不能为空"
            ).diagnostics
        )
    return normalized


def source_references(manifest: JsonObject, subtasks: JsonObject) -> dict[str, JsonObject]:
    """按编辑前规范副本构造关联候选；同批移交不会被前一项清空影响。"""
    existing = {
        str(ref["source_id"]): ref
        for task in objects(subtasks, "tasks")
        for ref in objects(task, "sources")
        if isinstance(ref.get("source_id"), str)
    }
    result: dict[str, JsonObject] = {}
    for source in objects(manifest, "sources"):
        identifier = str(source["source_id"])
        # 有原引用时保留其范围和证据；首次建立关联只声明整块引用，不猜测episode或视频边界。
        result[identifier] = copy.deepcopy(
            existing.get(
                identifier,
                {
                    "source_id": identifier,
                    "root": source.get("direct_path"),
                    "scope": "whole_root",
                    "format": source.get("format"),
                    "version": source.get("version"),
                    "entry_path": source.get("entry_path"),
                },
            )
        )
    return result
