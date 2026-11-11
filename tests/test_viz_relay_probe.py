"""M5-12 A 路：经命令行验证探测协议，只替换 ROS 和时钟系统边界。"""

import json
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest
from viz_relay_support import FakeSource

from rdp.robot_side.viz_relay import __main__ as cli


class _ProbeSource(FakeSource):
    """用离散消息和假单调时钟驱动真实探测循环，不启动线程或网络。"""

    def __init__(self, second_count: int) -> None:
        super().__init__()
        self.now_s = 0.0
        self.closed = False
        self.events = [
            (0.5, "/viz/camera/head_left"),
            (1.0, "/viz/joint/left_arm/obs"),
            (2.25, "/viz/camera/head_left"),
            (2.26, "/viz/camera/head_left"),
            (6.9, "/viz/camera/head_left"),
        ] + [(3.0 + index * 0.01, "/viz/joint/left_arm/obs") for index in range(second_count)]
        self.events.sort()

    def spin_once(self, timeout_s: float) -> None:
        """只推进允许等待的时长；无效 CDR 证明探测不能解析或转换载荷。"""
        deadline = self.now_s + timeout_s
        if self.events and self.events[0][0] <= deadline:
            self.now_s, channel = self.events.pop(0)
            self.emit(channel, b"not CDR")
        else:
            self.now_s = deadline

    def close(self) -> None:
        """记录节点关闭，订阅由探测器先释放。"""
        self.closed = True


def _config(path: Path) -> Path:
    """低限频和不同源话题使误用转发逻辑或源话题作为结果键立即暴露。"""
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "profile": "r1lite",
                "profile_version": 3,
                "host": "127.0.0.1",
                "port": 8765,
                "qos_reliability": "best_effort",
                "routes": [
                    {
                        "channel": "/viz/camera/head_left",
                        "source_topic": "/camera",
                        "source_type": "sensor_msgs/msg/CompressedImage",
                        "transform": "h264_to_compressed_video",
                        "max_rate_hz": 1,
                    },
                    {
                        "channel": "/viz/joint/left_arm/obs",
                        "source_topic": "/arm",
                        "source_type": "sensor_msgs/msg/JointState",
                        "transform": "passthrough",
                        "max_rate_hz": 1,
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    return path


@pytest.mark.parametrize("second_count", [0, 2])
def test_probe_reports_only_window_counts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    second_count: int,
) -> None:
    """两路原始计数排除预热、保留零值，输出恰好一行并回收订阅和节点。"""
    source = _ProbeSource(second_count)

    def create_source(reliability: str, *, node_name: str) -> _ProbeSource:
        assert (reliability, node_name) == ("best_effort", "rdp_viz_probe")
        return source

    ros = ModuleType("rdp.robot_side.viz_relay._ros")
    monkeypatch.setattr(ros, "RosSource", create_source, raising=False)
    monkeypatch.setitem(sys.modules, ros.__name__, ros)
    for name in ("rclpy", "sensor_msgs.msg"):
        monkeypatch.setitem(sys.modules, name, ModuleType(name))
    # 探测不需要 Foxglove；误导入 SDK 或建输出通道会让入口失败。
    monkeypatch.setitem(sys.modules, "foxglove", None)
    monkeypatch.setattr(cli, "time", SimpleNamespace(monotonic=lambda: source.now_s))

    assert cli.main(["--probe", "--config", str(_config(tmp_path / "config.json"))]) == 0
    assert capsys.readouterr().out == (
        'RDP_VIZ_PROBE {"counts": {"/viz/camera/head_left": 3, '
        f'"/viz/joint/left_arm/obs": {second_count}}}, "window_s": 5.0}}\n'
    )
    assert not source.active
    assert source.closed


def test_probe_and_self_test_are_mutually_exclusive(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """探测与自检同时指定必须先报配置错误，退出码为 2，不加载机器人依赖。"""
    assert (
        cli.main(["--probe", "--self-test", "--config", str(_config(tmp_path / "config.json"))])
        == 2
    )
    assert capsys.readouterr().out.startswith("RDP_VIZ_ERROR config_invalid ")
