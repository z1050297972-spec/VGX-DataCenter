"""第二段存储读取（领域层，M1-02、ADR0006），只读数据，不持导航锁。

标准库提供路径、JSON和有限数校验；超时线程与挂载身份复用M0检查器。
每根结果在线程私有列表中形成，成功返回后才发布，迟到线程不能修改扫描结果。
"""

import json
import math
import os
from collections.abc import Callable, Iterator
from dataclasses import replace
from functools import partial
from pathlib import Path
from threading import Event
from typing import cast

from rdp.infra.config import StorageRootConfig
from rdp.infra.diagnostics import (
    DIAGNOSTIC_SAMPLE_LIMIT,
    Diagnostic,
    DiagnosticCategory,
    DiagnosticLevel,
    DiagnosticObject,
)
from rdp.infra.storage import OFFLINE_REASON_LABELS, StorageAccessChecker, StorageRootStatus
from rdp.infra.timeutil import ensure_utc
from rdp.jobs.datasets._panel_issue import difference
from rdp.jobs.datasets._readonly import open_file, scan_directory
from rdp.jobs.datasets._references import references
from rdp.jobs.datasets._storage_paths import (
    MAX_SYMLINKS,
    PathObservation,
    inspect_path,
    locate_path,
)
from rdp.jobs.datasets.panel import aggregate_findings
from rdp.jobs.datasets.scan_types import (
    LinkCheck,
    LinkStatus,
    NavigationScan,
    SourceCheck,
    SourceStatus,
    StorageScan,
    StorageStage,
)
from rdp.jobs.datasets.types import (
    EntrySnapshot,
    Finding,
    FindingGroup,
    PanelGroup,
    PanelSeverity,
    View,
)

# 元信息只提取三个标量；1MiB预算足够常见特征表，防止异常文件占满worker内存。
MAX_META_BYTES = 1024 * 1024
# 索引fps_rounded使用SQLite有符号64位整数，浮点转换后也须满足此上限。
MAX_INDEX_FPS_ROUNDED = 2**63 - 1


def scan(
    navigation: NavigationScan, checker: StorageAccessChecker, checkpoint: Callable[[], None]
) -> StorageScan:
    """逐根在M0总预算内读取，只有完成的根才接收数据块观察。"""
    sources: list[SourceCheck] = []
    roots: list[StorageRootStatus] = []
    existence: dict[str, PathObservation] = {}
    root_findings: dict[str, list[tuple[str, FindingGroup]]] = {}
    entries = tuple(entry for item in navigation.datasets for entry in item.entries)
    for root in navigation.registered_roots:
        status, captured, paths, content = _root_read(
            root,
            navigation,
            checker,
            checkpoint,
        )
        roots.append(status)
        if status.online:
            sources.extend(captured)
            existence.update(paths)
            root_findings[root.name] = content
        else:
            sources.extend(
                SourceCheck(
                    str(entry.location.path),
                    ordinal,
                    root.name,
                    SourceStatus.OFFLINE,
                    status.checked_at,
                    None,
                    None,
                    None,
                    None,
                )
                for entry in entries
                for ordinal, source in enumerate(entry.sources)
                if Path(source.direct_path).is_relative_to(root.path)
            )
    _follow_paths(existence, roots, checker, checkpoint)
    sources.extend(
        SourceCheck(
            str(entry.location.path),
            ordinal,
            None,
            SourceStatus.UNREGISTERED,
            ensure_utc(checker.mounts.clock()),
            None,
            None,
            None,
            None,
        )
        for entry in entries
        for ordinal, source in enumerate(entry.sources)
        if not any(
            Path(source.direct_path).is_relative_to(root.path)
            for root in navigation.registered_roots
        )
    )
    sources = _follow_sources(
        navigation,
        sources,
        existence,
        roots,
        partial(_redirect_meta, checker=checker, checkpoint=checkpoint),
    )
    links, link_findings = _links(navigation, checker, existence, roots)
    findings = (
        tuple(group for root in roots if root.online for group in root_findings.get(root.name, ()))
        + _source_findings(navigation, sources)
        + _path_findings(navigation, existence, roots)
        + link_findings
        + tuple(
            ("global", group)
            for group in aggregate_findings(_offline(root) for root in roots if not root.online)
        )
    )
    return StorageScan(
        StorageStage.COMPLETED,
        tuple(roots),
        tuple(sorted(links, key=lambda item: (item.entry_path, item.ordinal))),
        tuple(sorted(sources, key=lambda item: (item.entry_path, item.ordinal))),
        _merge_findings(findings),
        sum(not root.online for root in roots),
    )


