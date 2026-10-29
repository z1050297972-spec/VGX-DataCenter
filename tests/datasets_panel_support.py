"""面板契约的公开读取边界；每次只读测试临时导航，不复用生产私有判断。"""

from datasets_support import checkpoint
from nav_manifest import FakeNavigation

from rdp.infra.diagnostics import DiagnosticLevel
from rdp.jobs.datasets.reading import discover_entries, read_entry
from rdp.jobs.datasets.types import EntrySnapshot, Finding, PanelGroup, PanelSeverity


def entries(nav: FakeNavigation, name: str = "libero_10") -> tuple[EntrySnapshot, ...]:
    """按目录名从公开发现接口取得两个视图快照，保留文件原样。"""
    return tuple(
        read_entry(nav.nav_root, item, checkpoint=checkpoint)
        for item in discover_entries(nav.nav_root).entries
        if item.dataset_name == name
    )


def assert_finding(
    findings: tuple[Finding, ...], rule: str, path: str, *, group: PanelGroup = PanelGroup.JSON
) -> Finding:
    """独立核对规则码、对象、级别和五段结构，不对整段说明做快照。"""
    selected = [item for item in findings if item.diagnostic.rule == rule]
    assert selected, (rule, findings)
    item = selected[0]
    assert item.group is group
    assert item.severity is PanelSeverity.ACTION_REQUIRED
    assert item.diagnostic.level is DiagnosticLevel.ERROR
    assert any(obj.key == "entry_path" and obj.value == path for obj in item.diagnostic.objects)
    assert item.diagnostic.actual and item.diagnostic.expected
    assert item.diagnostic.consequence and item.diagnostic.next_step
    return item
