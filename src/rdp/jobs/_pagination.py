"""作业按自增编号翻页的内部游标；标准库base64/JSON编码，绑定筛选与首页上界，拒绝损坏输入。"""

import base64
import json
import re
from typing import cast

from rdp.infra.db.validation import invalid_field
from rdp.infra.ids import MAX_SQLITE_INTEGER
from rdp.jobs.errors import JobInputError
from rdp.jobs.policy import JOB_CURSOR_MAX_CHARS, JOB_PAGE_LIMIT
from rdp.jobs.types import JobQuery, JobState


def decode(query: JobQuery) -> tuple[int, int] | None:
    """返回首页最大编号和上页末编号；非法游标绝不回退首页。"""
    if (
        type(query.limit) is not int
        or not 1 <= query.limit <= JOB_PAGE_LIMIT
        or (query.state is not None and not isinstance(cast(object, query.state), JobState))
    ):
        raise JobInputError(invalid_field("query", "有效状态和1至100的分页上限").diagnostics)
    if query.cursor is None:
        return None
    try:
        value = query.cursor
        if len(value) > JOB_CURSOR_MAX_CHARS or re.fullmatch(r"[A-Za-z0-9_-]+", value) is None:
            raise ValueError("非法编码")
        data: object = json.loads(
            base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)
        )
        if not isinstance(data, dict) or set(cast(dict[str, object], data)) != {
            "v",
            "state",
            "limit",
            "head",
            "last",
        }:
            raise ValueError("非法结构")
        fields = cast(dict[str, object], data)
        if (
            fields["v"] != 1
            or type(fields["v"]) is not int
            or fields["state"] != query.state
            or fields["limit"] != query.limit
            or type(fields["limit"]) is not int
        ):
            raise ValueError("游标与查询不匹配")
        head, last = fields["head"], fields["last"]
        if (
            type(head) is not int
            or type(last) is not int
            or not 1 <= last <= head <= MAX_SQLITE_INTEGER
        ):
            raise ValueError("非法编号")
        return head, last
    except (ValueError, TypeError, UnicodeError):
        raise JobInputError(
            invalid_field("cursor", "当前筛选与每页上限对应的有效游标").diagnostics
        ) from None


def encode(query: JobQuery, head: int, last: int) -> str:
    """只编码必要的固定字段，编号整数在服务端编码，不经浏览器Number。"""
    data = {"v": 1, "state": query.state, "limit": query.limit, "head": head, "last": last}
    return (
        base64.urlsafe_b64encode(json.dumps(data, separators=(",", ":")).encode())
        .decode()
        .rstrip("=")
    )
