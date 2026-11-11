"""工单 07 的编码换算契约；期望参数取自登记工具 config.rs，不调用真实编码器。"""

from typing import TypedDict

import pytest
from pydantic import JsonValue

from rdp.jobs.cleaning._config import ToolConfig
from rdp.jobs.conversion._encoder import encoder_parameters


class EncoderCase(TypedDict):
    """工具视频配置及按 config.rs 独立列出的有序参数。"""

    video: dict[str, JsonValue]
    codec: str
    options: list[tuple[str, str]]


@pytest.mark.parametrize(
    "case",
    [
        EncoderCase(
            video={"vcodec": "hevc_nvenc", "crf": 30},
            codec="hevc_nvenc",
            options=[("g", "2"), ("bf", "0"), ("rc", "constqp"), ("qp", "30")],
        ),
        EncoderCase(
            video={},
            codec="libsvtav1",
            options=[
                ("g", "2"),
                ("crf", "30"),
                ("preset", "12"),
                ("svtav1-params", "fast-decode=0"),
            ],
        ),
        EncoderCase(
            video={"vcodec": "libx265", "fast_decode": 1},
            codec="libx265",
            options=[("g", "2"), ("crf", "30"), ("tune", "fastdecode")],
        ),
        EncoderCase(
            video={"vcodec": "hevc_nvenc", "crf": 30.0},
            codec="hevc_nvenc",
            options=[("g", "2"), ("bf", "0"), ("rc", "constqp"), ("qp", "30.0")],
        ),
    ],
    ids=["r1lite", "svtav1-defaults", "x265-fastdecode", "float-crf"],
)
def test_encoder_parameters_match_tool(case: EncoderCase) -> None:
    """范围1：复用 ToolConfig 默认值，保持参数顺序、fast_decode 和整数/浮点文本区别。"""
    config = ToolConfig.model_validate(
        {
            "fps": 30,
            "sync": {"reference_topic": "/camera", "max_dt_ms": 10},
            "feature": [{"name": "image", "type": "video", "topic": "/camera"}],
            "video": case["video"],
        }
    )
    actual = encoder_parameters(config)
    assert actual["vcodec"] == case["codec"]
    assert actual["pix_fmt"] == "yuv420p"
    assert list(actual["options"].items()) == case["options"]
