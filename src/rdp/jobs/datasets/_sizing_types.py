"""统计大小的不可变交接值（领域层，M1-02），不携带活动Session或文件描述符。"""

from dataclasses import dataclass
from pathlib import Path

from rdp.jobs.datasets.fingerprint import DatasetFingerprint


@dataclass(frozen=True)
class SizeValue:
    """一次完整链接目标遍历的结果。

    Attributes:
        size_bytes: 非负表观字节数，只计普通文件和内部软链接自身，不计目录；硬链接去重。
        aria2_count: .aria2普通文件数，非负。
        incomplete_count: .incomplete普通文件数，非负。
        samples: 未完成文件的前十个路径，不存整棵树。
    """

    size_bytes: int
    aria2_count: int
    incomplete_count: int
    samples: tuple[Path, ...] = ()


@dataclass(frozen=True)
class SizeLink:
    """统计前索引中的一条声明链接及实际目标。

    Attributes:
        ordinal: 入口内非负序号。
        source_path: JSON声明路径，用于发布时核对身份。
        target: 第一段readlink值；不存在为None。
    """

    ordinal: int
    source_path: str
    target: str | None


@dataclass(frozen=True)
class SizeEntry:
    """入口身份和链接的冻结副本。

    Attributes:
        path: 导航相对路径。
        canonical: 是否按任务入口。
        links: 按序号排列的链接，可空。
    """

    path: str
    canonical: bool
    links: tuple[SizeLink, ...]


@dataclass(frozen=True)
class SizeDataset:
    """一个数据集的统计输入。

    Attributes:
        dataset_id: 原永久编号，非空。
        fingerprint: 统计前索引保存的完整导航状态。
        entries: 两个视图的入口，按路径排列。
    """

    dataset_id: str
    fingerprint: DatasetFingerprint
    entries: tuple[SizeEntry, ...]
