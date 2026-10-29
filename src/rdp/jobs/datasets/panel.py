"""一致性面板①②组（领域层，M1-01）；只比较导航快照，不探测磁盘、不修复事实来源。

五段诊断和有界样例复用 infra.diagnostics；跨视图的子集规则是11 Q14业务逻辑。
面板发现与扫描失败条目分别计数，不能因为 ERROR 展示级别就判作业失败。
"""

from collections.abc import Iterable
from enum import StrEnum

from rdp.jobs.datasets.types import EntrySnapshot, Finding, FindingGroup


class NavigationRule(StrEnum):
    """稳定规则码供五段诊断聚合，不能把对象名放进规则码。"""

    JSON_UNREADABLE = "JSON_UNREADABLE"
    JSON_INVALID = "JSON_INVALID"
    JSON_REQUIRED_FIELD = "JSON_REQUIRED_FIELD"
    JSON_SCHEMA_VERSION = "JSON_SCHEMA_VERSION"
    DATASET_ID_MISMATCH = "DATASET_ID_MISMATCH"
    DATASET_NAME_MISMATCH = "DATASET_NAME_MISMATCH"
    DUPLICATE_TASK_ID = "DUPLICATE_TASK_ID"
    CANONICAL_MISSING = "CANONICAL_MISSING"
    FORMAT_UNREGISTERED = "FORMAT_UNREGISTERED"
    TOP_LEVEL_UNREGISTERED = "TOP_LEVEL_UNREGISTERED"
    NAV_UNSAFE_DIRECTORY = "NAV_UNSAFE_DIRECTORY"
    DERIVED_FIELD_MISMATCH = "DERIVED_FIELD_MISMATCH"
    INFORMATION_MISMATCH = "INFORMATION_MISMATCH"
    SOURCE_SUBSET_MISMATCH = "SOURCE_SUBSET_MISMATCH"
    SOURCE_CONTENT_MISMATCH = "SOURCE_CONTENT_MISMATCH"
    DATASET_HEADER_MISMATCH = "DATASET_HEADER_MISMATCH"
    TASK_SUBSET_MISMATCH = "TASK_SUBSET_MISMATCH"
    TASK_CONTENT_MISMATCH = "TASK_CONTENT_MISMATCH"
    PROVENANCE_MISSING = "PROVENANCE_MISSING"
    RECORDED_SIZE_MISSING = "RECORDED_SIZE_MISSING"
    DATASET_CHANGED = "DATASET_CHANGED"


def inspect_entry(entry: EntrySnapshot) -> tuple[Finding, ...]:
    """核对单入口身份、推导字段及来源文件存在性。

    Args:
        entry: 同一次读取的入口快照，允许部分或全部文件不可用。

    Returns:
        按规则码、对象字段路径排序的发现，合法且有来源文件时可为空。
        三份可用 JSON 的 dataset_id 不同、任何已存 dataset_name 与目录名不同，
        或 view/format/version/links.entry_path/sources.entry_path 与投影不同均为需要处理。
        缺省 version 与 null 等价；按任务的 format/version 必须推导为 None。
        来源.json 缺失产生 PROVENANCE_MISSING 提示；有文件也不猜测数据来源或解析血缘。
        不重复加入 entry.findings，不因文件不可用连锁报告它的所有字段都不同。

    Raises:
        DefectError: 快照内部种类、位置与投影类型不符合读取契约。

    Side Effects:
        无；只比较输入对象，不修改文档，不上报作业失败或警告计数。

    Time Semantics:
        不读取当前磁盘或时钟；检查结果属于快照观察时间，不声称当前链接仍存在。
    """
    raise NotImplementedError


def inspect_views(entries: tuple[EntrySnapshot, ...]) -> tuple[Finding, ...]:
    """按永久编号核对规范副本唯一性和格式入口的子集关系。

    Args:
        entries: 一个 dataset_id 的全部入口，路径升序；全量归组时也保留重复按任务入口。
            无法识别编号的入口单独一组，不按同名目录冒认同一数据集。

    Returns:
        需要处理发现的确定顺序元组；只有按格式入口报 CANONICAL_MISSING。
        多个按任务入口声明同编号报 DUPLICATE_TASK_ID，不任取一份作规范副本，也不覆盖入口。
        唯一规范副本存在时，信息 JSON 按解析内容比较（对象键顺序和排版无关，数组顺序保留）；
        格式 sources 按 source_id、tasks 按 task_key 对规范副本作子集检查。
        同身份记录只排除位置字段 view/format/version（入口顶层）及 entry_path；
        数据块自身 format/version 是数据属性，必须比较，省略 version 与 null 等价。
        子任务引用按入选数据块作子集核对，允许 EgoProDemo 筛去数据块及相关任务引用；
        未知非位置字段同样比较；dataset_name/dataset_roots 与规范副本不同单独报告。
        文件不可用不执行依赖它的比较；子任务非依赖结构错误以 TASK_CONTENT_MISMATCH 报告，
        不反过来让合法读取失效。规范副本显示优先，孤立格式入口仍可列出。

    Raises:
        DefectError: 输入重复路径、混入互不相关编号或包含未验证的快照类型。

    Side Effects:
        无；只比较快照，不重新算 source_id，不重写 original_path，不查存储根。

    Time Semantics:
        同批次的视图之间比较；空输入返回空元组，不等待规范副本出现。
    """
    raise NotImplementedError


def aggregate_findings(findings: Iterable[Finding]) -> tuple[FindingGroup, ...]:
    """完整计数面板发现并保留每组前几个五段样例。

    Args:
        findings: 有限、按入口路径及规则排序的发现迭代器，可空；迭代异常向上传播。

    Returns:
        按组、级别、来源和规则排序的元组；每组复用 aggregate_diagnostics，
        总数完整、样例至多 DIAGNOSTIC_SAMPLE_LIMIT 条，空输入为空。

    Raises:
        DefectError: 发现级别和 Diagnostic.level 映射不一致或组非法。
        Exception: 输入迭代器本身失败，不把部分聚合结果冒充完整结果。

    Side Effects:
        无；单次消费迭代器，只保留有界样例，不累积所有诊断文本，不修改作业计数。

    Time Semantics:
        结果只反映输入顺序，无系统时钟；不按发现时间重新排序或丢弃旧发现。
    """
    raise NotImplementedError
