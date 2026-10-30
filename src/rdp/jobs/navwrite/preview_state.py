"""预览状态的记录与核对（领域层，M1-07，ADR 0009 L12）。

建立在第 01 张的数据集状态指纹上：不另造一套哈希。预览（只读作业）调用 capture，
写入作业拿到写锁之后、写之前调用 verify。只读导航层，不访问存储根。
"""

import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from rdp.infra.diagnostics import InputError
from rdp.jobs.datasets.fingerprint import (
    DatasetFingerprint,
    EntryFingerprint,
    fingerprint_dataset,
)
from rdp.jobs.navwrite.allocation import scan_max_dataset_number
from rdp.jobs.navwrite.errors import nav_conflict_error, nav_input_error
from rdp.jobs.navwrite.models import NewDatasetState, PreviewState

_RULE = "NAV_PREVIEW_STATE"
# 冲突诊断里最多逐条列出的差异；总数写进 actual，列表不无限长（规范 6.6）。
_LISTED_DIFFERENCES = 20


@dataclass(frozen=True)
class StateDifference:
    """预览状态与现状的一处差异，用于冲突诊断和页面列表。

    Attributes:
        dataset_id: 所属数据集；新增数据集的"目的目录""最大编号"差异为 None。
        entry_path: 相对 nav_root 的入口路径；与入口无关的差异为 None。
        kind: 差异种类：json_changed（某份 JSON 的哈希变了）、names_changed（条目名清单变了）、
            link_changed（某条链接的 readlink 变了）、entry_missing_or_new（入口被删除或新增）、
            unverifiable（现状无法确认，不能证明没变）、destination_exists（新增的目的目录已出现）、
            max_number_changed（最大编号变了）、nav_root_changed（导航根与预览所用不同，整体视为差异）。
        name: 具体的文件名或链接名，没有则为 None。
        expected: 预览时的值（哈希前 12 位、readlink 或描述），非空。
        actual: 现在的值，非空。
    """

    dataset_id: str | None
    entry_path: str | None
    kind: str
    name: str | None
    expected: str
    actual: str


def capture_preview_state(
    nav_root: Path,
    dataset_ids: tuple[str, ...],
    new_destination: str | None,
    *,
    checkpoint: Callable[[], None],
) -> PreviewState:
    """记下受影响数据集的预览状态（L12），供之后核对。

    Args:
        nav_root: 导航层根目录绝对路径，不是软链接。
        dataset_ids: 受影响的永久编号，不重复；新增数据集时为空元组。
        new_destination: 新增数据集预计的按任务入口（相对 nav_root）；其余操作为 None。
        checkpoint: 必填的有界检查点，每份文件、每个读块之间调用。

    Returns:
        PreviewState：每个数据集的 fingerprint_dataset 结果（含来源.json 的哈希，不论存在与否都占一项）；
        新增数据集另含"目的目录是否不存在"和 scan_max_dataset_number 的值。
        任何一个数据集的指纹 verifiable=False 时仍原样返回，由调用方（预览作业）拒绝生成预览。

    Raises:
        InputError: dataset_id 不合约、扫描超过 MAX_SCAN_BYTES/ENTRIES，或某个编号在导航层里找不到入口。
        ExternalError: 导航根或视图无法枚举。
        JobCancelledError: checkpoint 检出人为取消（预览作业不持写锁，可立即响应）。
        WorkerStoppingError: checkpoint 检出 worker 停止。

    Side Effects:
        无（只读导航层，不访问链接目标）。

    Time Semantics:
        预览作业内调用，不持有导航层写锁；各数据集的指纹不是同一时刻的原子快照，这没关系，
        因为执行前会在写锁下重算并比对（ADR 0005）。不读墙钟。
    """
    fingerprints: list[DatasetFingerprint] = []
    for dataset_id in sorted(dataset_ids):
        fingerprint = fingerprint_dataset(
            nav_root, dataset_id, known_entry_paths=(), checkpoint=checkpoint
        )
        if not fingerprint.entries or all(
            entry.state.value == "missing" for entry in fingerprint.entries
        ):
            problem = nav_input_error(
                _RULE, "导航层里找不到这个数据集的入口", objects=(("dataset_id", dataset_id),)
            )
            raise problem
        fingerprints.append(fingerprint)
    new_dataset = None
    if new_destination is not None:
        new_dataset = NewDatasetState(
            destination_path=new_destination,
            destination_absent=not os.path.lexists(nav_root / new_destination),
            max_number=scan_max_dataset_number(nav_root),
        )
    return PreviewState(
        nav_root=str(nav_root), datasets=tuple(fingerprints), new_dataset=new_dataset
    )


