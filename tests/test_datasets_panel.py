"""面板①②组；每例在fake_nav上改一处，核对对象、规则、级别及五段后果。"""

import os
import shutil
import weakref
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from datasets_execution_support import dataset_case
from datasets_panel_support import assert_finding, entries
from datasets_support import checkpoint, edit_json
from nav_manifest import FakeNavigation
from sqlalchemy import func, select

from rdp.infra.db.connection import session_scope
from rdp.infra.diagnostics import DIAGNOSTIC_SAMPLE_LIMIT, Diagnostic
from rdp.jobs.datasets.models import FindingRow
from rdp.jobs.datasets.panel import aggregate_findings, inspect_entry, inspect_views
from rdp.jobs.datasets.reading import discover_entries, read_entry
from rdp.jobs.datasets.types import Finding, PanelGroup, PanelSeverity


def test_json_unreadable(fake_nav: FakeNavigation, monkeypatch: pytest.MonkeyPatch) -> None:
    """验收7①1：文件打不开报JSON_UNREADABLE，需要处理，包含入口和文件身份。"""
    original = os.open

    def fail(path: Any, *args: Any, **kwargs: Any) -> int:
        if path == "原始路径.json":
            raise PermissionError("测试权限拒绝")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(os, "open", fail)
    entry = entries(fake_nav)[0]
    assert entry.dataset_id == "dataset-14"
    assert_finding(entry.findings + inspect_entry(entry), "JSON_UNREADABLE", "按任务/libero_10")


def test_json_invalid(fake_nav: FakeNavigation) -> None:
    """验收7①1：JSON解析失败报JSON_INVALID，需要处理，失败入口只计一次。"""
    (fake_nav.nav_root / "按任务/libero_10/原始路径.json").write_text("{")
    entry = entries(fake_nav)[0]
    assert_finding(entry.findings + inspect_entry(entry), "JSON_INVALID", "按任务/libero_10")
    assert entry.documents[0].payload is None and entry.documents[1].payload is not None


def test_required_field(fake_nav: FakeNavigation) -> None:
    """验收7①1：缺依赖字段报JSON_REQUIRED_FIELD，需要处理，不为同文件每个缺字段重复计失败条目。"""
    edit_json(
        fake_nav.nav_root / "按任务/libero_10/原始路径.json", lambda data: data.pop("dataset_roots")
    )
    entry = entries(fake_nav)[0]
    result = entry.findings + inspect_entry(entry)
    item = assert_finding(result, "JSON_REQUIRED_FIELD", "按任务/libero_10")
    assert "dataset_roots" in item.diagnostic.actual
    assert len([item for item in result if item.diagnostic.rule == "JSON_REQUIRED_FIELD"]) == 1


def test_schema_version(fake_nav: FakeNavigation) -> None:
    """验收7①1：不认识的schema_version报JSON_SCHEMA_VERSION，需要处理，文件不参与下游比较。"""
    edit_json(
        fake_nav.nav_root / "按任务/libero_10/原始路径.json",
        lambda data: data.update(schema_version=9),
    )
    entry = entries(fake_nav)[0]
    assert_finding(entry.findings + inspect_entry(entry), "JSON_SCHEMA_VERSION", "按任务/libero_10")
    assert entry.documents[0].payload is None
    assert not any(
        item.diagnostic.rule == "DERIVED_FIELD_MISMATCH" for item in inspect_entry(entry)
    )


def test_identity_mismatch(fake_nav: FakeNavigation) -> None:
    """验收7①2：入口三份dataset_id不同报DATASET_ID_MISMATCH，需要处理，保留各原值。"""
    edit_json(
        fake_nav.nav_root / "按任务/libero_10/子任务.json",
        lambda data: data.update(dataset_id="dataset-other"),
    )
    entry = entries(fake_nav)[0]
    result = inspect_entry(entry)
    assert_finding(result, "DATASET_ID_MISMATCH", "按任务/libero_10")


def test_name_mismatch(fake_nav: FakeNavigation) -> None:
    """验收7①2：dataset_name不等于目录名报DATASET_NAME_MISMATCH，需要处理；不把dataset_id文本与目录名直接比较。"""
    edit_json(
        fake_nav.nav_root / "按任务/libero_10/原始路径.json",
        lambda data: data.update(dataset_name="错误目录名"),
    )
    entry = entries(fake_nav)[0]
    assert_finding(inspect_entry(entry), "DATASET_NAME_MISMATCH", "按任务/libero_10")