def _source_findings(
    navigation: NavigationScan, sources: list[SourceCheck]
) -> tuple[tuple[str, FindingGroup], ...]:
    """按数据集归属聚合数据块失效，样例数量复用统一诊断上限。"""
    indexed = {(item.entry_path, item.ordinal): item for item in sources}
    result: list[tuple[str, FindingGroup]] = []
    for dataset in navigation.datasets:
        findings: list[Finding] = []
        for entry in dataset.entries:
            for ordinal, source in enumerate(entry.sources):
                observed = indexed.get((str(entry.location.path), ordinal))
                if observed and observed.status is SourceStatus.UNREGISTERED:
                    findings.append(
                        difference(
                            entry,
                            "SOURCE_OUTSIDE_STORAGE",
                            (
                                f"sources[{ordinal}].direct_path",
                                source.direct_path,
                                "数据块位于已登记存储根内",
                            ),
                            group=PanelGroup.DISK,
                        )
                    )
                if observed and observed.status is SourceStatus.MISSING:
                    findings.append(
                        difference(
                            entry,
                            "SOURCE_MISSING",
                            (
                                f"sources[{ordinal}].direct_path",
                                source.direct_path,
                                "数据块当前路径存在",
                            ),
                            group=PanelGroup.DISK,
                        )
                    )
                if (
                    observed
                    and observed.codebase_version
                    and source.version
                    and observed.codebase_version.removeprefix("v")
                    != source.version.removeprefix("v")
                ):
                    findings.append(
                        difference(
                            entry,
                            "SOURCE_VERSION_MISMATCH",
                            (
                                f"sources[{ordinal}].version",
                                observed.codebase_version,
                                source.version,
                            ),
                            group=PanelGroup.DISK,
                        )
                    )
        owner = (
            "dataset:" + dataset.dataset_id
            if dataset.dataset_id
            else "entry:" + str(dataset.entries[0].location.path)
        )
        result.extend((owner, group) for group in aggregate_findings(findings))
    return tuple(result)


def _sources(
    entries: tuple[EntrySnapshot, ...],
    root: Path,
    checker: StorageAccessChecker,
    name: str,
    active: Callable[[], bool],
) -> list[SourceCheck]:
    """只处理本根的数据块；元信息不可读不影响数据路径本身的可用性。"""
    result: list[SourceCheck] = []
    for entry in entries:
        for ordinal, source in enumerate(entry.sources):
            if not active():
                return result
            path = Path(source.direct_path)
            if not path.is_relative_to(root):
                continue
            observed = inspect_path(path, root)
            exists = observed.exists is True
            meta = (
                _meta(path, root) if exists and source.format == "lerobot" else (None, None, None)
            )
            now = ensure_utc(checker.mounts.clock())
            result.append(
                SourceCheck(
                    str(entry.location.path),
                    ordinal,
                    None if observed.exists is None else name,
                    SourceStatus.UNREGISTERED
                    if observed.exists is None
                    else SourceStatus.AVAILABLE
                    if exists
                    else SourceStatus.MISSING,
                    now,
                    *meta,
                    now if exists and source.format == "lerobot" else None,
                )
            )
    return result


def _meta(path: Path, root: Path) -> tuple[str | None, float | None, str | None]:
    """有界读取结构化元信息，坏JSON和未知标量不伪造筛选值。"""
    try:
        observed = inspect_path(path / "meta/info.json", root)
        if observed.exists is not True:
            return None, None, None
        with open_file(observed.resolved) as stream:
            raw = stream.read(MAX_META_BYTES + 1)
        if len(raw) > MAX_META_BYTES:
            return None, None, None
        value: object = json.loads(raw)
    except (OSError, ValueError):
        return None, None, None
    if not isinstance(value, dict):
        return None, None, None
    data = cast(dict[str, object], value)
    return (
        _label(data.get("robot_type")),
        _fps(data.get("fps")),
        _label(data.get("codebase_version")),
    )


def _label(value: object) -> str | None:
    """null、unknown和空字符串统一为未知，不从Markdown猜测。"""
    return (
        value if isinstance(value, str) and value.strip() and value.lower() != "unknown" else None
    )


