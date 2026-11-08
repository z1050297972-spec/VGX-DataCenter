"""M3-05 关键契约：真实 HTTP 和 worker 操作 tests 假导航层，既有流水线负责写入和扫描。"""

import json
from pathlib import Path
from typing import Literal

import pytest
from account_api_support import ApiCase
from data_origin_support import run_submitted
from dataset_api_support import browser_case
from nav_manifest import FakeNavigation
from navwrite_support import tree_state

from rdp.jobs.datasets.types import JsonObject
from rdp.jobs.navwrite.jsonio import dump_navigation_json, load_navigation_json

_TARGET = "按任务/libero_10"
_INPUT = "按任务/R1_lite_table_withdrawing_mcap"


def _worker_record() -> JsonObject:
    """独立的工具记录样本含 source_id 和未知输入，验证人工功能兼容 M4 记录。"""
    return {
        "record_id": 7,
        "kind": "转换",
        "status": "完整",
        "note": "工具转换",
        "inputs": [
            {"dataset_id": "dataset-35", "source_id": "source-test"},
            {"dataset_id": "dataset-999", "source_id": "source-missing"},
        ],
        "outputs": [{"source_id": "out", "format": "lerobot", "codebase_version": "3.0"}],
        "tool": {"name": "convert", "version": "1", "commit": None},
        "config": None,
        "robot_profile": None,
        "parameters": None,
        "job_id": 123,
        "started_at": None,
        "finished_at": None,
        "recorded_by": {
            "kind": "worker",
            "account_id": None,
            "account_name": None,
            "at": "2026-11-08T10:00:00Z",
        },
    }


def _seed(nav: FakeNavigation, legacy: Literal["absent", "null", "value"] = "value") -> Path:
    """旧文件字段刻意采用不同顺序，记录省略可选 ingest_check，编辑不得顺手重写。"""
    path = nav.nav_root / _TARGET / "来源.json"
    payload: JsonObject = {
        "dataset_name": "libero_10",
        "lineage": [_worker_record()],
        "dataset_id": "dataset-14",
        "schema_version": 2,
    }
    if legacy != "absent":
        payload["collection_task_id"] = "legacy-task" if legacy == "value" else None
    path.write_bytes(dump_navigation_json(payload))
    return path


def _preview(case: ApiCase, nav: FakeNavigation, parameters: JsonObject) -> int:
    """通过真实接口和执行器完成预览，并核对 HTTP 作业报告可读。"""
    response = case.client.post("/api/navigation/lineage/preview", json=parameters)
    assert response.status_code == 201, response.text
    job_id = int(response.json()["job_id"])
    result = run_submitted(case, nav, job_id)
    assert result.summary is not None and not result.summary.aborted, result.diagnostics
    report = case.client.get(f"/api/navigation/previews/{job_id}")
    assert report.status_code == 200, report.text
    assert report.json()["report"]["file_count"] == 1
    return job_id


def _apply(case: ApiCase, nav: FakeNavigation, preview_id: int) -> int:
    """与删除分类值相同，通用作业接口只提交预览编号作为确认。"""
    response = case.client.post(
        "/api/jobs",
        json={"type_name": "nav_write_apply", "parameters": {"preview_job_id": preview_id}},
    )
    assert response.status_code == 201, response.text
    job_id = int(response.json()["job_id"])
    result = run_submitted(case, nav, job_id)
    assert result.summary is not None and not result.summary.aborted, result.diagnostics
    return job_id


def _detail(case: ApiCase, path: str) -> dict[str, list[JsonObject]]:
    """从真实详情接口观察索引结果，不用数据库内部行作断言。"""
    response = case.client.get("/api/datasets/detail", params={"entry_path": path})
    assert response.status_code == 200, response.text
    return response.json()["lineage"]


