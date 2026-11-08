"""血缘编辑的只读边界；索引定位规范入口，沿用受限文件读取，不访问数据链接目标。"""

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import Engine

from rdp.infra.db.connection import session_scope
from rdp.jobs.dataset_browser import _scope
from rdp.jobs.datasets import _io
from rdp.jobs.datasets.models import DatasetRow
from rdp.jobs.datasets.types import JsonObject, ProvenanceState
from rdp.jobs.errors import JobInputError
from rdp.jobs.navwrite.errors import nav_conflict_error, nav_external_error, nav_input_error
from rdp.jobs.navwrite.jsonio import load_navigation_json
from rdp.jobs.navwrite.lineage_parameters import LineageParameters
from rdp.jobs.navwrite.provenance import ProvenanceDocument, new_provenance, read_provenance


@dataclass(frozen=True)
class LineageSource:
    """同一原字节的已验证文档和保序对象。

    Attributes:
        path: 按任务来源文件的导航相对路径。
        raw: 原字节；文件不存在时为 None。
        payload: 原键值及顺序；新文件不添加废弃的 collection_task_id。
        document: 校验后的身份及记录，用于规则判断，不用于重写旧字段。
    """

    path: str
    raw: bytes | None
    payload: JsonObject
    document: ProvenanceDocument


def read(
    engine: Engine, nav_root: Path, parameters: LineageParameters, checkpoint: Callable[[], None]
) -> LineageSource:
    """Web 同步拒绝不可删除记录和不存在输入，worker 重读同一规则，文件 I/O 不占事务。"""
    with session_scope(engine, read_only=True) as session:
        _scope.require_dataset(session, parameters.dataset_id)
        target = session.get(DatasetRow, parameters.dataset_id)
        if target is None or target.canonical_entry_path is None:
            raise nav_input_error("NAV_LINEAGE", "数据集必须有唯一按任务入口")
        entry_path, name = target.canonical_entry_path, target.name
        for identifier in parameters.input_dataset_ids:
            if session.get(DatasetRow, identifier) is None:
                raise JobInputError(
                    nav_input_error(
                        "NAV_LINEAGE", "输入数据集不存在", objects=(("dataset_id", identifier),)
                    ).diagnostics
                )
    # 索引是服务端生成的相对路径，也做分量边界检查后才交给 O_NOFOLLOW。
    entry = Path(entry_path)
    if entry.is_absolute() or ".." in entry.parts or entry.parts[:1] != ("按任务",):
        raise nav_input_error("NAV_LINEAGE", "索引中的规范入口路径非法")
    checkpoint()
    observed = read_provenance(nav_root / entry)
    if observed.state is ProvenanceState.INVALID:
        raise nav_input_error("NAV_LINEAGE", "来源.json 无法读取，不能覆盖坏文件")
    raw = None
    if observed.document is None:
        document = new_provenance(parameters.dataset_id, name)
        payload: JsonObject = {
            "schema_version": 2,
            "dataset_id": parameters.dataset_id,
            "dataset_name": name,
            "lineage": [],
        }
    else:
        document = observed.document
        try:
            with _io.directory(nav_root / entry) as descriptor:
                raw = _io.read_file(descriptor, "来源.json", checkpoint)
        except OSError as error:
            raise nav_external_error("NAV_LINEAGE", "读取来源文件前像失败") from error
        if hashlib.sha256(raw).hexdigest() != observed.sha256:
            raise nav_conflict_error("NAV_LINEAGE", "读取期间来源文件发生变化")
        payload = load_navigation_json(raw)
    if (document.dataset_id, document.dataset_name) != (parameters.dataset_id, name):
        raise nav_input_error("NAV_LINEAGE", "来源文件身份与规范入口不一致")
    _validate_records(document, parameters)
    return LineageSource(str(entry / "来源.json"), raw, payload, document)


def _validate_records(document: ProvenanceDocument, parameters: LineageParameters) -> None:
    """先排除重复编号，再只允许删除有明确人工补录身份的整条记录。"""
    identifiers = [record.record_id for record in document.lineage]
    if len(identifiers) != len(set(identifiers)):
        raise nav_input_error("NAV_LINEAGE", "来源文件记录编号重复，无法安全编辑")
    if parameters.action == "remove":
        record = next(
            (item for item in document.lineage if item.record_id == parameters.record_id), None
        )
        if record is None or record.recorded_by.kind != "人工补录":
            raise JobInputError(
                nav_input_error(
                    "NAV_LINEAGE",
                    "记录不存在或不是人工补录，不能删除",
                    objects=(
                        ("dataset_id", parameters.dataset_id),
                        ("record_id", str(parameters.record_id)),
                    ),
                ).diagnostics
            )
