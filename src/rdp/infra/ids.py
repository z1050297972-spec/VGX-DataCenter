"""基础层的请求、作业和错误编号规则（M0 工单 06 前置搬移）。

Python、OpenAPI 与表模型复用同一编号声明；只依赖标准库 re 和 typing，
不读取输入载荷，不依赖数据库或日志，不读取上下文或生成编号。
"""

import re
from typing import Literal

# SQLite 有符号 64 位整数上限；作业编号文本的范围与 SQLite INTEGER 一致。
MAX_SQLITE_INTEGER = (1 << 63) - 1
# uuid4.hex 的固定长度，无单位；去掉 UUID 的分隔符后为 32 个十六进制字符。
REQUEST_ID_HEX_LENGTH = 32
# v4 版本位和 RFC variant 位必须有效；核心不带锚点，供不同编号模式组合。
REQUEST_ID_CORE = r"[0-9a-f]{12}4[0-9a-f]{3}[89ab][0-9a-f]{15}"
# 加锚点供 Pydantic/OpenAPI 复用，保持原有完整请求编号模式。
REQUEST_ID_PATTERN = f"^{REQUEST_ID_CORE}$"
# 作业号形状先限定十进制位数，再由 MAX_SQLITE_INTEGER 检查上界；拒绝前导零。
JOB_ID_PATTERN = rf"[1-9][0-9]{{0,{len(str(MAX_SQLITE_INTEGER)) - 1}}}"
ERROR_ID_PATTERN = f"^({REQUEST_ID_CORE}|{JOB_ID_PATTERN})$"


def is_request_id(identifier: object) -> bool:
    """判断一个值是否是服务端请求编号。

    Args:
        identifier: 任意待校验值，无单位；仅接受 32 位小写 uuid4 hex 字符串。

    Returns:
        合法请求编号为 True；非字符串、空值、格式或版本位不合法为 False。

    Raises:
        无。

    Side Effects:
        无；不回显原值，不读取上下文或生成编号。

    Time Semantics:
        同步校验，无时钟读取、等待或重试。
    """
    return isinstance(identifier, str) and re.fullmatch(REQUEST_ID_PATTERN, identifier) is not None


def error_source_kind(identifier: str) -> Literal["request", "job"] | None:
    """按互斥的 E2 编号格式识别来源。

    Args:
        identifier: 待校验字符串，无单位；允许空串或任意非法内容，原值不回显。

    Returns:
        合法 uuid4 hex 返回 request；1 至 MAX_SQLITE_INTEGER 的规范十进制编号返回 job；
        其他字符串返回 None，不修剪空白或转换前导零。

    Raises:
        无。

    Side Effects:
        无；不查询数据库、上下文或日志。

    Time Semantics:
        同步校验，无时钟读取、等待或重试。
    """
    if is_request_id(identifier):
        return "request"
    if re.fullmatch(JOB_ID_PATTERN, identifier) and int(identifier) <= MAX_SQLITE_INTEGER:
        return "job"
    return None
