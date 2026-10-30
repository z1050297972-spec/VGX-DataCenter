"""单入口①组比较；原载荷与投影分开，不重复生成读取层已经报告的文件失败。"""

from rdp.jobs.datasets import _json, vocabulary
from rdp.jobs.datasets._panel_issue import difference
from rdp.jobs.datasets.panel import NavigationRule
from rdp.jobs.datasets.types import EntrySnapshot, Finding, JsonObject, View


def check(entry: EntrySnapshot) -> tuple[Finding, ...]:
    """只比较可用文件声明的身份，缺文件不会触发连锁身份误报。"""
    issues: list[Finding] = []
    identifiers = {
        doc.name: doc.payload["dataset_id"] for doc in entry.documents if doc.payload is not None
    }
    if len(set(str(value) for value in identifiers.values())) > 1:
        issues.append(
            difference(
                entry,
                NavigationRule.DATASET_ID_MISMATCH,
                ("dataset_id", identifiers, "三份文件声明同一永久编号"),
            )
        )
    for document in entry.documents:
        payload = document.payload
        if (
            payload is not None
            and "dataset_name" in payload
            and payload["dataset_name"] != entry.location.dataset_name
        ):
            issues.append(
                difference(
                    entry,
                    NavigationRule.DATASET_NAME_MISMATCH,
                    (
                        document.name + ".dataset_name",
                        payload["dataset_name"],
                        entry.location.dataset_name,
                    ),
                )
            )
    if entry.location.view is View.TASK and not entry.provenance_present:
        # ADR0008把来源文件放在规范入口；按数据集提示一次，不要求格式切片复制血缘文件。
        issues.append(
            difference(
                entry,
                NavigationRule.PROVENANCE_MISSING,
                ("来源.json", "文件缺失，数据来源与来历未知", "规范入口有来源记录"),
                notice=True,
            )
        )
    if entry.location.view is View.TASK:
        issues.extend(_vocabulary(entry))
    issues.extend(_derived(entry))
    return tuple(
        sorted(issues, key=lambda item: (item.diagnostic.rule, item.diagnostic.objects[-1].value))
    )


def _vocabulary(entry: EntrySnapshot) -> tuple[Finding, ...]:
    """分类字段的词表外取值只提示不拦截：值照样保留，筛选里按原值出现（M1.5-03）。"""
    issues: list[Finding] = []
    if entry.scene is not None and vocabulary.scene_name(entry.scene) is None:
        issues.append(
            difference(
                entry,
                NavigationRule.VOCABULARY_UNKNOWN,
                ("数据集信息.json.scene", f"不在词表：{entry.scene}", "场景词表内的编码"),
                notice=True,
            )
        )
    unknown = [code for code in entry.tasks if vocabulary.task_name(code) is None]
    if unknown:
        issues.append(
            difference(
                entry,
                NavigationRule.VOCABULARY_UNKNOWN,
                ("数据集信息.json.tasks", f"不在词表：{'、'.join(unknown)}", "任务词表内的编码"),
                notice=True,
            )
        )
    return tuple(issues)


def _derived(entry: EntrySnapshot) -> tuple[Finding, ...]:
    """顶层位置与逐项入口路径分别比较，数据块format/version不当作位置字段覆盖。"""
    issues: list[Finding] = []
    expected = {
        "view": entry.location.view.value,
        "format": entry.location.format,
        "version": entry.location.version,
    }
    for document in entry.documents:
        payload = document.payload
        if payload is None or document.name == "数据集信息.json":
            continue
        for field, value in expected.items():
            if payload.get(field) != value:
                issues.append(
                    difference(
                        entry,
                        NavigationRule.DERIVED_FIELD_MISMATCH,
                        (document.name + "." + field, payload.get(field), value),
                    )
                )
        if document.name == "原始路径.json":
            issues.extend(
                _paths(entry, payload, "links", tuple(link.entry_path for link in entry.links))
            )
            issues.extend(
                _paths(
                    entry, payload, "sources", tuple(source.entry_path for source in entry.sources)
                )
            )
    return tuple(issues)


def _paths(
    entry: EntrySnapshot, payload: JsonObject, field: str, expected: tuple[str, ...]
) -> tuple[Finding, ...]:
    """只核对读取依赖已通过的原始路径清单，文件失败不再逐字段连锁报错。"""
    result: list[Finding] = []
    for index, (item, value) in enumerate(
        zip(_json.objects(payload[field], field), expected, strict=True)
    ):
        if item.get("entry_path") != value:
            result.append(
                difference(
                    entry,
                    NavigationRule.DERIVED_FIELD_MISMATCH,
                    (f"原始路径.json.{field}[{index}].entry_path", item.get("entry_path"), value),
                )
            )
    return tuple(result)