def diff_preview_state(
    nav_root: Path, expected: PreviewState, *, checkpoint: Callable[[], None]
) -> tuple[StateDifference, ...]:
    """重新采集现状，与预览状态逐项比对，列出全部差异。

    Args:
        nav_root: 导航层根目录绝对路径；必须等于 expected.nav_root，否则整体视为差异。
        expected: 预览时记下的状态。
        checkpoint: 必填的有界检查点；写锁内由框架延后控制异常。

    Returns:
        差异元组，按 dataset_id、入口路径、种类升序；为空表示每项都与预览时相同。
        任一方 verifiable=False 时，该数据集产生一条 unverifiable 差异，两个不可验证的值不算"没变"。

    Raises:
        InputError: expected 里的路径逃逸 nav_root。
        ExternalError: 导航根或视图无法枚举，无法确定现状。
        JobCancelledError: 非保护段的 checkpoint 检出人为取消。
        WorkerStoppingError: 非保护段的 checkpoint 检出 worker 停止。

    Side Effects:
        无（只读导航层）。

    Time Semantics:
        写入作业在写锁内调用；撤回预览也调用它与 #N 的后像比对前先调用一次。不读墙钟，不重试。
    """
    if str(nav_root) != expected.nav_root:
        return (
            StateDifference(None, None, "nav_root_changed", None, expected.nav_root, str(nav_root)),
        )
    differences: list[StateDifference] = []
    for before in expected.datasets:
        known = tuple(entry.path for entry in before.entries)
        for path in known:
            if ".." in Path(path).parts or Path(path).is_absolute():
                problem = nav_input_error(
                    _RULE, "预览状态里的路径逃逸导航根", objects=(("path", path),)
                )
                raise problem
        after = fingerprint_dataset(
            nav_root, before.dataset_id, known_entry_paths=known, checkpoint=checkpoint
        )
        differences.extend(_diff_dataset(before, after))
    if expected.new_dataset is not None:
        differences.extend(_diff_new_dataset(nav_root, expected.new_dataset))
    return tuple(
        sorted(
            differences,
            key=lambda d: (d.dataset_id or "", d.entry_path or "", d.kind, d.name or ""),
        )
    )


def verify_preview_state(
    nav_root: Path, expected: PreviewState, *, checkpoint: Callable[[], None]
) -> None:
    """核对预览状态仍然成立，不成立就以冲突失败，什么都不写。

    Args:
        nav_root: 导航层根目录绝对路径。
        expected: 预览时记下的状态。
        checkpoint: 必填的有界检查点。

    Returns:
        无；通过即表示 diff_preview_state 为空。

    Raises:
        ConflictError: 存在任何差异。诊断列出差异（数据集、入口、文件或链接、预期与实际），
            后果写"一行都没写"，下一步写"重新预览后再提交"。
        ExternalError: 同 diff_preview_state。
        JobCancelledError: 非保护段的 checkpoint 检出人为取消。
        WorkerStoppingError: 非保护段的 checkpoint 检出 worker 停止。

    Side Effects:
        无（只读导航层）。

    Time Semantics:
        作为 ExecutionContext.write_navigation 的 verify 回调，在拿到写锁之后、落写入日志之前调用；
        顺序不能颠倒，否则核对和写入之间可能插进别的作业（规范 2.3，ADR 0005）。
    """
    differences = diff_preview_state(nav_root, expected, checkpoint=checkpoint)
    if not differences:
        return
    listed = differences[:_LISTED_DIFFERENCES]
    objects = tuple(
        (
            f"diff_{index}",
            f"{d.dataset_id or '-'} {d.entry_path or '-'} {d.kind} {d.name or '-'}："
            f"预览时 {d.expected}，现在 {d.actual}",
        )
        for index, d in enumerate(listed, start=1)
    )
    problem = nav_conflict_error(
        _RULE,
        f"预览之后导航层有 {len(differences)} 处变化",
        expected="与预览时记下的状态完全相同",
        objects=objects,
    )
    raise problem


