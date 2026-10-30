"""L19 的 worker 存储检查；复用 M0 挂载身份和总超时，不在 Web 访问数据盘。

按根批量检查去重路径，避免为数千处重复引用反复创建访问线程；路径解析复用现有受限解析器。
"""

from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

from rdp.infra.config import StorageRootConfig
from rdp.infra.diagnostics import DefectError, InputError
from rdp.jobs.datasets._storage_paths import inspect_path, locate_path
from rdp.jobs.datasets.rescan import RescanDependencies
from rdp.jobs.navwrite.errors import nav_external_error, nav_input_error
from rdp.jobs.navwrite.models import PreviewNotice

_RULE = "NAV_REPOINT_TARGET"


def check_targets(
    deps: RescanDependencies, replacements: dict[str, str], checkpoint: Callable[[], None]
) -> tuple[PreviewNotice, ...]:
    """先检查全部旧位置，只对存在的旧位置要求新位置存在。"""
    old = _observe(deps, tuple(replacements), checkpoint)
    # 缺失旧路径只豁免“新位置必须存在”，不豁免登记根、在线和 realpath 边界。
    new = _observe(deps, tuple(replacements.values()), checkpoint)
    required = {replacements[path] for path, exists in old.items() if exists}
    for path, exists in new.items():
        if path in required and not exists:
            raise nav_input_error(
                _RULE,
                "旧位置存在，但新位置缺失，整批拒绝",
                objects=(("new_path", path),),
            )
    return tuple(
        PreviewNotice(
            code="old_path_missing",
            message="旧位置原本就不存在，仍按前缀替换",
            objects=(("old_path", path), ("new_path", replacements[path])),
        )
        for path, exists in old.items()
        if not exists
    )


def _root(deps: RescanDependencies, path: Path) -> StorageRootConfig:
    """拒绝根外和导航层内部路径；NAS 等待 12 的 1B。"""
    roots = [root for root in deps.roots if path.is_relative_to(root.path)]
    if not roots or path.is_relative_to(deps.nav_root):
        raise nav_input_error(
            _RULE, "路径必须在登记根下且不能在导航层内", objects=(("path", str(path)),)
        )
    root = max(roots, key=lambda item: len(item.path.parts))
    if root.nfs_export is not None:
        raise nav_input_error(_RULE, "NAS 改指向尚不在本操作范围内", objects=(("path", str(path)),))
    return root


def _observe(
    deps: RescanDependencies, paths: tuple[str, ...], checkpoint: Callable[[], None]
) -> dict[str, bool]:
    """每个根在同一次总预算内只读观察，离线与读失败不得伪装成不存在。"""
    if deps.storage is None:
        raise DefectError()
    grouped: dict[str, tuple[StorageRootConfig, list[tuple[str, Path]]]] = {}
    for text in dict.fromkeys(paths):
        checkpoint()
        path = locate_path(Path(text), tuple(root.path for root in deps.roots))
        root = _root(deps, path)
        grouped.setdefault(root.name, (root, []))[1].append((text, path))
    result: dict[str, bool] = {}
    for root, candidates in grouped.values():
        result.update(_observe_root(deps, root, candidates, checkpoint))
    return result


def _observe_root(
    deps: RescanDependencies,
    root: StorageRootConfig,
    candidates: list[tuple[str, Path]],
    checkpoint: Callable[[], None],
) -> dict[str, bool]:
    """回调闭包属于本次根检查，超时后的迟到线程不会写入下一轮的结果槽。"""
    if deps.storage is None:
        raise DefectError()
    checkpoint()
    observed: dict[str, bool] = {}
    problems: list[InputError] = []

    def access(_path: Path) -> None:
        # checker 将回调异常视为适配器缺陷；业务拒绝通过结果槽返回调用线程。
        for text, path in candidates:
            item = inspect_path(path, root.path)
            if item.exists is None or not item.resolved.is_relative_to(root.path):
                problems.append(
                    nav_input_error(_RULE, "realpath 越过登记根边界", objects=(("path", text),))
                )
                return
            observed[text] = item.exists

    status = replace(deps.storage, access=access).check(root.name, checkpoint=checkpoint)
    if not status.online:
        raise nav_external_error(
            _RULE, f"存储根离线或检查失败：{status.reason}", objects=(("storage_root", root.name),)
        )
    if problems:
        raise problems[0]
    return observed
