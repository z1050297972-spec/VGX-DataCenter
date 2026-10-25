"""基础层公开的编号规则和安全字段诊断，供数据库、日志和入口共同使用。

Python、OpenAPI 与表模型的编号声明集中在此；迁移脚本冻结历史 CHECK，
由建表 SQL 一致性测试防止漂移。不读取输入载荷，不连接数据库或记录日志。
"""

import re
from typing import Literal

from rdp.infra.diagnostics import (
    Diagnostic,
    DiagnosticCategory,
    DiagnosticLevel,
    DiagnosticObject,
    InputError,
)

# SQLite 有符号 64 位整数上限；作业编号文本的范围与 SQLite INTEGER 一致。
MAX_SQLITE_INTEGER = (1 << 63) - 1
# uuid4.hex 的固定长度，无单位；去掉 UUID 的分隔符后为 32 个十六进制字符。
REQUEST_ID_HEX_LENGTH = 32
# v4 版本位和 RFC variant 位必须有效；加锚点供 Pydantic/OpenAPI 复用。
REQUEST_ID_PATTERN = r"^[0-9a-f]{12}4[0-9a-f]{3}[89ab][0-9a-f]{15}$"
# 作业号形状先限定十进制位数，再由 MAX_SQLITE_INTEGER 检查上界；拒绝前导零。
JOB_ID_PATTERN = rf"[1-9][0-9]{{0,{len(str(MAX_SQLITE_INTEGER)) - 1}}}"
ERROR_ID_PATTERN = f"^({REQUEST_ID_PATTERN[1:-1]}|{JOB_ID_PATTERN})$"
# SQLite 不依赖自定义 REGEXP 函数，用原生 CHECK 表达同一编号规则，便于独立打开备份。
ERROR_SOURCE_CHECK_SQL = (
    f"(source_kind = 'request' AND length(error_id) = {REQUEST_ID_HEX_LENGTH} "
    "AND error_id NOT GLOB '*[^0-9a-f]*' AND substr(error_id,13,1) = '4' "
    "AND substr(error_id,17,1) IN ('8','9','a','b')) OR "
    "(source_kind = 'job' AND CAST(error_id AS INTEGER) > 0 "
    "AND CAST(CAST(error_id AS INTEGER) AS TEXT) = error_id)"
)


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


def invalid_field(field: str, expected: str) -> InputError:
    """构造不回显载荷的输入问题，供 UTC 和报错字段的共同边界使用。

    Args:
        field: 安全的字段名，非空白字符串，无单位；不能传字段原值。
        expected: 字段应满足的规则，非空白安全文本，无单位。

    Returns:
        含字段身份、规则、实际占位、期望、拒绝后果及修正建议的 InputError；调用者负责抛出。

    Raises:
        ValueError: 字段名或期望为空白等导致诊断模型校验失败；不回显输入载荷。

    Side Effects:
        无；不修改输入、不记日志、不抛返回的异常。

    Time Semantics:
        同步构造，不读时钟或等待。
    """
    return InputError(
        (
            Diagnostic(
                level=DiagnosticLevel.ERROR,
                category=DiagnosticCategory.INPUT,
                stage="数据库校验",
                source="平台",
                objects=(DiagnosticObject(key="field", value=field),),
                rule="数据库字段必须符合声明",
                actual="字段格式或范围不合法（原值不回显）",
                expected=expected,
                consequence="本次操作被拒绝，未提交数据",
                next_step="修正输入；存量数据异常时核实数据库与备份",
            ),
        )
    )
