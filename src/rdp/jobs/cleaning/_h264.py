"""逐条重写 h264.rs 的 Annex-B 头部判断，不解码画面、不调用视频工具。

现有依赖没有工具的最小 slice 检查；仅扫描起始码和前 16 字节，避免引入完整解码器。
"""

from collections.abc import Iterator
from dataclasses import dataclass


def nal_units(data: bytes) -> Iterator[memoryview]:
    """按 00 00 01 分割，非最后一个 NAL 去尾零，兼容四字节起始码。"""
    view = memoryview(data)
    start = data.find(b"\x00\x00\x01")
    while start >= 0:
        start += 3
        next_start = data.find(b"\x00\x00\x01", start)
        end = len(data) if next_start < 0 else next_start
        if next_start >= 0:
            while end > start and data[end - 1] == 0:
                end -= 1
        if end > start:
            yield view[start:end]
        start = next_start


def is_keyframe(data: bytes) -> bool:
    """任一 NAL 类型为 5 即为 IDR，与工具一致。"""
    return any(nal[0] & 0x1F == 5 for nal in nal_units(data))


def has_b_slice(data: bytes) -> bool:
    """slice_type 模 5 为 1 即 B slice；截断位串和工具一样返回未检出。"""
    return any(
        (kind := _slice_type(nal)) is not None and kind % 5 == 1
        for nal in nal_units(data)
        if nal[0] & 0x1F in (1, 5)
    )


def _slice_type(nal: memoryview) -> int | None:
    """只取 NAL 头之后 16 字节，去掉 00 00 03 防竞争字节后读两个 ue(v)。"""
    rbsp = bytearray()
    for value in nal[1:17]:
        if value == 3 and rbsp.endswith(b"\x00\x00"):
            continue
        rbsp.append(value)
    bits = "".join(f"{value:08b}" for value in rbsp)
    first = _ue(bits, 0)
    second = _ue(bits, first[1]) if first is not None else None
    return second[0] if second is not None else None


def _ue(bits: str, position: int) -> tuple[int, int] | None:
    """读取无符号指数哥伦布值，前导零上限 31 与 Rust 一致。"""
    end = bits.find("1", position)
    zeros = end - position
    if end < 0 or zeros > 31 or end + zeros >= len(bits):
        return None
    suffix = bits[end + 1 : end + 1 + zeros]
    value = (1 << zeros) - 1 + (int(suffix, 2) if suffix else 0)
    return value, end + 1 + zeros


@dataclass
class KeyframeGate:
    """每文件、每视频话题独立的关键帧门。

    Attributes:
        started: 是否已经遇到第一个 IDR；默认 False。
    """

    started: bool = False

    def accept(self, data: bytes) -> bool:
        """首个 IDR 及之后全部接受，之前的帧不能参与对齐。"""
        self.started = self.started or is_keyframe(data)
        return self.started
