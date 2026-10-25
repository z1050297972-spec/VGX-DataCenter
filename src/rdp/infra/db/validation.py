"""基础层数据库的编号 CHECK 与安全字段诊断（M0 工单 05、06 前置搬移）。

编号格式来自 rdp.infra.ids；迁移脚本冻结历史 CHECK，由建表 SQL 一致性测试防止漂移。
只声明数据库约束和构造诊断，不读取输入载荷，不连接数据库或记录日志。
"""

from rdp.infra.diagnostics import (
    Diagnostic,
    DiagnosticCategory,
    DiagnosticLevel,
    DiagnosticObject,
    InputError,
)
from rdp.infra.ids import REQUEST_ID_HEX_LENGTH

# SQLite 不依赖自定义 REGEXP 函数，用原生 CHECK 表达同一编号规则，便于独立打开备份。
ERROR_SOURCE_CHECK_SQL = (
    f"(source_kind = 'request' AND length(error_id) = {REQUEST_ID_HEX_LENGTH} "
    "AND error_id NOT GLOB '*[^0-9a-f]*' AND substr(error_id,13,1) = '4' "
    "AND substr(error_id,17,1) IN ('8','9','a','b')) OR "
    "(source_kind = 'job' AND CAST(error_id AS INTEGER) > 0 "
    "AND CAST(CAST(error_id AS INTEGER) AS TEXT) = error_id)"
)


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
