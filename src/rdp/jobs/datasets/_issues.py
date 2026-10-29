"""数据集内部五段诊断构造；只补对象和后果，不记录日志或改变作业结果。"""

from rdp.infra.diagnostics import (
    Diagnostic,
    DiagnosticCategory,
    DiagnosticLevel,
    DiagnosticObject,
    ExternalError,
    InputError,
)
from rdp.jobs.datasets.types import Finding, PanelGroup, PanelSeverity


def finding(path: str, rule: str, actual: str, *, notice: bool = False) -> Finding:
    """为导航读取问题提供稳定规则及有界、可公开的上下文，不回显文件全文。"""
    return Finding(
        PanelGroup.JSON,
        PanelSeverity.NOTICE if notice else PanelSeverity.ACTION_REQUIRED,
        Diagnostic(
            level=DiagnosticLevel.WARNING if notice else DiagnosticLevel.ERROR,
            category=DiagnosticCategory.INPUT,
            stage="读取导航层",
            source="平台",
            objects=(DiagnosticObject(key="entry_path", value=path),),
            rule=rule,
            actual=actual,
            expected="导航文件符合已登记的读取契约",
            consequence="保留入口展示；相关字段或检查结果不可用",
            next_step="核对该入口的文件或目录后重新扫描",
        ),
    )


def input_error(path: str, actual: str) -> InputError:
    """将路径或预算错误归入既有输入异常，避免另建异常体系。"""
    return InputError((finding(path, "NAV_INPUT", actual).diagnostic,))


def external_error(path: str, actual: str) -> ExternalError:
    """不可枚举整个导航是外部失败，诊断类别必须与异常基类一致。"""
    issue = finding(path, "NAV_UNREADABLE", actual).diagnostic
    diagnostic = Diagnostic.model_validate(
        issue.model_dump() | {"category": DiagnosticCategory.EXTERNAL}
    )
    return ExternalError((diagnostic,))
