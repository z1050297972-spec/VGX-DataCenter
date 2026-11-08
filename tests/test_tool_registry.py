"""M4 工具登记关键行为；只读真实登记包，程序与改写后的清单都位于 tmp。"""

import hashlib
import shutil
import tomllib
from pathlib import Path

import pytest
from tool_registry_support import isolated_tool_cache as isolated_tool_cache
from tool_registry_support import tool_files

from rdp.tools.manifest import ToolManifest
from rdp.tools.registry import load_tool_registry


def test_real_manifest_is_valid() -> None:
    """验收 3：真实登记清单通过校验，只检查登记包内配置，不访问工具库。"""
    package = Path(__file__).parents[1] / "tools" / "mcap2lerobot"
    manifest = ToolManifest.model_validate(
        tomllib.loads((package / "tool.toml").read_text(encoding="utf-8")),
        context={"package_dir": package},
    )
    assert manifest.tool.name == "mcap2lerobot"
    assert manifest.models == {"Galaxea R1 Lite": "configs/r1lite.toml"}
    assert manifest.io.output_versions == ("v3.0", "v2.1")


def test_program_changes_and_removal_change_status(tmp_path: Path) -> None:
    """验收 1：程序可用、同大小改一字节后指纹不符、删除后找不到；诊断给出独立指纹。"""
    files = tool_files(tmp_path)
    registry = load_tool_registry(files.registry, files.library)
    assert registry.items[0].status == "可用"
    assert registry.items[0].diagnostics == ()

    changed = b"test program v2\n"
    files.program.write_bytes(changed)
    item = load_tool_registry(files.registry, files.library).items[0]
    assert item.status == "指纹不符"
    diagnostic = item.diagnostics[0]
    assert {obj.key: obj.value for obj in diagnostic.objects} == {
        "tool": "mcap2lerobot",
        "program": str(files.program),
    }
    assert hashlib.sha256(changed).hexdigest()[:12] in diagnostic.actual
    assert "16 字节" in diagnostic.actual
    assert hashlib.sha256(b"test program v1\n").hexdigest()[:12] in (diagnostic.expected or "")
    assert diagnostic.consequence == "不能用于转换"
    assert diagnostic.next_step == "工具程序已变化，需要执行线重新登记"

    files.program.unlink()
    assert load_tool_registry(files.registry, files.library).items[0].status == "程序找不到"


@pytest.mark.parametrize("invalid", ["name", "force", "missing_output"])
def test_invalid_manifest_does_not_hide_other_tools(tmp_path: Path, invalid: str) -> None:
    """验收 2：名字不符、强制覆盖和缺输出占位符各自使清单无效，其他工具仍可用。"""
    files = tool_files(tmp_path)
    bad = files.registry / "bad2tool"
    shutil.copytree(files.package, bad)
    manifest = bad / "tool.toml"
    text = manifest.read_text(encoding="utf-8")
    if invalid != "name":
        text = text.replace('name = "mcap2lerobot"', 'name = "bad2tool"')
    if invalid == "force":
        text = text.replace('["convert",', '["convert", "--force",')
    elif invalid == "missing_output":
        text = text.replace('"{output}", ', "")
    manifest.write_text(text, encoding="utf-8")

    broken, usable = load_tool_registry(files.registry, files.library).items
    assert broken.name == "bad2tool" and broken.status == "清单无效"
    assert usable.name == "mcap2lerobot" and usable.status == "可用"
    diagnostic = broken.diagnostics[0]
    assert {obj.key: obj.value for obj in diagnostic.objects}["tool"] == "bad2tool"
    expected_field = "tool.name" if invalid == "name" else "command.convert"
    assert expected_field in diagnostic.actual
    assert diagnostic.expected and diagnostic.next_step
    assert diagnostic.consequence == "不能用于转换"
