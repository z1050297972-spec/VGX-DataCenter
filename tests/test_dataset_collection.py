"""M3-03 采集信息关键契约；只使用测试提供的临时假导航层。"""

import json
from pathlib import Path

import pytest
from datasets_support import checkpoint, location
from nav_manifest import FakeNavigation

from rdp.jobs.datasets.reading import read_entry
from rdp.jobs.datasets.types import PanelSeverity


@pytest.mark.parametrize(
    "value",
    [
        None,
        {"status": "bad"},
        {"status": "done", "method_id": True, "purpose_id": None, "robot_ids": []},
    ],
)
def test_collection_read_tolerates_bad_shape(fake_nav: FakeNavigation, value: object) -> None:
    """缺失和 null 无发现；坏采集字段只降级自身，保留信息文件并给提示。"""
    path = fake_nav.nav_root / "按任务/libero_10/数据集信息.json"
    payload = json.loads(path.read_bytes())
    payload["collection"] = value
    path.write_text(json.dumps(payload))
    entry = read_entry(fake_nav.nav_root, location(fake_nav), checkpoint=checkpoint)
    assert entry.documents[1].payload is not None
    assert entry.collection is None
    findings = [item for item in entry.findings if item.diagnostic.rule == "COLLECTION_INVALID"]
    assert len(findings) == (0 if value is None else 1)
    assert all(item.severity is PanelSeverity.NOTICE for item in findings)


def test_collection_index_filters_detail_and_reference_counts(
    tmp_path: Path, fake_nav: FakeNavigation
) -> None:
    """扫描投影去重、筛选不重复数副本；名称实时解析，未知编号提示，引用阻止删除。"""
    from data_origin_support import run_submitted
    from dataset_api_support import browser_case

    path = fake_nav.nav_root / "按任务/libero_10/数据集信息.json"
    payload = json.loads(path.read_bytes())
    payload["collection"] = {
        "status": "collecting",
        "method_id": 1,
        "purpose_id": 1,
        "robot_ids": [1, 999, 1],
    }
    path.write_text(json.dumps(payload))
    with browser_case(tmp_path / "state", fake_nav) as case:
        created = case.client.post("/api/robots", json={"name": "一号", "robot_model": "R1"})
        assert created.status_code == 201, created.text
        assert created.json()["reference_count"] == 1
        assert case.client.delete("/api/robots/1").status_code == 409
        assert case.client.post("/api/robots/1/retire").status_code == 200
        for kind in ("methods", "purposes"):
            assert case.client.delete(f"/api/collection-vocabulary/{kind}/1").status_code == 409
            assert (
                case.client.get("/api/collection-vocabulary").json()[kind][0]["reference_count"]
                == 1
            )
        for key, value in (
            ("collection_robot", "1"),
            ("collection_method", "1"),
            ("collection_purpose", "1"),
            ("collection_status", "collecting"),
        ):
            response = case.client.get("/api/datasets", params={key: value})
            assert response.status_code == 200, response.text
            assert [row["name"] for row in response.json()["items"]] == ["libero_10"]
            assert case.client.get("/api/datasets", params={key: "unlabeled"}).json()["total"] == 4
        assert case.client.get("/api/datasets", params={"collection_robot": "0"}).status_code == 422
        assert (
            case.client.get("/api/datasets", params={"collection_status": "bad"}).status_code == 422
        )
        assert (
            case.client.get(
                "/api/datasets", params={"collection_robot": "1", "collection_method": "2"}
            ).json()["total"]
            == 0
        )
        case.client.put("/api/robots/1", json={"name": "改名", "robot_model": "R1"})
        options = case.client.get("/api/datasets/filters").json()
        assert options["collection_robots"] == [
            {"value": "1", "label": "改名", "count": 1},
            {"value": "999", "label": "未知编号 999", "count": 1},
            {"value": "unlabeled", "label": "无采集信息", "count": 4},
        ]
        assert options["collection_statuses"] == [
            {"value": "planned", "label": "计划中", "count": 0},
            {"value": "collecting", "label": "采集中", "count": 1},
            {"value": "done", "label": "已完成", "count": 0},
            {"value": "unlabeled", "label": "无采集信息", "count": 4},
        ]
        detail = case.client.get(
            "/api/datasets/detail", params={"entry_path": "按格式/lerobot/3.0/libero_10"}
        ).json()
        assert detail["collection"] == {
            "status": "collecting",
            "method": {
                "id": 1,
                "name": "主从臂遥操作",
                "data_origin": "真机采集",
                "status": "active",
            },
            "purpose": {"id": 1, "name": "训练", "status": "active"},
            "robots": [
                {"robot_id": 1, "name": "改名", "status": "retired"},
                {"robot_id": 999, "name": None, "status": "missing"},
            ],
        }
        panel = case.client.get("/api/datasets/panel", params={"dataset_id": "dataset-14"}).json()
        assert "COLLECTION_UNKNOWN_REF" in json.dumps(panel) and "999" in json.dumps(panel)
        # 单数据集重扫清空旧关联，引用计数必须下降，不能一直累计。
        payload["collection"] = None
        path.write_text(json.dumps(payload))
        response = case.client.post("/api/datasets/dataset-14/rescan")
        run_submitted(case, fake_nav, int(response.json()["job_id"]))
        assert case.client.get("/api/robots").json()["items"][0]["reference_count"] == 0
        assert case.client.delete("/api/robots/1").status_code == 204


