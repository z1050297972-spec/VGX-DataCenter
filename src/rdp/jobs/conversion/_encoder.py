"""把登记工具配置换算为删除脚本参数，不探测编码器或修改视频元数据。

配置解析复用清洗模块；LeRobot 自带换算与工具的 NVENC 规则不同，故按 config.rs
的 VideoConfig.codec_options 保留分支和插入顺序。
标准库 JSON 会把小指数写成 1e-07，故复用已有 Pydantic 的 Rust 序列化器生成值文本。
"""

from typing import TypedDict

from pydantic import JsonValue, TypeAdapter

from rdp.jobs.cleaning._config import ToolConfig

# 与清洗配置共用 JsonValue 类型，保留整数/浮点区别和 Rust 的指数写法。
_JSON_VALUE = TypeAdapter(JsonValue)


class EncoderParameters(TypedDict):
    """跨进程编码参数；options 按工具顺序插入，所有选项值都是字符串。"""

    vcodec: str
    pix_fmt: str
    options: dict[str, str]


def encoder_parameters(config: ToolConfig) -> EncoderParameters:
    """按工具规则换算已解析的登记配置，不使用 info.json 推断编码器。

    Args:
        config: 转换命令所用配置经清洗解析器校验后的对象，视频默认值已补齐。

    Returns:
        编码器名、像素格式及有序选项表；g 优先，其余依 config.rs 分支顺序。
        字符串原样保留，JSON 数字保留整数和浮点区别，不附加设备或线程选项。

    Raises:
        无。

    Side Effects:
        无。

    Time Semantics:
        纯配置换算，不读取时钟，也不处理视频时间戳。
    """
    video = config.video
    options: dict[str, str] = {}

    def set_option(key: str, value: JsonValue) -> None:
        if value is not None:
            options[key] = (
                value if isinstance(value, str) else _JSON_VALUE.dump_json(value).decode()
            )

    # config.rs 先写通用 GOP，再写编码器专用参数；dict 保持同样的插入顺序。
    set_option("g", video.g)
    match video.vcodec:
        case "libsvtav1":
            set_option("crf", video.crf)
            set_option("preset", video.preset)
            # 工具把 fast_decode 限制在 0-2，零值也显式写出。
            set_option("svtav1-params", f"fast-decode={min(video.fast_decode, 2)}")
        case "h264" | "hevc" | "libx264" | "libx265":
            set_option("crf", video.crf)
            set_option("preset", video.preset)
            if video.fast_decode > 0:
                set_option("tune", "fastdecode")
        case "h264_nvenc" | "hevc_nvenc" | "av1_nvenc":
            # 工具禁用 B 帧，保证 g=2 等短 GOP 可以初始化并便于随机读取。
            set_option("bf", "0")
            set_option("rc", "constqp" if video.crf is not None else None)
            set_option("qp", video.crf)
            set_option("preset", video.preset)
        case "h264_vaapi" | "hevc_vaapi" | "av1_vaapi":
            set_option("qp", video.crf)
        case "h264_qsv" | "hevc_qsv" | "av1_qsv":
            set_option("global_quality", video.crf)
            set_option("preset", video.preset)
        case _:
            set_option("crf", video.crf)
            set_option("preset", video.preset)
    return {"vcodec": video.vcodec, "pix_fmt": video.pix_fmt, "options": options}