def test_duplicate_task_identity(fake_nav: FakeNavigation) -> None:
    """验收7①2：两个按任务入口同编号报DUPLICATE_TASK_ID，需要处理，均保留且不任取规范副本。"""
    source = fake_nav.nav_root / "按任务/libero_10"
    shutil.copytree(source, fake_nav.nav_root / "按任务/libero_copy", symlinks=True)
    observed = tuple(
        read_entry(fake_nav.nav_root, item, checkpoint=checkpoint)
        for item in discover_entries(fake_nav.nav_root).entries
        if item.dataset_name in {"libero_10", "libero_copy"}
    )
    result = inspect_views(observed)
    assert_finding(result, "DUPLICATE_TASK_ID", "按任务/libero_copy")
    assert not any(item.group is PanelGroup.VIEWS for item in result)


def test_canonical_missing(fake_nav: FakeNavigation) -> None:
    """验收7①3：仅有按格式入口报CANONICAL_MISSING，需要处理，仍正常列出。"""
    shutil.rmtree(fake_nav.nav_root / "按任务/libero_10")
    result = inspect_views(entries(fake_nav))
    assert_finding(result, "CANONICAL_MISSING", "按格式/lerobot/3.0/libero_10")


def test_unregistered_format(fake_nav: FakeNavigation) -> None:
    """验收7①4：未知格式目录报FORMAT_UNREGISTERED，需要处理且不进入目标扫描。"""
    (fake_nav.nav_root / "按格式/未登记格式").mkdir()
    result = discover_entries(fake_nav.nav_root)
    assert_finding(result.findings, "FORMAT_UNREGISTERED", "按格式/未登记格式")
    assert len(result.entries) == 10


def test_unregistered_top_directory(fake_nav: FakeNavigation) -> None:
    """验收7①4：假VGX_video目录报TOP_LEVEL_UNREGISTERED，需要处理，非数据集登记目录不扫描。"""
    (fake_nav.nav_root / "new-directory").mkdir()
    result = discover_entries(fake_nav.nav_root)
    assert_finding(result.findings, "TOP_LEVEL_UNREGISTERED", "VGX_video")
    assert any(item.diagnostic.objects[0].value == "new-directory" for item in result.findings)
    assert len(result.entries) == 10


def test_unregistered_top_file(fake_nav: FakeNavigation) -> None:
    """验收7①4：顶层未知文件同样报TOP_LEVEL_UNREGISTERED，需要处理。"""
    (fake_nav.nav_root / "unknown.txt").write_text("外部说明")
    result = discover_entries(fake_nav.nav_root)
    item = next(
        item for item in result.findings if item.diagnostic.objects[0].value == "unknown.txt"
    )
    assert_finding((item,), "TOP_LEVEL_UNREGISTERED", "unknown.txt")


def test_removed_directory(fake_nav: FakeNavigation) -> None:
    """验收7：已移除目录属于L7登记表，不报未知顶层，不扫描内部入口。"""
    folder = fake_nav.nav_root / "已移除/旧数据集"
    folder.mkdir(parents=True)
    (folder / "原始路径.json").write_text("{")
    result = discover_entries(fake_nav.nav_root)
    assert len(result.entries) == 10
    assert not any(
        "已移除" in obj.value for item in result.findings for obj in item.diagnostic.objects
    )


def test_derived_mismatch(fake_nav: FakeNavigation) -> None:
    """验收7①5：分别改view/format/version及links和sources的entry_path均报DERIVED_FIELD_MISMATCH，需要处理。"""
    path = fake_nav.nav_root / "按任务/libero_10/原始路径.json"
    original = path.read_text()
    for field in ("view", "format", "version", "links", "sources"):

        def change(data: dict[str, Any], field: str = field) -> None:
            if field in {"links", "sources"}:
                data[field][0]["entry_path"] = "错误位置"
            else:
                data[field] = "错误位置"

        edit_json(path, change)
        result = inspect_entry(entries(fake_nav)[0])
        item = assert_finding(result, "DERIVED_FIELD_MISMATCH", "按任务/libero_10")
        assert field in item.diagnostic.objects[-1].value
        path.write_text(original)
    edit_json(path, lambda data: data.pop("version"))
    assert not any(
        item.diagnostic.rule == "DERIVED_FIELD_MISMATCH"
        for item in inspect_entry(entries(fake_nav)[0])
    )


