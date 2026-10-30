"""M1-09 改指向行为测试；只读写临时导航和临时存储根。"""

import json
import shutil
from pathlib import Path

import pytest
from creation_support import creation_case
from nav_manifest import FakeNavigation
from navwrite_support import noop, tree_state


def test_repoint_both_views_and_provenance(tmp_path: Path, fake_nav: FakeNavigation) -> None:
    """验证 L8/L18：两个视图跟随前缀，来源和 original_path 不改，预览没有写副作用。"""
    from rdp.jobs.navwrite.repoint import build_repoint_preview
    from rdp.jobs.navwrite.repoint_models import RepointParameters

    with creation_case(tmp_path, fake_nav) as h:
        old = h.case.scanning.roots[1].path
        new = h.case.scanning.roots[0].path / "mirror"
        shutil.copytree(old, new)
        provenance = h.nav / "按任务/EgoProDemo/来源.json"
        provenance.write_text(json.dumps({"original_path": str(old), "lineage": [str(old)]}))
        before = tree_state(h.nav)
        build = build_repoint_preview(
            h.case.scanning,
            RepointParameters(dataset_id=h.dataset, old_prefix=str(old), new_prefix=str(new)),
            checkpoint=noop,
        )
        assert build.plan.operation.value == "repoint_dataset"
        assert build.report.file_count == 6 and build.report.link_count == 2
        assert all(not step.path.endswith("来源.json") for step in build.plan.steps)
        files = [step for step in build.plan.steps if step.op == "write_file"]
        for step in files:
            value = json.loads(step.after_content)
            if step.path.endswith("原始路径.json"):
                assert value["links"][0]["source_path"].startswith(str(new) + "/")
                assert value["sources"][0]["original_path"].startswith(str(old) + "/")
        assert build.report.field_counts
        assert tree_state(h.nav) == before


@pytest.mark.parametrize(
    "ending",
    [
        "",
        "/child",
        " ",
        "\t",
        "\n",
        "`",
        "'",
        '"',
        ")",
        "]",
        ">",
        "，",
        "。",
        "；",
        "：",
        "）",
        "」",
        "）。",
    ],
)
def test_markdown_boundary_each_occurrence(
    tmp_path: Path, fake_nav: FakeNavigation, ending: str
) -> None:
    """验证 L17/L18：Markdown 每种结束字符均可匹配，多次出现逐处列出且不误伤同名前缀。"""
    from rdp.jobs.navwrite.repoint import build_repoint_preview
    from rdp.jobs.navwrite.repoint_models import RepointParameters

    with creation_case(tmp_path, fake_nav) as h:
        old = str(h.case.scanning.roots[1].path / "EgoProDemo")
        new = str(h.case.scanning.roots[0].path / "mirror")
        shutil.copytree(old, new)
        path = h.nav / "按任务/EgoProDemo/数据集信息.json"
        value = json.loads(path.read_text())
        for field in value["fields"]:
            field["value_markdown"] = ""
        value["fields"][0]["value_markdown"] = f"{old}{ending} {old}_sim {old}"
        path.write_text(json.dumps(value))
        build = build_repoint_preview(
            h.case.scanning,
            RepointParameters(dataset_id=h.dataset, old_prefix=old, new_prefix=new),
            checkpoint=noop,
        )
        step = next(s for s in build.plan.steps if s.path == "按任务/EgoProDemo/数据集信息.json")
        assert step.op == "write_file"
        assert (
            json.loads(step.after_content)["fields"][0]["value_markdown"]
            == f"{new}{ending} {old}_sim {new}"
        )
        listed = [c for c in build.report.listed_changes if c.file == step.path]
        assert len(listed) == 2
        assert listed[0].json_path == "fields[0].value_markdown"
        counts = [c for c in build.report.field_counts if c.file == step.path]
        assert [(c.field, c.count) for c in counts] == [("fields[].value_markdown", 2)]


