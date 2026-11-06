"""第 08、10 张合并回归：创建与字段编辑共用临时导航层、写入底座和来源模型。"""

import json
from pathlib import Path

from creation_support import creation_api_case, preview_job, run_queued
from nav_manifest import FakeNavigation


def test_created_dataset_supports_origin_detail_filter_and_update(
    tmp_path: Path, fake_nav: FakeNavigation
) -> None:
    """合并契约：新建来源可被两视图详情、索引筛选及字段编辑读取，格式副本不复制来源。"""
    with creation_api_case(tmp_path, fake_nav) as (api, deps):
        preview = preview_job(
            api, deps, fake_nav, operation="dataset", format_entries=[{"format": "mcap"}]
        )
        view = api.client.get(f"/api/datasets/creation-previews/{preview}")
        assert view.status_code == 200, view.text
        dataset = view.json()["dataset_id"]
        submitted = api.client.post(
            "/api/datasets/creation-writes", json={"preview_job_id": preview}
        )
        assert submitted.status_code == 201, submitted.text
        result = run_queued(api, deps, submitted.json()["job_id"])
        assert result.summary is not None and not result.summary.aborted

        for origin, code in (("开源下载", "open_source"), ("仿真生成", "simulation")):
            if origin == "仿真生成":
                page = api.client.get(
                    f"/api/datasets/{dataset}/editable-fields",
                    params={"document": "数据集信息.json"},
                ).json()
                response = api.client.post(
                    "/api/navigation/fields/preview",
                    json={
                        "dataset_id": dataset,
                        "changes": [
                            {
                                "document": "数据集信息.json",
                                "expected_sha256": page["sha256"],
                                "path": ["data_origin"],
                                "value": origin,
                            }
                        ],
                    },
                )
                assert response.status_code == 201, response.text
                identifier = response.json()["job_id"]
                result = run_queued(api, deps, identifier)
                assert result.summary is not None and not result.summary.aborted
                response = api.client.post(
                    "/api/jobs",
                    json={
                        "type_name": "nav_write_apply",
                        "parameters": {"preview_job_id": int(identifier)},
                    },
                )
                assert response.status_code == 201, response.text
                result = run_queued(api, deps, response.json()["job_id"])
                assert result.summary is not None and not result.summary.aborted
                assert (
                    api.client.get("/api/datasets", params={"data_origin": "open_source"}).json()[
                        "items"
                    ]
                    == []
                )
            for entry in ("按任务/接口新数据集", "按格式/mcap/接口新数据集"):
                response = api.client.get("/api/datasets/detail", params={"entry_path": entry})
                assert response.status_code == 200, response.text
                provenance = response.json()["provenance"]
                assert provenance == {"state": "valid"}
                assert (
                    json.loads(response.json()["information"]["content"])["data_origin"] == origin
                )
                assert response.json()["index_stale"] is False
            response = api.client.get("/api/datasets", params={"data_origin": code})
            assert response.status_code == 200, response.text
            assert [item["dataset_id"] for item in response.json()["items"]] == [dataset]
        assert not (deps.rescan.nav_root / "按格式/mcap/接口新数据集/来源.json").exists()
