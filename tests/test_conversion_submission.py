"""转换提交在真实HTTP边界校验；GPU声明只观察公开登记结果。"""

from pathlib import Path

import pytest
from conversion_support import fake_converter, settings
from dataset_api_support import browser_case
from nav_manifest import FakeNavigation

from rdp.jobs.conversion.registration import register_conversion_jobs
from rdp.jobs.registry import production_registry


@pytest.mark.parametrize(
    "change",
    [
        {"source_ids": ["src_0b33c900c7fa"]},
        {"dataset_id": "dataset-14", "source_ids": ["src_0b33c900c7fa"]},
        {"robot_model": "wrong-model"},
    ],
)
def test_submission_rejects_invalid_selection(
    tmp_path: Path, fake_nav: FakeNavigation, change: dict[str, object]
) -> None:
    """验收4：异集数据块、非mcap和未登记型号分别返回422。"""
    files = fake_converter(tmp_path / "tool")
    registry = production_registry()
    register_conversion_jobs(registry, settings(files), fake_nav.storage_roots, None)
    with browser_case(tmp_path / "state", fake_nav, registry=registry) as case:
        payload: dict[str, object] = {
            "dataset_id": "dataset-35",
            "source_ids": ["src_01e0bc7e9cc8"],
            "robot_model": "Galaxea R1 Lite",
        }
        payload.update(change)
        response = case.client.post(
            "/api/jobs", json={"type_name": "convert_mcap2lerobot", "parameters": payload}
        )
        assert response.status_code == 422


@pytest.mark.parametrize("needs_gpu", [True, False])
def test_gpu_requirement_follows_manifest(tmp_path: Path, needs_gpu: bool) -> None:
    """验收6：启动登记从清单取GPU要求，恢复为interrupt且成员可提交。"""
    files = fake_converter(tmp_path / "tool")
    manifest = files.package / "tool.toml"
    manifest.write_text(
        manifest.read_text().replace("needs_gpu = true", f"needs_gpu = {str(needs_gpu).lower()}")
    )
    registry = production_registry()
    register_conversion_jobs(registry, settings(files), (), None)
    definition = registry.lookup("convert_mcap2lerobot")
    assert definition is not None
    assert definition.requires_gpu is needs_gpu
    assert definition.recovery_mode.value == "interrupt"
    assert definition.submission_role.value == "member"
    parameters = definition.parameters_model.model_validate(
        {
            "dataset_id": "dataset-35",
            "source_ids": ["src_01e0bc7e9cc8"],
            "robot_model": "Galaxea R1 Lite",
        }
    )
    assert parameters.model_dump()["output_format"] == "v3.0"