@pytest.mark.parametrize("legacy", ["absent", "null", "value"])
def test_manual_lineage_roundtrip_preserves_existing_content(
    tmp_path: Path, fake_nav: FakeNavigation, legacy: Literal["absent", "null", "value"]
) -> None:
    """登记只改来源，最大编号加一且审计属于写作业；两视图双向投影，删除只去人工记录。"""
    path = _seed(fake_nav, legacy)
    original = path.read_bytes()
    with browser_case(tmp_path / "state", fake_nav) as case:
        before = tree_state(fake_nav.nav_root)
        preview = _preview(
            case,
            fake_nav,
            {
                "dataset_id": "dataset-14",
                "action": "add",
                "input_dataset_ids": ["dataset-35", "dataset-33"],
                "note": "补录转换",
            },
        )
        assert tree_state(fake_nav.nav_root) == before
        applied = _apply(case, fake_nav, preview)
        content = json.loads(path.read_bytes())
        record = content["lineage"][-1]
        assert record == {
            "record_id": 8,
            "kind": "转换",
            "status": "来历部分未知",
            "note": "补录转换",
            "inputs": [{"dataset_id": "dataset-35"}, {"dataset_id": "dataset-33"}],
            "outputs": [],
            "tool": None,
            "config": None,
            "robot_profile": None,
            "parameters": None,
            "job_id": applied,
            "started_at": None,
            "finished_at": None,
            "ingest_check": None,
            "recorded_by": {
                "kind": "人工补录",
                "account_id": 1,
                "account_name": "管理员",
                "at": case.clock.value.strftime("%Y-%m-%dT%H:%M:%SZ"),
            },
        }
        previous = json.loads(original)
        assert list(content) == list(previous)
        assert {key: value for key, value in content.items() if key != "lineage"} == {
            key: value for key, value in previous.items() if key != "lineage"
        }
        assert content["lineage"][0] == previous["lineage"][0]
        after = tree_state(fake_nav.nav_root)
        assert before.keys() == after.keys()
        assert {name for name in before if before[name] != after[name]} == {_TARGET + "/来源.json"}
        upstream = _detail(case, _TARGET)["upstream"]
        assert isinstance(upstream, list)
        assert upstream[-2:] == [
            {
                "record_id": 8,
                "dataset_id": "dataset-35",
                "name": "R1_lite_table_withdrawing_mcap",
                "entry_path": _INPUT,
                "note": "补录转换",
                "removable": True,
            },
            {
                "record_id": 8,
                "dataset_id": "dataset-33",
                "name": "EgoProDemo",
                "entry_path": "按任务/EgoProDemo",
                "note": "补录转换",
                "removable": True,
            },
        ]
        assert _detail(case, "按格式/lerobot/3.0/libero_10")["upstream"] == upstream
        assert _detail(case, _INPUT)["downstream"] == [
            {
                "record_id": 7,
                "dataset_id": "dataset-14",
                "name": "libero_10",
                "entry_path": _TARGET,
                "note": "工具转换",
            },
            {
                "record_id": 8,
                "dataset_id": "dataset-14",
                "name": "libero_10",
                "entry_path": _TARGET,
                "note": "补录转换",
            },
        ]
        remove = _preview(
            case, fake_nav, {"dataset_id": "dataset-14", "action": "remove", "record_id": 8}
        )
        _apply(case, fake_nav, remove)
        assert path.read_bytes() == original
        assert len(_detail(case, _INPUT)["downstream"]) == 1
        assert len(_detail(case, _TARGET)["upstream"]) == 2


def test_worker_record_is_indexed_but_cannot_be_removed(
    tmp_path: Path, fake_nav: FakeNavigation
) -> None:
    """工具记录同样投影全部输入；未知数据集名称/路径为 null，删除非人工记录同步返回 422。"""
    _seed(fake_nav)
    with browser_case(tmp_path / "state", fake_nav) as case:
        assert _detail(case, _TARGET)["upstream"] == [
            {
                "record_id": 7,
                "dataset_id": "dataset-35",
                "name": "R1_lite_table_withdrawing_mcap",
                "entry_path": _INPUT,
                "note": "工具转换",
                "removable": False,
            },
            {
                "record_id": 7,
                "dataset_id": "dataset-999",
                "name": None,
                "entry_path": None,
                "note": "工具转换",
                "removable": False,
            },
        ]
        before = tree_state(fake_nav.nav_root)
        response = case.client.post(
            "/api/navigation/lineage/preview",
            json={"dataset_id": "dataset-14", "action": "remove", "record_id": 7},
        )
        assert response.status_code == 422, response.text
        assert response.json()["diagnostics"][0]["rule"] == "NAV_LINEAGE"
        assert tree_state(fake_nav.nav_root) == before
        # 通用提交绕过 HTTP 预检也不能绕过 worker 的删除规则。
        response = case.client.post(
            "/api/jobs",
            json={
                "type_name": "nav_lineage_preview",
                "parameters": {"dataset_id": "dataset-14", "action": "remove", "record_id": 7},
            },
        )
        assert response.status_code == 201, response.text
        result = run_submitted(case, fake_nav, int(response.json()["job_id"]))
        assert result.summary is not None and result.summary.aborted
        assert tree_state(fake_nav.nav_root) == before


@pytest.mark.parametrize(
    "fields",
    [
        {"input_dataset_ids": ["dataset-14"]},
        {"input_dataset_ids": ["dataset-999"]},
        {"input_dataset_ids": []},
        {"input_dataset_ids": ["dataset-35"] * 9},
        {"input_dataset_ids": ["dataset-35"], "note": "字" * 501},
    ],
)
def test_invalid_lineage_inputs_return_422(
    tmp_path: Path, fake_nav: FakeNavigation, fields: JsonObject
) -> None:
    """自身、不存在编号、空输入、超过 8 项和超过 500 字符说明均同步拒绝，导航不变。"""
    with browser_case(tmp_path / "state", fake_nav) as case:
        before = tree_state(fake_nav.nav_root)
        response = case.client.post(
            "/api/navigation/lineage/preview",
            json={"dataset_id": "dataset-14", "action": "add", **fields},
        )
        assert response.status_code == 422, response.text
        assert tree_state(fake_nav.nav_root) == before