def test_edit_collection_preserves_other_fields_and_syncs_replicas(
    tmp_path: Path, fake_nav: FakeNavigation
) -> None:
    """预览自动带出来源并同步副本，其余信息键值和顺序不变；停用引用可保留，显式来源优先。"""
    from data_origin_support import run_submitted
    from dataset_api_support import browser_case

    path = fake_nav.nav_root / "按任务/libero_10/数据集信息.json"
    original = json.loads(path.read_bytes())
    original["data_origin"] = "未知"
    path.write_text(json.dumps(original))
    with browser_case(tmp_path / "state", fake_nav) as case:
        case.client.post("/api/robots", json={"name": "一号", "robot_model": "R1"})
        for status, override in (("planned", None), ("done", "未知")):
            page = case.client.get(
                "/api/datasets/dataset-14/editable-fields", params={"document": "数据集信息.json"}
            ).json()
            field = next(item for item in page["fields"] if item["path"] == ["collection"])
            assert field["label"] == "采集信息"
            changes = [
                {
                    "document": "数据集信息.json",
                    "expected_sha256": page["sha256"],
                    "path": ["collection"],
                    "value": {
                        "status": status,
                        "method_id": 1,
                        "purpose_id": 1,
                        "robot_ids": [1, 1],
                    },
                }
            ]
            if override is not None:
                changes.append(
                    {
                        "document": "数据集信息.json",
                        "expected_sha256": page["sha256"],
                        "path": ["data_origin"],
                        "value": override,
                    }
                )
            response = case.client.post(
                "/api/navigation/fields/preview",
                json={"dataset_id": "dataset-14", "changes": changes},
            )
            assert response.status_code == 201, response.text
            preview_id = int(response.json()["job_id"])
            preview = run_submitted(case, fake_nav, preview_id)
            assert preview.summary is not None and not preview.summary.aborted
            report = case.client.get(f"/api/navigation/previews/{preview_id}").json()["report"]
            assert any(change["json_path"] == "data_origin" for change in report["listed_changes"])
            response = case.client.post(f"/api/navigation/fields/previews/{preview_id}/apply")
            assert response.status_code == 201, response.text
            result = run_submitted(case, fake_nav, int(response.json()["job_id"]))
            assert result.summary is not None and not result.summary.aborted
            current = json.loads(path.read_bytes())
            assert current["collection"] == {
                "status": status,
                "method_id": 1,
                "purpose_id": 1,
                "robot_ids": [1],
            }
            assert current["data_origin"] == (override or "真机采集")
            assert list(current) == [*original, "collection"]
            assert {
                key: value
                for key, value in current.items()
                if key not in {"collection", "data_origin"}
            } == {key: value for key, value in original.items() if key != "data_origin"}
            assert (
                json.loads(
                    (
                        fake_nav.nav_root / "按格式/lerobot/3.0/libero_10/数据集信息.json"
                    ).read_bytes()
                )
                == current
            )
            for url in (
                "/api/robots/1",
                "/api/collection-vocabulary/methods/1",
                "/api/collection-vocabulary/purposes/1",
            ):
                assert case.client.post(url + "/retire").status_code == 200


