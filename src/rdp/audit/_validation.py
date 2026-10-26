"""日志领域的纯字段校验，复用Pydantic、UTC与诊断工具；不读库或记录输入原文。"""

import json
from dataclasses import replace
from datetime import datetime
from typing import cast

from pydantic import ValidationError

from rdp.audit._context import validate_context
from rdp.audit.errors import AuditInputError
from rdp.audit.policy import MAX_DETAILS_BYTES
from rdp.audit.types import (
    OPERATION_DETAIL_FIELDS,
    AuditValues,
    LoginEvent,
    LoginKind,
    LoginResult,
    ObjectRef,
    OperationDetails,
    OperationEvent,
    OperationResult,
    OperationType,
)
from rdp.infra.actors import OPS_ACTOR, ActorRef, is_display_name
from rdp.infra.db.validation import invalid_field
from rdp.infra.diagnostics import DefectError, DiagnosticCategory
from rdp.infra.ids import MAX_SQLITE_INTEGER
from rdp.infra.timeutil import ensure_utc


def invalid(field: str) -> AuditInputError:
    """仅用可信字段名构造安全诊断，不把任意拒绝值或序列化异常挂到错误链。"""
    return AuditInputError(invalid_field(field, "符合日志字段类型、范围和组合约束").diagnostics)


def identifier(value: object) -> int:
    """严格限制SQLite正整数编号，拒绝bool与浮点等隐式转换。"""
    if type(value) is not int or not 1 <= value <= MAX_SQLITE_INTEGER:
        raise invalid("account_id")
    return value


def moment(value: datetime) -> datetime:
    """沿用基础层UTC换算，日期边界溢出与naive值都不回显。"""
    try:
        return ensure_utc(value)
    except (TypeError, ValueError, OverflowError):
        raise invalid("occurred_at") from None


def name(value: object) -> str:
    """历史名字保留原文但拒绝空白边界和不可显示的控制字符。"""
    if not is_display_name(value):
        raise invalid("name")
    return value


def actor(value: object) -> None:
    """账号身份必须是原编号快照；只有运维可以没有编号。"""
    if not isinstance(value, ActorRef):
        raise invalid("actor")
    name(value.name)
    if value.account_id is None:
        if value.name != OPS_ACTOR.name:
            raise invalid("actor")
    else:
        identifier(value.account_id)


def target(value: object) -> None:
    """限定对象类型及规范账号编号文本，不把设置对象的键当作账号。"""
    if not isinstance(value, ObjectRef) or value.kind not in {"account", "audit_settings"}:
        raise invalid("target")
    name(value.name)
    if value.kind == "audit_settings":
        if value.object_id != "retention" or value.name != "日志保留期":
            raise invalid("target")
    elif value.object_id is not None:
        key = value.object_id
        if (
            not isinstance(cast(object, key), str)
            or len(key) > 19
            or not key.isascii()
            or not key.isdecimal()
            or str(int(key)) != key
        ):
            raise invalid("target")
        identifier(int(key))


def details(value: object, operation: OperationType) -> OperationDetails:
    """重验已构造模型，防止model_construct/model_copy绕过边界及逐操作白名单。"""
    if not isinstance(value, OperationDetails):
        raise invalid("details")
    try:
        checked = OperationDetails.model_validate(
            value.model_dump(exclude_none=True, warnings=False)
        )
        encoded = checked.model_dump(mode="json", exclude_none=True)
        if len(json.dumps(encoded, ensure_ascii=False).encode("utf-8")) > MAX_DETAILS_BYTES:
            raise invalid("details")
    except (ValidationError, TypeError, ValueError, UnicodeError):
        raise invalid("details") from None
    allowed = OPERATION_DETAIL_FIELDS[operation]
    if not (checked.before.model_fields_set | checked.after.model_fields_set) <= allowed:
        raise invalid("details")
    return checked


def operation(value: object) -> OperationEvent:
    """验证一条操作事件的类型、上下文和成功/失败结构，返回UTC副本。"""
    if (
        not isinstance(value, OperationEvent)
        or not isinstance(cast(object, value.operation), OperationType)
        or not isinstance(cast(object, value.result), OperationResult)
    ):
        raise invalid("event")
    validate_context(value.context, request=False)
    actor(value.actor)
    target(value.target)
    checked = details(value.details, value.operation)
    operation_shape(value, checked)
    if value.result is OperationResult.SUCCESS:
        if value.failure_category is not None:
            raise invalid("failure_category")
    elif not isinstance(value.failure_category, DiagnosticCategory) or checked.after.model_dump(
        exclude_none=True
    ):
        raise invalid("failure_category")
    return replace(value, occurred_at=moment(value.occurred_at), details=checked)


def operation_shape(value: OperationEvent, checked: OperationDetails) -> None:
    """区分创建、删除与设置的前后值，避免撤回结构把未提交状态当成事实。"""
    creating = value.operation in {OperationType.CREATE_ACCOUNT, OperationType.CREATE_FIRST_ADMIN}
    if creating and checked.before.model_dump(exclude_none=True):
        raise invalid("before")
    if value.operation is OperationType.DELETE_ACCOUNT and checked.after.model_dump(
        exclude_none=True
    ):
        raise invalid("after")
    if (value.operation is OperationType.SET_RETENTION) != (value.target.kind == "audit_settings"):
        raise invalid("target")
    if value.result is OperationResult.SUCCESS and value.target.object_id is None:
        raise invalid("target")


def login(value: object) -> LoginEvent:
    """登录类型与结果必须相容，未知身份不允许通过任何名字字段保存输入原文。"""
    if (
        not isinstance(value, LoginEvent)
        or not isinstance(cast(object, value.kind), LoginKind)
        or not isinstance(cast(object, value.result), LoginResult)
    ):
        raise invalid("login_event")
    validate_context(value.context, request=False)
    if value.kind is not LoginKind.LOGIN and value.result is not LoginResult.SUCCESS:
        raise invalid("login_result")
    if value.result is LoginResult.FAILURE:
        if not isinstance(value.failure_category, DiagnosticCategory):
            raise invalid("failure_category")
    elif value.failure_category is not None:
        raise invalid("failure_category")
    login_identity(value)
    return replace(value, occurred_at=moment(value.occurred_at))


def login_identity(value: LoginEvent) -> None:
    """未知账号或未确认身份的执行故障必须匿名，已确认身份保留完整快照。"""
    if value.account is None:
        if (
            value.result not in {LoginResult.ACCOUNT_MISSING, LoginResult.FAILURE}
            or value.login_name is not None
        ):
            raise invalid("account")
        if value.context.request_id is not None:
            raise DefectError()
    else:
        actor(value.account)
        identifier(value.account.account_id)
        if value.result is LoginResult.ACCOUNT_MISSING or value.login_name is None:
            raise invalid("login_name")
        try:
            AuditValues(login_name=value.login_name)
        except ValidationError:
            raise invalid("login_name") from None
