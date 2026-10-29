"""L12内部有限采集；同一次目录清单与字节读取供身份关联及摘要共用，避免两套哈希算法。"""

import hashlib
import json
import os
import stat
from collections.abc import Callable
from pathlib import Path, PurePosixPath
from typing import cast

from rdp.infra.diagnostics import InputError
from rdp.jobs.datasets import _io, catalog
from rdp.jobs.datasets._discovery import discover
from rdp.jobs.datasets._issues import input_error
from rdp.jobs.datasets.fingerprint import (
    DatasetFingerprint,
    EntryFingerprint,
    FileState,
    JsonFingerprint,
    LinkFingerprint,
)


def collect(
    root: Path, checkpoint: Callable[[], None]
) -> dict[str, tuple[EntryFingerprint, frozenset[str], bool]]:
    """一次枚举所有入口，累计字节预算不能按每个数据集重新置零。"""
    budget = [0]
    return {
        str(location.path): entry(root, str(location.path), checkpoint, budget)
        for location in discover(root).entries
    }


def select(
    root: Path,
    dataset_id: str | None,
    known: tuple[str, ...],
    observed: dict[str, tuple[EntryFingerprint, frozenset[str], bool]],
    checkpoint: Callable[[], None],
) -> DatasetFingerprint:
    """旧路径并集防止改身份或删除入口逃过比较，None编号只关联指定位置。"""
    if dataset_id is not None and (not dataset_id.strip() or "\x00" in dataset_id):
        raise input_error(str(root), "数据集编号非法")
    if dataset_id is None and len(known) != 1:
        raise input_error(str(root), "未知身份必须指定一个入口")
    paths = set(known)
    if len(paths) != len(known):
        raise input_error(str(root), "旧入口路径重复")
    for path in paths:
        parsed = PurePosixPath(path)
        if (
            parsed.is_absolute()
            or ".." in parsed.parts
            or not parsed.parts
            or parsed.parts[0] not in {"按任务", "按格式"}
        ):
            raise input_error(path, "旧入口路径越界")
    if dataset_id is not None:
        paths.update(path for path, (_, ids, _) in observed.items() if dataset_id in ids)
    rows = [
        observed[path] if path in observed else entry(root, path, checkpoint, [0])
        for path in sorted(paths)
    ]
    return DatasetFingerprint(
        nav_root=str(root),
        dataset_id=dataset_id,
        entries=tuple(row[0] for row in rows),
        verifiable=all(row[2] for row in rows),
    )


def entry(
    root: Path, path: str, checkpoint: Callable[[], None], budget: list[int]
) -> tuple[EntryFingerprint, frozenset[str], bool]:
    """记录入口所有直接子项，读取失败不能转换为可靠的空目录。"""
    try:
        with _io.directory(root / path) as descriptor:
            names = _io.names(descriptor)
            files, identities = _files(descriptor, names, checkpoint, budget)
            links = _links(descriptor, names)
            stable = names == _io.names(descriptor)
    except FileNotFoundError:
        return (
            EntryFingerprint(path=path, state=FileState.MISSING, names=(), json_files=(), links=()),
            frozenset(),
            True,
        )
    except OSError:
        return (
            EntryFingerprint(
                path=path, state=FileState.UNREADABLE, names=(), json_files=(), links=()
            ),
            frozenset(),
            False,
        )
    valid = (
        stable
        and all(item.state in {FileState.PRESENT, FileState.MISSING} for item in files)
        and all(link.target is not None for link in links)
    )
    return (
        EntryFingerprint(
            path=path, state=FileState.PRESENT, names=names, json_files=files, links=links
        ),
        identities,
        valid,
    )


def _files(
    descriptor: int, names: tuple[str, ...], checkpoint: Callable[[], None], budget: list[int]
) -> tuple[tuple[JsonFingerprint, ...], frozenset[str]]:
    """四份约定JSON即使缺失也占一项；额外JSON的原字节同样参与状态。"""
    result: list[JsonFingerprint] = []
    identities: set[str] = set()
    selected = (
        set(catalog.REQUIRED_DOCUMENTS)
        | {catalog.PROVENANCE_DOCUMENT}
        | {name for name in names if name.endswith(".json")}
    )
    for name in sorted(selected):
        content: bytes | None = None
        state = FileState.MISSING
        if name in names:
            try:
                mode = os.stat(name, dir_fd=descriptor, follow_symlinks=False).st_mode
                if stat.S_ISREG(mode):
                    content = _io.read_file(descriptor, name, checkpoint)
                    state = FileState.PRESENT
                else:
                    state = FileState.NOT_REGULAR
            except (OSError, InputError):
                state = FileState.UNREADABLE
        if content is not None:
            budget[0] += len(content)
            if budget[0] > catalog.MAX_SCAN_BYTES:
                raise input_error("导航层", "JSON总字节数超过扫描预算")
            if name in catalog.REQUIRED_DOCUMENTS:
                identities.update(_identity(content))
        result.append(
            JsonFingerprint(
                name=name,
                state=state,
                sha256=hashlib.sha256(content).hexdigest() if content is not None else None,
            )
        )
    return tuple(result), frozenset(identities)


def _identity(content: bytes) -> tuple[str, ...]:
    """只提取可解析文件的声明编号，读取可用性由reading另行判断。"""
    try:
        payload: object = json.loads(content)
    except (ValueError, UnicodeError, RecursionError):
        return ()
    if not isinstance(payload, dict):
        return ()
    value = cast(dict[str, object], payload).get("dataset_id")
    return (value,) if isinstance(value, str) and value.strip() else ()


def _links(descriptor: int, names: tuple[str, ...]) -> tuple[LinkFingerprint, ...]:
    """仅lstat与readlink，断链无需访问目标即可记录。"""
    result: list[LinkFingerprint] = []
    for name in names:
        try:
            if stat.S_ISLNK(os.stat(name, dir_fd=descriptor, follow_symlinks=False).st_mode):
                result.append(
                    LinkFingerprint(name=name, target=os.readlink(name, dir_fd=descriptor))
                )
        except OSError:
            result.append(LinkFingerprint(name=name, target=None))
    return tuple(result)
