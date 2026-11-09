"""读取工具支持的 CDR 图像头并抽样亮度，不保留图片原文。

数值消息由 mcap-ros2-support 解码；图像使用 struct 读取最小字段，避免把大 uint8[]
展开成 Python 整数列表，且保留 cdr.rs 对封装、字符串和行填充的语义。
JPEG 缩略解码和灰度统计复用 Pillow；H.264 只检查码流头。
"""

import io
import struct
from dataclasses import dataclass

from mcap.records import Schema
from PIL import Image, ImageStat

# 抽样 JPEG 的目标尺寸（像素），只影响亮度近似值，不影响对齐及摘要。
BRIGHTNESS_SIZE = 128
# 防止损坏图片声明超大尺寸造成解码内存膨胀，最多 16M 像素。
MAX_IMAGE_PIXELS = 16 * 1024 * 1024


def has_header(schema: Schema) -> bool:
    """对应 ros2msg::has_header，只检查主定义第一个可解析、非常量字段的类型。"""
    if schema.encoding != "ros2msg":
        return False
    for line in schema.data.decode("utf-8").splitlines():
        if line.startswith("===="):
            break
        parts = line.split("#", 1)[0].split()
        if len(parts) < 2 or "=" in parts[1]:
            continue
        base = parts[0].split("[", 1)[0]
        if base == "wstring" or base.startswith("wstring<="):
            continue
        return base in ("Header", "std_msgs/Header", "std_msgs/msg/Header")
    return False


class Cdr:
    """工具 CDR 顺序头解析；偏移相对四字节封装头对齐。"""

    def __init__(self, data: bytes) -> None:
        """拒绝非 XCDR1 封装，保持工具的字节序判断。"""
        if len(data) < 4 or data[1] not in (0, 1):
            raise ValueError("不支持的 CDR 封装")
        self.data = data
        self.position = 4
        self.endian = "<" if data[1] == 1 else ">"

    def number(self, code: str) -> int:
        """按基本类型大小对齐读取整数。"""
        size = struct.calcsize(code)
        self.position += (-(self.position - 4)) % size
        value: int = struct.unpack_from(self.endian + code, self.data, self.position)[0]
        self.position += size
        return value

    def take(self, length: int) -> bytes:
        """读字节串前检查长度，截断不能成为合法空图像。"""
        end = self.position + length
        if end > len(self.data):
            raise ValueError("CDR 数据越界")
        result = self.data[self.position : end]
        self.position = end
        return result

    def string(self) -> str:
        """与工具一样允许没有尾零的 UTF-8 字符串。"""
        return self.take(self.number("I")).removesuffix(b"\x00").decode("utf-8")

    def header(self) -> int:
        """消费 Header 的 sec、nanosec、frame_id，返回纳秒时间戳。"""
        stamp = self.number("i") * 1_000_000_000 + self.number("I")
        self.string()
        return stamp


@dataclass(frozen=True)
class ImagePayload:
    """一条消息的临时图像内容，处理后立即释放。

    Attributes:
        kind: h264、compressed 或原图编码 rgb8/bgr8/mono8。
        data: 图片字节，原图已经去除行尾填充。
    """

    kind: str
    data: bytes


def image_payload(schema_name: str, reader: Cdr) -> ImagePayload:
    """Header 已消费后解析图像；H.265 和工具不支持的原图格式拒绝。"""
    if schema_name == "sensor_msgs/msg/CompressedImage":
        encoding = reader.string().lower()
        data = reader.take(reader.number("I"))
        if "h264" in encoding:
            return ImagePayload("h264", data)
        if "h265" in encoding or "hevc" in encoding:
            raise ValueError("不支持 H.265 码流")
        return ImagePayload("compressed", data)
    if schema_name == "sensor_msgs/msg/Image":
        return _raw_image(reader)
    raise ValueError("video 话题不是工具支持的图像消息")


def _raw_image(reader: Cdr) -> ImagePayload:
    """只接收工具 RawFormat 支持的八位格式，忽略八位数据的端序标记。"""
    height, width = reader.number("I"), reader.number("I")
    encoding = reader.string()
    channels = {"rgb8": 3, "bgr8": 3, "mono8": 1, "8UC1": 1}.get(encoding)
    if channels is None:
        raise ValueError("不支持的原始图像编码")
    reader.number("B")
    step = reader.number("I")
    data = reader.take(reader.number("I"))
    row = width * channels
    if step < row or len(data) < step * height or width * height > MAX_IMAGE_PIXELS:
        raise ValueError("图像尺寸超限或数据长度与尺寸不符")
    tight = b"".join(data[y * step : y * step + row] for y in range(height))
    return ImagePayload("mono8" if channels == 1 else encoding, tight)


def brightness(payload: ImagePayload) -> float:
    """返回 0-255 平均灰度；JPEG 使用 draft，原始图按像素字节直接算。"""
    if payload.kind == "compressed":
        with Image.open(io.BytesIO(payload.data)) as image:
            if image.width * image.height > MAX_IMAGE_PIXELS:
                raise ValueError("图像超过 16M 像素安全上限")
            image.draft("L", (BRIGHTNESS_SIZE, BRIGHTNESS_SIZE))
            with image.convert("L") as gray:
                return float(ImageStat.Stat(gray).mean[0])
    if not payload.data:
        raise ValueError("图像没有像素")
    if payload.kind == "mono8":
        return sum(payload.data) / len(payload.data)
    # 与灰度转换的 RGB 权重一致，BGR 仅交换红蓝通道，不把行尾填充算入亮度。
    weights = (299, 587, 114) if payload.kind == "rgb8" else (114, 587, 299)
    return sum(sum(payload.data[i::3]) * weight for i, weight in enumerate(weights)) / (
        len(payload.data) / 3 * 1000
    )
