"""工单 01 的小 MCAP 现场生成器；数据全部写入 pytest 临时目录，不读真实样本。"""

from collections.abc import Callable
from io import BytesIO
from pathlib import Path

from mcap_ros2.writer import Writer
from PIL import Image

# 从 h264.rs 测试逐字节搬来的最小 Annex-B 头，仅供关键帧和 B slice 判断，不是真视频。
P_SLICE = bytes([0, 0, 0, 1, 0x41, 0b11000000])
B_SLICE = bytes([0, 0, 1, 0x01, 0b10011100])
IDR = bytes([0, 0, 0, 1, 0x67, 0x64, 0, 0, 0, 1, 0x68, 0xEE, 0, 0, 1, 0x65, 0b10001000])

HEADER = """
================================================================================
MSG: std_msgs/Header
builtin_interfaces/Time stamp
string frame_id
================================================================================
MSG: builtin_interfaces/Time
int32 sec
uint32 nanosec
"""
VECTOR = "std_msgs/Header header\nfloat64[] position\n" + HEADER
COMPRESSED = "std_msgs/Header header\nstring format\nuint8[] data\n" + HEADER

CONFIG = """
fps = 30
[sync]
reference_topic = "/camera"
max_dt_ms = 10
max_frame_gap = 1.6
min_episode_frames = 90
[[feature]]
name = "observation.images.head"
type = "video"
topic = "/camera"
[[feature]]
name = "observation.images.wrist"
type = "video"
topic = "/wrist"
max_dt_ms = 35
[[feature]]
name = "observation.state"
type = "vector"
sources = [{topic = "/state", field = "position"}]
[[feature]]
name = "action"
type = "vector"
sources = [
    {topic = "/action", field = "position"},
    {topic = "/optional", field = "position", optional = true, fill = [100.0]},
]
"""
RULES = """
schema_version = 1
[static]
feature = "observation.state"
long_static_s = 3.0
[jump]
feature = "action"
[image]
frozen_s = 1.0
sample_interval_s = 1.0
dark_below = 10.0
bright_above = 245.0
[[source]]
topic = "/state"
static_threshold = 0.001
[[source]]
topic = "/action"
jump_threshold = 0.5
"""


def configs(tmp_path: Path) -> tuple[Path, Path]:
    """生成 30 fps、90 帧最短段的独立配置，预期值可直接手算。"""
    tool, rules = tmp_path / "tool.toml", tmp_path / "rules.toml"
    tool.write_text(CONFIG)
    rules.write_text(RULES)
    return tool, rules


def jpeg(value: int) -> bytes:
    """用 Pillow 现场生成 8x8 灰度 JPEG，避免把图片 fixture 放进仓库。"""
    output = BytesIO()
    with Image.new("L", (8, 8), color=value) as image:
        image.save(output, format="JPEG")
    return output.getvalue()


def write_scene(path: Path, mode: str = "normal", frames: int = 120) -> None:
    """生成物理顺序消息，log_time 故意反序以验证只使用 header.stamp。"""
    with path.open("wb") as output:
        writer = Writer(output)
        vector = writer.register_msgdef("test_msgs/msg/Vector", VECTOR)
        camera = writer.register_msgdef("sensor_msgs/msg/CompressedImage", COMPRESSED)
        images = (jpeg(64), jpeg(96), jpeg(0))
        for i in range(frames):
            stamp = 1_000_000_000 + i * 1_000_000_000 // 30
            if mode == "gaps" and i >= 270:
                stamp += 1_000_000_000
            header = {
                "stamp": {"sec": stamp // 1_000_000_000, "nanosec": stamp % 1_000_000_000},
                "frame_id": "test",
            }
            for topic in ("/camera", "/wrist"):
                if topic == "/wrist" and (mode == "missing" or mode == "gaps" and 100 <= i < 110):
                    continue
                data, encoding = _image(i, mode, images, topic)
                writer.write_message(
                    topic,
                    camera,
                    {"header": header, "format": encoding, "data": data},
                    log_time=frames - i,
                    publish_time=frames - i,
                )
            state, action = _values(i, mode)
            for topic, value in (("/state", state), ("/action", action)):
                writer.write_message(
                    topic,
                    vector,
                    {"header": header, "position": [value]},
                    log_time=frames - i,
                    publish_time=frames - i,
                )
        writer.finish()


def _image(i: int, mode: str, images: tuple[bytes, ...], topic: str) -> tuple[bytes, str]:
    """只有基准相机用 H.264，其他图像交替灰度，避免无关冻结问题。"""
    if mode in ("gate", "b_slice") and topic == "/camera":
        data = P_SLICE if i < 2 else IDR if i == 2 else P_SLICE
        if mode == "b_slice" and i == 60:
            data = B_SLICE
        return data, "h264"
    if mode == "black":
        return images[2], "jpeg"
    return images[0 if mode == "frozen" else i % 2], "jpeg"


def _values(i: int, mode: str) -> tuple[float, float]:
    """一次阶跃保持偏移，不产生第二次回跳；NaN 只放在第 60 帧。"""
    state = 1.0 if mode == "static" else i * 0.01
    if mode == "nan" and i == 60:
        state = float("nan")
    action = i * 0.01 + (0.75 if mode == "jump" and i >= 60 else 0)
    return state, action


def noop() -> None:
    """测试调用方不取消。"""


def ignore_progress(_bytes: int) -> None:
    """不把检查进度写到外部环境。"""


CHECKPOINT: Callable[[], None] = noop
