"""创建预览提供可勾选入口，前端不自行推断版本目录。"""

from pathlib import Path

from creation_support import creation_api_case, preview_job
from nav_manifest import FakeNavigation


def test_creation_preview_returns_format_choices(tmp_path: Path, fake_nav: FakeNavigation) -> None:
    """验证契约：成功预览返回登记的格式和版本选择，mcap 不带版本。"""
    with creation_api_case(tmp_path, fake_nav) as (api, dependencies):
        identifier = preview_job(api, dependencies, fake_nav)
        response = api.client.get(f"/api/datasets/creation-previews/{identifier}")
        assert response.status_code == 200
        assert {"format": "mcap", "version": None} in response.json()["format_entry_options"]
