"""工具登记测试样例；从真实登记包复制配置，仅在 tmp 中改程序大小与指纹。"""

import hashlib
import shutil
import tomllib
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest

from rdp.tools import registry as registry_module


@pytest.fixture(autouse=True)
def isolated_tool_cache() -> Iterator[None]:
    """只清理跨测试缓存资源，不断言私有状态或缓存函数调用次数。"""
    # 仅清理进程缓存，避免为测试新增生产公开接口；不用于观察或断言实现细节。
    clear_cache = registry_module._fingerprint.cache_clear  # pyright: ignore[reportPrivateUsage]
    clear_cache()
    try:
        yield
    finally:
        clear_cache()


@dataclass(frozen=True)
class ToolFiles:
    """单例测试的登记目录、工具库和假程序位置。"""

    registry: Path
    library: Path
    program: Path
    package: Path


def tool_files(root: Path) -> ToolFiles:
    """把真实清单和配置复制到 tmp，程序内容由测试自己生成，不使用真实工具库。"""
    source = Path(__file__).parents[1] / "tools" / "mcap2lerobot"
    registry = root / "registry"
    library = root / "library"
    package = registry / source.name
    shutil.copytree(source, package)
    content = b"test program v1\n"
    manifest_path = package / "tool.toml"
    text = manifest_path.read_text(encoding="utf-8")
    manifest = tomllib.loads(text)
    text = text.replace(str(manifest["program"]["size"]), str(len(content)))
    text = text.replace(manifest["program"]["sha256"], hashlib.sha256(content).hexdigest())
    manifest_path.write_text(text, encoding="utf-8")
    program = library / "mcap2lerobot" / manifest["program"]["path"]
    program.parent.mkdir(parents=True)
    program.write_bytes(content)
    return ToolFiles(registry, library, program, package)
