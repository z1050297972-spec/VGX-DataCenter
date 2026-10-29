"""由规范副本生成按格式入口（领域层，M1-07，ADR 0009 L8/L9）。

纯计算：输入是已读取的快照，输出是要写的字节，不访问文件系统。
按任务入口是规范副本，按格式入口的内容都由它重新生成（ADR 0006）；
本模块只实现一遍规则，建链、新增数据集、改指向、撤回都调用它，不各自重算（规范 2.2）。
"""

from dataclasses import dataclass

from rdp.jobs.datasets.types import EntryLocation, EntrySnapshot, JsonObject


@dataclass(frozen=True)
class GeneratedFile:
    """生成出来的一份入口内 JSON。

    Attributes:
        name: 文件名，原始路径.json、数据集信息.json 或 子任务.json。
        content: 完整字节，已按 L11 写出格式序列化。
    """

    name: str
    content: bytes


@dataclass(frozen=True)
class GeneratedEntry:
    """一个按格式入口由规范副本生成的结果。

    Attributes:
        location: 该按格式入口的位置。
        files: 三份文件，顺序固定为原始路径、数据集信息、子任务。
        omitted_source_ids: 链接够不着、因此没有收进来的数据块的 source_id，按规范副本里的顺序（L9）；
            预览要列出它们，例如 alpha 的 3 个。
        omitted_task_references: 子任务.json 里因引用的数据块未入选而被筛掉的引用条数，≥ 0。
        dropped_task_keys: 筛完之后一个数据引用都不剩、因此整体去掉的任务的 task_key。
    """

    location: EntryLocation
    files: tuple[GeneratedFile, ...]
    omitted_source_ids: tuple[str, ...]
    omitted_task_references: int
    dropped_task_keys: tuple[str, ...]


def select_reachable_sources(
    sources: tuple[JsonObject, ...], link_targets: tuple[str, ...]
) -> tuple[tuple[JsonObject, ...], tuple[JsonObject, ...]]:
    """把规范副本的数据块分成"链接够得着"和"够不着"两组（L8、L9）。

    Args:
        sources: 规范副本 `sources[]` 的各项，保持文件里的顺序。
        link_targets: 该按格式入口自己 `links[]` 里各条链接的目标（`source_path`），绝对路径。

    Returns:
        (够得着, 够不着)：够得着的是 `direct_path` 等于某个链接目标，或位于其下（前缀后紧跟 `/`）的数据块；
        两组各自保持输入顺序，彼此不重叠，合起来等于输入。`/mnt/a/b` 不覆盖 `/mnt/a/bc`。

    Raises:
        InputError: 某项没有字符串类型的 `direct_path`，或链接目标不是绝对路径。

    Side Effects:
        无。

    Time Semantics:
        同步纯函数，无时钟、无 I/O。
    """
    raise NotImplementedError


def filter_subtasks(
    subtasks: JsonObject, kept_source_ids: frozenset[str]
) -> tuple[JsonObject, int, tuple[str, ...]]:
    """只保留引用到入选数据块的子任务，任务内部的数据引用同样筛（L8）。

    Args:
        subtasks: 规范副本的 子任务.json 内容；`tasks[].sources[]` 的每一项以 `source_id` 指向一个数据块。
        kept_source_ids: 入选数据块的 source_id 集合，可为空。

    Returns:
        (新对象, 被筛掉的引用条数, 整体去掉的任务的 task_key)。任务的 `sources[]` 筛完为空则整个任务去掉；
        `task_count` 随之重算，其余键（含 `shared_source_roots`）原样保留，未知键不丢。
        没有 `source_id` 的引用项如何处理，以真实样本的对拍结果为准（验收 1）。

    Raises:
        InputError: tasks 或其 sources 的结构不是约定的数组。

    Side Effects:
        无；返回新对象，不改输入。

    Time Semantics:
        同步纯函数，无时钟、无 I/O。
    """
    raise NotImplementedError


def generate_format_entry(canonical: EntrySnapshot, current: EntrySnapshot) -> GeneratedEntry:
    """由规范副本生成一个按格式入口的三份 JSON。

    Args:
        canonical: 按任务入口（规范副本）的快照，三份文件都必须可用。
        current: 该按格式入口现在的快照；只取它自己的 `links[]`（以它为准，L8）、
            位置（决定推导字段）和原有未知键的顺序；它的 `sources[]` 和子任务内容不参与结果。

    Returns:
        GeneratedEntry。原始路径.json：`links[]` 取 current 的；`sources[]` 取 select_reachable_sources
        的"够得着"组，`entry_path` 重新推导；推导字段按 regenerate_derived_fields 整组重写；其余键以规范副本为准。
        数据集信息.json：整份复制规范副本的字节内容。子任务.json：filter_subtasks 的结果，再重写推导字段。
        `dataset_id` 在三份文件里与规范副本相同。

    Raises:
        InputError: 规范副本的任一份文件不可用，或 canonical 与 current 的 dataset_id 不同、
            current 不是按格式入口。

    Side Effects:
        无；不写任何文件，写入由 NavWritePlan 的步骤承担。

    Time Semantics:
        同步纯函数，无时钟、无 I/O；结果只反映传入快照那一刻的内容。
    """
    raise NotImplementedError
