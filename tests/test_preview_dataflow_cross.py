"""M5-12 交叉测试：机器人探测入口的真实输出，必须能被平台判定逐路解析。"""

import json
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest
from viz_relay_support import FakeSource

from rdp.collection.preview_config import build_relay_config
from rdp.collection.preview_dataflow import evaluate_dataflow
from rdp.collection.profile import load_robot_profiles
from rdp.robot_side.viz_relay import __main__ as cli

# 每次轮询 0.1 秒内各通道投递的条数；乘 10 即 Hz。缺省的通道不投递。
_PER_SPIN = {
    "/viz/camera/head_left": 0,  # 相机无数据：失败
    "/viz/camera/wrist_left": 1,  # 10 Hz，低于标称 29.75 的一半：警告
    "/viz/joint/left_arm/target": 0,  # 目标静默：提示
}
_DEFAULT_PER_SPIN = 20  # 200 Hz，所有标称值的一半以上：通过


class _TimedSource(FakeSource):
    """按假单调时钟推进，每次轮询向每个活跃通道投递固定条数。"""

    def __init__(self) -> None:
        super().__init__()
        self.now_s = 0.0

    def spin_once(self, timeout_s: float) -> None:
        self.now_s += timeout_s
        for route, _ in tuple(self.active.values()):
            for _ in range(_PER_SPIN.get(route.channel, _DEFAULT_PER_SPIN)):
                self.emit(route.channel, b"x")

    def close(self) -> None:
        """探测入口回收节点；本假源没有资源。"""


def test_robot_probe_output_is_evaluated_by_platform(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """R1 Lite 真实配置经 A 路入口输出一行，B 路按通道逐路给出四种结论。"""
    profile = next(
        p for p in load_robot_profiles(Path("profiles").resolve()) if p.profile == "r1lite"
    )
    config = build_relay_config(profile, "127.0.0.1")
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    source = _TimedSource()
    ros = ModuleType("rdp.robot_side.viz_relay._ros")

    def create_source(reliability: str, *, node_name: str) -> _TimedSource:
        assert (reliability, node_name) == ("best_effort", "rdp_viz_probe")
        return source

    monkeypatch.setattr(ros, "RosSource", create_source, raising=False)
    monkeypatch.setitem(sys.modules, ros.__name__, ros)
    for name in ("rclpy", "sensor_msgs.msg"):
        monkeypatch.setitem(sys.modules, name, ModuleType(name))
    monkeypatch.setattr(cli, "time", SimpleNamespace(monotonic=lambda: source.now_s))

    assert cli.main(["--probe", "--config", str(path)]) == 0
    results = {
        r.channel: r.status
        for r in evaluate_dataflow(profile, config["routes"], capsys.readouterr().out)
    }

    assert results.pop("/viz/camera/head_left") == "失败"
    assert results.pop("/viz/camera/wrist_left") == "警告"
    assert results.pop("/viz/joint/left_arm/target") == "提示"
    assert set(results.values()) == {"通过"}
