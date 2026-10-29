"""预览状态的记录与核对（领域层，M1-07，ADR 0009 L12）。

建立在第 01 张的数据集状态指纹上：不另造一套哈希。预览（只读作业）调用 capture，
写入作业拿到写锁之后、写之前调用 verify。只读导航层，不访问存储根。
"""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from rdp.jobs.navwrite.models import PreviewState


@dataclass(frozen=True)
class StateDifference:
    """预览状态与现状的一处差异，用于冲突诊断和页面列表。

    Attributes:
        dataset_id: 所属数据集；新增数据集的"目的目录""最大编号"差异为 None。
        entry_path: 相对 nav_root 的入口路径；与入口无关的差异为 None。
        kind: 差异种类：json_changed（某份 JSON 的哈希变了）、names_changed（条目名清单变了）、
            link_changed（某条链接的 readlink 变了）、entry_missing_or_new（入口被删除或新增）、
            unverifiable（现状无法确认，不能证明没变）、destination_exists（新增的目的目录已出现）、
            max_number_changed（最大编号变了）。
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
    raise NotImplementedError


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
    raise NotImplementedError


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
    raise NotImplementedError
