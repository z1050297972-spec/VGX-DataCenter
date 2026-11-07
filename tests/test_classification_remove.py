"""删除分类值的关键验收；真实 HTTP、worker 和撤回流水线只使用临时导航层。"""

from pathlib import Path

from account_api_support import ApiCase
from data_origin_support import run_submitted
from dataset_api_support import browser_case
from nav_manifest import FakeNavigation
from navwrite_support import tree_state

from rdp.jobs.datasets.types import JsonObject, JsonValue
from rdp.jobs.navwrite.jsonio import dump_navigation_json, load_navigation_json


def test_remove_tasks_preserves_information_syncs_and_reverts(
    tmp_path: Path, fake_nav: FakeNavigation
) -> None:
    """两个数据集只去掉洗碗，保留其他键值和顺序，格式同步，预览不写，撤回逐字节恢复。"""
    originals: dict[Path, JsonObject] = {}
    for name in ("EgoProDemo", "libero_10"):
        path = fake_nav.nav_root / "按任务" / name / "数据集信息.json"
        payload = load_navigation_json(path.read_bytes())
        payload.update(
            tasks=["洗碗", "保留任务"],
            scene=" 实验室 ",
            robot_model=" PR2 ",
            unknown={"z": [1, " 保留 "]},
        )
        path.write_bytes(dump_navigation_json(payload))
        originals[path] = payload
    with browser_case(tmp_path / "state", fake_nav) as case:
        before = tree_state(fake_nav.nav_root)
        submitted = case.client.post(
            "/api/navigation/classification/remove/preview", json={"kind": "tasks", "value": "洗碗"}
        )
        assert submitted.status_code == 201, submitted.text
        preview_id = int(submitted.json()["job_id"])
        result = run_submitted(case, fake_nav, preview_id)
        assert result.summary is not None and not result.summary.aborted, result.diagnostics
        assert tree_state(fake_nav.nav_root) == before
        preview = case.client.get(f"/api/navigation/previews/{preview_id}")
        assert preview.status_code == 200, preview.text
        assert len(preview.json()["dataset_ids"]) == 2
        applied_id = _apply(case, fake_nav, preview_id)
        for path, original in originals.items():
            written = load_navigation_json(path.read_bytes())
            assert list(written) == list(original)
            assert written == {**original, "tasks": ["保留任务"]}
            for entry in fake_nav.manifest.entries:
                if entry.dataset_id == original["dataset_id"] and entry.path.startswith("按格式/"):
                    assert (
                        fake_nav.nav_root / entry.path / path.name
                    ).read_bytes() == path.read_bytes()
        after = tree_state(fake_nav.nav_root)
        affected_ids = [original["dataset_id"] for original in originals.values()]
        expected_paths = {
            str(Path(entry.path) / "数据集信息.json")
            for entry in fake_nav.manifest.entries
            if entry.dataset_id in affected_ids
        }
        assert before.keys() == after.keys()
        assert {path for path in before if before[path] != after[path]} == expected_paths
        options = case.client.get("/api/datasets/filters").json()["tasks"]
        assert "洗碗" not in {item["value"] for item in options}
        reverted = case.client.post(
            "/api/jobs",
            json={"type_name": "nav_revert_preview", "parameters": {"target_job_id": applied_id}},
        )
        assert reverted.status_code == 201, reverted.text
        revert_id = int(reverted.json()["job_id"])
        result = run_submitted(case, fake_nav, revert_id)
        assert result.summary is not None and not result.summary.aborted, result.diagnostics
        _apply(case, fake_nav, revert_id)
        assert tree_state(fake_nav.nav_root) == before


def test_remove_only_scene_becomes_unlabeled(tmp_path: Path, fake_nav: FakeNavigation) -> None:
    """旧字符串和单项数组的唯一场景删除后均写 []，筛选归未标注，自定义候选消失。"""
    paths = [
        fake_nav.nav_root / "按任务" / name / "数据集信息.json"
        for name in ("EgoProDemo", "libero_10")
    ]
    scenes: tuple[JsonValue, ...] = (" 实验室 ", ["实验室"])
    for path, scene in zip(paths, scenes, strict=True):
        payload = load_navigation_json(path.read_bytes())
        payload["scene"] = scene
        path.write_bytes(dump_navigation_json(payload))
    with browser_case(tmp_path / "state", fake_nav) as case:
        submitted = case.client.post(
            "/api/navigation/classification/remove/preview",
            json={"kind": "scene", "value": "实验室"},
        )
        assert submitted.status_code == 201, submitted.text
        preview_id = int(submitted.json()["job_id"])
        result = run_submitted(case, fake_nav, preview_id)
        assert result.summary is not None and not result.summary.aborted, result.diagnostics
        preview = case.client.get(f"/api/navigation/previews/{preview_id}").json()
        assert any(change["after"] == "[]" for change in preview["report"]["listed_changes"])
        _apply(case, fake_nav, preview_id)
        assert all(load_navigation_json(path.read_bytes())["scene"] == [] for path in paths)
        filtered = case.client.get("/api/datasets", params={"scene": "unlabeled"})
        assert filtered.status_code == 200, filtered.text
        names = {item["name"] for item in filtered.json()["items"]}
        assert {"EgoProDemo", "libero_10"} <= names
        options = case.client.get("/api/datasets/filters").json()["scenes"]
        assert "实验室" not in {item["value"] for item in options}


def test_unlabeled_and_unused_values_are_rejected(tmp_path: Path, fake_nav: FakeNavigation) -> None:
    """专用接口同步拒绝无人使用的值；未标注即使误写进原文，也不能由任一入口删除。"""
    path = fake_nav.nav_root / "按任务/libero_10/数据集信息.json"
    payload = load_navigation_json(path.read_bytes())
    payload.update(scene=["unlabeled"], tasks=["unlabeled"])
    path.write_bytes(dump_navigation_json(payload))
    with browser_case(tmp_path / "state", fake_nav) as case:
        before = tree_state(fake_nav.nav_root)
        for kind in ("scene", "tasks"):
            for value in ("unlabeled", "没有数据集使用的值"):
                rejected = case.client.post(
                    "/api/navigation/classification/remove/preview",
                    json={"kind": kind, "value": value},
                )
                assert rejected.status_code == 422, rejected.text
            rejected = case.client.post(
                "/api/jobs",
                json={
                    "type_name": "nav_classification_remove_preview",
                    "parameters": {"kind": kind, "value": "unlabeled"},
                },
            )
            assert rejected.status_code == 422, rejected.text
        assert tree_state(fake_nav.nav_root) == before


def _apply(case: ApiCase, nav: FakeNavigation, preview_id: int) -> int:
    """经真实通用作业接口确认同一预览，并要求 worker 成功完成写入。"""
    submitted = case.client.post(
        "/api/jobs",
        json={"type_name": "nav_write_apply", "parameters": {"preview_job_id": preview_id}},
    )
    assert submitted.status_code == 201, submitted.text
    job_id = int(submitted.json()["job_id"])
    result = run_submitted(case, nav, job_id)
    assert result.summary is not None and not result.summary.aborted, result.diagnostics
    return job_id
