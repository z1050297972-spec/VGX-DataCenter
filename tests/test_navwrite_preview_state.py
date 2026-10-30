"""预览状态的契约测试（M1-07，L12）：记录与核对。

三样状态各改一处都必须以冲突失败，并且一行都没写。假导航层只在 pytest 临时目录里。
"""

import shutil
from pathlib import Path

import pytest
from nav_manifest import FakeNavigation
from navwrite_support import dataset_id_of, noop, tree_state

from rdp.infra.diagnostics import ConflictError, InputError
from rdp.jobs.datasets.fingerprint import FileState
from rdp.jobs.errors import JobCancelledError
from rdp.jobs.navwrite.errors import nav_conflict_error
from rdp.jobs.navwrite.models import PreviewState
from rdp.jobs.navwrite.preview_state import (
    capture_preview_state,
    diff_preview_state,
    verify_preview_state,
)

NAME = "EgoProDemo"


def _capture(fake_nav: FakeNavigation, name: str = NAME) -> PreviewState:
    """记下某个数据集的预览状态。"""
    return capture_preview_state(
        fake_nav.nav_root, (dataset_id_of(fake_nav, name),), None, checkpoint=noop
    )


def _assert_conflict_writes_nothing(
    fake_nav: FakeNavigation, state: PreviewState, mutate: None = None
) -> ConflictError:
    """核对必须以冲突失败，且核对本身没有改动导航层。"""
    before = tree_state(fake_nav.nav_root)
    with pytest.raises(ConflictError) as caught:
        verify_preview_state(fake_nav.nav_root, state, checkpoint=noop)
    assert tree_state(fake_nav.nav_root) == before
    return caught.value


def test_capture_includes_all_entries_and_provenance(fake_nav: FakeNavigation) -> None:
    """L12：capture_preview_state 对数据集的按任务入口和全部按格式入口各记一份指纹，来源.json 缺失也占一项。"""
    state = _capture(fake_nav)
    assert state.nav_root == str(fake_nav.nav_root) and state.new_dataset is None
    (fingerprint,) = state.datasets
    assert fingerprint.dataset_id == dataset_id_of(fake_nav, NAME) and fingerprint.verifiable
    assert [e.path for e in fingerprint.entries] == [
        "按任务/EgoProDemo",
        "按格式/lerobot/3.0/EgoProDemo",
    ]
    for entry in fingerprint.entries:
        provenance = next(f for f in entry.json_files if f.name == "来源.json")
        assert provenance.state is FileState.MISSING
    both = capture_preview_state(
        fake_nav.nav_root,
        (dataset_id_of(fake_nav, "libero_10"), dataset_id_of(fake_nav, NAME)),
        None,
        checkpoint=noop,
    )
    assert len(both.datasets) == 2
    ids = [d.dataset_id for d in both.datasets]
    assert ids == sorted(ids, key=str)


def test_capture_new_dataset_records_destination_and_max_number(fake_nav: FakeNavigation) -> None:
    """L12：新增数据集另记目的目录不存在和当时的最大编号。"""
    state = capture_preview_state(fake_nav.nav_root, (), "按任务/新数据集", checkpoint=noop)
    assert state.datasets == ()
    assert state.new_dataset is not None
    assert state.new_dataset.destination_path == "按任务/新数据集"
    assert state.new_dataset.destination_absent is True
    assert state.new_dataset.max_number == 35  # 假导航层里最大的是 dataset-35
    taken = capture_preview_state(fake_nav.nav_root, (), "按任务/EgoProDemo", checkpoint=noop)
    assert taken.new_dataset is not None and taken.new_dataset.destination_absent is False


def test_capture_unknown_dataset_is_input_error(fake_nav: FakeNavigation) -> None:
    """契约 capture_preview_state：编号在导航层找不到入口时报 InputError。"""
    with pytest.raises(InputError):
        capture_preview_state(fake_nav.nav_root, ("dataset-999",), None, checkpoint=noop)


def test_verify_passes_when_nothing_changed(fake_nav: FakeNavigation) -> None:
    """契约 verify_preview_state：状态没变时通过，且不写任何文件。"""
    state = _capture(fake_nav)
    before = tree_state(fake_nav.nav_root)
    verify_preview_state(fake_nav.nav_root, state, checkpoint=noop)
    assert diff_preview_state(fake_nav.nav_root, state, checkpoint=noop) == ()
    assert tree_state(fake_nav.nav_root) == before


