"""`dataset_id` 分配（领域层，M1-07，ADR 0009 L6/L7）。

只读导航层。要求调用方在导航层写锁下使用，否则两个并发作业会拿到同一个编号；
本模块自己不拿锁，也不记录"已分配"的账本（ADR 0009 放弃了编号账本，编号从目录里推出来）。
"""

import os
import re
import stat
from pathlib import Path, PurePosixPath

from rdp.jobs.datasets.catalog import MAX_ENTRY_MEMBERS
from rdp.jobs.datasets.reading import read_entry
from rdp.jobs.datasets.types import EntryLocation, View
from rdp.jobs.navwrite.errors import Advice, nav_external_error, nav_input_error
from rdp.jobs.navwrite.policy import (
    DATASET_ID_PREFIX,
    DATASET_NUMBER_MIN_DIGITS,
    REMOVED_DIRNAME,
    TASK_VIEW_DIRNAME,
)

_ID_PATTERN = re.compile(rf"^{re.escape(DATASET_ID_PREFIX)}([0-9]+)$")
_REMOVED_PATTERN = re.compile(rf"^{re.escape(DATASET_ID_PREFIX)}([0-9]+)_")
_RULE = "NAV_ALLOCATION"


def scan_max_dataset_number(nav_root: Path) -> int:
    """扫描 `按任务/` 与 `已移除/`，返回已用过的最大 dataset-N 里的 N。

    Args:
        nav_root: 导航层根目录绝对路径，路径分量不得是软链接。

    Returns:
        `按任务/` 每个入口取三份 JSON 里首个可用的 dataset_id（与第 01 张 EntrySnapshot 相同的顺序），
        `已移除/` 每个子目录取目录名里 `dataset-N_` 的前缀；两处合并取最大 N。两处都没有时为 0。
        不认识格式的 dataset_id（不是 `dataset-` 加整数）被忽略，但会在 Raises 的条件里计数。

    Raises:
        InputError: 有入口的 dataset_id 一份都读不出来、或 `已移除/` 下有目录名不带编号前缀。
            此时无法保证取到的最大值不被漏掉的入口抬高，宁可拒绝也不分配（编号永不复用）。
        ExternalError: `按任务/` 或 `已移除/` 无法枚举。

    Side Effects:
        无（只读导航层）。

    Time Semantics:
        同步；目录项数受 MAX_ENTRY_MEMBERS 限制。结果只在调用方持有写锁期间有效；
        预览时算出的值记进 NewDatasetState.max_number，执行时重算比对。
    """
    highest = 0
    for name in _subdirectories(nav_root / TASK_VIEW_DIRNAME):
        location = EntryLocation(
            PurePosixPath(TASK_VIEW_DIRNAME, name), View.TASK, None, None, name
        )
        dataset_id = read_entry(nav_root, location, checkpoint=_no_checkpoint).dataset_id
        if dataset_id is None:
            problem = nav_input_error(
                _RULE,
                "有入口的三份 JSON 都读不出 dataset_id，无法保证新编号不重复",
                advice=Advice("这次写入没有开始，导航层一行都没写", "先修好该入口，再重新预览"),
                objects=(("entry_path", str(location.path)),),
            )
            raise problem
        matched = _ID_PATTERN.match(dataset_id)
        if matched:
            highest = max(highest, int(matched[1]))
    for name in _subdirectories(nav_root / REMOVED_DIRNAME):
        matched = _REMOVED_PATTERN.match(name)
        if matched is None:
            problem = nav_input_error(
                _RULE,
                "已移除目录下有不带编号前缀的目录，无法保证新编号不重复",
                expected=f"{DATASET_ID_PREFIX}<编号>_<名称>",
                advice=Advice("这次写入没有开始，导航层一行都没写", "先改好该目录名，再重新预览"),
                objects=(("directory", f"{REMOVED_DIRNAME}/{name}"),),
            )
            raise problem
        highest = max(highest, int(matched[1]))
    return highest


def allocate_dataset_id(nav_root: Path) -> str:
    """分配下一个 dataset_id：已用过的最大编号加 1，至少两位。

    Args:
        nav_root: 导航层根目录绝对路径，同 scan_max_dataset_number。

    Returns:
        形如 `dataset-36`、`dataset-05` 的文本；`已移除/dataset-40_x/` 存在时至少是 `dataset-41`。
        编号只增不减，移除过的编号不复用。

    Raises:
        InputError: 同 scan_max_dataset_number。
        ExternalError: 同 scan_max_dataset_number。

    Side Effects:
        无（只读导航层，不创建目录、不记账本）。

    Time Semantics:
        调用方必须已持有导航层写锁，且在落写入日志之前调用；预览时可无锁调用，得到的是"预计编号"。
    """
    number = scan_max_dataset_number(nav_root) + 1
    return f"{DATASET_ID_PREFIX}{number:0{DATASET_NUMBER_MIN_DIGITS}d}"


def _no_checkpoint() -> None:
    """分配编号是短扫描，调用方已持锁或在预览里，没有需要响应的取消点。"""


def _subdirectories(directory: Path) -> tuple[str, ...]:
    """列出直接子目录名（不跟随链接）；目录本身不存在视为空，其余枚举失败是外部失败。"""
    names: list[str] = []
    try:
        with os.scandir(directory) as entries:
            for entry in entries:
                if len(names) >= MAX_ENTRY_MEMBERS:
                    problem = nav_input_error(
                        _RULE, "目录项超过预算", objects=(("directory", directory.name),)
                    )
                    raise problem
                if stat.S_ISDIR(entry.stat(follow_symlinks=False).st_mode):
                    names.append(entry.name)
    except FileNotFoundError:
        return ()
    except OSError as error:
        problem = nav_external_error(
            _RULE, "目录无法枚举", objects=(("directory", directory.name),)
        )
        raise problem from error
    return tuple(sorted(names))
