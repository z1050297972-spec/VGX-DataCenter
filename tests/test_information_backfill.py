"""M1.5-15 回填关键契约；通过真实 worker 预览和写入流水线，只使用临时导航层。"""

from dataclasses import replace
from pathlib import Path

from nav_manifest import FakeNavigation
from navwrite_pipeline_support import WHEN, Harness, harness, run_apply
from navwrite_support import tree_state
from sqlalchemy import select

from rdp.infra.db.connection import session_scope
from rdp.jobs.datasets.models import SourceRow
from rdp.jobs.datasets.types import JsonObject
from rdp.jobs.execution import ExecutionContext
from rdp.jobs.navwrite.jsonio import dump_navigation_json, load_navigation_json
from rdp.jobs.navwrite.models import NavPreview, WriteFileStep
from rdp.jobs.navwrite.previews import read_preview
from rdp.jobs.registry import production_registry


def _preview(h: Harness) -> NavPreview:
    """从生产登记入口生成并读取持久化预览，不直接调用解析内部函数。"""
    definition = production_registry(h.case.scanning, h.dependencies).lookup(
        "nav_information_backfill_preview"
    )
    assert definition is not None

    def execute(context: ExecutionContext) -> None:
        definition.execute(
            replace(context, parameters=definition.parameters_model.model_validate({}))
        )

    record = h.case.run(execute=execute)
    assert record.summary is not None and not record.summary.aborted, record.diagnostics
    return read_preview(h.case.paths, record.job_id)


def test_fps_priority_and_unique_canonical_fallback(
    tmp_path: Path, fake_nav: FakeNavigation
) -> None:
    """第8项纯整数/括号优先；自由文字仅回退规范 LeRobot 唯一帧率，多帧率不写。"""
    with harness(tmp_path, fake_nav) as h:
        h.case.run()
        path = h.nav / "按任务/EgoProDemo/数据集信息.json"
        original = load_navigation_json(path.read_bytes())
        for text, rates, expected in (
            (" 20 ", (30, 36), 20),
            ("50（meta/info.json 声明的数据帧率）", (30, 36), 50),
            ("50(meta/info.json 声明的数据帧率)", (30, 36), 50),
            ("自由文字含 60 FPS", (30, 30), 30),
            ("自由文字含 60 FPS", (30, 36), None),
        ):
            payload = dict(original)
            payload.pop("fps", None)
            payload["fields"] = [{"number": 8, "name": "FPS", "value_markdown": text}]
            path.write_bytes(dump_navigation_json(payload))
            with session_scope(h.case.engine) as session:
                rows = list(
                    session.scalars(
                        select(SourceRow)
                        .where(SourceRow.entry_path == "按任务/EgoProDemo")
                        .order_by(SourceRow.ordinal)
                    )
                )
                assert len(rows) >= 2
                for index, row in enumerate(rows):
                    row.format = "lerobot"
                    row.fps = float(rates[index % 2])
                    row.fps_rounded = rates[index % 2]
                    row.meta_checked_at = WHEN
            preview = _preview(h)
            contents = [
                load_navigation_json(step.after_content.encode())
                for step in preview.plan.steps
                if isinstance(step, WriteFileStep)
                and step.path == "按任务/EgoProDemo/数据集信息.json"
            ]
            if expected is None:
                assert not contents or "fps" not in contents[0]
            else:
                assert contents[0]["fps"] == expected


def test_backfill_preserves_values_and_is_idempotent(
    tmp_path: Path, fake_nav: FakeNavigation
) -> None:
    """回填只追加两键、保持空型号与血缘；格式副本同步、再次预览为空。"""
    with harness(tmp_path, fake_nav) as h:
        information_path = h.nav / "按任务/EgoProDemo/数据集信息.json"
        information = load_navigation_json(information_path.read_bytes())
        information.update(
            robot_model="", fields=[{"number": 8, "name": "FPS", "value_markdown": "20"}]
        )
        information.pop("fps", None)
        information.pop("data_origin", None)
        information_path.write_bytes(dump_navigation_json(information))
        provenance: JsonObject = {
            "schema_version": 1,
            "dataset_id": h.dataset,
            "dataset_name": "EgoProDemo",
            "data_origin": "ego 采集",
            "data_origin_set_by": {"kind": "人工标注"},
            "collection_task_id": "collection-42",
            "lineage": [{"unknown_nested": [1, " 保留空格 ", {"x": True}]}],
            "unknown_extension": " 保留 ",
        }
        source_path = information_path.with_name("来源.json")
        source_path.write_bytes(dump_navigation_json(provenance))
        existing_path, existing_bytes = _existing_information(h)
        before = tree_state(h.nav)
        preview = _preview(h)
        assert tree_state(h.nav) == before
        applied = run_apply(h, preview.preview_job_id)
        assert applied.error is None, applied.error
        assert existing_path.read_bytes() == existing_bytes
        written = load_navigation_json(information_path.read_bytes())
        assert list(written) == [*information, "fps", "data_origin"]
        for key, value in information.items():
            assert written[key] == value
        assert written["robot_model"] == ""
        assert written["fps"] == 20 and written["data_origin"] == "ego 采集"
        updated_source = load_navigation_json(source_path.read_bytes())
        assert updated_source == {
            key: 2 if key == "schema_version" else value
            for key, value in provenance.items()
            if key not in ("data_origin", "data_origin_set_by")
        }
        assert list(updated_source) == [
            key for key in provenance if key not in ("data_origin", "data_origin_set_by")
        ]
        for location in fake_nav.manifest.entries:
            if location.dataset_id == h.dataset and location.path.startswith("按格式/"):
                assert (
                    h.nav / location.path / "数据集信息.json"
                ).read_bytes() == information_path.read_bytes()
        assert _preview(h).plan.steps == ()


def _existing_information(h: Harness) -> tuple[Path, bytes]:
    """预置已有顶层值及前导空格，验证回填只新增、不纠正人工内容。"""
    path = h.nav / "按任务/libero_10/数据集信息.json"
    existing = load_navigation_json(path.read_bytes())
    existing.update(robot_model=" PR2 ", fps=17, data_origin="仿真生成")
    content = dump_navigation_json(existing)
    path.write_bytes(content)
    return path, content
