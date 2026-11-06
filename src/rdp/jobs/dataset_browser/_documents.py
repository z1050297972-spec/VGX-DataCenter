"""详情只读导航适配：复用第01张描述符读取、宽松解析和L12指纹，不跟随存储目标。"""

from pathlib import Path, PurePosixPath
from typing import Literal

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from rdp.infra.db.validation import invalid_field
from rdp.infra.diagnostics import Diagnostic, DiagnosticCategory, ExternalError, InputError
from rdp.jobs.dataset_browser import _index, _listing
from rdp.jobs.dataset_browser.errors import DatasetNotFoundError
from rdp.jobs.dataset_browser.schemas import (
    DatasetLink,
    DatasetProvenance,
    DatasetSource,
    NavigationDocument,
)
from rdp.jobs.datasets import _io, reading
from rdp.jobs.datasets._issues import finding as navigation_finding
from rdp.jobs.datasets._issues import input_error as navigation_input_error
from rdp.jobs.datasets.fingerprint import DatasetFingerprint, EntryFingerprint, fingerprint_dataset
from rdp.jobs.datasets.models import EntryRow, LinkRow
from rdp.jobs.datasets.types import EntryLocation, ProvenanceState, View
from rdp.jobs.navwrite.provenance import read_provenance

# 手册第5节的历史标签，不能被本次路径检查改写。
VALIDATION_STATUS_LABELS = {
    "path_exists_only": "只核对了路径存在",
    "archive_not_opened": "归档没有打开核对",
    "metadata_and_references_pass": "元数据和引用都核对通过",
    "attention_required": "需要关注",
    "download_state_only": "只有下载控制文件",
}


def provenance(root: Path, row: EntryRow | None) -> DatasetProvenance | None:
    """只读取已索引的唯一规范入口来源，坏文件或身份不符不伪装成未标注。"""
    if row is None:
        return None
    try:
        read = read_provenance(root / row.path)
    except ExternalError:
        return DatasetProvenance(state=ProvenanceState.INVALID)
    document = read.document
    if read.state is ProvenanceState.ABSENT:
        return DatasetProvenance(state=ProvenanceState.ABSENT)
    if document is None or (document.dataset_id, document.dataset_name) != (
        row.dataset_id,
        row.name,
    ):
        return DatasetProvenance(state=ProvenanceState.INVALID)
    return DatasetProvenance(state=ProvenanceState.VALID)


def checkpoint() -> None:
    """HTTP读取没有worker取消信号，字节/条目预算仍由第01张读取器执行。"""


def location(row: EntryRow) -> EntryLocation:
    """索引位置不经过resolve，随后由O_NOFOLLOW逐分量打开。"""
    return EntryLocation(PurePosixPath(row.path), View(row.view), row.format, row.version, row.name)


def selected(index: _index.Index, path: str) -> EntryRow:
    """只接受已入索引的入口，不将请求路径直接拼成可读文件名。"""
    _listing.validate(_listing.DatasetFilters(entry_path=path))
    row = next((entry for entry in index.entries if entry.path == path), None)
    if row is None:
        raise DatasetNotFoundError(invalid_field("entry_path", "已入索引的入口").diagnostics)
    return row


def links(session: Session, path: str) -> tuple[DatasetLink, ...]:
    """链接状态是索引观察，保留原检查时间和未检查状态。"""
    rows = session.scalars(
        select(LinkRow).where(LinkRow.entry_path == path).order_by(LinkRow.ordinal)
    )
    return tuple(
        DatasetLink.model_validate(
            {
                column.name: getattr(row, column.name)
                for column in LinkRow.__table__.columns
                if column.name != "entry_path"
            }
        )
        for row in rows
    )


def document(
    root: Path, row: EntryRow, name: Literal["原始路径.json", "数据集信息.json"]
) -> NavigationDocument:
    """原字节读取和语义校验都复用第01张；单文件不可用局部返回诊断。"""
    try:
        with _io.directory(root / row.path) as descriptor:
            content = _io.read_file(descriptor, name, checkpoint)
        parsed = reading.parse_document(location(row), name, content)
        text = content.decode("utf-8")
        return NavigationDocument(
            name=name,
            entry_path=row.path,
            content=text,
            sha256=parsed.sha256,
            usable=parsed.payload is not None,
            diagnostics=tuple(finding.diagnostic for finding in parsed.findings),
        )
    except (OSError, InputError, UnicodeError) as error:
        diagnostic = (
            navigation_finding(
                row.path,
                "JSON_UNREADABLE",
                f"{name}：无法读取普通UTF-8文件（{type(error).__name__}）",
            ).diagnostic,
        )
        return NavigationDocument(
            name=name,
            entry_path=row.path,
            content=None,
            sha256=None,
            usable=False,
            diagnostics=diagnostic,
        )


