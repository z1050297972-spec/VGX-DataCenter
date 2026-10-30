"""M1-10 数据来源标注：经公开作业边界验证预览、写入和撤回，只使用假导航层。"""

from dataclasses import replace
from pathlib import Path

from nav_manifest import FakeNavigation
from navwrite_pipeline_support import Harness, harness
from navwrite_support import tree_state

from rdp.jobs.execution import ExecutionContext
from rdp.jobs.navwrite.models import NavOperation, WriteFileStep
from rdp.jobs.navwrite.previews import read_preview
from rdp.jobs.registry import production_registry
from rdp.jobs.types import JobRecord, JobState, RecoveryMode


def _preview(h: Harness, origin: str = "开源下载") -> JobRecord:
    """用登记表的实际执行入口生成预览；测试夹具只替换参数输入。"""
    definition = production_registry(h.case.scanning, h.dependencies).lookup(
        "nav_data_origin_preview"
    )
    assert definition is not None
    assert definition.recovery_mode is RecoveryMode.RESTART
    assert not definition.writes_navigation

    def execute(context: ExecutionContext) -> None:
        parameters = definition.parameters_model.model_validate(
            {"dataset_id": h.dataset, "data_origin": origin}
        )
        definition.execute(replace(context, parameters=parameters))

    return h.case.run(execute=execute)


def test_preview_new_provenance_is_read_only(tmp_path: Path, fake_nav: FakeNavigation) -> None:
    """验收：预览缺失的来源文件时只保存一条规范入口写入计划，报告未知到新值，不改导航层。"""
    with harness(tmp_path, fake_nav) as h:
        before = tree_state(h.nav)
        record = _preview(h)
        assert record.state is JobState.COMPLETED
        preview = read_preview(h.case.paths, record.job_id)
        assert tree_state(h.nav) == before
        assert preview.plan.operation is NavOperation.SET_DATA_ORIGIN
        assert preview.plan.dataset_ids == (h.dataset,)
        (step,) = preview.plan.steps
        assert isinstance(step, WriteFileStep)
        assert step.path == "按任务/EgoProDemo/来源.json"
        assert not step.before.exists and step.after.exists
        (change,) = preview.report.listed_changes
        assert (change.before, change.after) == ("未知", "开源下载")
        assert preview.report.file_count == 1 and preview.report.link_count == 0
        assert preview.parameters == {"dataset_id": h.dataset, "data_origin": "开源下载"}


def test_modify_preserves_lineage_bytes(tmp_path: Path, fake_nav: FakeNavigation) -> None:
    """验收：只改来源和人工印记，既有血缘原字节、采集任务和其他文件保持不变。"""
    import json

    from navwrite_pipeline_support import run_apply

    with harness(tmp_path, fake_nav) as h:
        fixture = Path(__file__).parent / "fixtures/provenance-draft.json"
        payload = json.loads(fixture.read_text(encoding="utf-8"))
        payload.update(
            dataset_id=h.dataset, dataset_name="EgoProDemo", collection_task_id="task-42"
        )
        path = h.nav / "按任务/EgoProDemo/来源.json"
        old = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode()
        path.write_bytes(old)
        before = tree_state(h.nav)
        record = _preview(h, "ego 采集")
        outcome = run_apply(h, record.job_id)
        assert outcome.error is None and outcome.result is not None
        new = path.read_bytes()
        assert new.split(b'"lineage": ', 1)[1] == old.split(b'"lineage": ', 1)[1]
        written = json.loads(new)
        assert written["collection_task_id"] == "task-42"
        assert written["data_origin"] == "ego 采集"
        assert written["data_origin_set_by"] == {
            "kind": "人工标注",
            "account_id": 7,
            "account_name": "历史提交人",
            "at": "2026-10-26T12:00:00Z",
        }
        before.pop("按任务/EgoProDemo/来源.json")
        after = tree_state(h.nav)
        after.pop("按任务/EgoProDemo/来源.json")
        assert after == before


