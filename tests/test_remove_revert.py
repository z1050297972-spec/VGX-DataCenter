"""撤回下线的 HTTP 契约；只使用临时导航层和应用。"""

from pathlib import Path

from creation_support import creation_api_case
from nav_manifest import FakeNavigation


def test_revert_job_type_is_not_registered(tmp_path: Path, fake_nav: FakeNavigation) -> None:
    """验收：通用作业接口拒绝提交已移除的撤回预览类型。"""
    with creation_api_case(tmp_path, fake_nav) as (api, _dependencies):
        response = api.client.post(
            "/api/jobs",
            json={"type_name": "nav_revert_preview", "parameters": {"target_job_id": 1}},
        )
        assert response.status_code == 422, response.text
