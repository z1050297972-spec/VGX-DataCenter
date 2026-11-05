"""M1-08 契约行为清单；只使用临时目录或 tests 假导航，真实副本演练由执行线负责。"""

from pathlib import Path

import pytest
from creation_support import creation_case, link_parameters, target_path
from nav_manifest import FakeNavigation
from navwrite_support import noop, tree_state

from rdp.jobs.navwrite.create_builders import build_dataset_preview, build_link_preview
from rdp.jobs.navwrite.create_models import (
    DatasetPreviewParameters,
    FirstLink,
    FormatEntrySelection,
)
from rdp.jobs.navwrite.provenance import ActorStamp


def test_link_plan_updates_manifest(tmp_path: Path, fake_nav: FakeNavigation) -> None:
    """验证契约：L3：追加 links，未被覆盖才加一个 source；entry_path 推导且 source_id 首次分配后不重算。"""
    with creation_case(tmp_path, fake_nav) as h:
        original = tree_state(h.nav)
        build = build_link_preview(h.case.scanning, link_parameters(h), checkpoint=noop)
        assert build.plan.operation.value == "create_link"
        details = build.report.creation
        assert details is not None
        assert len(details.sources_added) == 1
        assert details.sources_added[0].source_id.startswith("src_")
        assert details.sources_added[0].validation_status == "path_exists_only"
        assert details.resolved_format == "mcap" and details.resolved_version is None
        assert build.report.link_count == 1
        assert build.report.file_count == 4
        assert tree_state(h.nav) == original


def test_source_coverage_uses_path_boundary(tmp_path: Path, fake_nav: FakeNavigation) -> None:
    """验证契约：L3：已有数据块覆盖目标时不重复追加，路径 /a/b 不覆盖 /a/bc，source_id 碰撞拒绝。"""
    import hashlib
    import json

    from creation_support import creation_case, link_parameters, target_path
    from navwrite_support import (
        noop,
        read_json,
        task_location,
    )

    from rdp.infra.diagnostics import InputError
    from rdp.jobs.navwrite.create_builders import build_link_preview
    from rdp.jobs.navwrite.create_models import FirstLink

    with creation_case(tmp_path, fake_nav) as h:
        parent = target_path(h)
        child = parent / "child"
        child.mkdir()
        location = task_location(h.nav, "EgoProDemo")
        manifest = read_json(h.nav, location, "原始路径.json")
        manifest["sources"] = [
            {
                "source_id": "kept-id",
                "original_path": str(parent),
                "direct_path": str(parent),
                "format": "mcap",
                "version": None,
            }
        ]
        (h.nav / location.path / "原始路径.json").write_text(json.dumps(manifest))
        params = link_parameters(
            h, link=FirstLink(name="x", target_path=str(child), fallback_format="mcap")
        )
        first = build_link_preview(h.case.scanning, params, checkpoint=noop)
        assert first.report.creation is not None and first.report.creation.sources_added == ()
        sibling = parent.parent / (parent.name + "suffix")
        sibling.mkdir()
        params = params.model_copy(
            update={"link": FirstLink(name="x", target_path=str(sibling), fallback_format="mcap")}
        )
        second = build_link_preview(h.case.scanning, params, checkpoint=noop)
        assert second.report.creation is not None and len(second.report.creation.sources_added) == 1
        manifest["sources"] = [
            {
                "source_id": "src_" + hashlib.sha256(str(sibling).encode()).hexdigest()[:12],
                "original_path": str(parent),
                "direct_path": str(parent),
                "format": "mcap",
                "version": None,
            }
        ]
        (h.nav / location.path / "原始路径.json").write_text(json.dumps(manifest))
        with pytest.raises(InputError):
            build_link_preview(h.case.scanning, params, checkpoint=noop)


def test_dataset_roots_notice_and_diff(tmp_path: Path, fake_nav: FakeNavigation) -> None:
    """验证契约：L1：不在 dataset_roots 内才追加，报告和 creation 差异明确列出目标及提示。"""
    import json

    from creation_support import creation_case, link_parameters, target_path
    from navwrite_support import (
        noop,
        read_json,
        task_location,
    )

    from rdp.jobs.navwrite.create_builders import build_link_preview

    with creation_case(tmp_path, fake_nav) as h:
        build = build_link_preview(h.case.scanning, link_parameters(h), checkpoint=noop)
        assert build.report.creation is not None and build.report.creation.dataset_roots_added == (
            str(target_path(h)),
        )
        assert any(note.code == "will_add_dataset_root" for note in build.report.notices)
        location = task_location(h.nav, "EgoProDemo")
        manifest = read_json(h.nav, location, "原始路径.json")
        manifest["dataset_roots"] = [str(target_path(h).parent)]
        (h.nav / location.path / "原始路径.json").write_text(json.dumps(manifest))
        again = build_link_preview(h.case.scanning, link_parameters(h), checkpoint=noop)
        assert again.report.creation is not None and again.report.creation.dataset_roots_added == ()


