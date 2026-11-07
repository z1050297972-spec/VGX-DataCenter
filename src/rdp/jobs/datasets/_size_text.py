"""大小说明的纯规则（领域层，M1.5-17），不读文件或时钟。

用标准库 decimal 和 re 实现约定格式，不依赖显示文案猜测其他大小单位。
"""

import json
import re
from collections.abc import Iterator
from datetime import date
from decimal import Decimal
from typing import cast

from rdp.jobs.datasets.types import JsonValue

# 工单指定十进制 GB/TB；只认中文左括号到字节分号的片段。
_GB_BYTES = 1_000_000_000
_TB_BYTES = 1_000_000_000_000
_BYTES = re.compile(r"（([0-9]+|[0-9]{1,3}(?:,[0-9]{3})+) B；")


def format_size_text(size_bytes: int, local_date: date) -> str:
    """将非负整数字节数和调用方提供的本地统计日期格式化为第4项文字。"""
    size = Decimal(size_bytes)
    return (
        f"{size / _GB_BYTES:.2f} GB / {size / _TB_BYTES:.2f} TB（{size_bytes:,} B；"
        f"LeRobot 只计 parquet、mp4 和 meta，其他格式计全部文件；统计于 {local_date.isoformat()}）"
    )


def parse_size_bytes(text: str) -> int | None:
    """只解析约定字节片段；旧自由文字返回 None，触发首次同步。"""
    match = _BYTES.search(text)
    return int(match[1].replace(",", "")) if match else None


def replace_size_text(content: bytes, size_bytes: int, local_date: date) -> bytes | None:
    """只替换第4项字符串的原始区间；相等或没有合法第4项时不写。

    标准 json 编解码负责字符串转义；raw_decode 给出值的结束位置，避免整份重序列化
    改掉未知字段、空白和数字写法。没有现成库能在现有依赖内完成原文局部替换。

    Returns:
        局部替换后的 UTF-8 原文；无须更新或缺合法第4项时为 None。
    """
    text = content.decode("utf-8")
    decoder = json.JSONDecoder()
    for key, start, _end in _members(text, 0):
        if key != "fields" or text[start] != "[":
            continue
        position = start + 1
        while True:
            position = _skip(text, position)
            if text[position] == "]":
                return None
            decoded, end = decoder.raw_decode(text, position)
            value = cast(JsonValue, decoded)
            if (
                isinstance(value, dict)
                and value.get("number") == 4
                and value.get("name") == "数据大小"
            ):
                for name, left, right in _members(text, position):
                    if name != "value_markdown":
                        continue
                    previous = value.get(name)
                    if not isinstance(previous, str) or parse_size_bytes(previous) == size_bytes:
                        return None
                    replacement = json.dumps(
                        format_size_text(size_bytes, local_date), ensure_ascii=False
                    )
                    return (text[:left] + replacement + text[right:]).encode("utf-8")
                return None
            position = end
    return None


def _skip(text: str, position: int) -> int:
    """跳过已验证 JSON 的空白和成员分隔符，不解释字符串内部内容。"""
    while text[position] in " \r\n\t,":
        position += 1
    return position


def _members(text: str, start: int) -> Iterator[tuple[str, int, int]]:
    """遍历对象直接成员的值区间；嵌套值由标准解码器整体跳过。"""
    decoder = json.JSONDecoder()
    position = _skip(text, start) + 1
    while True:
        position = _skip(text, position)
        if text[position] == "}":
            return
        key, position = decoder.raw_decode(text, position)
        position = _skip(text, position)
        position = _skip(text, position + 1)
        _, end = decoder.raw_decode(text, position)
        yield key, position, end
        position = end