def _links(
    navigation: NavigationScan,
    checker: StorageAccessChecker,
    existence: dict[str, PathObservation],
    roots: list[StorageRootStatus],
) -> tuple[tuple[LinkCheck, ...], tuple[tuple[str, FindingGroup], ...]]:
    """用第一段readlink快照比较声明，不二次读取导航以免混合代次。"""
    links: list[LinkCheck] = []
    groups: list[tuple[str, FindingGroup]] = []
    for dataset in navigation.datasets:
        findings: list[Finding] = []
        for entry in dataset.entries:
            path = str(entry.location.path)
            fp = next(item for item in dataset.fingerprint.entries if item.path == path)
            actual = {link.name: link.target for link in fp.links}
            for ordinal, link in enumerate(entry.links):
                target = actual.get(link.name)
                actual_target = (
                    str(Path(dataset.fingerprint.nav_root) / path / target)
                    if target is not None
                    else link.source_path
                )
                observed = existence.get(actual_target)
                resolved = observed.resolved if observed else Path(actual_target)
                root = next(
                    (
                        root
                        for root in navigation.registered_roots
                        if resolved.is_relative_to(root.path)
                    ),
                    None,
                )
                if (
                    root is not None
                    and not next(item for item in roots if item.name == root.name).online
                ):
                    links.append(
                        LinkCheck(
                            path,
                            ordinal,
                            root.name,
                            LinkStatus.OFFLINE,
                            ensure_utc(checker.mounts.clock()),
                        )
                    )
                    continue
                target = actual.get(link.name)
                status = LinkStatus.AVAILABLE
                if link.name not in actual:
                    status = LinkStatus.MISSING
                elif (
                    target is None
                    or str(Path(dataset.fingerprint.nav_root) / path / target) != link.source_path
                    and (
                        existence.get(actual_target) is None
                        or existence.get(actual_target) != existence.get(link.source_path)
                    )
                ):
                    status = LinkStatus.MISMATCH
                if status is not LinkStatus.AVAILABLE:
                    findings.append(
                        difference(
                            entry,
                            "LINK_DECLARATION_MISMATCH",
                            ("links." + link.name, target, link.source_path),
                            group=PanelGroup.DISK,
                        )
                    )
                actual_target = (
                    str(Path(dataset.fingerprint.nav_root) / path / target)
                    if target is not None
                    else link.source_path
                )
                status, disk_findings = _link_disk(
                    entry, link.name, existence, status, actual_target
                )
                findings.extend(disk_findings)
                links.append(
                    LinkCheck(
                        path,
                        ordinal,
                        root.name if root else None,
                        status,
                        ensure_utc(checker.mounts.clock()),
                    )
                )
            findings.extend(
                _extra_links(entry, actual, roots, Path(dataset.fingerprint.nav_root), existence)
            )
        if dataset.entries:
            owner = (
                "dataset:" + dataset.dataset_id
                if dataset.dataset_id
                else "entry:" + str(dataset.entries[0].location.path)
            )
            groups.extend((owner, group) for group in aggregate_findings(findings))
    return tuple(links), tuple(groups)


def _root_read(
    config: StorageRootConfig,
    navigation: NavigationScan,
    checker: StorageAccessChecker,
    checkpoint: Callable[[], None],
) -> tuple[
    StorageRootStatus, list[SourceCheck], dict[str, PathObservation], list[tuple[str, FindingGroup]]
]:
    """每次调用持有自己的结果槽，超时的旧线程不能写入后一个根的结果。"""
    entries = tuple(entry for item in navigation.datasets for entry in item.entries)
    nav_root = Path(navigation.datasets[0].fingerprint.nav_root) if navigation.datasets else None
    abandoned = Event()

    def active() -> bool:
        return not abandoned.is_set()

    captured: list[SourceCheck] = []
    paths: dict[str, PathObservation] = {}
    content: list[tuple[str, FindingGroup]] = []

    def access(root: Path) -> None:
        checker.access(root)
        captured.extend(_sources(entries, config.path, checker, config.name, active))
        for value in _requested_paths(navigation):
            if not active():
                return
            if value in paths:
                continue
            target = Path(value)
            if target.is_relative_to(root):
                paths[value] = inspect_path(target, root)
            elif nav_root is not None and target.is_relative_to(nav_root):
                paths[value] = inspect_path(target, nav_root)
        content.extend(_root_content(entries, paths, active))

    try:
        status = replace(checker, access=access).check(config.name, checkpoint=checkpoint)
    finally:
        # 不能终止内核中已开始的读取；它返回后禁止继续下一条请求。
        abandoned.set()
    return (status, captured, paths, content) if status.online else (status, [], {}, [])


