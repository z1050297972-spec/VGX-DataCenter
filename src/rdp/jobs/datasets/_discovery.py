"""登记视图的有限目录遍历；未知目录只报告，不猜测深度或递归进入。"""

import os
import stat
from pathlib import Path, PurePosixPath

from rdp.jobs.datasets import _io, catalog
from rdp.jobs.datasets._issues import external_error, finding, input_error
from rdp.jobs.datasets.types import EntryLocation, Finding, NavigationCatalog, View


def discover(root: Path) -> NavigationCatalog:
    """只按两张登记表遍历合法层级，无法枚举必需目录时整批失败。"""
    entries: list[EntryLocation] = []
    issues: list[Finding] = []
    try:
        with _io.directory(root) as descriptor:
            for name in _io.names(descriptor):
                if name not in {"按任务", "按格式"} | catalog.NON_DATASET_DIRECTORIES:
                    issues.append(finding(name, "TOP_LEVEL_UNREGISTERED", "顶层条目未登记"))
        for name in _directories(root / "按任务", issues):
            entries.append(
                EntryLocation(PurePosixPath("按任务", name), View.TASK, None, None, name)
            )
        formats = {item.directory: item for item in catalog.FORMAT_DIRECTORIES}
        for name in _directories(root / "按格式", issues):
            if name not in formats:
                issues.append(
                    finding(
                        str(PurePosixPath("按格式", name)), "FORMAT_UNREGISTERED", "格式目录未登记"
                    )
                )
                continue
            definition = formats[name]
            base = root / "按格式" / name
            versions: tuple[str | None, ...] = (
                _directories(base, issues) if definition.has_versions else (None,)
            )
            for version in versions:
                parent = base if version is None else base / version
                for dataset in _directories(parent, issues):
                    path = PurePosixPath((parent / dataset).relative_to(root))
                    entries.append(
                        EntryLocation(path, View.FORMAT, definition.format, version, dataset)
                    )
                    _check_count(root, entries)
    except OSError as error:
        problem = external_error(str(root), "导航目录无法完整枚举")
        raise problem from error
    if len(entries) > catalog.MAX_SCAN_ENTRIES:
        raise input_error(str(root), "入口数超过预算")
    return NavigationCatalog(tuple(sorted(entries, key=lambda item: str(item.path))), tuple(issues))


def _directories(path: Path, issues: list[Finding]) -> tuple[str, ...]:
    """不把软链接目录当入口；普通文件同样不能形成一个导航层级。"""
    result: list[str] = []
    with _io.directory(path) as descriptor:
        for name in _io.names(descriptor):
            mode = os.stat(name, dir_fd=descriptor, follow_symlinks=False).st_mode
            if stat.S_ISDIR(mode):
                result.append(name)
            else:
                issues.append(
                    finding(str(path / name), "NAV_UNSAFE_DIRECTORY", "该层条目不是普通目录")
                )
    return tuple(result)


def _check_count(root: Path, entries: list[EntryLocation]) -> None:
    """每增加入口即检查上界，不等完成遍历才分配巨大清单。"""
    if len(entries) > catalog.MAX_SCAN_ENTRIES:
        raise input_error(str(root), "入口数超过预算")
