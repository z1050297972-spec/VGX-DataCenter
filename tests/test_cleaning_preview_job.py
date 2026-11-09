"""M4.5-02 的 API→worker→报告关键验收；只使用临时只读存储根。"""

from pathlib import Path

from cleaning_preview_support import preview_case
from tool_registry_support import isolated_tool_cache as isolated_tool_cache

from rdp.jobs.outcome import JobOutcome


def test_preview_success_and_member_read(tmp_path: Path) -> None:
    """管理员提交后成功落库，成员读取的报告保留手算的帧数和段数。"""
    with preview_case(tmp_path) as case:
        response = case.submit()
        assert response.status_code == 201
        assert response.json()["type_name"] == "cleaning_preview_mcap2lerobot"
        assert response.json()["recovery_mode"] == "interrupt"
        definition = case.registry.lookup("cleaning_preview_mcap2lerobot")
        assert definition is not None and not definition.requires_gpu
        assert definition.storage == () and not definition.writes_navigation
        identifier = response.json()["job_id"]
        assert case.api.client.get(f"/api/cleaning-previews/{identifier}").status_code == 404
        result = case.run(identifier)
        assert result is not None and result.summary is not None
        assert result.summary.outcome is JobOutcome.SUCCEEDED
        case.login_member()
        response = case.api.client.get(f"/api/cleaning-previews/{identifier}")
        assert response.status_code == 200
        body = response.json()
        assert body["report"]["summary"] == {
            "files": 1,
            "excluded_files": 0,
            "episodes": 1,
            "excluded_episodes": 0,
            "reference_frames": 120,
            "kept_frames": 120,
        }
        assert body["job_id"] == identifier
        assert body["dataset_id"] == "dataset-preview"
        assert body["robot_model"] == "Galaxea R1 Lite"
        assert body["tool_name"] == "mcap2lerobot"
        assert len(body["binary_sha256"]) == 64
        assert body["config_sha256"] == body["report"]["tool_config_sha256"]
        assert body["rules_sha256"] == body["report"]["rules_sha256"]
        assert body["created_at"].endswith("Z")
        assert case.report_count() == 1
        assert result.progress is not None and result.progress.stage_index == 4
        assert not (case.root / "暂存").exists()


def test_member_cannot_submit(tmp_path: Path) -> None:
    """成员通过专用和通用提交入口都不能创建预览作业。"""
    with preview_case(tmp_path) as case:
        case.login_member()
        assert case.submit().status_code == 403
        assert (
            case.api.client.post(
                "/api/jobs",
                json={
                    "type_name": "cleaning_preview_mcap2lerobot",
                    "parameters": case.payload,
                },
            ).status_code
            == 403
        )


def test_model_without_cleaning_rules(tmp_path: Path) -> None:
    """工具支持转换但没有清洗规则的型号在提交时返回 422。"""
    with preview_case(tmp_path) as case:
        assert case.submit(robot_model="other").status_code == 422


def test_offline_input_has_storage_diagnostic_and_no_report(tmp_path: Path) -> None:
    """选中只读根离线时存储检查使作业失败，报告库不留记录。"""
    with preview_case(tmp_path, offline=True) as case:
        identifier = case.submit().json()["job_id"]
        result = case.run(identifier)
        assert result is not None and result.summary is not None
        assert result.summary.outcome is JobOutcome.FAILED
        assert any(group.rule == "storage.offline" for group in result.diagnostics)
        assert case.report_count() == 0
        assert case.api.client.get(f"/api/cleaning-previews/{identifier}").status_code == 404


def test_cancellation_during_read_does_not_save_report(tmp_path: Path) -> None:
    """实际读到文件字节后从 HTTP 取消，终态为取消且没有部分报告。"""
    with preview_case(tmp_path) as case:
        identifier = case.submit().json()["job_id"]
        result = case.run(identifier, cancel_during_read=True)
        assert result is not None and result.state.value == "cancelled"
        assert case.report_count() == 0
        assert case.api.client.get(f"/api/cleaning-previews/{identifier}").status_code == 404
