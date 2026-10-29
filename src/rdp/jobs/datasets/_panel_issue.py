"""面板五段诊断构造；只处理已读取身份与字段差异，不读取路径或决定作业结果。"""

from rdp.infra.diagnostics import Diagnostic, DiagnosticCategory, DiagnosticLevel, DiagnosticObject
from rdp.jobs.datasets.types import EntrySnapshot, Finding, PanelGroup, PanelSeverity

# 诊断仅显示一个字段的短预览，单位字符；避免超大JSON值令每个有界样例仍占用大量内存。
VALUE_PREVIEW_CHARS = 256


def difference(
    entry: EntrySnapshot,
    rule: str,
    detail: tuple[str, object, object],
    *,
    group: PanelGroup = PanelGroup.JSON,
    notice: bool = False,
) -> Finding:
    """保留入口、数据集和字段身份，正文不回显整份载荷。"""
    field, actual, expected = detail
    objects = (DiagnosticObject(key="entry_path", value=str(entry.location.path)),)
    if entry.dataset_id is not None:
        objects += (DiagnosticObject(key="dataset_id", value=entry.dataset_id),)
    objects += (DiagnosticObject(key="field", value=field),)
    return Finding(
        group,
        PanelSeverity.NOTICE if notice else PanelSeverity.ACTION_REQUIRED,
        Diagnostic(
            level=DiagnosticLevel.WARNING if notice else DiagnosticLevel.ERROR,
            category=DiagnosticCategory.INPUT,
            stage="检查导航一致性",
            source="平台",
            objects=objects,
            rule=rule,
            actual=_preview(actual),
            expected=_preview(expected),
            consequence="保留入口展示；有规范副本时以规范副本为准，不自动修改导航",
            next_step="核对指定入口和字段，修正后重新扫描",
        ),
    )


def _preview(value: object) -> str:
    """省略标记明确说明诊断预览被截短，完整文件仍由导航提供。"""
    rendered = repr(value)
    return (
        rendered if len(rendered) <= VALUE_PREVIEW_CHARS else rendered[:VALUE_PREVIEW_CHARS] + "…"
    )