def test_verify_conflicts_when_json_hash_changes(fake_nav: FakeNavigation) -> None:
    """L12 验收（样一）：改动入口里一份 JSON 的内容（哪怕只多一个空格），冲突失败，诊断指出文件名，导航层一行都没写。"""
    state = _capture(fake_nav)
    target = fake_nav.nav_root / "按任务" / NAME / "子任务.json"
    target.write_bytes(target.read_bytes() + b" ")
    error = _assert_conflict_writes_nothing(fake_nav, state)
    assert "子任务.json" in repr(error.diagnostics)
    (difference,) = diff_preview_state(fake_nav.nav_root, state, checkpoint=noop)
    assert difference.kind == "json_changed" and difference.name == "子任务.json"
    assert difference.entry_path == "按任务/EgoProDemo"


def test_verify_conflicts_when_entry_names_change(fake_nav: FakeNavigation) -> None:
    """L12 验收（样二）：入口目录多出或少了一个条目，冲突失败，导航层一行都没写。"""
    state = _capture(fake_nav)
    (fake_nav.nav_root / "按任务" / NAME / "多出来.txt").write_text("x", encoding="utf-8")
    _assert_conflict_writes_nothing(fake_nav, state)
    kinds = {d.kind for d in diff_preview_state(fake_nav.nav_root, state, checkpoint=noop)}
    assert kinds == {"names_changed"}
    (fake_nav.nav_root / "按任务" / NAME / "多出来.txt").unlink()
    (fake_nav.nav_root / "按任务" / NAME / "数据集信息.json").unlink()
    assert {d.kind for d in diff_preview_state(fake_nav.nav_root, state, checkpoint=noop)} >= {
        "names_changed"
    }


def test_verify_conflicts_when_link_target_changes(fake_nav: FakeNavigation) -> None:
    """L12 验收（样三）：某条链接的 readlink 改了，冲突失败，导航层一行都没写。"""
    state = _capture(fake_nav)
    link = fake_nav.nav_root / "按任务" / NAME / "原始数据"
    link.unlink()
    link.symlink_to(fake_nav.nav_root.parent / "roots" / "dataset1")
    _assert_conflict_writes_nothing(fake_nav, state)
    (difference,) = diff_preview_state(fake_nav.nav_root, state, checkpoint=noop)
    assert difference.kind == "link_changed" and difference.name == "原始数据"


def test_verify_conflicts_when_entry_added_or_removed(fake_nav: FakeNavigation) -> None:
    """L12：数据集多了或少了一个按格式入口，冲突失败。"""
    state = _capture(fake_nav)
    removed = fake_nav.nav_root / "按格式" / "lerobot" / "3.0" / NAME
    shutil.copytree(removed, fake_nav.nav_root / "按格式" / "mcap" / NAME, symlinks=True)
    _assert_conflict_writes_nothing(fake_nav, state)
    assert any(
        d.kind == "entry_missing_or_new" and d.entry_path == f"按格式/mcap/{NAME}"
        for d in diff_preview_state(fake_nav.nav_root, state, checkpoint=noop)
    )
    shutil.rmtree(fake_nav.nav_root / "按格式" / "mcap" / NAME)
    shutil.rmtree(removed)
    assert any(
        d.kind == "entry_missing_or_new" and d.entry_path == f"按格式/lerobot/3.0/{NAME}"
        for d in diff_preview_state(fake_nav.nav_root, state, checkpoint=noop)
    )
    _assert_conflict_writes_nothing(fake_nav, state)


def test_verify_conflicts_when_destination_appears(fake_nav: FakeNavigation) -> None:
    """L12：新增数据集的目的目录在预览之后出现，冲突失败。"""
    state = capture_preview_state(fake_nav.nav_root, (), "按任务/新数据集", checkpoint=noop)
    verify_preview_state(fake_nav.nav_root, state, checkpoint=noop)
    destination = fake_nav.nav_root / "按任务" / "新数据集"
    destination.mkdir()
    for name in ("原始路径.json", "数据集信息.json", "子任务.json"):
        (destination / name).write_text('{"dataset_id": "dataset-12"}', encoding="utf-8")
    _assert_conflict_writes_nothing(fake_nav, state)
    (difference,) = diff_preview_state(fake_nav.nav_root, state, checkpoint=noop)
    assert difference.kind == "destination_exists" and difference.dataset_id is None


