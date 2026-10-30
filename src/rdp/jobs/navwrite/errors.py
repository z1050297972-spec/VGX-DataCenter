"""写导航层底座的五段诊断构造（领域层，M1-07）；只组装异常，不记日志、不改作业结果。

诊断文本只含路径、编号、哈希前缀等可公开的短字段，从不回显文件正文（规范 6.6）。
"""

from typing import NamedTuple

from rdp.infra.diagnostics import (
    ConflictError,
    Diagnostic,
    DiagnosticCategory,
    DiagnosticLevel,
    DiagnosticObject,
    ExternalError,
    InputError,
)

_STAGE = "写导航层"
_SOURCE = "平台"
# 诊断里单个对象值的字符上限，避免把长路径或差异列表整段塞进一个对象。
_OBJECT_VALUE_LIMIT = 512


class Advice(NamedTuple):
    """后果与下一步，两段文字成对给出，覆盖各类异常的默认说法。

    Attributes:
        consequence: 这次失败的后果，非空。
        next_step: 建议的下一步，非空。
    """

    consequence: str
    next_step: str


_DEFAULT_INPUT = Advice("这次写入没有开始，导航层一行都没写", "核对输入后重新预览")
_DEFAULT_CONFLICT = Advice("导航层一行都没写", "重新预览后再提交")
_DEFAULT_EXTERNAL = Advice("这一步没有完成", "检查状态目录与导航层所在磁盘后重试")


def _diagnostic(
    category: DiagnosticCategory,
    rule: str,
    actual: str,
    advice: Advice,
    detail: tuple[str | None, tuple[tuple[str, str], ...]],
) -> Diagnostic:
    """按统一口径组装一条错误级诊断（detail 为期望值和对象），对象值截到上限。"""
    expected, objects = detail
    return Diagnostic(
        level=DiagnosticLevel.ERROR,
        category=category,
        stage=_STAGE,
        source=_SOURCE,
        objects=tuple(
            DiagnosticObject(key=key, value=value[:_OBJECT_VALUE_LIMIT] or "-")
            for key, value in objects
        ),
        rule=rule,
        actual=actual,
        expected=expected,
        consequence=advice.consequence,
        next_step=advice.next_step,
    )


def nav_input_error(
    rule: str,
    actual: str,
    *,
    expected: str | None = None,
    objects: tuple[tuple[str, str], ...] = (),
    advice: Advice | None = None,
) -> InputError:
    """构造输入或数据类异常，调用方 `raise` 它。

    Args:
        rule: 稳定的规则码，英文，不嵌入文件名或实测值。
        actual: 实际情况，中文，不回显文件正文。
        expected: 期望情况；没有可比较的期望为 None。
        objects: 涉及的对象，键唯一的 (键, 值) 元组；值超过 512 字符被截断。
        advice: 后果与下一步；省略时用该类别的默认说法。

    Returns:
        InputError，诊断恰好一条，来源"平台"，阶段"写导航层"。

    Raises:
        ValidationError: 对象键重复或文本为空白（调用方缺陷，诊断模型拒绝）。

    Side Effects:
        无；只构造异常，不记日志。

    Time Semantics:
        同步纯函数，无时钟、无 I/O。
    """
    detail = (expected, objects)
    return InputError(
        (_diagnostic(DiagnosticCategory.INPUT, rule, actual, advice or _DEFAULT_INPUT, detail),)
    )


def nav_conflict_error(
    rule: str,
    actual: str,
    *,
    expected: str | None = None,
    objects: tuple[tuple[str, str], ...] = (),
    advice: Advice | None = None,
) -> ConflictError:
    """构造冲突类异常，调用方 `raise` 它。

    Args:
        rule: 稳定的规则码，英文，不嵌入文件名或实测值。
        actual: 实际情况，中文，不回显文件正文。
        expected: 期望情况；没有可比较的期望为 None。
        objects: 涉及的对象，键唯一的 (键, 值) 元组；值超过 512 字符被截断。
        advice: 后果与下一步；省略时用该类别的默认说法。

    Returns:
        ConflictError，诊断恰好一条，来源"平台"，阶段"写导航层"。

    Raises:
        ValidationError: 对象键重复或文本为空白（调用方缺陷，诊断模型拒绝）。

    Side Effects:
        无；只构造异常，不记日志。

    Time Semantics:
        同步纯函数，无时钟、无 I/O。
    """
    detail = (expected, objects)
    return ConflictError(
        (
            _diagnostic(
                DiagnosticCategory.CONFLICT, rule, actual, advice or _DEFAULT_CONFLICT, detail
            ),
        )
    )


def nav_external_error(
    rule: str,
    actual: str,
    *,
    expected: str | None = None,
    objects: tuple[tuple[str, str], ...] = (),
    advice: Advice | None = None,
) -> ExternalError:
    """构造外部失败类异常，调用方 `raise` 它。

    Args:
        rule: 稳定的规则码，英文，不嵌入文件名或实测值。
        actual: 实际情况，中文，不回显文件正文。
        expected: 期望情况；没有可比较的期望为 None。
        objects: 涉及的对象，键唯一的 (键, 值) 元组；值超过 512 字符被截断。
        advice: 后果与下一步；省略时用该类别的默认说法。

    Returns:
        ExternalError，诊断恰好一条，来源"平台"，阶段"写导航层"。

    Raises:
        ValidationError: 对象键重复或文本为空白（调用方缺陷，诊断模型拒绝）。

    Side Effects:
        无；只构造异常，不记日志。

    Time Semantics:
        同步纯函数，无时钟、无 I/O。
    """
    detail = (expected, objects)
    return ExternalError(
        (
            _diagnostic(
                DiagnosticCategory.EXTERNAL, rule, actual, advice or _DEFAULT_EXTERNAL, detail
            ),
        )
    )