def test_information_mismatch(fake_nav: FakeNavigation) -> None:
    """验收7②6：修改格式入口信息正文报INFORMATION_MISMATCH，需要处理，展示仍取规范副本。"""
    path = fake_nav.nav_root / "按格式/lerobot/3.0/libero_10/数据集信息.json"
    edit_json(path, lambda data: data["fields"][0].update(value_markdown="错误说明"))
    observed = entries(fake_nav)
    assert_finding(
        inspect_views(observed),
        "INFORMATION_MISMATCH",
        "按格式/lerobot/3.0/libero_10",
        group=PanelGroup.VIEWS,
    )
    assert observed[0].documents[1].payload != observed[1].documents[1].payload


def test_source_subset(fake_nav: FakeNavigation) -> None:
    """验收7②7：格式入口增加规范副本没有的source_id报SOURCE_SUBSET_MISMATCH，需要处理。"""
    path = fake_nav.nav_root / "按格式/lerobot/3.0/libero_10/原始路径.json"

    def add(data: dict[str, Any]) -> None:
        data["sources"].append(data["sources"][0] | {"source_id": "src_extra"})

    edit_json(path, add)
    item = assert_finding(
        inspect_views(entries(fake_nav)),
        "SOURCE_SUBSET_MISMATCH",
        "按格式/lerobot/3.0/libero_10",
        group=PanelGroup.VIEWS,
    )
    assert "src_extra" in item.diagnostic.actual


def test_source_content(fake_nav: FakeNavigation) -> None:
    """验收7②7：相同source_id的非位置字段（包括数据块format/version及未知字段）改变报SOURCE_CONTENT_MISMATCH。"""
    path = fake_nav.nav_root / "按格式/lerobot/3.0/libero_10/原始路径.json"
    original = path.read_text()
    for field in ("format", "version", "validation_status", "unknown_field"):

        def change_source(data: dict[str, Any], key: str = field) -> None:
            data["sources"][0][key] = "changed"

        edit_json(path, change_source)
        assert_finding(
            inspect_views(entries(fake_nav)),
            "SOURCE_CONTENT_MISMATCH",
            "按格式/lerobot/3.0/libero_10",
            group=PanelGroup.VIEWS,
        )
        path.write_text(original)
    edit_json(path, lambda data: data["sources"].append(data["sources"][0].copy()))
    assert_finding(
        inspect_views(entries(fake_nav)),
        "SOURCE_CONTENT_MISMATCH",
        "按格式/lerobot/3.0/libero_10",
        group=PanelGroup.VIEWS,
    )


def test_dataset_header(fake_nav: FakeNavigation) -> None:
    """验收7②7：格式入口dataset_name或dataset_roots不同报DATASET_HEADER_MISMATCH，需要处理。"""
    path = fake_nav.nav_root / "按格式/lerobot/3.0/libero_10/原始路径.json"
    original = path.read_text()
    for field, value in (
        ("dataset_name", "不一致"),
        ("dataset_roots", [str(fake_nav.storage_roots[0].path / "other")]),
    ):

        def change_header(data: dict[str, Any], key: str = field, selected: object = value) -> None:
            data[key] = selected

        edit_json(path, change_header)
        item = assert_finding(
            inspect_views(entries(fake_nav)),
            "DATASET_HEADER_MISMATCH",
            "按格式/lerobot/3.0/libero_10",
            group=PanelGroup.VIEWS,
        )
        assert field in item.diagnostic.objects[-1].value
        path.write_text(original)


def test_task_subset(fake_nav: FakeNavigation) -> None:
    """验收7②7：格式入口增加规范副本没有的task_key报TASK_SUBSET_MISMATCH，需要处理。"""
    path = fake_nav.nav_root / "按格式/lerobot/3.0/libero_10/子任务.json"
    edit_json(
        path, lambda data: data["tasks"].append(data["tasks"][0] | {"task_key": "task_extra"})
    )
    item = assert_finding(
        inspect_views(entries(fake_nav)),
        "TASK_SUBSET_MISMATCH",
        "按格式/lerobot/3.0/libero_10",
        group=PanelGroup.VIEWS,
    )
    assert "task_extra" in item.diagnostic.actual