def _offline(root: StorageRootStatus) -> Finding:
    """每个不可访问根只给一条顶部诊断，不把它展开成大量断链。"""
    return Finding(
        PanelGroup.STORAGE,
        PanelSeverity.ACTION_REQUIRED,
        Diagnostic(
            level=DiagnosticLevel.ERROR,
            category=DiagnosticCategory.EXTERNAL,
            stage="存储检查",
            source="平台",
            objects=(DiagnosticObject(key="storage_root", value=root.name),),
            rule="STORAGE_OFFLINE",
            actual=OFFLINE_REASON_LABELS[root.reason] if root.reason else "离线",
            expected="登记挂载源在线且访问未超时",
            consequence="跳过此根的磁盘检查，保留已有大小；链接标为存储根离线",
            next_step="检查挂载来源与连接，恢复后重新扫描",
        ),
    )


def _path_findings(
    navigation: NavigationScan, paths: dict[str, PathObservation], roots: list[StorageRootStatus]
) -> tuple[tuple[str, FindingGroup], ...]:
    """只对已完成检查的路径生成发现，离线根没有观察就跳过。"""
    result: list[tuple[str, FindingGroup]] = []
    for dataset in navigation.datasets:
        findings: list[Finding] = []
        for entry in dataset.entries:
            for reference in references(entry):
                observed = paths.get(reference.path)
                if (
                    observed is not None
                    and observed.exists is False
                    and not any(
                        not root.online
                        and (
                            Path(reference.path).is_relative_to(root.path)
                            or observed.resolved.is_relative_to(root.path)
                        )
                        for root in roots
                    )
                ):
                    findings.append(
                        difference(
                            entry,
                            reference.rule,
                            (reference.field, reference.path, "引用路径存在"),
                            group=PanelGroup.DISK,
                            notice=reference.notice,
                        )
                    )
        if dataset.entries:
            owner = (
                "dataset:" + dataset.dataset_id
                if dataset.dataset_id
                else "entry:" + str(dataset.entries[0].location.path)
            )
            result.extend((owner, group) for group in aggregate_findings(findings))
    return tuple(result)


def _root_content(
    entries: tuple[EntrySnapshot, ...],
    paths: dict[str, PathObservation],
    active: Callable[[], bool],
) -> list[tuple[str, FindingGroup]]:
    """只扫规范入口的子目录链接根，格式视图有意筛选的子集不报遗漏。"""
    result: list[tuple[str, FindingGroup]] = []
    for entry in entries:
        if entry.location.view is not View.TASK:
            continue
        excluded = tuple(
            Path(ref.path) for ref in references(entry) if ref.rule == "EXCLUDED_PATH_MISSING"
        )
        covered = tuple(Path(link.source_path) for link in entry.links) + excluded
        for value in entry.dataset_roots:
            observed = paths.get(value)
            root = Path(value)
            if (
                observed is None
                or observed.exists is not True
                or any(root.is_relative_to(path) for path in covered)
            ):
                continue
            owner = (
                "dataset:" + entry.dataset_id
                if entry.dataset_id
                else "entry:" + str(entry.location.path)
            )
            result.extend(
                (owner, group)
                for group in aggregate_findings(_unlinked(entry, root, covered, active))
            )
    return result


def _unlinked(
    entry: EntrySnapshot, root: Path, covered: tuple[Path, ...], active: Callable[[], bool]
):
    """只枚举一层并流式聚合，不递归数百万个文件。"""
    with scan_directory(root) as stream:
        for child in stream:
            if not active():
                return
            path = root / child.name
            if not any(path.is_relative_to(link) or link.is_relative_to(path) for link in covered):
                yield difference(
                    entry,
                    "ROOT_CONTENT_UNLINKED",
                    ("dataset_roots", str(path), "内容被链接或登记为排除"),
                    group=PanelGroup.DISK,
                    notice=True,
                )


def _fps(value: object) -> float | None:
    """有限正FPS才参与筛选；整数过大不能让float转换或SQLite整数索引溢出。"""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    # fps_rounded持久化为SQLite有符号64位整数；超过该上限无法形成合法筛选值。
    if not 0 < value < MAX_INDEX_FPS_ROUNDED:
        return None
    number = float(value)
    return number if math.isfinite(number) and int(number + 0.5) <= MAX_INDEX_FPS_ROUNDED else None


