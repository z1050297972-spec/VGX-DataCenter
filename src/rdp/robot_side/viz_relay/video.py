"""机器人侧纯字节转换（M5-03），不解码图像，不依赖 ROS 或 Foxglove。

标准库 struct 足以解析固定的 CompressedImage 小端 CDR。自行解析的理由是
rclpy 反序列化在工作站测不了，大数组转 Python 对象费时；mcap-ros2-support
会给机器人多装一个包。SPS 修正依据调研《M5-预览组件选型》末节，
等 Lichtblick 修复 constraint_set5_flag 位移后可移除清位逻辑。
"""

import struct
from dataclasses import dataclass

# ROS header 的秒和纳秒合成整数，避免浮点损失破坏严格递增比较。
NANOSECONDS_PER_SECOND = 1_000_000_000


@dataclass(frozen=True)
class VideoFrame:
    """保留 ROS header 的压缩视频载荷，适配层再转成 SDK 消息。

    Attributes:
        timestamp_ns: header.stamp 的整数纳秒，不用工作站接收时刻替代。
        frame_id: header.frame_id，可为空。
        format: 源消息的格式文本，只有 h264 会被转发。
        data: 一帧 Annex B 数据；不转码，不改变尺寸或帧顺序。
    """

    timestamp_ns: int
    frame_id: str
    format: str
    data: bytes


class _CdrReader:
    """只解析本票所需的四字节对齐字段，不实现通用 CDR。"""

    def __init__(self, data: bytes) -> None:
        """去掉封装头，使后续偏移相对 CDR 内容计算。"""
        if len(data) < 4 or data[:2] != b"\x00\x01":
            raise ValueError("仅支持小端 CDR 封装")
        self.data = memoryview(data)[4:]
        self.offset = 0

    def uint32(self) -> int:
        """按 CDR 四字节对齐读取长度。"""
        self.offset = (self.offset + 3) & ~3
        result = int(struct.unpack_from("<I", self.data, self.offset)[0])
        self.offset += 4
        return result

    def block(self) -> bytes:
        """读取有长度前缀的字节块，拒绝截断数据。"""
        size = self.uint32()
        end = self.offset + size
        if end > len(self.data):
            raise ValueError("CDR 字节块截断")
        result = bytes(self.data[self.offset : end])
        self.offset = end
        return result

    def string(self) -> str:
        """CDR 字符串包含末尾 NUL，不能把它带进 frame_id。"""
        data = self.block()
        if not data or data[-1] != 0:
            raise ValueError("CDR 字符串缺少终止符")
        return data[:-1].decode("utf-8")


def parse_compressed_image(data: bytes) -> VideoFrame:
    """从小端 CompressedImage CDR 提取 header、format 和压缩载荷。

    Args:
        data: 完整 CDR 字节，封装标识必须为 00 01，消息类型为 CompressedImage。

    Returns:
        未修改压缩载荷的帧，时间为源 header 的纳秒。

    Raises:
        ValueError: CDR 封装、字段长度、字符串或纳秒范围非法。

    Side Effects:
        无。

    Time Semantics:
        不读取时钟，不重排消息；负秒按 ROS 的有符号秒保留。
    """
    try:
        reader = _CdrReader(data)
        sec, nsec = struct.unpack_from("<iI", reader.data)
        if nsec >= NANOSECONDS_PER_SECOND:
            raise ValueError("header 纳秒超出范围")
        reader.offset = 8
        return VideoFrame(
            int(sec) * NANOSECONDS_PER_SECOND + int(nsec),
            reader.string(),
            reader.string(),
            reader.block(),
        )
    except (struct.error, UnicodeError) as error:
        raise ValueError("CompressedImage CDR 无效") from error


def patch_sps(data: bytes) -> tuple[bytes, bytes | None]:
    """清除 Annex B 内所有 SPS 的 set5 声明位，其余字节逐字节保留。

    Args:
        data: 一帧 Annex B H.264，允许三或四字节起始码。

    Returns:
        修正后的整帧和首个 SPS 的三个编解码器字节；无 SPS 时第二项为 None。

    Raises:
        无。

    Side Effects:
        无；不修改输入字节。

    Time Semantics:
        只处理当前帧，不缓存 GOP，也不等待下一关键帧。
    """
    patched: bytearray | None = None
    first: bytes | None = None
    start = data.find(b"\x00\x00\x01")
    while start >= 0 and start + 6 < len(data):
        nal = start + 3
        if data[nal] & 0x1F == 7:
            # Lichtblick 1.30.0 错把 set5 放在保留位；只清声明，不改编码内容。
            if patched is None:
                patched = bytearray(data)
            patched[nal + 2] &= 0xFB
            if first is None:
                first = bytes(patched[nal + 1 : nal + 4])
        start = data.find(b"\x00\x00\x01", nal)
    return (data if patched is None else bytes(patched)), first


def codec_standard(sps: bytes) -> str:
    """按 H.264 标准得到 avc1 编解码器字符串。

    Args:
        sps: SPS 去掉 NAL 头后的前三字节，依次是 profile、约束、level。

    Returns:
        大写十六进制的 avc1.PPCCLL。

    Raises:
        ValueError: 输入不是恰好三个字节。

    Side Effects:
        无。

    Time Semantics:
        无；不读取或生成时间戳。
    """
    if len(sps) != 3:
        raise ValueError("SPS 编解码器头必须为三个字节")
    return "avc1." + sps.hex().upper()


def codec_lichtblick(sps: bytes) -> str:
    """复现 Lichtblick 1.30.0 的编解码器字符串算法，用于运行时自检。

    Args:
        sps: SPS 去掉 NAL 头后的三个字节，长度必须为 3。

    Returns:
        将 constraint_set5_flag 左移 1 位时的 avc1.PPCCLL。

    Raises:
        ValueError: SPS 头不是三个字节。

    Side Effects:
        无；本函数保留前端缺陷用于比较，不修正输入。

    Time Semantics:
        无；与关键帧到达时刻无关。
    """
    if len(sps) != 3:
        raise ValueError("SPS 编解码器头必须为三个字节")
    flags = (sps[1] & 0xF8) | ((sps[1] & 0x04) >> 1)
    return f"avc1.{sps[0]:02X}{flags:02X}{sps[2]:02X}"
