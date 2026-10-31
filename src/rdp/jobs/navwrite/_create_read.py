"""创建预览的只读观察边界（M1-08）；复用受限导航读取和 M0 存储总超时，不创建导航产物。"""

import hashlib
import json
import os
import stat
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Literal

from rdp.infra.diagnostics import DefectError, InputError
from rdp.jobs.datasets import _io, _json
from rdp.jobs.datasets._readonly import open_file
from rdp.jobs.datasets._storage_paths import inspect_path, locate_path
from rdp.jobs.datasets._storage_scan import MAX_META_BYTES
from rdp.jobs.datasets.reading import read_entry
from rdp.jobs.datasets.rescan import RescanDependencies
from rdp.jobs.datasets.types import EntryLocation, EntrySnapshot
from rdp.jobs.navwrite.create_models import (
    FirstLink,
    validate_entry_name,
    validate_registered_format,
)
from rdp.jobs.navwrite.errors import nav_conflict_error, nav_external_error, nav_input_error
from rdp.jobs.navwrite.models import PreviewState

_RULE = "NAV_CREATE"


@dataclass(frozen=True)
class Target:
    """经过有界只读检查的链接目标。

    Attributes:
        path: 原样绝对目标文本，不跟随末级链接。
        kind: file 或 directory。
        format: 登记格式键；未读取元信息时为 None。
        version: 文件里的格式版本；无元信息时为 None。
        metadata: meta_info、selected_format 或 not_checked。
    """

    path: str
    kind: Literal["file", "directory"]
    format: str | None
    version: str | None
    metadata: Literal["meta_info", "selected_format", "not_checked"]


def target(
    deps: RescanDependencies,
    link: FirstLink,
    checkpoint: Callable[[], None],
    *,
    metadata: bool = True,
) -> Target:
    """在同一次 M0 总预算内核对根、目标及元信息；迟到结果不发布。"""
    if deps.storage is None or not deps.nav_root.is_absolute():
        raise DefectError()
    path = locate_path(Path(link.target_path), tuple(root.path for root in deps.roots))
    roots = [root for root in deps.roots if path.is_relative_to(root.path)]
    if not path.is_absolute() or path.is_relative_to(deps.nav_root) or not roots:
        raise nav_input_error(_RULE, "目标必须在登记根下且不能在导航层内")
    root = max(roots, key=lambda item: len(item.path.parts))
    if root.nfs_export is not None:
        raise nav_input_error(_RULE, "NAS 目标尚不在本操作范围内")
    found: list[Target] = []
    problems: list[InputError] = []

    def observe(_root: Path) -> None:
        # M0 将回调异常视为适配器缺陷；业务拒绝放入私有结果槽，回到调用线程再抛。
        try:
            found.append(_observe(path, root.path, deps.nav_root, link, metadata))
        except InputError as error:
            problems.append(error)

    status = replace(deps.storage, access=observe).check(root.name, checkpoint=checkpoint)
    if not status.online:
        raise nav_external_error(
            _RULE, f"存储根离线：{status.reason}", objects=(("storage_root", root.name),)
        )
    if problems:
        raise problems[0]
    if len(found) != 1:
        raise DefectError()
    return found[0]


def _observe(path: Path, root: Path, nav: Path, link: FirstLink, metadata: bool) -> Target:
    """只在已核对根的预算线程内访问目标，解析越界时停止。"""
    observed = inspect_path(path, root)
    if (
        observed.exists is not True
        or not observed.resolved.is_relative_to(root)
        or observed.resolved.is_relative_to(nav)
    ):
        raise nav_input_error(_RULE, "目标不存在或 realpath 越过允许的存储边界")
    mode = path.lstat().st_mode
    if stat.S_ISLNK(mode) or not (stat.S_ISDIR(mode) or stat.S_ISREG(mode)):
        raise nav_input_error(_RULE, "目标不能是软链接或特殊文件")
    kind = "directory" if stat.S_ISDIR(mode) else "file"
    if not metadata:
        return Target(str(path), kind, None, None, "not_checked")
    resolved = _metadata(observed.resolved, root) if kind == "directory" else None
    if resolved is not None:
        return Target(str(path), kind, *resolved, "meta_info")
    if link.fallback_format is None:
        raise nav_input_error(_RULE, "没有 meta/info.json，必须从登记表选择格式")
    return Target(str(path), kind, link.fallback_format, None, "selected_format")


def _metadata(path: Path, root: Path) -> tuple[str, str | None] | None:
    """缺文件可回退，坏文件、软链接及越界都拒绝，读取采用已有 O_NOATIME 边界。"""
    meta = path / "meta" / "info.json"
    try:
        if stat.S_ISLNK(meta.parent.lstat().st_mode):
            raise nav_input_error(_RULE, "元信息目录不能是软链接")
        if not stat.S_ISREG(meta.lstat().st_mode):
            raise nav_input_error(_RULE, "元信息不是普通文件")
    except FileNotFoundError:
        return None
    if inspect_path(meta, root).exists is not True:
        raise nav_input_error(_RULE, "元信息路径不可确认")
    with open_file(meta) as stream:
        raw = stream.read(MAX_META_BYTES + 1)
    if len(raw) > MAX_META_BYTES:
        raise nav_input_error(_RULE, "元信息超过读取预算")
    try:
        data = _json.object_value(json.loads(raw, parse_constant=_json.finite_number))
        format_name = validate_registered_format(
            _json.text(data.get("format", "lerobot"), "format")
        )
        version = data.get("version", data.get("codebase_version"))
        if version is not None:
            version = validate_entry_name(_json.text(version, "version").removeprefix("v"))
        if format_name == "lerobot" and version is None:
            raise ValueError("缺少格式版本")
    except (ValueError, UnicodeError) as error:
        raise nav_input_error(_RULE, "元信息内容或格式版本不合约") from error
    return format_name, version


def snapshot(
    root: Path, location: EntryLocation, state: PreviewState, checkpoint: Callable[[], None]
) -> tuple[EntrySnapshot, dict[str, bytes]]:
    """将原字节前像与预览指纹对齐，防止旧正文与新状态拼接。"""
    value = read_entry(root, location, checkpoint=checkpoint)
    if any(doc.payload is None for doc in value.documents):
        raise nav_input_error(_RULE, "入口的三份 JSON 必须可用")
    entry = next(
        item
        for dataset in state.datasets
        for item in dataset.entries
        if item.path == str(location.path)
    )
    expected = {item.name: item.sha256 for item in entry.json_files}
    try:
        with _io.directory(root / location.path) as descriptor:
            raw = {
                doc.name: _io.read_file(descriptor, doc.name, checkpoint) for doc in value.documents
            }
    except OSError as error:
        raise nav_external_error(_RULE, "读取导航前像失败") from error
    if any(
        hashlib.sha256(content).hexdigest() != expected[name] for name, content in raw.items()
    ) or any(doc.sha256 != expected[doc.name] for doc in value.documents):
        raise nav_conflict_error(_RULE, "构造期间导航 JSON 发生变化")
    return value, raw


def present(path: Path) -> bool:
    """不跟随末级链接判断目的是否已占用，断链也占用名称。"""
    return os.path.lexists(path)