def test_existing_old_missing_new_rejects_whole_preview(
    tmp_path: Path, fake_nav: FakeNavigation
) -> None:
    """验证 L19：旧位置存在而新位置缺任一引用，预览整批拒绝、诊断带路径、导航未改。"""
    from rdp.infra.diagnostics import InputError
    from rdp.jobs.navwrite.repoint import build_repoint_preview
    from rdp.jobs.navwrite.repoint_models import RepointParameters

    with creation_case(tmp_path, fake_nav) as h:
        old = h.case.scanning.roots[1].path
        new = h.case.scanning.roots[0].path / "mirror"
        shutil.copytree(old, new)
        info = h.nav / "按任务/EgoProDemo/数据集信息.json"
        value = json.loads(info.read_text())
        old_file = old / "only-in-markdown.txt"
        old_file.write_text("原文件")
        value["fields"][0]["value_markdown"] = f"核对 `{old_file}`"
        info.write_text(json.dumps(value))
        before = tree_state(h.nav)
        with pytest.raises(InputError) as caught:
            build_repoint_preview(
                h.case.scanning,
                RepointParameters(dataset_id=h.dataset, old_prefix=str(old), new_prefix=str(new)),
                checkpoint=noop,
            )
        diagnostic = caught.value.diagnostics[0]
        assert diagnostic.rule == "NAV_REPOINT_TARGET"
        assert str(new / "only-in-markdown.txt") in str(diagnostic.objects)
        assert tree_state(h.nav) == before


def test_alpha_missing_paths_replaced_and_omissions_listed(
    tmp_path: Path, fake_nav: FakeNavigation
) -> None:
    """验证 L9/L19：alpha 原本缺失路径仍替换并标记，不可达三块从格式入口筛掉并明确列出。"""
    from navwrite_support import dataset_id_of

    from rdp.jobs.navwrite.repoint import build_repoint_preview
    from rdp.jobs.navwrite.repoint_models import RepointParameters

    with creation_case(tmp_path, fake_nav) as h:
        old = h.case.scanning.roots[1].path
        new = h.case.scanning.roots[0].path / "mirror"
        shutil.copytree(old, new)
        build = build_repoint_preview(
            h.case.scanning,
            RepointParameters(
                dataset_id=dataset_id_of(fake_nav, "agibot_world_alpha"),
                old_prefix=str(old),
                new_prefix=str(new),
            ),
            checkpoint=noop,
        )
        missing = [n for n in build.report.notices if n.code == "old_path_missing"]
        assert len(missing) >= 3
        assert all(dict(n.objects)["new_path"].startswith(str(new)) for n in missing)
        omitted = [n for n in build.report.notices if n.code == "source_not_reachable"]
        assert len(omitted) == 3
        canonical = next(
            s for s in build.plan.steps if s.path == "按任务/agibot_world_alpha/原始路径.json"
        )
        replica = next(
            s
            for s in build.plan.steps
            if s.path.startswith("按格式/") and s.path.endswith("原始路径.json")
        )
        assert canonical.op == "write_file"
        assert replica.op == "write_file"
        assert (
            len(json.loads(canonical.after_content)["sources"])
            - len(json.loads(replica.after_content)["sources"])
            == 3
        )


def test_report_describes_regenerated_replica_not_stale_copy(
    tmp_path: Path, fake_nav: FakeNavigation
) -> None:
    """验证 L8/规范2.2：格式信息整份来自规范副本，计数和逐处正文报告必须对应最终计划。"""
    from rdp.jobs.navwrite.repoint import build_repoint_preview
    from rdp.jobs.navwrite.repoint_models import RepointParameters

    with creation_case(tmp_path, fake_nav) as h:
        old = str(h.case.scanning.roots[1].path)
        new = str(h.case.scanning.roots[0].path / "mirror")
        shutil.copytree(old, new)
        canonical = h.nav / "按任务/EgoProDemo/数据集信息.json"
        replica = h.nav / "按格式/lerobot/3.0/EgoProDemo/数据集信息.json"
        value = json.loads(canonical.read_text())
        for field in value["fields"]:
            field["value_markdown"] = ""
        value["fields"][0]["value_markdown"] = old
        canonical.write_text(json.dumps(value))
        stale = json.loads(replica.read_text())
        for field in stale["fields"]:
            field["value_markdown"] = ""
        replica.write_text(json.dumps(stale))
        build = build_repoint_preview(
            h.case.scanning,
            RepointParameters(dataset_id=h.dataset, old_prefix=old, new_prefix=new),
            checkpoint=noop,
        )
        relative = "按格式/lerobot/3.0/EgoProDemo/数据集信息.json"
        listed = [c for c in build.report.listed_changes if c.file == relative]
        assert len(listed) == 1 and listed[0].after == new
        assert [(c.field, c.count) for c in build.report.field_counts if c.file == relative] == [
            ("fields[].value_markdown", 1)
        ]