def test_verify_conflicts_when_max_number_changes(fake_nav: FakeNavigation) -> None:
    """L12：新增数据集的最大编号在预览之后变了，冲突失败。"""
    state = capture_preview_state(fake_nav.nav_root, (), "按任务/新数据集", checkpoint=noop)
    (fake_nav.nav_root / "已移除" / "dataset-50_旧").mkdir(parents=True)
    _assert_conflict_writes_nothing(fake_nav, state)
    (difference,) = diff_preview_state(fake_nav.nav_root, state, checkpoint=noop)
    assert difference.kind == "max_number_changed"
    assert "35" in difference.expected and "50" in difference.actual


def test_unverifiable_fingerprints_never_equal(fake_nav: FakeNavigation) -> None:
    """契约 diff_preview_state：任一方 verifiable=False 时产生 unverifiable 差异，两个不可验证的值不算没变。"""
    state = _capture(fake_nav)
    broken = state.model_copy(
        update={"datasets": (state.datasets[0].model_copy(update={"verifiable": False}),)}
    )
    differences = diff_preview_state(fake_nav.nav_root, broken, checkpoint=noop)
    assert [d.kind for d in differences] == ["unverifiable"]
    with pytest.raises(ConflictError):
        verify_preview_state(fake_nav.nav_root, broken, checkpoint=noop)
    # 现状不可验证：目录读不了时同样不算没变。
    unreadable = fake_nav.nav_root / "按任务" / NAME / "子任务.json"
    unreadable.chmod(0)
    try:
        if unreadable.read_bytes is not None:  # root 身份下 chmod 无效，此时现状仍可验证
            try:
                unreadable.read_bytes()
                return
            except PermissionError:
                pass
        kinds = {d.kind for d in diff_preview_state(fake_nav.nav_root, state, checkpoint=noop)}
        assert "unverifiable" in kinds
    finally:
        unreadable.chmod(0o644)


def test_verify_rejects_other_nav_root(fake_nav: FakeNavigation, tmp_path: Path) -> None:
    """契约 diff_preview_state：nav_root 与预览所用不同时整体视为差异。"""
    state = _capture(fake_nav)
    other = tmp_path / "other-root"
    shutil.copytree(fake_nav.nav_root, other, symlinks=True)
    differences = diff_preview_state(other, state, checkpoint=noop)
    assert differences and all(d.kind == "nav_root_changed" for d in differences)
    with pytest.raises(ConflictError):
        verify_preview_state(other, state, checkpoint=noop)


def test_conflict_diagnostic_lists_differences(fake_nav: FakeNavigation) -> None:
    """契约 verify_preview_state：冲突诊断列出差异（数据集、入口、文件或链接、预期与实际），后果写一行都没写，下一步写重新预览。"""
    state = _capture(fake_nav)
    (fake_nav.nav_root / "按任务" / NAME / "子任务.json").write_bytes(b"{}\n")
    error = _assert_conflict_writes_nothing(fake_nav, state)
    (diagnostic,) = error.diagnostics
    rendered = " ".join(f"{o.key}={o.value}" for o in diagnostic.objects)
    assert dataset_id_of(fake_nav, NAME) in rendered and "按任务/EgoProDemo" in rendered
    assert "子任务.json" in rendered
    assert "一行都没写" in diagnostic.consequence and "重新预览" in diagnostic.next_step


def test_verify_checkpoint_cancellation_propagates(fake_nav: FakeNavigation) -> None:
    """契约 verify_preview_state：非保护段的 checkpoint 抛出的取消和停止异常原样传播。"""
    state = _capture(fake_nav)

    def cancel() -> None:
        raise JobCancelledError(nav_conflict_error("X", "取消").diagnostics)

    with pytest.raises(JobCancelledError):
        verify_preview_state(fake_nav.nav_root, state, checkpoint=cancel)
