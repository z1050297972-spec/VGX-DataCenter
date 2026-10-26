"""日志领域游标查询的公共机制；复用JSON/base64/SQLAlchemy，游标绑定本项目筛选与首页上界。"""

import base64
import hashlib
import json
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Literal, cast

from sqlalchemy import ColumnElement, and_, func, or_, select
from sqlalchemy.orm import Session

from rdp.audit import _validation as validate
from rdp.audit.errors import AuditInputError
from rdp.audit.models import LoginLogRow, OperationLogRow
from rdp.audit.policy import AUDIT_CURSOR_MAX_CHARS, AUDIT_PAGE_LIMIT
from rdp.audit.types import (
    AuditContext,
    ExistingAccounts,
    LoginEvent,
    LoginKind,
    LoginResult,
    LogQuery,
    ObjectRef,
    OperationDetails,
    OperationEvent,
    OperationResult,
    OperationType,
)
from rdp.infra.actors import ActorRef
from rdp.infra.db.validation import invalid_field
from rdp.infra.diagnostics import (
    ConflictError,
    DefectError,
    DiagnosticCategory,
    ExternalError,
    InputError,
)


@dataclass(frozen=True)
class Selection:
    """已规范化的筛选与游标，不接受未经过边界校验的SQL参数。

    Attributes:
        common: 校验后的LogQuery；时间为UTC微秒，分页上限100，必填。
        fingerprint: 全部规范化筛选的SHA-256十六进制摘要，64字符，必填。
        maximum: 首页最大日志编号，1至2^63-1；首页尚未读取时为None。
        last_time: 上页末项UTC微秒时刻；首页为None。
        last_id: 上页末项正整数编号，与last_time组成排序键；首页为None。
    """

    common: LogQuery
    fingerprint: str
    maximum: int | None
    last_time: datetime | None
    last_id: int | None


def prepare(common: LogQuery, filters: dict[str, object]) -> Selection:
    """把时间统一成UTC并把日志类型及全部筛选绑定到摘要，不把cursor自己纳入摘要。"""
    if not isinstance(cast(object, common), LogQuery):
        raise validate.invalid("query")
    if type(common.limit) is not int or not 1 <= common.limit <= AUDIT_PAGE_LIMIT:
        raise validate.invalid("limit")
    if common.account_id is not None:
        validate.identifier(common.account_id)
    start = None if common.start is None else validate.moment(common.start)
    end = None if common.end is None else validate.moment(common.end)
    if start is not None and end is not None and start >= end:
        raise validate.invalid("range")
    common = replace(common, start=start, end=end)
    payload = filters | {
        "start": None if start is None else start.isoformat(),
        "end": None if end is None else end.isoformat(),
        "account": common.account_id,
        "limit": common.limit,
    }
    fingerprint = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    if common.cursor is None:
        return Selection(common, fingerprint, None, None, None)
    maximum, moment, last = decode(common.cursor, fingerprint)
    if (start is not None and moment < start) or (end is not None and moment >= end):
        raise validate.invalid("cursor")
    return Selection(common, fingerprint, maximum, moment, last)


def decode(value: str, fingerprint: str) -> tuple[int, datetime, int]:
    """解码有界的v1游标，严格拒绝版本、键形状、筛选摘要和编号范围不匹配。"""
    if (
        not isinstance(cast(object, value), str)
        or not 1 <= len(value) <= AUDIT_CURSOR_MAX_CHARS
        or not value.isascii()
    ):
        raise validate.invalid("cursor")
    try:
        raw = base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)
        payload: dict[str, object] = json.loads(raw)
        if not isinstance(cast(object, payload), dict) or set(payload) != {"v", "h", "t", "i", "f"}:
            raise validate.invalid("cursor")
        if type(payload["v"]) is not int or payload["v"] != 1 or payload["f"] != fingerprint:
            raise validate.invalid("cursor")
        maximum, last = validate.identifier(payload["h"]), validate.identifier(payload["i"])
        timestamp = payload["t"]
        if not isinstance(timestamp, str) or last > maximum:
            raise validate.invalid("cursor")
        return maximum, validate.moment(datetime.fromisoformat(timestamp)), last
    except (ValueError, TypeError, UnicodeError):
        raise validate.invalid("cursor") from None


