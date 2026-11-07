"""由规范副本生成按格式入口（领域层，M1-07，ADR 0009 L8/L9）。

纯计算：输入是已读取的快照，输出是要写的字节，不访问文件系统。
按任务入口是规范副本，按格式入口的内容都由它重新生成（ADR 0006）；
本模块只实现一遍规则，建链、新增数据集、改指向都调用它，不各自重算（规范 2.2）。
"""

import copy
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import cast

from rdp.jobs.datasets.catalog import REQUIRED_DOCUMENTS
from rdp.jobs.datasets.types import EntryLocation, EntrySnapshot, JsonObject, JsonValue, View
from rdp.jobs.navwrite.errors import nav_input_error
from rdp.jobs.navwrite.jsonio import dump_navigation_json, regenerate_derived_fields

_RULE = "NAV_REPLICA"


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
        两组各自保持输入顺序，彼此不重叠，合起来等于输入。`/a/b` 不覆盖 `/a/bc`。

    Raises:
        InputError: 某项没有字符串类型的 `direct_path`，或链接目标不是绝对路径。

    Side Effects:
        无。

    Time Semantics:
        同步纯函数，无时钟、无 I/O。
    """
    for target in link_targets:
        if not PurePosixPath(target).is_absolute():
            problem = nav_input_error(_RULE, "链接目标不是绝对路径", objects=(("target", target),))
            raise problem
    reached: list[JsonObject] = []
    unreached: list[JsonObject] = []
    for source in sources:
        direct = source.get("direct_path")
        if not isinstance(direct, str):
            problem = nav_input_error(_RULE, "数据块没有字符串类型的 direct_path")
            raise problem
        if any(_is_under(direct, target) for target in link_targets):
            reached.append(source)
        else:
            unreached.append(source)
    return tuple(reached), tuple(unreached)


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
        没有 `source_id` 的引用项判断不了该不该留，保守起见保留、不计入被筛掉的条数；
        该规则是否合适，以验收 1 的真实样本对拍结果为准。

    Raises:
        InputError: tasks 或其 sources 的结构不是约定的数组。

    Side Effects:
        无；返回新对象，不改输入。

    Time Semantics:
        同步纯函数，无时钟、无 I/O。
    """
    tasks = subtasks.get("tasks")
    if not isinstance(tasks, list) or not all(isinstance(task, dict) for task in tasks):
        problem = nav_input_error(_RULE, "子任务.json 的 tasks 不是对象数组")
        raise problem
    result: JsonObject = dict(subtasks)
    kept_tasks: list[JsonValue] = []
    omitted = 0
    dropped: list[str] = []
    for task in cast(list[JsonObject], tasks):
        references = task.get("sources")
        if not isinstance(references, list) or not all(isinstance(ref, dict) for ref in references):
            problem = nav_input_error(_RULE, "子任务的 sources 不是对象数组")
            raise problem
        kept_refs: list[JsonValue] = []
        for reference in cast(list[JsonObject], references):
            source_id = reference.get("source_id")
            # 没有 source_id 的引用判断不了该不该留，保守起见保留，不凭空丢数据。
            if not isinstance(source_id, str) or source_id in kept_source_ids:
                kept_refs.append(copy.deepcopy(reference))
            else:
                omitted += 1
        if references and not kept_refs:
            dropped.append(str(task.get("task_key")))
            continue
        kept_tasks.append({**copy.deepcopy(task), "sources": kept_refs})
    result["tasks"] = kept_tasks
    result["task_count"] = len(kept_tasks)
    return result, omitted, tuple(dropped)


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
    if current.location.view is not View.FORMAT:
        problem = nav_input_error(_RULE, "current 不是按格式入口", objects=_where(current))
        raise problem
    if canonical.location.view is not View.TASK:
        problem = nav_input_error(_RULE, "canonical 不是按任务入口", objects=_where(canonical))
        raise problem
    if canonical.dataset_id is None or canonical.dataset_id != current.dataset_id:
        problem = nav_input_error(
            _RULE,
            "规范副本与按格式入口的 dataset_id 不同",
            objects=(("canonical_entry", str(canonical.location.path)), *_where(current)),
        )
        raise problem
    manifest = _payload(canonical, 0)
    information = _payload(canonical, 1)
    subtasks = _payload(canonical, 2)
    current_manifest = _payload(current, 0)
    links = copy.deepcopy(current_manifest.get("links"))
    if not isinstance(links, list):
        problem = nav_input_error(_RULE, "按格式入口没有可用的 links[]", objects=_where(current))
        raise problem
    targets = tuple(
        str(cast(JsonObject, link).get("source_path")) for link in cast(list[JsonValue], links)
    )
    source_list = manifest.get("sources")
    if not isinstance(source_list, list):
        problem = nav_input_error(_RULE, "规范副本的 sources 不是数组", objects=_where(canonical))
        raise problem
    reached, unreached = select_reachable_sources(
        tuple(copy.deepcopy(cast(list[JsonObject], source_list))), targets
    )
    generated_manifest: JsonObject = copy.deepcopy(manifest)
    generated_manifest["links"] = links
    generated_manifest["sources"] = list(cast(tuple[JsonValue, ...], reached))
    kept_ids = frozenset(
        str(source["source_id"]) for source in reached if isinstance(source.get("source_id"), str)
    )
    filtered, omitted_refs, dropped = filter_subtasks(subtasks, kept_ids)
    return GeneratedEntry(
        location=current.location,
        files=(
            GeneratedFile(
                REQUIRED_DOCUMENTS[0],
                dump_navigation_json(
                    regenerate_derived_fields(generated_manifest, current.location)
                ),
            ),
            GeneratedFile(REQUIRED_DOCUMENTS[1], dump_navigation_json(information)),
            GeneratedFile(
                REQUIRED_DOCUMENTS[2],
                dump_navigation_json(regenerate_derived_fields(filtered, current.location)),
            ),
        ),
        omitted_source_ids=tuple(str(source.get("source_id")) for source in unreached),
        omitted_task_references=omitted_refs,
        dropped_task_keys=dropped,
    )


def _is_under(path: str, target: str) -> bool:
    """路径等于 target，或位于其下（前缀后紧跟 /）；按字符串判断，不 resolve。"""
    base = target.rstrip("/") or "/"
    return path == base or path.startswith(base.rstrip("/") + "/")


def _where(snapshot: EntrySnapshot) -> tuple[tuple[str, str], ...]:
    """诊断里的入口位置。"""
    return (("entry_path", str(snapshot.location.path)),)


def _payload(snapshot: EntrySnapshot, index: int) -> JsonObject:
    """取入口某份文档的内容；不可用就报输入错误，不用空对象顶替。"""
    document = snapshot.documents[index]
    if document.payload is None:
        problem = nav_input_error(
            _RULE, f"{document.name} 不可用，无法生成按格式入口", objects=_where(snapshot)
        )
        raise problem
    return document.payload