def _link_disk(
    entry: EntrySnapshot,
    name: str,
    existence: dict[str, PathObservation],
    status: LinkStatus,
    target: str,
) -> tuple[LinkStatus, list[Finding]]:
    """路径检查只消费成功根的观察，不在诊断计算期间做I/O。"""
    findings: list[Finding] = []
    observed = existence.get(target)
    if observed is None or observed.exists is None:
        status = LinkStatus.UNREGISTERED
        findings.append(
            difference(
                entry,
                "LINK_OUTSIDE_STORAGE",
                (
                    "links." + name,
                    str(observed.resolved) if observed else target,
                    "目标realpath位于已登记存储根内",
                ),
                group=PanelGroup.DISK,
            )
        )
    resolved = observed.resolved if observed else Path(target)
    if status is not LinkStatus.UNREGISTERED and not any(
        resolved.is_relative_to(Path(root_path)) for root_path in entry.dataset_roots
    ):
        findings.append(
            difference(
                entry,
                "LINK_OUTSIDE_DATASET_ROOTS",
                ("links." + name, str(resolved), entry.dataset_roots),
                group=PanelGroup.DISK,
            )
        )
    if status is not LinkStatus.MISSING and observed is not None and observed.exists is False:
        status = LinkStatus.BROKEN
        findings.append(
            difference(
                entry,
                "LINK_BROKEN",
                ("links." + name, target, "在线存储根中的链接目标存在"),
                group=PanelGroup.DISK,
            )
        )
    return status, findings


def _extra_links(
    entry: EntrySnapshot,
    actual: dict[str, str | None],
    roots: list[StorageRootStatus],
    nav_root: Path,
    existence: dict[str, PathObservation],
) -> list[Finding]:
    """未声明的实际链接仍归③组；离线目标的检查延后。"""
    findings: list[Finding] = []
    for name in actual.keys() - {link.name for link in entry.links}:
        target = actual[name]
        if target and any(
            Path(os.path.normpath(nav_root / str(entry.location.path) / target)).is_relative_to(
                root.path
            )
            and not root.online
            for root in roots
        ):
            continue
        findings.append(
            difference(
                entry,
                "LINK_DECLARATION_MISMATCH",
                ("links." + name, target, "在links[]中登记"),
                group=PanelGroup.DISK,
            )
        )
        if target is not None:
            _, disk = _link_disk(
                entry,
                name,
                existence,
                LinkStatus.AVAILABLE,
                os.path.normpath(nav_root / str(entry.location.path) / target),
            )
            findings.extend(disk)
    return findings


def _follow_paths(
    paths: dict[str, PathObservation],
    roots: list[StorageRootStatus],
    checker: StorageAccessChecker,
    checkpoint: Callable[[], None],
) -> None:
    """跨根只在目标根身份通过后继续，额外访问仍经M0预算，循环链最多40次。"""
    for _ in range(MAX_SYMLINKS):
        changed = False
        for key, value in tuple(paths.items()):
            if value.exists is not None:
                continue
            value = replace(
                value, resolved=locate_path(value.resolved, tuple(root.path for root in roots))
            )
            paths[key] = value
            root = next((root for root in roots if value.resolved.is_relative_to(root.path)), None)
            if root is None or not root.online:
                continue
            known = paths.get(str(value.resolved))
            if known is None or known.exists is None:
                status, known = _redirect_read(root, value.resolved, checker, checkpoint)
                roots[roots.index(root)] = status
                if known is None:
                    continue
            paths[key] = known
            changed = True
        if not changed:
            break


def _redirect_read(
    root: StorageRootStatus,
    path: Path,
    checker: StorageAccessChecker,
    checkpoint: Callable[[], None],
) -> tuple[StorageRootStatus, PathObservation | None]:
    """跨根解析用独立结果槽，未完成结果不外泄。"""
    result: list[PathObservation] = []

    def access(base: Path) -> None:
        checker.access(base)
        result.append(inspect_path(path, base))

    status = replace(checker, access=access).check(root.name, checkpoint=checkpoint)
    return status, result[0] if status.online else None


