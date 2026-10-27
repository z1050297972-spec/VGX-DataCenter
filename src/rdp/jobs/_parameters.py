"""提交与每日登记共用的参数校验（领域内部）；只验证有界JSON及当前模型，不执行作业或访问数据库。"""

import json
from typing import cast

from pydantic import ValidationError

from rdp.infra.db.validation import invalid_field
from rdp.infra.diagnostics import DefectError
from rdp.jobs.errors import JobInputError
from rdp.jobs.policy import JOB_PARAMETERS_MAX_BYTES
from rdp.jobs.registry import JobDefinition, JobRegistry


def validate(
    registry: JobRegistry, type_name: str, parameters: dict[str, object]
) -> tuple[JobDefinition, dict[str, object]]:
    """参数校验在写事务外；只把固定字段诊断暴露给调用者，不回显拒绝的载荷。"""
    try:
        definition = registry.lookup(type_name)
    except DefectError:
        definition = None
    if definition is None:
        raise JobInputError(invalid_field("type_name", "已登记的作业类型").diagnostics)
    try:
        if (
            not isinstance(cast(object, parameters), dict)
            or len(json.dumps(parameters, ensure_ascii=False, allow_nan=False).encode())
            > JOB_PARAMETERS_MAX_BYTES
        ):
            raise ValueError("参数不是有界JSON对象")
        checked = definition.parameters_model.model_validate(parameters).model_dump(mode="json")
        if (
            len(json.dumps(checked, ensure_ascii=False, allow_nan=False).encode())
            > JOB_PARAMETERS_MAX_BYTES
        ):
            raise ValueError("完整参数超过容量")
    except (ValidationError, TypeError, ValueError, UnicodeError):
        raise JobInputError(
            invalid_field("parameters", "当前作业类型的合法有界参数").diagnostics
        ) from None
    return definition, checked
