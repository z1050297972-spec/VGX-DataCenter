"""M1.5-15 核心契约：只使用临时导航层验证读取、筛选和字段编辑。"""

import json
from pathlib import Path

from datasets_support import checkpoint, location
from nav_manifest import FakeNavigation

from rdp.jobs.datasets.reading import read_entry


def test_reads_information_and_ignores_legacy_origin(fake_nav: FakeNavigation) -> None:
    """读取：顶层 FPS、来源和去空白型号生效，旧来源文件只保留血缘。"""
    entry = fake_nav.nav_root / "按任务/libero_10"
    path = entry / "数据集信息.json"
    payload = json.loads(path.read_bytes())
    payload.update(fps=30, data_origin="仿真生成", robot_model=" PR2 ")
    path.write_text(json.dumps(payload, ensure_ascii=False))
    (entry / "来源.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "dataset_id": payload["dataset_id"],
                "dataset_name": "libero_10",
                "data_origin": "开源下载",
                "data_origin_set_by": None,
                "collection_task_id": None,
                "lineage": [],
            },
            ensure_ascii=False,
        )
    )
    snapshot = read_entry(fake_nav.nav_root, location(fake_nav), checkpoint=checkpoint)
    assert snapshot.fps == 30
    assert snapshot.data_origin == "simulation"
    assert snapshot.robot_model == "PR2"


def test_filters_use_information_index(tmp_path: Path, fake_nav: FakeNavigation) -> None:
    """筛选与空白：规范信息进索引，原文件值不影响匹配，旧参数返回 422。"""
    from dataset_api_support import browser_case, set_meta

    path = fake_nav.nav_root / "按任务/libero_10/数据集信息.json"
    payload = json.loads(path.read_bytes())
    payload.update(fps=30, data_origin="仿真生成", robot_model=" PR2 ")
    path.write_text(json.dumps(payload, ensure_ascii=False))
    with browser_case(tmp_path / "state", fake_nav) as case:
        set_meta(case, "按任务/libero_10", "franka", 60, 60)
        for params in ({"robot_model": "PR2"}, {"fps": "30"}, {"data_origin": "simulation"}):
            response = case.client.get("/api/datasets", params=params)
            assert response.status_code == 200, response.text
            assert [row["name"] for row in response.json()["items"]] == ["libero_10"]
            assert response.json()["items"][0]["robot_model"] == "PR2"
        unknown = case.client.get("/api/datasets", params={"robot_model": "unlabeled"}).json()
        assert unknown["total"] == 4
        assert case.client.get("/api/datasets", params={"fps": "60"}).json()["total"] == 0
        assert case.client.get("/api/datasets", params={"robot_type": "franka"}).status_code == 422
        options = case.client.get("/api/datasets/filters").json()
        assert options["robot_models"] == [
            {"value": "PR2", "label": "PR2", "count": 1},
            {"value": "unlabeled", "label": "未标注", "count": 4},
        ]
        assert (
            not {
                "robot_types",
                "robot_model_options",
                "robot_models_registered",
                "default_robot_filter",
            }
            & options.keys()
        )


def test_edit_information_syncs_replicas_and_trims_model(
    tmp_path: Path, fake_nav: FakeNavigation
) -> None:
    """编辑与空白：FPS、来源通过同一预览写入两视图，型号保存去空白后的值。"""
    from data_origin_support import run_submitted
    from dataset_api_support import browser_case

    with browser_case(tmp_path / "state", fake_nav) as case:
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
                        "path": [key],
                        "value": value,
                    }
                    for key, value in (
                        ("fps", 30),
                        ("data_origin", "仿真生成"),
                        ("robot_model", " PR2 "),
                    )
                ],
            },
        )
        assert response.status_code == 201, response.text
        preview_id = int(response.json()["job_id"])
        preview = run_submitted(case, fake_nav, preview_id)
        assert preview.summary is not None and not preview.summary.aborted
        response = case.client.post(f"/api/navigation/fields/previews/{preview_id}/apply")
        assert response.status_code == 201, response.text
        applied = run_submitted(case, fake_nav, int(response.json()["job_id"]))
        assert applied.summary is not None and not applied.summary.aborted
        canonical = json.loads(
            (fake_nav.nav_root / "按任务/libero_10/数据集信息.json").read_bytes()
        )
        replica = json.loads(
            (fake_nav.nav_root / "按格式/lerobot/3.0/libero_10/数据集信息.json").read_bytes()
        )
        assert canonical == replica
        assert (canonical["fps"], canonical["data_origin"], canonical["robot_model"]) == (
            30,
            "仿真生成",
            "PR2",
        )


def test_edit_rejects_invalid_origin_and_fps(tmp_path: Path, fake_nav: FakeNavigation) -> None:
    """编辑：来源必须在词表，FPS 只收正整数；在真实接口入队前返回 422。"""
    from dataset_api_support import browser_case

    with browser_case(tmp_path / "state", fake_nav) as case:
        for key, value in (("data_origin", "自定义来源"), ("fps", "30"), ("fps", 0)):
            response = case.client.post(
                "/api/navigation/fields/preview",
                json={
                    "dataset_id": "dataset-14",
                    "changes": [
                        {
                            "document": "数据集信息.json",
                            "expected_sha256": "a" * 64,
                            "path": [key],
                            "value": value,
                        }
                    ],
                },
            )
            assert response.status_code == 422, response.text
