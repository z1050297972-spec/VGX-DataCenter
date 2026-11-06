"""导航字段表单读取（Web 可读领域边界，M1.5-02）。

只读导航普通 JSON，不跟随数据链接；复用第 01 张描述符读取及标准库 JSON，不访问存储根。
"""

import errno
import hashlib
from pathlib import Path

from sqlalchemy import Engine, select

from rdp.accounts.service import authorize_job_actor
from rdp.infra.db.connection import session_scope
from rdp.infra.diagnostics import InputError
from rdp.jobs.datasets import _io
from rdp.jobs.datasets.models import EntryRow, SourceRow
from rdp.jobs.datasets.types import View
from rdp.jobs.navwrite._field_rules import page_fields
from rdp.jobs.navwrite.errors import nav_conflict_error, nav_external_error, nav_input_error
from rdp.jobs.navwrite.field_models import (
    EditableFieldsPage,
    EditableFieldsQuery,
)
from rdp.jobs.navwrite.jsonio import load_navigation_json
from rdp.jobs.service import JobRequest


def read_editable_fields(
    engine: Engine,
    nav_root: Path,
    request: JobRequest,
    dataset_id: str,
    query: EditableFieldsQuery,
) -> EditableFieldsPage:
    """读取唯一规范副本的有界表单页。

    Args:
        engine: 已迁移受管引擎，用于重验当前账号。
        nav_root: 已配置绝对导航根，不接收请求覆盖。
        request: 认证身份、请求 UTC 时刻和审计上下文。
        dataset_id: 永久编号，须对应唯一规范入口。
        query: 文件名、非负偏移及 1 至 FIELD_PAGE_LIMIT 条的页大小。

    Returns:
        当前文件摘要及有界表单页；未知键仍保存在原文件，不投影成可写项。

    Raises:
        InputError: 无唯一规范入口、文件不可用或字段结构不支持。
        AuthenticationError: 账号会话已失效。
        PasswordChangeRequiredError: 当前账号必须改密。
        ExternalError: 数据库或导航读取失败。
        ConflictError: 授权事务竞争。

    Side Effects:
        无（只读数据库及导航层，不访问存储根）。

    Time Semantics:
        授权事务结束后读取现场文件；sha256 属于本次正文，不保证跨页原子快照。
    """
    document, offset, limit = query.document, query.offset, query.limit
    with session_scope(engine, read_only=True) as session:
        authorize_job_actor(session, request.identity, now=request.now)
        rows = tuple(
            session.scalars(
                select(EntryRow).where(
                    EntryRow.dataset_id == dataset_id, EntryRow.view == View.TASK.value
                )
            )
        )
        if len(rows) != 1:
            problem = nav_input_error(
                "NAV_FIELDS", "数据集必须有唯一可读规范入口", objects=(("dataset_id", dataset_id),)
            )
            raise problem
        path = rows[0].path
        robot_types = tuple(
            sorted(
                {
                    value
                    for value in session.scalars(
                        select(SourceRow.robot_type).where(SourceRow.entry_path == path)
                    )
                    if value is not None
                }
            )
        )
        original_fps = tuple(
            sorted(
                {
                    value
                    for value in session.scalars(
                        select(SourceRow.fps).where(SourceRow.entry_path == path)
                    )
                    if value is not None
                }
            )
        )
    objects = (("dataset_id", dataset_id), ("file", document), ("entry_path", path))
    try:
        with _io.directory(nav_root / path) as descriptor:
            raw = _io.read_file(descriptor, document, _checkpoint)
        payload = load_navigation_json(raw)
    except InputError as error:
        problem = nav_input_error(
            "NAV_FIELDS", "文件内容或大小不符合导航 JSON 契约", objects=objects
        )
        raise problem from error
    except OSError as error:
        if error.errno in (errno.ENOENT, errno.ELOOP, errno.ENOTDIR):
            problem = nav_input_error(
                "NAV_FIELDS", "文件必须存在且为导航层普通文件", objects=objects
            )
            raise problem from error
        if error.errno is None:
            problem = nav_conflict_error("NAV_FIELDS", "文件在读取期间变化", objects=objects)
            raise problem from error
        problem = nav_external_error("NAV_FIELDS", "读取导航文件失败", objects=objects)
        raise problem from error
    if payload.get("dataset_id") != dataset_id:
        problem = nav_input_error(
            "NAV_FIELDS",
            "文件身份与规范入口不一致",
            objects=(("dataset_id", dataset_id), ("file", document)),
        )
        raise problem
    total, fields = page_fields(document, payload, offset, limit)
    return EditableFieldsPage(
        dataset_id=dataset_id,
        entry_path=path,
        document=document,
        sha256=hashlib.sha256(raw).hexdigest(),
        offset=offset,
        limit=limit,
        total=total,
        fields=tuple(fields),
        original_robot_types=robot_types,
        original_fps=original_fps,
    )


def _checkpoint() -> None:
    """HTTP 无 worker 取消信号；读取器仍执行文件大小上限。"""
