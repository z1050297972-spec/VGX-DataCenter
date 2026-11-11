#!/usr/bin/env python3
"""M5-03 离线端到端：用录制回放替换 ROS 层，驱动第 03 张的真实转发逻辑和 Foxglove 服务器。

只读本地 MCAP，只监听 127.0.0.1；不连接 ROS 或机器人。转发程序从 --relay-root 导入，
导入方式与机器人上一致（包名 viz_relay）。
"""

import argparse
import json
import signal
import sys
import tempfile
import time
from pathlib import Path
from threading import Event

from mcap.reader import make_reader

CACHE = Path.home() / ".cache/rdp-m5-offline"
RECONCILE_INTERVAL_S = 0.2


def _routes():
    """与第 09 张验收 7 一致的 R1 Lite 15 条路由（主机改成回环）。"""
    cams = [
        ("head_left", "/hdas/camera_head/left_raw/image_raw_color/compressed", "h264_to_compressed_video"),
        ("head_right", "/hdas/camera_head/right_raw/image_raw_color/compressed", "h264_to_compressed_video"),
        ("wrist_left", "/hdas/camera_wrist_left/color/image_raw/compressed", "passthrough"),
        ("wrist_right", "/hdas/camera_wrist_right/color/image_raw/compressed", "passthrough"),
    ]
    routes = [
        {"channel": f"/viz/camera/{n}", "source_topic": t, "source_type": "sensor_msgs/msg/CompressedImage",
         "transform": x, "max_rate_hz": None}
        for n, t, x in cams
    ]
    joints = {
        "left_arm": ("/hdas/feedback_arm_left", "/motion_target/target_joint_state_arm_left"),
        "right_arm": ("/hdas/feedback_arm_right", "/motion_target/target_joint_state_arm_right"),
        "left_gripper": ("/hdas/feedback_gripper_left", "/motion_target/target_position_gripper_left"),
        "right_gripper": ("/hdas/feedback_gripper_right", "/motion_target/target_position_gripper_right"),
        "torso": ("/hdas/feedback_torso", "/motion_target/target_joint_state_torso"),
    }
    for group, (obs, target) in joints.items():
        for suffix, topic in (("obs", obs), ("target", target)):
            routes.append({"channel": f"/viz/joint/{group}/{suffix}", "source_topic": topic,
                           "source_type": "sensor_msgs/msg/JointState", "transform": "passthrough",
                           "max_rate_hz": 50})
    routes.append({"channel": "/viz/joint/chassis/obs", "source_topic": "/hdas/feedback_chassis",
                   "source_type": "sensor_msgs/msg/JointState", "transform": "passthrough", "max_rate_hz": 50})
    return routes


class ReplaySource:
    """Source 接口的录制回放实现：订阅只记回调，由主循环按录制时刻投递。"""

    def __init__(self):
        self.callbacks = {}
        self.events = []

    def subscribe(self, route, callback):
        self.callbacks[route.source_topic] = callback
        self.events.append(("subscribe", route.channel, time.monotonic()))
        return route.source_topic

    def unsubscribe(self, subscription):
        self.callbacks.pop(subscription, None)
        self.events.append(("unsubscribe", subscription, time.monotonic()))


def _main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--relay-root", type=Path, required=True, help="含 viz_relay 包的目录")
    parser.add_argument("--file", type=Path, default=CACHE / "sample/r1lite_20261011_52s.mcap")
    parser.add_argument("--duration", type=float, default=50.0)
    parser.add_argument("--stats-json", type=Path)
    args = parser.parse_args()
    sys.path.insert(0, str(args.relay_root))
    from viz_relay import _sdk  # noqa: PLC0415
    from viz_relay.config import load_config  # noqa: PLC0415
    from viz_relay.core import Relay  # noqa: PLC0415

    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / "config.json"
        path.write_text(json.dumps({"schema_version": 1, "profile": "r1lite", "profile_version": 3,
                                    "host": "127.0.0.1", "port": 8765, "qos_reliability": "best_effort",
                                    "routes": _routes()}))
        config = load_config(path)
    stop = Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    listener = _sdk.Listener(config.routes)
    channels = {r.channel: _sdk.OutputChannel(r, listener) for r in config.routes}
    server = _sdk.start_server(config, listener)
    source = ReplaySource()
    relay = Relay(config.routes, source, channels, time.monotonic_ns)
    topics = {r.source_topic for r in config.routes}
    print("READY ws://127.0.0.1:8765", flush=True)
    started = time.monotonic()
    last_reconcile = 0.0
    try:
        with args.file.expanduser().open("rb") as stream:
            reader = make_reader(stream)
            first = None
            for _schema, channel, message in reader.iter_messages(topics=topics, log_time_order=True):
                first = first if first is not None else message.log_time
                due = started + (message.log_time - first) / 1e9
                while not stop.is_set():
                    now = time.monotonic()
                    if now - last_reconcile >= RECONCILE_INTERVAL_S:
                        relay.reconcile()
                        last_reconcile = now
                    if now >= due or now - started >= args.duration:
                        break
                    stop.wait(min(due - now, 0.02))
                if stop.is_set() or time.monotonic() - started >= args.duration:
                    break
                callback = source.callbacks.get(channel.topic)
                if callback is not None:
                    callback(message.data)
    finally:
        stats = {k: vars(v) for k, v in relay.statistics().items()}
        relay.close()
        server.stop()
        for c in channels.values():
            c.close()
        summary = {"elapsed_s": time.monotonic() - started, "stats": stats,
                   "events": [(e, c, round(t - started, 2)) for e, c, t in source.events]}
        if args.stats_json:
            args.stats_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
        print("STOPPED " + json.dumps(summary, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    _main()
