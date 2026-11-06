"""提交与每日登记共用的参数校验（领域内部）；只验证有界JSON及当前模型，不执行作业或访问数据库。"""

import json
from typing import cast

from pydantic import ValidationError

from rdp.infra.db.validation import invalid_field
from rdp.infra.diagnostics import (
    DefectError,
    Diagnostic,
    DiagnosticCategory,
    DiagnosticLevel,
    DiagnosticObject,
)
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
        if not isinstance(cast(object, parameters), dict):
            raise ValueError("参数不是JSON对象")
        _check_size(parameters)
        checked = definition.parameters_model.model_validate(parameters).model_dump(mode="json")
        _check_size(checked)
    except (ValidationError, TypeError, ValueError, UnicodeError):
        raise JobInputError(
            invalid_field("parameters", "当前作业类型的合法有界参数").diagnostics
        ) from None
    return definition, checked


def _check_size(parameters: dict[str, object]) -> None:
    """按UTF-8 JSON字节校验原始及补全参数；容量错误独立报告且不回显正文。"""
    if (
        len(json.dumps(parameters, ensure_ascii=False, allow_nan=False).encode("utf-8"))
        <= JOB_PARAMETERS_MAX_BYTES
    ):
        return
    raise JobInputError(
        (
            Diagnostic(
                level=DiagnosticLevel.ERROR,
                category=DiagnosticCategory.INPUT,
                stage="作业参数校验",
                source="平台",
                objects=(DiagnosticObject(key="field", value="parameters"),),
                rule="JOB_PARAMETERS_SIZE",
                actual="本次修改内容太长，作业参数超过容量上限（原值不回显）",
                expected=f"完整作业参数的 UTF-8 JSON 不超过 1 MiB（{JOB_PARAMETERS_MAX_BYTES} 字节）",
                consequence="本次操作被拒绝，未提交作业",
                next_step="缩短内容或拆成多次修改后重新预览",
            ),
        )
    )
