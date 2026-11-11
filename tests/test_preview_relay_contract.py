"""第 03/09 张交叉验收：真实配置解析器与默认发布目录，只读程序源、不连接机器人。"""

import io
import json
import tarfile
from pathlib import Path

from rdp.collection.preview_config import build_relay_config
from rdp.collection.profile import load_robot_profiles
from rdp.jobs.robot_connection._preview_scripts import bundle
from rdp.jobs.robot_connection._session import ConnectionDependencies
from rdp.robot_side.viz_relay.config import load_config


def test_r1lite_config_is_accepted_by_robot_relay(tmp_path: Path) -> None:
    """交叉验收 1：真实 R1 Lite 配置由机器人侧解析器接收，登记地址和 15 条路由完整保留。"""
    profile = next(p for p in load_robot_profiles(Path("profiles")) if p.profile == "r1lite")
    path = tmp_path / "config.json"
    # 地址只作为配置字面量，load_config 不建节点或发起连接。
    path.write_text(json.dumps(build_relay_config(profile, "192.168.0.229")), encoding="utf-8")
    config = load_config(path)
    assert config.host == "192.168.0.229"
    assert len(config.routes) == 15


def test_default_relay_bundle_contains_all_python_sources() -> None:
    """交叉验收 2：生产默认目录打包包含全部 Python 文件及包入口，文件内容原样保留。"""
    source = ConnectionDependencies.relay_source
    _, payload = bundle(source, {})
    with tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz") as archive:
        names = set(archive.getnames())
        assert {"viz_relay/__init__.py", "viz_relay/__main__.py"} <= names
        assert names == {f"viz_relay/{p.name}" for p in source.glob("*.py")} | {"config.json"}
        for path in source.glob("*.py"):
            member = archive.extractfile(f"viz_relay/{path.name}")
            assert member is not None
            with member:
                assert member.read() == path.read_bytes()
