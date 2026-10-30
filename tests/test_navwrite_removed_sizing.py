"""撤回新增数据集后的统计范围回归；只操作临时导航和真实作业队列。"""

from pathlib import Path

from creation_support import creation_api_case, preview_job, run_queued
from nav_manifest import FakeNavigation


def test_revert_creation_does_not_size_removed_dataset(
    tmp_path: Path, fake_nav: FakeNavigation
) -> None:
    """验证契约：撤回移除入口后不新增统计作业，结果阶段说明被删编号没有统计。"""
    with creation_api_case(tmp_path, fake_nav) as (api, dependencies):
        preview = preview_job(api, dependencies, fake_nav, operation="dataset")
        created = api.client.post(
            "/api/datasets/creation-writes", json={"preview_job_id": preview}
        ).json()["job_id"]
        committed = run_queued(api, dependencies, created)
        assert committed.summary is not None and not committed.summary.aborted
        before = {
            item["job_id"]
            for item in api.client.get("/api/jobs").json()["items"]
            if item["type_name"] == "dataset_sizing"
        }
        reverted = api.client.post(
            "/api/jobs",
            json={"type_name": "nav_revert_preview", "parameters": {"target_job_id": int(created)}},
        )
        assert reverted.status_code == 201, reverted.text
        preview_id = reverted.json()["job_id"]
        reversed_preview = run_queued(api, dependencies, preview_id)
        assert reversed_preview.summary is not None and not reversed_preview.summary.aborted
        apply = api.client.post(
            "/api/jobs",
            json={
                "type_name": "nav_write_apply",
                "parameters": {"preview_job_id": int(preview_id)},
            },
        )
        assert apply.status_code == 201, apply.text
        result = run_queued(api, dependencies, apply.json()["job_id"])
        assert result.summary is not None and not result.summary.aborted
        after = {
            item["job_id"]
            for item in api.client.get("/api/jobs").json()["items"]
            if item["type_name"] == "dataset_sizing"
        }
        assert after == before
        assert (
            result.summary.progress is not None
            and "dataset-36" in result.summary.progress.stage_name
        )
        assert "不统计" in result.summary.progress.stage_name
