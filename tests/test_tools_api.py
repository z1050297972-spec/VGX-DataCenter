"""M4-01 的成员只读工具接口，经真实应用和临时工具库验证，不启动网络服务。"""

import hashlib
from pathlib import Path

from account_api_support import add_actor, api_case
from pydantic import SecretStr
from tool_registry_support import isolated_tool_cache as isolated_tool_cache
from tool_registry_support import tool_files

from rdp.api.tools import configure_tools
from rdp.infra.config import ToolsConfig, load_config


def test_member_reads_list_and_configuration_detail(tmp_path: Path) -> None:
    """验收 4：成员可看列表和详情；配置全文、原始字节哈希、命令和源码说明均返回。"""
    files = tool_files(tmp_path)
    source = tmp_path / "config.toml"
    source.write_text(
        f'[tools]\nlibrary_root = "{files.library}"\nregistry_dir = "{files.registry}"\n',
        encoding="utf-8",
    )
    settings = load_config(environ={"RDP_CONFIG": str(source)}, home=tmp_path).config.tools
    with api_case(tmp_path / "state") as case:
        configure_tools(case.app, settings=settings)
        add_actor(case)
        assert case.login("member", SecretStr("member-updated-value")).status_code == 200
        response = case.client.get("/api/tools")
        assert response.status_code == 200
        item = response.json()["items"][0]
        assert item["name"] == "mcap2lerobot"
        assert item["robot_models"] == ["Galaxea R1 Lite"]
        assert item["needs_gpu"] is True
        assert item["program_path"] == str(files.program)
        response = case.client.get("/api/tools/mcap2lerobot")
        assert response.status_code == 200
        detail = response.json()
        config = detail["configurations"][0]
        content = (files.package / "configs/r1lite.toml").read_bytes()
        assert config == {
            "robot_model": "Galaxea R1 Lite",
            "filename": "configs/r1lite.toml",
            "content": content.decode("utf-8"),
            "sha256": hashlib.sha256(content).hexdigest(),
        }
        assert detail["command"]["verify"] == ["verify", "-c", "{config}", "{inputs}"]
        assert "{output}" in detail["command"]["convert"]
        assert detail["source_commit"] == "4027d15"
        assert "3 行未提交改动" in detail["source_note"]


def test_missing_tool_returns_not_found(tmp_path: Path) -> None:
    """验收 4：不存在的名字由真实应用返回 404 和指向该工具的统一诊断。"""
    files = tool_files(tmp_path)
    with api_case(tmp_path / "state") as case:
        configure_tools(
            case.app, settings=ToolsConfig(registry_dir=files.registry, library_root=files.library)
        )
        assert case.login().status_code == 200
        response = case.client.get("/api/tools/missing2tool")
        assert response.status_code == 404
        assert response.headers["content-type"].startswith("application/problem+json")
        assert response.json()["diagnostics"][0]["objects"] == [
            {"key": "tool", "value": "missing2tool"}
        ]