def test_existing_different_target_rejected(tmp_path: Path, fake_nav: FakeNavigation) -> None:
    """验证契约：L2 场景一：已有同名不同目标拒绝，诊断提示改走改指向。"""
    from creation_support import creation_case, link_parameters, target_path
    from navwrite_support import (
        noop,
        tree_state,
    )

    from rdp.infra.diagnostics import InputError
    from rdp.jobs.navwrite.create_builders import build_link_preview

    with creation_case(tmp_path, fake_nav) as h:
        params = link_parameters(h)
        (h.nav / "按任务/EgoProDemo" / params.link.name).symlink_to(target_path(h) / "other")
        before = tree_state(h.nav)
        with pytest.raises(InputError) as caught:
            build_link_preview(h.case.scanning, params, checkpoint=noop)
        assert "改走改指向" in caught.value.diagnostics[0].actual
        assert tree_state(h.nav) == before


def test_same_target_without_registration_rejected(
    tmp_path: Path, fake_nav: FakeNavigation
) -> None:
    """验证契约：L2：只有同目标但未在 links[] 登记时仍拒绝，不把不一致当 noop。"""
    from creation_support import creation_case, link_parameters
    from navwrite_support import (
        noop,
    )

    from rdp.infra.diagnostics import InputError
    from rdp.jobs.navwrite.create_builders import build_link_preview

    with creation_case(tmp_path, fake_nav) as h:
        params = link_parameters(h)
        (h.nav / "按任务/EgoProDemo" / params.link.name).symlink_to(params.link.target_path)
        with pytest.raises(InputError):
            build_link_preview(h.case.scanning, params, checkpoint=noop)


def test_registered_same_target_is_noop(tmp_path: Path, fake_nav: FakeNavigation) -> None:
    """验证契约：L2：同目标且已登记返回空步骤，即使勾新格式也不写，不强迫补选格式或读取元信息，执行结果为 noop。"""
    from creation_support import creation_case, link_parameters
    from navwrite_support import (
        noop,
        run_committed,
        tree_state,
    )

    from rdp.jobs.navwrite.create_builders import build_link_preview
    from rdp.jobs.navwrite.create_models import FormatEntrySelection

    with creation_case(tmp_path, fake_nav) as h:
        params = link_parameters(h)
        first = build_link_preview(h.case.scanning, params, checkpoint=noop)
        run_committed(h.case.paths, h.nav, first.plan, 900)
        params = params.model_copy(
            update={
                "link": params.link.model_copy(update={"fallback_format": None}),
                "format_entries": (FormatEntrySelection(format="mcap"),),
            }
        )
        before = tree_state(h.nav)
        again = build_link_preview(h.case.scanning, params, checkpoint=noop)
        assert (
            again.plan.steps == ()
            and again.report.creation is not None
            and again.report.creation.noop
        )
        assert again.report.creation.metadata_source == "not_checked"
        assert tree_state(h.nav) == before


def test_link_selection_and_all_replicas(tmp_path: Path, fake_nav: FakeNavigation) -> None:
    """验证契约：L4/L8：链接只先改规范副本；勾选入口加链接，全部已有副本按自己的 links 重生成。"""
    import json

    from creation_support import creation_case, link_parameters
    from navwrite_support import (
        noop,
        run_committed,
        snapshot,
        task_location,
    )

    from rdp.jobs.navwrite.create_builders import build_link_preview
    from rdp.jobs.navwrite.create_models import FormatEntrySelection

    with creation_case(tmp_path, fake_nav) as h:
        old = snapshot(h.nav, task_location(h.nav, "EgoProDemo"))
        params = link_parameters(h, format_entries=(FormatEntrySelection(format="mcap"),))
        build = build_link_preview(h.case.scanning, params, checkpoint=noop)
        assert build.report.link_count == 2 and build.report.file_count == 7
        assert (
            build.report.creation is not None and len(build.report.creation.format_entry_paths) == 2
        )
        run_committed(h.case.paths, h.nav, build.plan, 900)
        assert (h.nav / "按格式/mcap/EgoProDemo/新增链接").is_symlink()
        existing = h.nav / "按格式/lerobot/3.0/EgoProDemo"
        assert not (existing / "新增链接").exists()
        assert (
            json.loads((existing / "原始路径.json").read_text())["links"][0]["name"]
            == old.links[0].name
        )