def _short(value: str | None) -> str:
    """哈希只列前 12 位，其余原样；None 写"不存在"。"""
    if value is None:
        return "不存在"
    return value[:12] if len(value) == 64 else value


def _diff_dataset(before: DatasetFingerprint, after: DatasetFingerprint) -> list[StateDifference]:
    """比较同一个数据集的两次指纹；任一方不可验证就不能证明没变。"""
    dataset_id = before.dataset_id
    if not before.verifiable or not after.verifiable:
        return [
            StateDifference(
                dataset_id,
                None,
                "unverifiable",
                None,
                "可验证" if before.verifiable else "不可验证",
                "可验证" if after.verifiable else "不可验证",
            )
        ]
    old = {entry.path: entry for entry in before.entries}
    new = {entry.path: entry for entry in after.entries}
    result: list[StateDifference] = []
    for path in sorted(old.keys() | new.keys()):
        first, second = old.get(path), new.get(path)
        present_before = first is not None and first.state.value == "present"
        present_after = second is not None and second.state.value == "present"
        if present_before != present_after or first is None or second is None:
            result.append(
                StateDifference(
                    dataset_id,
                    path,
                    "entry_missing_or_new",
                    None,
                    "入口存在" if present_before else "入口不存在",
                    "入口存在" if present_after else "入口不存在",
                )
            )
        elif present_before:
            result.extend(_diff_entry(dataset_id, first, second))
    return result


def _diff_entry(
    dataset_id: str | None, first: EntryFingerprint, second: EntryFingerprint
) -> list[StateDifference]:
    """同一个入口前后的条目名、JSON 哈希、链接目标差异。"""
    result: list[StateDifference] = []
    if first.names != second.names:
        added = sorted(set(second.names) - set(first.names))
        removed = sorted(set(first.names) - set(second.names))
        result.append(
            StateDifference(
                dataset_id,
                first.path,
                "names_changed",
                None,
                "缺 " + "、".join(added) if added else f"共 {len(first.names)} 项",
                "多 " + "、".join(removed) if removed else f"共 {len(second.names)} 项",
            )
        )
    old_json = {item.name: item for item in first.json_files}
    new_json = {item.name: item for item in second.json_files}
    for name in sorted(old_json.keys() | new_json.keys()):
        left, right = old_json.get(name), new_json.get(name)
        if left != right:
            result.append(
                StateDifference(
                    dataset_id,
                    first.path,
                    "json_changed",
                    name,
                    f"{left.state.value} {_short(left.sha256)}" if left else "无记录",
                    f"{right.state.value} {_short(right.sha256)}" if right else "无记录",
                )
            )
    old_links = {item.name: item.target for item in first.links}
    new_links = {item.name: item.target for item in second.links}
    for name in sorted(old_links.keys() | new_links.keys()):
        if (name in old_links) != (name in new_links) or old_links.get(name) != new_links.get(name):
            result.append(
                StateDifference(
                    dataset_id,
                    first.path,
                    "link_changed",
                    name,
                    _short(old_links.get(name)),
                    _short(new_links.get(name)),
                )
            )
    return result


def _diff_new_dataset(nav_root: Path, expected: NewDatasetState) -> list[StateDifference]:
    """新增数据集另记的两样：目的目录不存在、当时的最大编号。"""
    result: list[StateDifference] = []
    exists = os.path.lexists(nav_root / expected.destination_path)
    if exists == expected.destination_absent:
        result.append(
            StateDifference(
                None,
                expected.destination_path,
                "destination_exists",
                None,
                "目的目录不存在" if expected.destination_absent else "目的目录存在",
                "目的目录存在" if exists else "目的目录不存在",
            )
        )
    try:
        current = scan_max_dataset_number(nav_root)
    except InputError:
        # 有入口读不出编号：现在无法确认最大编号，不能证明没变。
        result.append(
            StateDifference(
                None,
                None,
                "unverifiable",
                None,
                f"最大编号 {expected.max_number}",
                "无法确认最大编号",
            )
        )
        return result
    if current != expected.max_number:
        result.append(
            StateDifference(
                None,
                None,
                "max_number_changed",
                None,
                f"最大编号 {expected.max_number}",
                f"最大编号 {current}",
            )
        )
    return result