def test_missing_old_still_rejects_unregistered_new_root(
    tmp_path: Path, fake_nav: FakeNavigation
) -> None:
    """验证本地根边界：旧路径本就缺失也不能把引用改到未登记根；不探测根外目标。"""
    from rdp.infra.diagnostics import InputError
    from rdp.jobs.navwrite.repoint import build_repoint_preview
    from rdp.jobs.navwrite.repoint_models import RepointParameters

    with creation_case(tmp_path, fake_nav) as h:
        old = str(h.case.scanning.roots[1].path / "already-missing")
        path = h.nav / "按任务/EgoProDemo/数据集信息.json"
        value = json.loads(path.read_text())
        value["future_path"] = old
        path.write_text(json.dumps(value))
        with pytest.raises(InputError) as caught:
            build_repoint_preview(
                h.case.scanning,
                RepointParameters(
                    dataset_id=h.dataset, old_prefix=old, new_prefix=str(tmp_path / "unregistered")
                ),
                checkpoint=noop,
            )
        assert caught.value.diagnostics[0].rule == "NAV_REPOINT_TARGET"


def test_json_values_notes_and_original_path_boundaries(
    tmp_path: Path, fake_nav: FakeNavigation
) -> None:
    """验证 L17/L18：未知键的嵌套字符串也替换，普通值只认斜杠/串尾，original_path 整项保留，notes 逐处列出。"""
    from rdp.jobs.navwrite.repoint import build_repoint_preview
    from rdp.jobs.navwrite.repoint_models import RepointParameters

    with creation_case(tmp_path, fake_nav) as h:
        old = str(h.case.scanning.roots[1].path)
        new = str(h.case.scanning.roots[0].path / "mirror")
        shutil.copytree(old, new)
        path = h.nav / "按任务/EgoProDemo/原始路径.json"
        value = json.loads(path.read_text())
        value["future"] = {
            "paths": [old, old + "/child", old + "_sim", old + " ", old + "。"],
            "original_path": {"nested": old},
            "notes": old + "。以及 " + old,
        }
        path.write_text(json.dumps(value))
        build = build_repoint_preview(
            h.case.scanning,
            RepointParameters(dataset_id=h.dataset, old_prefix=old, new_prefix=new),
            checkpoint=noop,
        )
        step = next(s for s in build.plan.steps if s.path == "按任务/EgoProDemo/原始路径.json")
        assert step.op == "write_file"
        result = json.loads(step.after_content)["future"]
        assert result["paths"] == [new, new + "/child", old + "_sim", old + " ", old + "。"]
        assert result["original_path"] == {"nested": old}
        assert result["notes"] == new + "。以及 " + new
        listed = [
            c
            for c in build.report.listed_changes
            if c.file == step.path and c.json_path == "future.notes"
        ]
        assert len(listed) == 2


@pytest.mark.parametrize("fault", ["offline", "escape", "nas"])
def test_target_failures_are_explicit_and_read_only(
    tmp_path: Path, fake_nav: FakeNavigation, fault: str
) -> None:
    """验证 L19：根离线、realpath 越界和 NAS 均明确拒绝，不降级为旧路径缺失，不写导航。"""
    from dataclasses import replace

    from datasets_storage_support import enable_storage

    from rdp.infra.config import StorageRootConfig
    from rdp.infra.diagnostics import ExternalError, InputError
    from rdp.jobs.navwrite.repoint import build_repoint_preview
    from rdp.jobs.navwrite.repoint_models import RepointParameters

    with creation_case(tmp_path, fake_nav) as h:
        deps = h.case.scanning
        old = deps.roots[1].path
        new = deps.roots[0].path / "mirror"
        if fault == "offline":
            enable_storage(h.case, table="")
            deps = h.case.scanning
        elif fault == "escape":
            new.symlink_to(tmp_path / "outside")
        else:
            root = StorageRootConfig(
                name=deps.roots[0].name, path=deps.roots[0].path, nfs_export="fake:/export"
            )
            deps = replace(deps, roots=(root, deps.roots[1]))
        before = tree_state(h.nav)
        with pytest.raises((ExternalError, InputError)) as caught:
            build_repoint_preview(
                deps,
                RepointParameters(dataset_id=h.dataset, old_prefix=str(old), new_prefix=str(new)),
                checkpoint=noop,
            )
        diagnostic = caught.value.diagnostics[0]
        assert diagnostic.rule == "NAV_REPOINT_TARGET"
        assert (
            isinstance(caught.value, ExternalError)
            if fault == "offline"
            else isinstance(caught.value, InputError)
        )
        assert tree_state(h.nav) == before