@pytest.mark.parametrize("kind", ["robots", "methods", "purposes", "missing"])
def test_edit_rejects_new_retired_or_missing_reference(
    tmp_path: Path, fake_nav: FakeNavigation, kind: str
) -> None:
    """真实预览作业拒绝新选停用项和不存在编号，不改导航文件。"""
    from data_origin_support import run_submitted
    from dataset_api_support import browser_case

    path = fake_nav.nav_root / "按任务/libero_10/数据集信息.json"
    before = path.read_bytes()
    with browser_case(tmp_path / "state", fake_nav) as case:
        case.client.post("/api/robots", json={"name": "一号", "robot_model": "R1"})
        if kind != "missing":
            url = "/api/robots/1" if kind == "robots" else f"/api/collection-vocabulary/{kind}/1"
            assert case.client.post(url + "/retire").status_code == 200
        page = case.client.get(
            "/api/datasets/dataset-14/editable-fields", params={"document": "数据集信息.json"}
        ).json()
        response = case.client.post(
            "/api/navigation/fields/preview",
            json={
                "dataset_id": "dataset-14",
                "changes": [
                    {
                        "document": "数据集信息.json",
                        "expected_sha256": page["sha256"],
                        "path": ["collection"],
                        "value": {
                            "status": "planned",
                            "method_id": 1,
                            "purpose_id": 1,
                            "robot_ids": [999 if kind == "missing" else 1],
                        },
                    }
                ],
            },
        )
        assert response.status_code == 201, response.text
        preview = run_submitted(case, fake_nav, int(response.json()["job_id"]))
        assert preview.summary is not None and preview.summary.aborted
        assert path.read_bytes() == before


def test_clear_collection_and_unknown_terms(tmp_path: Path, fake_nav: FakeNavigation) -> None:
    """未知词表编号保留为 missing 并给提示；清空 collection 同步副本并移除筛选引用。"""
    from data_origin_support import run_submitted
    from dataset_api_support import browser_case

    path = fake_nav.nav_root / "按任务/libero_10/数据集信息.json"
    payload = json.loads(path.read_bytes())
    payload["collection"] = {"status": "done", "method_id": 999, "purpose_id": 998, "robot_ids": []}
    path.write_text(json.dumps(payload))
    with browser_case(tmp_path / "state", fake_nav) as case:
        detail = case.client.get(
            "/api/datasets/detail", params={"entry_path": "按任务/libero_10"}
        ).json()
        assert detail["collection"]["method"] == {
            "id": 999,
            "name": None,
            "status": "missing",
            "data_origin": None,
        }
        assert detail["collection"]["purpose"] == {"id": 998, "name": None, "status": "missing"}
        options = case.client.get("/api/datasets/filters").json()
        assert options["collection_methods"][-2] == {
            "value": "999",
            "label": "未知编号 999",
            "count": 1,
        }
        assert options["collection_purposes"][-2] == {
            "value": "998",
            "label": "未知编号 998",
            "count": 1,
        }
        panel = case.client.get("/api/datasets/panel", params={"dataset_id": "dataset-14"}).json()
        finding = next(
            row
            for row in panel["findings"]
            if row["diagnostics"]["rule"] == "COLLECTION_UNKNOWN_REF"
        )
        assert finding["severity"] == "notice" and finding["diagnostics"]["total"] == 2
        page = case.client.get(
            "/api/datasets/dataset-14/editable-fields", params={"document": "数据集信息.json"}
        ).json()
        response = case.client.post(
            "/api/navigation/fields/preview",
            json={
                "dataset_id": "dataset-14",
                "changes": [
                    {
                        "document": "数据集信息.json",
                        "expected_sha256": page["sha256"],
                        "path": ["collection"],
                        "value": None,
                    }
                ],
            },
        )
        assert response.status_code == 201, response.text
        preview_id = int(response.json()["job_id"])
        run_submitted(case, fake_nav, preview_id)
        response = case.client.post(f"/api/navigation/fields/previews/{preview_id}/apply")
        assert response.status_code == 201, response.text
        result = run_submitted(case, fake_nav, int(response.json()["job_id"]))
        assert result.summary is not None and not result.summary.aborted
        assert json.loads(path.read_bytes())["collection"] is None
        assert (
            json.loads(
                (fake_nav.nav_root / "按格式/lerobot/3.0/libero_10/数据集信息.json").read_bytes()
            )["collection"]
            is None
        )
        assert (
            case.client.get(
                "/api/datasets/detail", params={"entry_path": "按任务/libero_10"}
            ).json()["collection"]
            is None
        )
        assert (
            case.client.get("/api/datasets", params={"collection_status": "unlabeled"}).json()[
                "total"
            ]
            == 5
        )
