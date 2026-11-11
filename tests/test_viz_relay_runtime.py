"""M5-03 服务器安全边界与可搬运性验收；所有 SDK 网络调用均用假对象。"""

import ast
import sys
from pathlib import Path
from types import ModuleType

import pytest

from rdp.robot_side.viz_relay import _sdk
from rdp.robot_side.viz_relay.config import Config


def test_server_has_no_write_capabilities(monkeypatch: pytest.MonkeyPatch) -> None:
    """验收 6：服务器禁止写能力并设置有限队列，测试不绑定真实端口。"""
    options: dict[str, object] = {}
    server = object()

    def start_server(**kwargs: object) -> object:
        options.update(kwargs)
        return server

    sdk = ModuleType("foxglove")
    monkeypatch.setattr(sdk, "start_server", start_server, raising=False)
    monkeypatch.setitem(sys.modules, "foxglove", sdk)
    config = Config("r1lite", 3, "127.0.0.1", 8765, "best_effort", ())
    assert _sdk.start_server(config, _sdk.Listener(())) is server
    assert options["capabilities"] == []
    assert (options["host"], options["port"]) == ("127.0.0.1", 8765)
    backlog = options["message_backlog_size"]
    assert isinstance(backlog, int) and 0 < backlog <= 1024


def test_package_is_python310_and_standalone() -> None:
    """验收 7：每个源码可被 3.10 语法解析，仅使用允许的依赖和标准库名字。"""
    package = Path(__file__).parents[1] / "src/rdp/robot_side/viz_relay"
    allowed = (sys.stdlib_module_names - {"tomllib"}) | {"foxglove", "rclpy", "sensor_msgs"}
    unavailable = {"override", "Self", "UTC", "ExceptionGroup", "BaseExceptionGroup"}
    for path in sorted(package.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), feature_version=(3, 10))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert all(alias.name.split(".")[0] in allowed for alias in node.names), path
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                assert node.module is not None and node.module.split(".")[0] in allowed, path
                assert not {alias.name for alias in node.names} & unavailable, path
            elif isinstance(node, ast.Attribute):
                assert node.attr not in unavailable, path
            elif isinstance(node, ast.Name):
                assert node.id not in unavailable, path