def test_missing_provenance_is_created_with_null_note(
    tmp_path: Path, fake_nav: FakeNavigation
) -> None:
    """没有来源文件时新建第 2 版，空说明为 null，不引入已废弃采集任务键。"""
    path = fake_nav.nav_root / _TARGET / "来源.json"
    assert not path.exists()
    with browser_case(tmp_path / "state", fake_nav) as case:
        preview = _preview(
            case,
            fake_nav,
            {
                "dataset_id": "dataset-14",
                "action": "add",
                "input_dataset_ids": ["dataset-35"],
                "note": "",
            },
        )
        _apply(case, fake_nav, preview)
        content = json.loads(path.read_bytes())
        assert content["schema_version"] == 2 and "collection_task_id" not in content
        assert content["lineage"][0]["note"] is None
        assert content["lineage"][0]["record_id"] == 1
        assert len(_detail(case, _INPUT)["downstream"]) == 1
        remove = _preview(
            case, fake_nav, {"dataset_id": "dataset-14", "action": "remove", "record_id": 1}
        )
        _apply(case, fake_nav, remove)
        assert _detail(case, _TARGET) == {"upstream": [], "downstream": []}
        assert _detail(case, _INPUT)["downstream"] == []
        assert json.loads(path.read_bytes())["lineage"] == []


def test_changed_provenance_aborts_confirmed_write(
    tmp_path: Path, fake_nav: FakeNavigation
) -> None:
    """预览后来源变化由通用流水线持锁拒绝，保留外部新内容，不覆写或追加关系。"""
    path = _seed(fake_nav)
    with browser_case(tmp_path / "state", fake_nav) as case:
        preview = _preview(
            case,
            fake_nav,
            {"dataset_id": "dataset-14", "action": "add", "input_dataset_ids": ["dataset-35"]},
        )
        payload = load_navigation_json(path.read_bytes())
        payload["collection_task_id"] = "外部修改"
        path.write_bytes(dump_navigation_json(payload))
        before = tree_state(fake_nav.nav_root)
        response = case.client.post(
            "/api/jobs",
            json={"type_name": "nav_write_apply", "parameters": {"preview_job_id": preview}},
        )
        assert response.status_code == 201, response.text
        result = run_submitted(case, fake_nav, int(response.json()["job_id"]))
        assert result.summary is not None and result.summary.aborted
        assert any(item.rule == "NAV_PREVIEW_STATE" for item in result.diagnostics)
        assert tree_state(fake_nav.nav_root) == before


def test_multiple_sources_keep_upstream_inputs_but_one_downstream_record(
    tmp_path: Path, fake_nav: FakeNavigation
) -> None:
    """M4 同一记录可引用同一数据集的多个块，上游逐输入展开而下游每条记录只显示一次。"""
    path = _seed(fake_nav)
    content = json.loads(path.read_bytes())
    content["lineage"][0]["inputs"].append(
        {"dataset_id": "dataset-35", "source_id": "source-second"}
    )
    path.write_text(json.dumps(content))
    with browser_case(tmp_path / "state", fake_nav) as case:
        upstream = _detail(case, _TARGET)["upstream"]
        assert [item["dataset_id"] for item in upstream] == [
            "dataset-35",
            "dataset-999",
            "dataset-35",
        ]
        assert _detail(case, _INPUT)["downstream"] == [
            {
                "record_id": 7,
                "dataset_id": "dataset-14",
                "name": "libero_10",
                "entry_path": _TARGET,
                "note": "工具转换",
            },
        ]


@pytest.mark.parametrize("broken", ["invalid", "symlink"])
def test_unusable_provenance_is_not_overwritten(
    tmp_path: Path, fake_nav: FakeNavigation, broken: str
) -> None:
    """坏来源文件和指向假数据根的来源软链接必须拒绝，不能当空血缘覆盖。"""
    path = fake_nav.nav_root / _TARGET / "来源.json"
    if broken == "invalid":
        path.write_text("{损坏")
    else:
        target = fake_nav.storage_roots[0].path / "来源.json"
        target.write_text("原始数据不可改")
        path.symlink_to(target)
    with browser_case(tmp_path / "state", fake_nav) as case:
        before = tree_state(fake_nav.nav_root)
        response = case.client.post(
            "/api/navigation/lineage/preview",
            json={"dataset_id": "dataset-14", "action": "add", "input_dataset_ids": ["dataset-35"]},
        )
        assert response.status_code == 400, response.text
        assert tree_state(fake_nav.nav_root) == before
        if broken == "symlink":
            assert (fake_nav.storage_roots[0].path / "来源.json").read_text() == "原始数据不可改"