def _follow_sources(
    navigation: NavigationScan,
    sources: list[SourceCheck],
    paths: dict[str, PathObservation],
    roots: list[StorageRootStatus],
    read_meta: Callable[
        [StorageRootStatus, Path],
        tuple[StorageRootStatus, tuple[str | None, float | None, str | None]],
    ],
) -> list[SourceCheck]:
    """跨根数据块在实际根的访问预算内补元信息；离线覆盖先前部分观察。"""
    entries = {
        str(entry.location.path): entry
        for dataset in navigation.datasets
        for entry in dataset.entries
    }
    result: list[SourceCheck] = []
    for source in sources:
        record = entries[source.entry_path].sources[source.ordinal]
        observed = paths.get(record.direct_path)
        root = next(
            (
                root
                for root in roots
                if (observed.resolved if observed else Path(record.direct_path)).is_relative_to(
                    root.path
                )
            ),
            None,
        )
        if root is None:
            result.append(source)
        elif not root.online:
            result.append(
                replace(
                    source,
                    storage_root_name=root.name,
                    status=SourceStatus.OFFLINE,
                    checked_at=root.checked_at,
                    robot_type=None,
                    fps=None,
                    codebase_version=None,
                    meta_checked_at=None,
                )
            )
        elif observed and observed.exists is True and source.status is SourceStatus.UNREGISTERED:
            status, meta = (
                read_meta(root, observed.resolved)
                if record.format == "lerobot"
                else (root, (None, None, None))
            )
            roots[roots.index(root)] = status
            result.append(
                SourceCheck(
                    source.entry_path,
                    source.ordinal,
                    root.name,
                    SourceStatus.AVAILABLE if status.online else SourceStatus.OFFLINE,
                    status.checked_at,
                    *meta,
                    status.checked_at if status.online and record.format == "lerobot" else None,
                )
            )
        elif observed and observed.exists is False:
            result.append(
                replace(
                    source,
                    storage_root_name=root.name,
                    status=SourceStatus.MISSING,
                    robot_type=None,
                    fps=None,
                    codebase_version=None,
                    meta_checked_at=None,
                )
            )
        else:
            result.append(source)
    # 后续跨根补读可能使一个已观察过的根超时；最终统一降级，避免半在线快照。
    offline = {root.name: root for root in roots if not root.online}
    return [
        replace(
            source,
            status=SourceStatus.OFFLINE,
            checked_at=offline[source.storage_root_name].checked_at,
            robot_type=None,
            fps=None,
            codebase_version=None,
            meta_checked_at=None,
        )
        if source.storage_root_name in offline
        else source
        for source in result
    ]


def _redirect_meta(
    root: StorageRootStatus,
    path: Path,
    checker: StorageAccessChecker,
    checkpoint: Callable[[], None],
) -> tuple[StorageRootStatus, tuple[str | None, float | None, str | None]]:
    """跨根meta读取和原根一样走超时，迟到值不进入索引。"""
    result: list[tuple[str | None, float | None, str | None]] = []

    def access(base: Path) -> None:
        checker.access(base)
        result.append(_meta(path, base))

    status = replace(checker, access=access).check(root.name, checkpoint=checkpoint)
    return status, result[0] if status.online else (None, None, None)


def _requested_paths(navigation: NavigationScan) -> Iterator[str]:
    """按快照提取请求路径，根内去重；实际链接目标也参加检查。"""
    for dataset in navigation.datasets:
        for entry in dataset.entries:
            yield from (source.direct_path for source in entry.sources)
            yield from (reference.path for reference in references(entry))
            yield from (link.source_path for link in entry.links)
        for entry in dataset.fingerprint.entries:
            for link in entry.links:
                if link.target is not None:
                    yield str(Path(dataset.fingerprint.nav_root) / entry.path / link.target)


def _merge_findings(
    groups: tuple[tuple[str, FindingGroup], ...],
) -> tuple[tuple[str, FindingGroup], ...]:
    """合并跨根的已聚合计数，样例沿用统一上限，不能从有限样例重算总数。"""
    result: dict[tuple[str, PanelGroup, PanelSeverity, str, str], FindingGroup] = {}
    for owner, group in groups:
        current = group.diagnostics
        key = owner, group.group, group.severity, current.source, current.rule
        prior = result.get(key)
        if prior is None:
            result[key] = group
            continue
        old = prior.diagnostics
        result[key] = replace(
            group,
            diagnostics=replace(
                current,
                total=old.total + current.total,
                error_count=old.error_count + current.error_count,
                warning_count=old.warning_count + current.warning_count,
                samples=(old.samples + current.samples)[:DIAGNOSTIC_SAMPLE_LIMIT],
            ),
        )
    return tuple((key[0], result[key]) for key in sorted(result))
