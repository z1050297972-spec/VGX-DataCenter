"""M4-01 的成员只读工具接口，经真实应用和临时工具库验证，不启动网络服务。"""

import hashlib
from pathlib import Path

import pytest
from account_api_support import add_actor, api_case
from pydantic import SecretStr
from tool_registry_support import isolated_tool_cache as isolated_tool_cache
from tool_registry_support import tool_files

from rdp.api.tools import configure_tools
from rdp.infra.config import ToolsConfig, load_config


def test_member_reads_tool_readme(tmp_path: Path) -> None:
    """M4.5-10：登录成员能读取工具目录的 README，保留 UTF-8 内容和换行。"""
    files = tool_files(tmp_path)
    content = "# 工具说明\n\n| 参数 | 含义 |\n| --- | --- |\n| input | 输入 |\n"
    (files.library / "mcap2lerobot/README.md").write_text(content, encoding="utf-8")
    with api_case(tmp_path / "state") as case:
        configure_tools(
            case.app, settings=ToolsConfig(registry_dir=files.registry, library_root=files.library)
        )
        add_actor(case)
        assert case.login("member", SecretStr("member-updated-value")).status_code == 200
        response = case.client.get("/api/tools/mcap2lerobot/readme")
        assert response.status_code == 200
        assert response.json() == {"name": "mcap2lerobot", "content": content}


def test_missing_readme_returns_not_found(tmp_path: Path) -> None:
    """M4.5-10：README 缺失返回 404，诊断指出工具身份和缺失文件。"""
    files = tool_files(tmp_path)
    with api_case(tmp_path / "state") as case:
        configure_tools(
            case.app, settings=ToolsConfig(registry_dir=files.registry, library_root=files.library)
        )
        assert case.login().status_code == 200
        response = case.client.get("/api/tools/mcap2lerobot/readme")
        assert response.status_code == 404
        diagnostic = response.json()["diagnostics"][0]
        assert {"key": "tool", "value": "mcap2lerobot"} in diagnostic["objects"]
        assert diagnostic["actual"] == "该工具目录里没有 README.md"
        assert diagnostic["consequence"] == "无法查看工具说明"


def test_readme_symlink_outside_tool_directory_is_rejected(tmp_path: Path) -> None:
    """M4.5-10：即使目标仍在工具库内，README 越出本工具目录的软链接也拒绝。"""
    files = tool_files(tmp_path)
    outside = files.library / "outside.md"
    outside.write_text("不能泄露的其他工具内容", encoding="utf-8")
    (files.library / "mcap2lerobot/README.md").symlink_to(outside)
    with api_case(tmp_path / "state") as case:
        configure_tools(
            case.app, settings=ToolsConfig(registry_dir=files.registry, library_root=files.library)
        )
        assert case.login().status_code == 200
        response = case.client.get("/api/tools/mcap2lerobot/readme")
        assert response.status_code == 400
        diagnostic = response.json()["diagnostics"][0]
        assert diagnostic["rule"] == "tools.readme_invalid"
        assert "越出登记边界" in diagnostic["actual"]
        assert diagnostic["consequence"] == "无法查看工具说明"
        assert "不能泄露的其他工具内容" not in response.text


@pytest.mark.parametrize("size_bytes, status", [(1024 * 1024, 200), (1024 * 1024 + 1, 400)])
def test_readme_size_limit(tmp_path: Path, size_bytes: int, status: int) -> None:
    """M4.5-10：1 MiB 恰好可读，多一个字节即返回输入诊断，不截断后冒充完整内容。"""
    files = tool_files(tmp_path)
    (files.library / "mcap2lerobot/README.md").write_bytes(b"a" * size_bytes)
    with api_case(tmp_path / "state") as case:
        configure_tools(
            case.app, settings=ToolsConfig(registry_dir=files.registry, library_root=files.library)
        )
        assert case.login().status_code == 200
        response = case.client.get("/api/tools/mcap2lerobot/readme")
        assert response.status_code == status
        if status == 200:
            assert len(response.json()["content"]) == size_bytes
        else:
            diagnostic = response.json()["diagnostics"][0]
            assert diagnostic["rule"] == "tools.readme_invalid"
            assert "1 MiB" in diagnostic["actual"]
            assert diagnostic["consequence"] == "无法查看工具说明"


@pytest.mark.parametrize("state", ["present", "missing", "outside", "invalid_manifest"])
def test_readme_availability_in_list_and_detail(tmp_path: Path, state: str) -> None:
    """M4.5-10：摘要只把有效清单、目录内存在的普通 README 标为可用，详情与列表一致。"""
    files = tool_files(tmp_path)
    readme = files.library / "mcap2lerobot/README.md"
    if state in {"present", "invalid_manifest"}:
        readme.write_text("# 使用说明", encoding="utf-8")
    elif state == "outside":
        outside = files.library / "outside.md"
        outside.write_text("其他工具", encoding="utf-8")
        readme.symlink_to(outside)
    if state == "invalid_manifest":
        (files.package / "tool.toml").write_text("invalid", encoding="utf-8")
    with api_case(tmp_path / "state") as case:
        configure_tools(
            case.app, settings=ToolsConfig(registry_dir=files.registry, library_root=files.library)
        )
        assert case.login().status_code == 200
        response = case.client.get("/api/tools")
        assert response.status_code == 200
        assert response.json()["items"][0]["readme_available"] is (state == "present")
        response = case.client.get("/api/tools/mcap2lerobot")
        assert response.status_code == 200
        assert response.json()["readme_available"] is (state == "present")


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
        assert response.json()["lerobot_environment"]["status"] == "unconfigured"
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


@pytest.mark.parametrize("state", ["available", "mismatch", "error"])
def test_lerobot_status_is_probed_without_failing_tool_list(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, state: str
) -> None:
    """M4.5：使用假解释器现场探测，源码改变或探测失败仍返回工具列表和明确状态。"""
    from conversion_cleaning_support import fake_lerobot

    from rdp.jobs.conversion import lerobot
    from rdp.jobs.sandbox import SandboxSpec

    files = tool_files(tmp_path / "tools")
    python, registration = fake_lerobot(tmp_path / "lerobot")
    monkeypatch.setattr(lerobot, "ENV_DIRECTORY", registration)

    def sandbox(
        argv: tuple[str, ...], spec: SandboxSpec, *, readonly_roots: tuple[Path, ...]
    ) -> tuple[str, ...]:
        return argv

    monkeypatch.setattr(lerobot, "sandbox_argv", sandbox)
    if state == "mismatch":
        (registration / "package/datasets/read.py").write_text("# changed\n")
    elif state == "error":
        python.write_text("#!/bin/sh\nexit 1\n")
    with api_case(tmp_path / "state") as case:
        configure_tools(
            case.app,
            settings=ToolsConfig(
                registry_dir=files.registry, library_root=files.library, lerobot_python=python
            ),
        )
        assert case.login().status_code == 200
        response = case.client.get("/api/tools")
        assert response.status_code == 200, response.text
        environment = response.json()["lerobot_environment"]
        assert environment["status"] == state
        assert environment["expected_version"] == "0.6.2"
        assert len(environment["expected_fingerprint"]) == 64
        if state == "available":
            assert environment["actual_version"] == "0.6.2"
            assert environment["actual_fingerprint"] == environment["expected_fingerprint"]
            assert environment["message"] is None
        else:
            assert environment["message"]
        assert len(response.json()["items"]) == 1