def test_notes_array_replaces_and_lists_each_occurrence(
    tmp_path: Path, fake_nav: FakeNavigation
) -> None:
    """验证真实 notes[] 结构的 L18：数组内每处引用按正文边界替换，并给出带下标的位置和分组计数。"""
    from rdp.jobs.navwrite.repoint import build_repoint_preview
    from rdp.jobs.navwrite.repoint_models import RepointParameters

    with creation_case(tmp_path, fake_nav) as h:
        old = str(h.case.scanning.roots[1].path)
        new = str(h.case.scanning.roots[0].path / "mirror")
        shutil.copytree(old, new)
        path = h.nav / "按任务/EgoProDemo/子任务.json"
        value = json.loads(path.read_text())
        value["tasks"][0]["notes"] = [f"核对 `{old}` 和 `{old}/child`"]
        path.write_text(json.dumps(value))
        build = build_repoint_preview(
            h.case.scanning,
            RepointParameters(dataset_id=h.dataset, old_prefix=old, new_prefix=new),
            checkpoint=noop,
        )
        step = next(s for s in build.plan.steps if s.path == "按任务/EgoProDemo/子任务.json")
        assert step.op == "write_file"
        assert json.loads(step.after_content)["tasks"][0]["notes"] == [
            f"核对 `{new}` 和 `{new}/child`"
        ]
        listed = [
            c
            for c in build.report.listed_changes
            if c.file == step.path and c.json_path == "tasks[0].notes[0]"
        ]
        assert len(listed) == 2
        counts = [
            c.count
            for c in build.report.field_counts
            if c.file == step.path and c.field == "tasks[].notes[]"
        ]
        assert counts == [2]


def test_complete_prose_report_survives_500_sample_limit(
    tmp_path: Path, fake_nav: FakeNavigation
) -> None:
    """验证 L18：超过底座500条样例预算仍能读取每处正文替换，原有样例字段上限保持不变。"""
    from rdp.jobs.navwrite.repoint import build_repoint_preview
    from rdp.jobs.navwrite.repoint_models import RepointParameters

    with creation_case(tmp_path, fake_nav) as h:
        old = str(h.case.scanning.roots[1].path)
        new = str(h.case.scanning.roots[0].path / "mirror")
        shutil.copytree(old, new)
        path = h.nav / "按任务/EgoProDemo/原始路径.json"
        value = json.loads(path.read_text())
        value["notes"] = [f"位置 `{old}`"] * 501
        path.write_text(json.dumps(value))
        build = build_repoint_preview(
            h.case.scanning,
            RepointParameters(dataset_id=h.dataset, old_prefix=old, new_prefix=new),
            checkpoint=noop,
        )
        payload = build.report.model_dump(mode="json")
        assert len(payload["listed_changes"]) == 500
        complete = payload["repoint_changes"]
        assert complete is not None and len(complete) == payload["listed_total"]
        canonical_notes = [
            c
            for c in complete
            if c["file"] == "按任务/EgoProDemo/原始路径.json"
            and c["json_path"].startswith("notes[")
        ]
        assert len(canonical_notes) == 501
        assert canonical_notes[-1]["json_path"] == "notes[500]"
        assert new in canonical_notes[-1]["after"]


def test_complete_prose_report_over_budget_rejects(
    tmp_path: Path, fake_nav: FakeNavigation
) -> None:
    """验证完整报告预算：超30000处则整批拒绝而非静默丢失正文差异，导航未改。"""
    from rdp.infra.diagnostics import InputError
    from rdp.jobs.navwrite.repoint import build_repoint_preview
    from rdp.jobs.navwrite.repoint_models import RepointParameters

    with creation_case(tmp_path, fake_nav) as h:
        old = str(h.case.scanning.roots[1].path)
        path = h.nav / "按任务/EgoProDemo/原始路径.json"
        value = json.loads(path.read_text())
        value["notes"] = [old] * 30_001
        path.write_text(json.dumps(value))
        before = tree_state(h.nav)
        with pytest.raises(InputError) as caught:
            build_repoint_preview(
                h.case.scanning,
                RepointParameters(
                    dataset_id=h.dataset,
                    old_prefix=old,
                    new_prefix=str(h.case.scanning.roots[0].path),
                ),
                checkpoint=noop,
            )
        diagnostic = caught.value.diagnostics[0]
        assert diagnostic.rule == "NAV_REPOINT_REPORT"
        assert any(o.key == "limit" and o.value == "30000" for o in diagnostic.objects)
        assert tree_state(h.nav) == before