def test_zero_and_multiple_format_entries(tmp_path: Path, fake_nav: FakeNavigation) -> None:
    """验证契约：L4：零和多个勾选都可用，新入口父目录先创建；archives 使用原登记目录名。"""
    from creation_support import creation_case, new_parameters, stamp
    from navwrite_support import (
        noop,
        run_committed,
    )

    from rdp.jobs.navwrite.create_builders import build_dataset_preview
    from rdp.jobs.navwrite.create_models import FormatEntrySelection

    with creation_case(tmp_path, fake_nav) as h:
        zero = build_dataset_preview(h.case.scanning, new_parameters(h), stamp(), checkpoint=noop)
        assert zero.report.file_count == 4 and zero.report.link_count == 1
        params = new_parameters(
            h,
            format_entries=(
                FormatEntrySelection(format="mcap"),
                FormatEntrySelection(format="archives"),
                FormatEntrySelection(format="lerobot", version="9.9"),
            ),
        )
        build = build_dataset_preview(h.case.scanning, params, stamp(), checkpoint=noop)
        assert build.report.file_count == 13 and build.report.link_count == 4
        run_committed(h.case.paths, h.nav, build.plan, 900)
        assert (h.nav / "按格式/tar、tar.gz（含分卷）/新数据集/新增链接").is_symlink()
        assert (h.nav / "按格式/lerobot/9.9/新数据集/新增链接").is_symlink()


def test_egopro_and_alpha_replica_regression(tmp_path: Path, fake_nav: FakeNavigation) -> None:
    """验证契约：L8/L9：EgoProDemo 对拍正确，alpha 不可达三块只留规范副本且预览列出遗漏。"""
    import json

    from creation_support import creation_case, link_parameters
    from navwrite_support import (
        dataset_id_of,
        noop,
        run_committed,
        snapshot,
        task_location,
    )

    from rdp.jobs.navwrite.create_builders import build_link_preview

    with creation_case(tmp_path, fake_nav) as h:
        canonical = snapshot(h.nav, task_location(h.nav, "agibot_world_alpha"))
        unreachable = {
            source.source_id for source in canonical.sources if source.entry_path.startswith("/")
        }
        assert len(unreachable) == 3
        params = link_parameters(h, dataset_id=dataset_id_of(h.fake, "agibot_world_alpha"))
        build = build_link_preview(h.case.scanning, params, checkpoint=noop)
        run_committed(h.case.paths, h.nav, build.plan, 900)
        files = [
            step
            for step in build.plan.steps
            if step.op == "write_file"
            and step.path.startswith("按格式/")
            and step.path.endswith("原始路径.json")
        ]
        assert files
        for step in files:
            ids = {item["source_id"] for item in json.loads(step.after_content)["sources"]}
            assert ids.isdisjoint(unreachable)
        assert any(note.code == "source_not_reachable" for note in build.report.notices)


def test_create_dataset_full_plan(tmp_path: Path, fake_nav: FakeNavigation) -> None:
    """验证契约：L5：一个计划建目录、第一链接、规范三 JSON 和来源文件，格式副本只有三 JSON。"""
    with creation_case(tmp_path, fake_nav) as h:
        params = DatasetPreviewParameters(
            dataset_name="新数据集",
            data_origin="开源下载",
            link=FirstLink(
                name="原始数据", target_path=str(target_path(h)), fallback_format="mcap"
            ),
            format_entries=(FormatEntrySelection(format="mcap"),),
        )
        stamp = ActorStamp(
            kind="人工标注", account_id=1, account_name="甲", at="2026-10-30T07:00:00Z"
        )
        build = build_dataset_preview(h.case.scanning, params, stamp, checkpoint=noop)
        assert build.plan.dataset_ids == ("dataset-36",)
        assert build.report.file_count == 7 and build.report.link_count == 2
        assert build.report.creation is not None
        assert build.report.creation.format_entry_paths == ("按格式/mcap/新数据集",)
        assert (
            len(
                [
                    step
                    for step in build.plan.steps
                    if step.op == "write_file" and step.path.endswith("来源.json")
                ]
            )
            == 1
        )
        assert not (h.nav / "按任务/新数据集").exists()


