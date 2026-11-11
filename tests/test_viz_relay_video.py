"""M5-03 编解码器字符串验收，期望值直接来自工单。"""

import pytest

from rdp.robot_side.viz_relay.video import codec_lichtblick, codec_standard


@pytest.mark.parametrize(
    ("sps", "standard", "lichtblick"),
    [
        (b"\x64\x0c\x33", "avc1.640C33", "avc1.640A33"),
        (b"\x64\x08\x33", "avc1.640833", "avc1.640833"),
    ],
)
def test_codec_strings(sps: bytes, standard: str, lichtblick: str) -> None:
    """验收 2：分别复现标准算法和 Lichtblick 1.30.0 的 set5 位移缺陷。"""
    assert codec_standard(sps) == standard
    assert codec_lichtblick(sps) == lichtblick
