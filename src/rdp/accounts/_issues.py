"""账号领域的安全诊断构造，复用基础层四类异常，不接收凭据或记录日志。"""

from rdp.infra.diagnostics import (
    ConflictError,
    DefectError,
    Diagnostic,
    DiagnosticLevel,
    DiagnosticObject,
    ExternalError,
    InputError,
)


def problem[T: InputError | ConflictError | ExternalError | DefectError](
    kind: type[T],
    detail: str,
    *,
    field: str = "账号",
    expected: str = "符合账号操作的前置条件",
    account_id: int | None = None,
) -> T:
    """用调用点固定的安全文本构造五段诊断，不回显字段原值。"""
    return kind(
        (
            Diagnostic(
                level=DiagnosticLevel.ERROR,
                category=kind.category,
                stage="账号",
                source="平台",
                objects=(DiagnosticObject(key="field", value=field),)
                if account_id is None
                else (DiagnosticObject(key="account_id", value=str(account_id)),),
                rule="账号操作须满足前置条件",
                actual=detail,
                expected=expected,
                consequence="本次请求的账号操作未完成",
                next_step="对照诊断修正后重试",
            ),
        )
    )