def test_information_and_subtask_skeletons(tmp_path: Path, fake_nav: FakeNavigation) -> None:
    """验证契约：L5：信息 14 项按手册固定编号/名称、正文全空；子任务 tasks=[] 且 task_count=0，不补信息 schema_version。"""
    import json

    from creation_support import creation_case, new_parameters, stamp
    from navwrite_support import (
        noop,
    )

    from rdp.jobs.navwrite.create_builders import build_dataset_preview

    with creation_case(tmp_path, fake_nav) as h:
        build = build_dataset_preview(h.case.scanning, new_parameters(h), stamp(), checkpoint=noop)
        files = {
            step.path.rsplit("/", 1)[-1]: json.loads(step.after_content)
            for step in build.plan.steps
            if step.op == "write_file"
        }
        info = files["数据集信息.json"]
        assert [field["number"] for field in info["fields"]] == list(range(1, 15))
        assert [field["name"] for field in info["fields"]] == [
            "数据集标识",
            "地址",
            "类型与组成",
            "数据大小",
            "采集机器人型号",
            "任务与场景",
            "数据格式",
            "FPS",
            "相机配置",
            "状态维度",
            "动作维度",
            "动作控制方式及单位",
            "轨迹\uff0f帧数",
            "信息来源与核验日期",
        ]
        assert all(field["value_markdown"] == "" for field in info["fields"])
        assert "schema_version" not in info
        assert not {"robot_model", "scene", "tasks"} & info.keys()
        assert files["子任务.json"]["tasks"] == [] and files["子任务.json"]["task_count"] == 0


def test_provenance_actor_and_unknown_lineage(tmp_path: Path, fake_nav: FakeNavigation) -> None:
    """验证契约：L5 与 ADR 0008：来源必填、真实提交人印记、UTC 时刻、采集任务 null、血缘空；未知也保留人工印记。"""
    import json

    from creation_support import creation_case, new_parameters, stamp
    from navwrite_support import (
        noop,
    )

    from rdp.jobs.navwrite.create_builders import build_dataset_preview

    with creation_case(tmp_path, fake_nav) as h:
        build = build_dataset_preview(
            h.case.scanning, new_parameters(h, data_origin="未知"), stamp(), checkpoint=noop
        )
        provenance = next(
            json.loads(step.after_content)
            for step in build.plan.steps
            if step.op == "write_file" and step.path.endswith("来源.json")
        )
        assert provenance["data_origin"] == "未知"
        assert provenance["data_origin_set_by"] == {
            "kind": "人工标注",
            "account_id": 1,
            "account_name": "甲",
            "at": "2026-10-30T07:00:00Z",
        }
        assert provenance["collection_task_id"] is None and provenance["lineage"] == []


def test_allocate_36_from_max_35(tmp_path: Path, fake_nav: FakeNavigation) -> None:
    """验证契约：L6：临时导航已有 01-35 时预计 dataset-36；至少两位，移除目录最大编号参与计算且不可复用。"""
    from creation_support import creation_case, new_parameters, stamp
    from navwrite_support import (
        noop,
    )

    from rdp.jobs.navwrite.create_builders import build_dataset_preview

    with creation_case(tmp_path, fake_nav) as h:
        first = build_dataset_preview(h.case.scanning, new_parameters(h), stamp(), checkpoint=noop)
        assert first.plan.dataset_ids == ("dataset-36",)
        (h.nav / "已移除/dataset-40_old").mkdir(parents=True)
        second = build_dataset_preview(h.case.scanning, new_parameters(h), stamp(), checkpoint=noop)
        assert second.plan.dataset_ids == ("dataset-41",)


def test_allocation_unreadable_id_rejected(tmp_path: Path, fake_nav: FakeNavigation) -> None:
    """验证契约：L6：入口读不出编号或已移除命名不合约时拒绝，不猜最大编号。"""
    from creation_support import creation_case, new_parameters, stamp
    from navwrite_support import (
        noop,
    )

    from rdp.infra.diagnostics import InputError
    from rdp.jobs.navwrite.create_builders import build_dataset_preview

    with creation_case(tmp_path, fake_nav) as h:
        for name in ("原始路径.json", "数据集信息.json", "子任务.json"):
            (h.nav / "按任务/EgoProDemo" / name).write_text("{}")
        with pytest.raises(InputError):
            build_dataset_preview(h.case.scanning, new_parameters(h), stamp(), checkpoint=noop)