def test_preview_refuses_wrong_provenance_identity(
    tmp_path: Path, fake_nav: FakeNavigation
) -> None:
    """契约：来源文件身份不属于规范入口时拒绝预览，不把另一数据集的血缘改挂到当前数据集。"""
    import json

    with harness(tmp_path, fake_nav) as h:
        payload = json.loads(
            (Path(__file__).parent / "fixtures/provenance-draft.json").read_bytes()
        )
        path = h.nav / "按任务/EgoProDemo/来源.json"
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        before = tree_state(h.nav)
        record = _preview(h)
        assert record.summary is not None and record.summary.aborted
        diagnostic = record.diagnostics[0].samples[0]
        assert diagnostic.category.value == "input"
        assert any(obj.key == "dataset_id" and obj.value == h.dataset for obj in diagnostic.objects)
        assert "身份" in diagnostic.actual
        assert "没写" in diagnostic.consequence
        assert tree_state(h.nav) == before
        assert not (h.case.paths.nav_previews / f"{record.job_id}.json.gz").exists()


def test_preview_refuses_ambiguous_canonical(tmp_path: Path, fake_nav: FakeNavigation) -> None:
    """契约：同一编号出现两个按任务入口时拒绝标注，不任取一个作为规范入口。"""
    import shutil

    with harness(tmp_path, fake_nav) as h:
        source = h.nav / "按任务/EgoProDemo"
        shutil.copytree(source, source.with_name("重复入口"), symlinks=True)
        before = tree_state(h.nav)
        record = _preview(h)
        assert record.summary is not None and record.summary.aborted
        diagnostic = record.diagnostics[0].samples[0]
        assert diagnostic.category.value == "input" and "唯一" in diagnostic.actual
        assert tree_state(h.nav) == before


def test_preview_refuses_disagreeing_identity_documents(
    tmp_path: Path, fake_nav: FakeNavigation
) -> None:
    """契约：三份基础 JSON 身份不一致时拒绝标注，避免对身份不明的入口补写来源。"""
    import json

    with harness(tmp_path, fake_nav) as h:
        path = h.nav / "按任务/EgoProDemo/子任务.json"
        payload = json.loads(path.read_bytes())
        payload["dataset_id"] = "dataset-other"
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        before = tree_state(h.nav)
        record = _preview(h)
        assert record.summary is not None and record.summary.aborted
        assert record.diagnostics[0].samples[0].category.value == "input"
        assert tree_state(h.nav) == before


def test_changed_provenance_conflicts_without_writing(
    tmp_path: Path, fake_nav: FakeNavigation
) -> None:
    """验收：预览后有人新建/修改来源文件，以冲突失败，保留对方字节，不生成变更记录。"""
    from navwrite_pipeline_support import run_apply

    from rdp.infra.diagnostics import ConflictError

    with harness(tmp_path, fake_nav) as h:
        record = _preview(h)
        path = h.nav / "按任务/EgoProDemo/来源.json"
        path.write_bytes(b'{"other": true}\n')
        before = tree_state(h.nav)
        result = run_apply(h, record.job_id)
        assert isinstance(result.error, ConflictError)
        assert result.record.summary is not None and result.record.summary.aborted
        assert tree_state(h.nav) == before
        assert not (h.case.paths.nav_changes / f"{result.record.job_id}.json.gz").exists()


def test_invalid_provenance_is_never_overwritten(tmp_path: Path, fake_nav: FakeNavigation) -> None:
    """契约：损坏来源 JSON 不当作缺失，拒绝预览并保留原字节。"""
    with harness(tmp_path, fake_nav) as h:
        path = h.nav / "按任务/EgoProDemo/来源.json"
        path.write_bytes(b'{"schema_version": 999}\n')
        before = tree_state(h.nav)
        record = _preview(h)
        assert record.summary is not None and record.summary.aborted
        diagnostic = record.diagnostics[0].samples[0]
        assert diagnostic.category.value == "input" and "schema_version" in diagnostic.actual
        assert tree_state(h.nav) == before