def current_fingerprint(
    root: Path, index: _index.Index, row: EntryRow
) -> tuple[DatasetFingerprint, bool]:
    """L12会重新发现全部入口，不能只校验旧路径而遗漏新增的格式副本。"""
    paths = (
        tuple(entry.path for entry in index.entries if entry.dataset_id == row.dataset_id)
        if row.dataset_id
        else (row.path,)
    )
    current = fingerprint_dataset(
        root, row.dataset_id, known_entry_paths=paths, checkpoint=checkpoint
    )
    dataset = next((item for item in index.datasets if item.dataset_id == row.dataset_id), None)
    try:
        if dataset is not None:
            baseline = DatasetFingerprint.model_validate(dataset.fingerprint)
            stale = not baseline.verifiable or not current.verifiable or current != baseline
        else:
            stale = not current.verifiable or current.entries != (
                EntryFingerprint.model_validate(row.fingerprint),
            )
    except ValidationError as error:
        raise invalid_field("fingerprint", "索引必须包含完整有效的L12指纹") from error
    return current, stale


def digest_matches(current: DatasetFingerprint, path: str, name: str, digest: str | None) -> bool:
    """发送内容与本次L12观察配对，拒绝以另一份文件摘要证明未过期。"""
    return digest is not None and any(
        entry.path == path
        and any(file.name == name and file.sha256 == digest for file in entry.json_files)
        for entry in current.entries
    )


def subtasks_bytes(root: Path, row: EntryRow) -> bytes:
    """复用受限读取器，先拒绝非普通项，将读期间变化与依赖I/O故障分开。"""
    import errno
    import os
    import stat

    from rdp.infra.diagnostics import ConflictError

    try:
        with _io.directory(root / row.path) as descriptor:
            info = os.stat("子任务.json", dir_fd=descriptor, follow_symlinks=False)
            if not stat.S_ISREG(info.st_mode):
                raise navigation_input_error(row.path, "子任务.json必须是导航层普通文件")
            content = _io.read_file(descriptor, "子任务.json", checkpoint)
        content.decode("utf-8")
        return content
    except (FileNotFoundError, UnicodeError) as error:
        raise navigation_input_error(row.path, "子任务.json必须存在且为UTF-8文件") from error
    except OSError as error:
        diagnostics = navigation_input_error(row.path, "子任务.json无法稳定读取").diagnostics
        if error.errno in {errno.ELOOP, errno.ENOTDIR}:
            raise InputError(diagnostics) from error
        if error.errno is None:
            # 第01张对普通文件读取期间的元信息变化抛无errno的OSError；此时尚未发出响应。
            raise ConflictError(
                tuple(
                    item.model_copy(update={"category": DiagnosticCategory.CONFLICT})
                    for item in diagnostics
                )
            ) from error
        raise ExternalError(
            tuple(
                item.model_copy(update={"category": DiagnosticCategory.EXTERNAL})
                for item in diagnostics
            )
        ) from error


def project(
    root: Path, row: EntryRow, manifest_sha: str | None, information_sha: str | None
) -> tuple[tuple[DatasetSource, ...], tuple[Diagnostic, ...], bool]:
    """投影与返回原文摘要不一致时标过期，局部读取失败保留诊断而非静默返回空数据块。"""
    try:
        snapshot = reading.read_entry(root, location(row), checkpoint=checkpoint)
    except ExternalError as error:
        return (), error.diagnostics, False
    sources = tuple(
        DatasetSource(
            ordinal=ordinal,
            source_id=source.source_id,
            original_path=source.original_path,
            direct_path=source.direct_path,
            derived_entry_path=source.entry_path,
            format=source.format,
            version=source.version,
            validation_status=source.validation_status,
            validation_status_label=VALIDATION_STATUS_LABELS.get(
                source.validation_status or "",
                "未知" if source.validation_status is None else "未识别",
            ),
        )
        for ordinal, source in enumerate(snapshot.sources)
    )
    stable = (
        manifest_sha is not None
        and information_sha is not None
        and snapshot.documents[0].sha256 == manifest_sha
        and snapshot.documents[1].sha256 == information_sha
    )
    return sources, tuple(finding.diagnostic for finding in snapshot.findings), stable