def test_task_content(fake_nav: FakeNavigation) -> None:
    """验收7②7：同task_key非位置字段不同或非依赖tasks结构损坏报TASK_CONTENT_MISMATCH，不影响宽松读取可用性。"""
    path = fake_nav.nav_root / "按格式/lerobot/3.0/libero_10/子任务.json"
    original = path.read_text()
    edit_json(path, lambda data: data["tasks"][0].update(display_name="改了任务名"))
    assert_finding(
        inspect_views(entries(fake_nav)),
        "TASK_CONTENT_MISMATCH",
        "按格式/lerobot/3.0/libero_10",
        group=PanelGroup.VIEWS,
    )
    path.write_text(original)
    edit_json(path, lambda data: data.update(tasks="损坏的非依赖结构"))
    observed = entries(fake_nav)
    assert observed[1].documents[2].payload is not None
    assert_finding(
        inspect_views(observed),
        "TASK_CONTENT_MISMATCH",
        "按格式/lerobot/3.0/libero_10",
        group=PanelGroup.VIEWS,
    )


def test_egopro_subset(fake_nav: FakeNavigation) -> None:
    """验收7②7：EgoProDemo按格式合法筛去source和task引用不报内容差异；位置字段和省略version不制造误报。"""
    for name in (
        "libero_10",
        "EgoProDemo",
        "EgoProStandard",
        "agibot_world_alpha",
        "R1_lite_table_withdrawing_mcap",
    ):
        assert inspect_views(entries(fake_nav, name)) == ()
    root = fake_nav.nav_root / "按任务/EgoProDemo"
    extra_path = str(fake_nav.storage_roots[1].path / "EgoProDemo/extra.mcap")

    def extend_manifest(data: dict[str, Any]) -> None:
        data["sources"].append(
            data["sources"][0]
            | {
                "source_id": "src_extra_mcap",
                "direct_path": extra_path,
                "original_path": extra_path,
                "format": "mcap",
                "version": None,
            }
        )

    edit_json(root / "原始路径.json", extend_manifest)

    def mix(data: dict[str, Any]) -> None:
        extra = data["tasks"][0]["sources"][0] | {
            "source_id": "src_extra_mcap",
            "root": extra_path,
            "format": "mcap",
            "version": None,
        }
        data["tasks"][0]["sources"].append(extra)

    edit_json(root / "子任务.json", mix)
    assert inspect_views(entries(fake_nav, "EgoProDemo")) == ()


def test_provenance_missing(fake_nav: FakeNavigation) -> None:
    """ADR0008：缺来源.json产生PROVENANCE_MISSING提示，数据来源未知，不计作业失败或作业警告。"""
    observations = entries(fake_nav)
    notices = [
        item
        for entry in observations
        for item in inspect_entry(entry)
        if item.diagnostic.rule == "PROVENANCE_MISSING"
    ]
    assert len(notices) == 1
    assert notices[0].severity.value == "notice" and notices[0].diagnostic.level.value == "warning"
    assert notices[0].diagnostic.objects[0].value == "按任务/libero_10"
    (fake_nav.nav_root / "按任务/libero_10/来源.json").write_text("不解析内容")
    assert not any(
        item.diagnostic.rule == "PROVENANCE_MISSING"
        for entry in entries(fake_nav)
        for item in inspect_entry(entry)
    )


def test_aggregation(fake_nav: FakeNavigation) -> None:
    """验收7：同组级别来源规则完整累计超过10条时只保留前10样例，顺序确定；对象、实际、期望、后果、下一步齐全。"""
    edit_json(
        fake_nav.nav_root / "按任务/libero_10/原始路径.json",
        lambda data: data.update(dataset_name="错误名"),
    )
    seed = next(
        item
        for item in inspect_entry(entries(fake_nav)[0])
        if item.diagnostic.rule == "DATASET_NAME_MISMATCH"
    )
    references: list[weakref.ReferenceType[Diagnostic]] = []

    def stream() -> Iterator[Finding]:
        for index in range(17):
            diagnostic = Diagnostic.model_validate(
                seed.diagnostic.model_dump() | {"actual": f"第{index}项不一致"}
            )
            references.append(weakref.ref(diagnostic))
            yield Finding(seed.group, seed.severity, diagnostic)
            assert sum(ref() is not None for ref in references) <= DIAGNOSTIC_SAMPLE_LIMIT + 1

    result = aggregate_findings(stream())
    assert len(result) == 1
    assert result[0].severity is PanelSeverity.ACTION_REQUIRED
    assert result[0].diagnostics.total == result[0].diagnostics.error_count == 17
    assert result[0].diagnostics.warning_count == 0
    assert len(result[0].diagnostics.samples) == 10
    assert result[0].diagnostics.samples[0].actual == "第0项不一致"
    assert result[0].diagnostics.samples[-1].actual == "第9项不一致"


