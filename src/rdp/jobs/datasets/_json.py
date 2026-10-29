"""导航JSON内部结构校验；只检查依赖字段，不剥除未知数据。"""

from pathlib import PurePosixPath
from typing import cast

from rdp.jobs.datasets.types import JsonObject, JsonValue


def object_value(value: object) -> JsonObject:
    """依赖记录必须是对象，不能把数组或null当成空对象。"""
    if not isinstance(value, dict):
        raise ValueError("需要JSON对象")
    return cast(JsonObject, value)


def text(value: JsonValue, field: str) -> str:
    """非空身份字段不接受数值强转，错误只包含字段名。"""
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise ValueError(field)
    return value


def objects(value: JsonValue, field: str) -> tuple[JsonObject, ...]:
    """保留数组顺序和重复项，不把非法清单默默变成空清单。"""
    if not isinstance(value, list):
        raise ValueError(field)
    return tuple(object_value(item) for item in value)


def validate(payload: JsonObject, name: str) -> None:
    """按三类文件分别核对依赖字段，子任务内容不在读取层解释。"""
    text(payload.get("dataset_id"), "dataset_id")
    if name == "原始路径.json":
        text(payload.get("dataset_name"), "dataset_name")
        roots = payload.get("dataset_roots")
        if not isinstance(roots, list):
            raise ValueError("dataset_roots")
        for root in roots:
            absolute(root, "dataset_roots")
        _records(payload, "links", ("name", "source_path", "source_type"))
        _records(payload, "sources", ("source_id", "original_path", "direct_path"))
    if name == "数据集信息.json":
        for item in objects(payload.get("fields"), "fields"):
            if type(item.get("number")) is not int or not isinstance(
                item.get("value_markdown"), str
            ):
                raise ValueError("fields.number/value_markdown")
            text(item.get("name"), "fields.name")


def _records(payload: JsonObject, key: str, required: tuple[str, ...]) -> None:
    """依赖子项缺失时整文件不可用，保留字段路径便于定位。"""
    for item in objects(payload.get(key), key):
        for field in required:
            value = text(item.get(field), key + "." + field)
            if field.endswith("_path"):
                absolute(value, key + "." + field)
            if key == "links" and field == "name" and ("/" in value or value in {".", ".."}):
                raise ValueError("links.name")


def finite_number(value: str) -> float:
    """标准库JSON的浮点和非标准常量入口统一拒绝NaN及溢出。"""
    import math

    number = float(value)
    if not math.isfinite(number):
        raise ValueError("非有限数值")
    return number


def absolute(value: JsonValue, field: str) -> str:
    """声明路径只作词法校验，不能为了验证读取契约访问存储根。"""
    result = text(value, field)
    if not PurePosixPath(result).is_absolute():
        raise ValueError(field)
    return result
