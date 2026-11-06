"""回填提交权限与既有预览、确认接口的集成检查，全部使用临时应用。"""

from pathlib import Path

from accounts_support import EXAMPLE_SECRET
from data_origin_support import run_submitted
from dataset_api_support import browser_case
from nav_manifest import FakeNavigation


def test_admin_backfill_uses_existing_pipeline_and_member_is_denied(
    tmp_path: Path, fake_nav: FakeNavigation
) -> None:
    """管理员提交可读预览并确认；成员不能经专用入口或通用作业接口绕过提交权限。"""
    with browser_case(tmp_path / "state", fake_nav) as case:
        submitted = case.client.post("/api/navigation/backfill/preview", json={})
        assert submitted.status_code == 201, submitted.text
        preview_id = int(submitted.json()["job_id"])
        result = run_submitted(case, fake_nav, preview_id)
        assert result.summary is not None and not result.summary.aborted, result.diagnostics
        report = case.client.get(f"/api/navigation/previews/{preview_id}")
        assert report.status_code == 200, report.text
        assert report.json()["operation"] == "edit_dataset_fields"
        applied = case.client.post(
            "/api/jobs",
            json={"type_name": "nav_write_apply", "parameters": {"preview_job_id": preview_id}},
        )
        assert applied.status_code == 201, applied.text
        result = run_submitted(case, fake_nav, int(applied.json()["job_id"]))
        assert result.summary is not None and not result.summary.aborted, result.diagnostics
        created = case.client.post(
            "/api/accounts",
            json={
                "login_name": "member",
                "password": EXAMPLE_SECRET.get_secret_value(),
                "display_name": "成员",
                "role": "member",
            },
        )
        assert created.status_code == 201, created.text
        assert case.login("member").status_code == 200
        changed = case.client.post(
            "/api/auth/password",
            json={
                "current_password": EXAMPLE_SECRET.get_secret_value(),
                "new_password": "MemberNewPassword-123!",
            },
        )
        assert changed.status_code == 200, changed.text
        assert case.client.post("/api/navigation/backfill/preview", json={}).status_code == 403
        denied = case.client.post(
            "/api/jobs", json={"type_name": "nav_information_backfill_preview", "parameters": {}}
        )
        assert denied.status_code == 403, denied.text
