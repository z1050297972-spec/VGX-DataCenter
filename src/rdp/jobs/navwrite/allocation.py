"""`dataset_id` 分配（领域层，M1-07，ADR 0009 L6/L7）。

只读导航层。要求调用方在导航层写锁下使用，否则两个并发作业会拿到同一个编号；
本模块自己不拿锁，也不记录"已分配"的账本（ADR 0009 放弃了编号账本，编号从目录里推出来）。
"""

from pathlib import Path


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
    raise NotImplementedError


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
    raise NotImplementedError