def test_findings_not_failures(tmp_path: Path, fake_nav: FakeNavigation) -> None:
    """11 Q14：面板需要处理发现不直接决定作业失败；只有无法完整索引的入口和跳过检查分别进入失败与警告计数。"""
    edit_json(
        fake_nav.nav_root / "按任务/libero_10/原始路径.json",
        lambda data: data.update(dataset_name="目录名不同"),
    )
    with dataset_case(tmp_path / "state", fake_nav) as case:
        result = case.run()
        assert result.summary is not None
        assert result.summary.failed_items == result.summary.warning_count == 0
        assert result.summary.outcome is not None and result.summary.outcome.value == "succeeded"
        with session_scope(case.engine, read_only=True) as session:
            rows = tuple(
                session.scalars(
                    select(FindingRow).where(FindingRow.rule == "DATASET_NAME_MISMATCH")
                )
            )
            assert len(rows) == 1 and rows[0].total == 1
        (fake_nav.nav_root / "按任务/libero_10/数据集信息.json").write_text("{")
        failed = case.run()
        assert failed.summary is not None and failed.summary.failed_items == 1
        assert (
            failed.summary.outcome is not None
            and failed.summary.outcome.value == "partially_succeeded"
        )


def test_fake_navigation_expected_findings(tmp_path: Path, fake_nav: FakeNavigation) -> None:
    """未修改样本只报VGX顶层目录和五个数据集缺来源，alpha失效路径及合法视图切片不属于①②组错误。"""
    with dataset_case(tmp_path / "state", fake_nav) as case:
        result = case.run()
        assert result.summary is not None and result.summary.outcome is not None
        assert result.summary.outcome.value == "succeeded"
        with session_scope(case.engine, read_only=True) as session:
            totals = {
                rule: total
                for rule, total in session.execute(
                    select(FindingRow.rule, func.sum(FindingRow.total)).group_by(FindingRow.rule)
                )
            }
        assert totals == {"TOP_LEVEL_UNREGISTERED": 1, "PROVENANCE_MISSING": 5}


def test_cross_dataset_task_reference_is_preserved(fake_nav: FakeNavigation) -> None:
    """libero类跨数据集引用在两视图相同时不被当作格式未入选块删除，不跨数据集全局去重task_key。"""
    for relative in ("按任务/libero_10", "按格式/lerobot/3.0/libero_10"):

        def extend(data: dict[str, Any]) -> None:
            data["tasks"][0]["sources"].append(
                data["tasks"][0]["sources"][0] | {"source_id": "src_other_dataset"}
            )

        edit_json(fake_nav.nav_root / relative / "子任务.json", extend)
    assert inspect_views(entries(fake_nav)) == ()


def test_duplicate_canonical_source_is_reported(fake_nav: FakeNavigation) -> None:
    """规范副本重复source_id不能被字典覆盖而静默通过，诊断定位规范入口。"""
    path = fake_nav.nav_root / "按任务/libero_10/原始路径.json"
    edit_json(path, lambda data: data["sources"].append(data["sources"][0].copy()))
    assert_finding(
        inspect_views(entries(fake_nav)),
        "SOURCE_CONTENT_MISMATCH",
        "按任务/libero_10",
        group=PanelGroup.VIEWS,
    )


def test_duplicate_task_key_is_reported(fake_nav: FakeNavigation) -> None:
    """任一入口重复task_key都须报告，跨数据集同名仍允许。"""
    for relative in ("按格式/lerobot/3.0/libero_10", "按任务/libero_10"):
        path = fake_nav.nav_root / relative / "子任务.json"
        original = path.read_text()
        edit_json(path, lambda data: data["tasks"].append(data["tasks"][0].copy()))
        assert_finding(
            inspect_views(entries(fake_nav)),
            "TASK_CONTENT_MISMATCH",
            relative,
            group=PanelGroup.VIEWS,
        )
        path.write_text(original)