def test_preview_captures_complete_state(tmp_path: Path, fake_nav: FakeNavigation) -> None:
    """验证契约：L12：记录规范及所有格式入口的 JSON 含来源哈希、条目清单、readlink；新建记录目的不存在和最大编号。"""
    from creation_support import creation_case, link_parameters, new_parameters, stamp
    from navwrite_support import (
        noop,
    )

    from rdp.jobs.navwrite.create_builders import build_dataset_preview, build_link_preview

    with creation_case(tmp_path, fake_nav) as h:
        build = build_link_preview(h.case.scanning, link_parameters(h), checkpoint=noop)
        fingerprint = build.plan.state.datasets[0]
        assert fingerprint.verifiable and len(fingerprint.entries) == 2
        for entry in fingerprint.entries:
            assert {item.name for item in entry.json_files} >= {
                "原始路径.json",
                "子任务.json",
                "数据集信息.json",
                "来源.json",
            }
            assert entry.names and entry.links
        new = build_dataset_preview(h.case.scanning, new_parameters(h), stamp(), checkpoint=noop)
        assert new.plan.state.datasets == () and new.plan.state.new_dataset is not None
        assert (
            new.plan.state.new_dataset.destination_absent
            and new.plan.state.new_dataset.max_number == 35
        )


def test_builder_reads_consistent_preimages(tmp_path: Path, fake_nav: FakeNavigation) -> None:
    """验证契约：契约：构造中 JSON/链接变化不得把旧正文和新指纹拼成计划，返回冲突或不可验证。"""
    import json
    from dataclasses import replace

    from creation_support import creation_case, link_parameters
    from navwrite_support import (
        noop,
    )

    from rdp.infra.diagnostics import ConflictError
    from rdp.jobs.navwrite.create_builders import build_link_preview

    with creation_case(tmp_path, fake_nav) as h:
        checker = h.case.scanning.storage
        assert checker is not None
        original = checker.mounts.read_mountinfo
        path = h.nav / "按任务/EgoProDemo/原始路径.json"

        def concurrent_change() -> str:
            value = json.loads(path.read_text())
            value["concurrent_change"] = True
            path.write_text(json.dumps(value))
            return original()

        deps = replace(
            h.case.scanning,
            storage=replace(
                checker, mounts=replace(checker.mounts, read_mountinfo=concurrent_change)
            ),
        )
        with pytest.raises(ConflictError):
            build_link_preview(deps, link_parameters(h), checkpoint=noop)
        assert not (h.nav / "按任务/EgoProDemo/新增链接").exists()


def test_json_unknown_keys_and_derived_fields(tmp_path: Path, fake_nav: FakeNavigation) -> None:
    """验证契约：L10/L11：保留未知键和顺序，2 空格、中文、末尾换行，推导 version 显式 null，不补信息 schema_version。"""
    import json

    from creation_support import creation_case, link_parameters
    from navwrite_support import (
        noop,
    )

    from rdp.jobs.navwrite.create_builders import build_link_preview

    with creation_case(tmp_path, fake_nav) as h:
        path = h.nav / "按任务/EgoProDemo/原始路径.json"
        payload = json.loads(path.read_text())
        payload["future"] = {"文字": "保留"}
        payload.pop("version", None)
        path.write_text(json.dumps(payload, ensure_ascii=False))
        build = build_link_preview(h.case.scanning, link_parameters(h), checkpoint=noop)
        step = next(
            step
            for step in build.plan.steps
            if step.op == "write_file" and step.path == "按任务/EgoProDemo/原始路径.json"
        )
        value = json.loads(step.after_content)
        assert value["future"] == {"文字": "保留"} and value["version"] is None
        assert step.after_content.endswith("\n") and '  "' in step.after_content
        assert list(value).index("future") == list(payload).index("future")


def test_report_matches_exact_plan(tmp_path: Path, fake_nav: FakeNavigation) -> None:
    """验证契约：规范 2.2/2.4：creation 路径与步骤逐一对应，计数不重算，检查范围及已知例外清楚展示，预览不写导航。"""
    from creation_support import creation_case, link_parameters
    from navwrite_support import (
        noop,
    )

    from rdp.jobs.navwrite.create_builders import build_link_preview

    with creation_case(tmp_path, fake_nav) as h:
        build = build_link_preview(h.case.scanning, link_parameters(h), checkpoint=noop)
        details = build.report.creation
        assert details is not None
        assert details.file_paths == tuple(
            step.path for step in build.plan.steps if step.op == "write_file"
        )
        assert tuple(item.path for item in details.links) == tuple(
            step.path for step in build.plan.steps if step.op == "set_link"
        )
        assert build.report.file_count == len(details.file_paths)
        assert {item.scope.value for item in build.report.checks} == {"full", "after_execution"}
        assert details.dataset_roots_added and details.sources_added