def encode(row: OperationLogRow | LoginLogRow, maximum: int, fingerprint: str) -> str:
    """仅编码已验证行的排序键和首页上界，客户端不能以offset制造翻页漂移。"""
    payload = {
        "v": 1,
        "h": maximum,
        "t": row.occurred_at.isoformat(),
        "i": row.log_id,
        "f": fingerprint,
    }
    return (
        base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode())
        .decode()
        .rstrip("=")
    )


def rows[Row: OperationLogRow | LoginLogRow](
    session: Session, model: type[Row], plan: Selection, filters: list[ColumnElement[bool]]
) -> tuple[list[Row], int]:
    """在同一只读快照内固定首页编号上界，取多一行判断是否存在下一页。"""
    if not session.info["rdp_read_only"]:
        raise DefectError()
    maximum = plan.maximum
    if maximum is None:
        maximum = int(session.scalar(select(func.max(model.log_id))) or 0)
    statement = select(model).where(model.log_id <= maximum, *filters)
    if plan.common.start is not None:
        statement = statement.where(model.occurred_at >= plan.common.start)
    if plan.common.end is not None:
        statement = statement.where(model.occurred_at < plan.common.end)
    if plan.last_time is not None:
        statement = statement.where(
            or_(
                model.occurred_at < plan.last_time,
                and_(model.occurred_at == plan.last_time, model.log_id < plan.last_id),
            )
        )
    statement = statement.order_by(model.occurred_at.desc(), model.log_id.desc()).limit(
        plan.common.limit + 1
    )
    return list(session.scalars(statement)), maximum


def existing(
    session: Session, identifiers: frozenset[int], lookup: ExistingAccounts
) -> frozenset[int]:
    """调用同事务的上层存在性接口，并拒绝扩大身份集合或异常失控的适配器。"""
    try:
        result = lookup(session, identifiers)
        if (
            not isinstance(cast(object, result), frozenset)
            or not result <= identifiers
            or any(type(item) is not int for item in result)
        ):
            raise DefectError()
        return result
    except (InputError, ConflictError, ExternalError, DefectError):
        raise
    except Exception:
        raise DefectError() from None


def operation_event(row: OperationLogRow) -> OperationEvent:
    """重验存量行，损坏数据归InputError而不是用户字段错误，不跳过坏行。"""
    try:
        event = OperationEvent(
            row.occurred_at,
            ActorRef(row.actor_id, row.actor_name),
            OperationType(row.operation),
            ObjectRef(
                cast(Literal["account", "audit_settings"], row.object_kind),
                row.object_id,
                row.object_name,
            ),
            OperationResult(row.result),
            None if row.failure_category is None else DiagnosticCategory(row.failure_category),
            AuditContext(row.source_ip, row.request_id),
            OperationDetails.model_validate(row.details),
        )
        return validate.operation(event)
    except (ValueError, TypeError, AuditInputError, DefectError):
        raise invalid_field("operation_logs", "已存操作日志满足版本及快照约束") from None


def login_event(row: LoginLogRow) -> LoginEvent:
    """将已存登录行变成安全快照；损坏的账号组合或类型按存量数据问题返回。"""
    try:
        account = (
            None if row.account_id is None else ActorRef(row.account_id, row.account_name or "")
        )
        if row.account_id is None and row.account_name is not None:
            raise validate.invalid("account")
        event = LoginEvent(
            row.occurred_at,
            account,
            row.login_name,
            LoginKind(row.kind),
            LoginResult(row.result),
            AuditContext(row.source_ip, row.request_id),
            None if row.failure_category is None else DiagnosticCategory(row.failure_category),
        )
        return validate.login(event)
    except (ValueError, TypeError, AuditInputError, DefectError):
        raise invalid_field("login_logs", "已存登录事件满足身份和结果约束") from None
