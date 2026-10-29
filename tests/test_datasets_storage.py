"""M1-02第一段验收：公开扫描结果及索引模型，全部I/O限定于临时目录。"""

import os
import shutil
from dataclasses import replace
from pathlib import Path
from threading import Event
from threading import enumerate as threads
from typing import Any, cast

import pytest
from datasets_execution_support import dataset_case
from datasets_storage_support import enable_storage, scan
from datasets_support import edit_json
from nav_manifest import FakeNavigation
from sqlalchemy import select

from rdp.infra.db.connection import session_scope
from rdp.jobs.datasets.models import FindingRow, LinkRow, SourceRow
from rdp.jobs.datasets.scan_types import SourceStatus, StorageStage
from rdp.jobs.datasets.types import PanelGroup, PanelSeverity


def test_realpath_preserves_symlink_parent_semantics(
    tmp_path: Path, fake_nav: FakeNavigation
) -> None:
    """L1：先展开软链接再处理其后的..，绝对和相对链接都以真实目标判定。"""
    root = fake_nav.storage_roots[0].path
    (root / "nested/sub").mkdir(parents=True)
    (root / "nested/data/meta").mkdir(parents=True)
    (root / "nested/data/meta/info.json").write_text('{"robot_type":"franka","fps":30}')
    alias = root / "alias"
    alias.symlink_to(root / "nested/sub")
    target = str(alias) + "/../data"
    for name in ("按任务/libero_10", "按格式/lerobot/3.0/libero_10"):
        entry = fake_nav.nav_root / name
        link = entry / "原始数据"
        link.unlink()
        link.symlink_to(
            target if name.startswith("按任务") else os.path.relpath(alias, entry) + "/../data"
        )

        def change(data: Any) -> None:
            data["links"][0]["source_path"] = target
            data["sources"][0]["direct_path"] = target
            data["dataset_roots"] = [str(root / "nested")]

        edit_json(entry / "原始路径.json", change)
    with dataset_case(tmp_path / "state", fake_nav) as case:
        enable_storage(case)
        result = scan(case)
        assert all(
            link.status.value == "available"
            for link in result.links
            if link.entry_path.endswith("/libero_10")
        )
        assert all(
            source.fps == 30
            for source in result.sources
            if source.entry_path.endswith("/libero_10")
        )


def test_unverified_placeholder_discards_storage_findings(
    tmp_path: Path, fake_nav: FakeNavigation
) -> None:
    """L12契约：首次扫描期间入口变化，只建占位，不发布旧快照的第二段发现。"""
    from rdp.jobs.datasets.rescan import publish_scan, scan_navigation, scan_storage
    from rdp.jobs.execution import ExecutionContext

    source = fake_nav.nav_root / "按任务/libero_10/原始路径.json"
    edit_json(
        source,
        lambda data: data["sources"][0].update(
            direct_path=str(fake_nav.storage_roots[0].path / "missing")
        ),
    )
    with dataset_case(tmp_path / "state", fake_nav) as case:
        enable_storage(case)

        def execute(context: ExecutionContext) -> None:
            navigation = scan_navigation(context, case.scanning)
            storage = scan_storage(navigation, case.scanning, checkpoint=lambda: None)
            edit_json(source, lambda data: data.update(notes=["changed"]))
            result = publish_scan(context, case.scanning, navigation, storage)
            assert result.skipped_dataset_count == 1

        record = case.run(execute=execute)
        assert record.summary is not None and not record.summary.aborted
        with session_scope(case.engine, read_only=True) as session:
            assert (
                session.scalar(
                    select(FindingRow).where(
                        FindingRow.owner_key == "dataset:dataset-14",
                        FindingRow.rule == "SOURCE_MISSING",
                    )
                )
                is None
            )


def test_publication_rejects_unknown_storage_entry(
    tmp_path: Path, fake_nav: FakeNavigation
) -> None:
    """已合并计划契约：第二段引用未知入口时报DefectError，不能悄悄丢弃越界结果。"""
    from jobs_storage_support import NOW

    from rdp.infra.diagnostics import DefectError
    from rdp.jobs.datasets.index import plan_index_replacement
    from rdp.jobs.datasets.rescan import scan_navigation, scan_storage
    from rdp.jobs.execution import ExecutionContext

    with dataset_case(tmp_path / "state", fake_nav) as case:
        enable_storage(case)

        def execute(context: ExecutionContext) -> None:
            navigation = scan_navigation(context, case.scanning)
            storage = scan_storage(navigation, case.scanning, checkpoint=lambda: None)
            invalid = replace(
                storage, links=(replace(storage.links[0], entry_path="按任务/unknown"),)
            )
            with pytest.raises(DefectError):
                plan_index_replacement(
                    navigation,
                    invalid,
                    tuple(item.fingerprint for item in navigation.datasets),
                    committed_at=NOW,
                )

        record = case.run(execute=execute)
        assert record.summary is not None and not record.summary.aborted


def test_offline_retains_size_and_storage_is_unlocked(
    tmp_path: Path, fake_nav: FakeNavigation
) -> None:
    """验收3/ADR0005：真实存储回调可取得导航锁；离线扫描保留大小及原统计时刻。"""
    from jobs_storage_support import NOW

    from rdp.jobs.datasets.models import DatasetRow
    from rdp.jobs.datasets.rescan import RescanExecutor
    from rdp.jobs.execution import ExecutionContext

    with dataset_case(tmp_path / "state", fake_nav) as case:
        enable_storage(case)
        checker = case.scanning.storage
        assert checker is not None
        unlocked: list[bool] = []

        def execute(context: ExecutionContext) -> None:
            def access(path: Path) -> None:
                unlocked.append(context.write_navigation(lambda: None, lambda: True))
                checker.access(path)

            RescanExecutor(replace(case.scanning, storage=replace(checker, access=access))).execute(
                context
            )

        record = case.run(execute=execute)
        assert record.summary is not None and not record.summary.aborted
        assert unlocked == [True, True]
        with session_scope(case.engine) as session:
            row = session.get(DatasetRow, "dataset-14")
            assert row is not None
            row.size_bytes, row.size_checked_at = 12345, NOW
        enable_storage(case, table="")
        case.run()
        with session_scope(case.engine, read_only=True) as session:
            row = session.get(DatasetRow, "dataset-14")
            assert row is not None and (row.size_bytes, row.size_checked_at) == (12345, NOW)
            assert (
                session.scalar(
                    select(LinkRow.status).where(LinkRow.entry_path == "按任务/libero_10")
                )
                == "offline"
            )


def test_actual_target_checked(tmp_path: Path, fake_nav: FakeNavigation) -> None:
    """验收4：磁盘链接指向JSON外的未登记目标时，既报指向不同也报实际目标越界。"""
    link = fake_nav.nav_root / "按任务/libero_10/原始数据"
    link.unlink()
    link.symlink_to(tmp_path / "unregistered")
    with dataset_case(tmp_path / "state", fake_nav) as case:
        enable_storage(case)
        rules = {
            group.diagnostics.rule
            for owner, group in scan(case).findings
            if owner == "dataset:dataset-14"
        }
        assert {"LINK_DECLARATION_MISMATCH", "LINK_OUTSIDE_STORAGE"} <= rules


def test_mismatched_and_extra_broken_links(tmp_path: Path, fake_nav: FakeNavigation) -> None:
    """验收4：实际目标断链，即使JSON指向不同或没有登记，也必须报告断链。"""
    entry = fake_nav.nav_root / "按任务/libero_10"
    missing = fake_nav.storage_roots[0].path / "libero_v3/libero_10/gone"
    (entry / "原始数据").unlink()
    (entry / "原始数据").symlink_to(missing)
    (entry / "extra").symlink_to(missing)
    with dataset_case(tmp_path / "state", fake_nav) as case:
        enable_storage(case)
        group = next(
            group
            for owner, group in scan(case).findings
            if owner == "dataset:dataset-14" and group.diagnostics.rule == "LINK_BROKEN"
        )
        assert group.diagnostics.total == 2


def test_unregistered_source(tmp_path: Path, fake_nav: FakeNavigation) -> None:
    """数据块契约：未登记根的direct_path不访问，仍有明确unregistered观察。"""
    edit_json(
        fake_nav.nav_root / "按任务/libero_10/原始路径.json",
        lambda data: data["sources"][0].update(direct_path=str(tmp_path / "outside")),
    )
    with dataset_case(tmp_path / "state", fake_nav) as case:
        enable_storage(case)
        result = scan(case)
        source = next(item for item in result.sources if item.entry_path == "按任务/libero_10")
        assert source.status is SourceStatus.UNREGISTERED and source.robot_type is None
        assert source.storage_root_name is None
        alias = fake_nav.storage_roots[0].path / "outside-alias"
        alias.symlink_to(tmp_path / "outside")
        edit_json(
            fake_nav.nav_root / "按任务/libero_10/原始路径.json",
            lambda data: data["sources"][0].update(direct_path=str(alias)),
        )
        source = next(item for item in scan(case).sources if item.entry_path == "按任务/libero_10")
        assert source.status is SourceStatus.UNREGISTERED and source.storage_root_name is None


def test_cross_root_symlink(tmp_path: Path, fake_nav: FakeNavigation) -> None:
    """L1/离线契约：真实目标在另一登记根时不误报越界；该根离线则标离线。"""
    alias = fake_nav.storage_roots[1].path / "alias"
    alias.symlink_to(fake_nav.storage_roots[0].path / "libero_v3/libero_10")
    entry = fake_nav.nav_root / "按任务/libero_10"
    (entry / "原始数据").unlink()
    (entry / "原始数据").symlink_to(alias)
    edit_json(entry / "原始路径.json", lambda data: data["links"][0].update(source_path=str(alias)))
    with dataset_case(tmp_path / "state", fake_nav) as case:
        enable_storage(case)
        result = scan(case)
        link = next(item for item in result.links if item.entry_path == "按任务/libero_10")
        assert link.status.value == "available" and link.storage_root_name == "dataset1"
        enable_storage(
            case, table=f"1 0 8:2 / {fake_nav.storage_roots[1].path} rw - ext4 /dev/fake rw"
        )
        result = scan(case)
        link = next(item for item in result.links if item.entry_path == "按任务/libero_10")
        assert link.status.value == "offline"


def test_cross_root_source_meta(tmp_path: Path, fake_nav: FakeNavigation) -> None:
    """数据块realpath跨登记根时读取目标元信息，不将存在的数据块误标缺失或未登记。"""
    alias = fake_nav.storage_roots[1].path / "alias"
    alias.symlink_to(fake_nav.storage_roots[0].path / "libero_v3/libero_10")
    edit_json(
        fake_nav.nav_root / "按任务/libero_10/原始路径.json",
        lambda data: data["sources"][0].update(direct_path=str(alias)),
    )
    with dataset_case(tmp_path / "state", fake_nav) as case:
        enable_storage(case)
        source = next(item for item in scan(case).sources if item.entry_path == "按任务/libero_10")
        assert source.status is SourceStatus.AVAILABLE
        assert (source.storage_root_name, source.robot_type, source.fps) == (
            "dataset1",
            "franka",
            20,
        )


def test_worker_assembly_runs_storage(tmp_path: Path, fake_nav: FakeNavigation) -> None:
    """生产装配契约：worker登记的扫描器确实执行第二段，Web不获得访问能力。"""
    from ops_support import runtime_inputs

    from rdp.jobs.datasets.models import DatasetScanRow
    from rdp.ops.runtime import prepare_service

    inputs = runtime_inputs(tmp_path / "runtime")
    (inputs.home / "nav/按任务").mkdir(parents=True)
    (inputs.home / "nav/按格式").mkdir()
    runtime = prepare_service("worker", no_stderr=True, inputs=inputs)
    try:
        definition = next(
            item for item in runtime.registry.definitions() if item.type_name == "dataset_rescan"
        )
        with dataset_case(tmp_path / "state", fake_nav) as case:
            record = case.run(execute=definition.execute)
            assert record.summary is not None and not record.summary.aborted
        with session_scope(runtime.engine, read_only=True) as session:
            assert session.scalar(select(DatasetScanRow.storage_stage)) == "completed"
    finally:
        runtime.engine.dispose()


def test_disk_results_published_and_cleared(tmp_path: Path, fake_nav: FakeNavigation) -> None:
    """索引契约：③④组、链接状态写入；修复后旧发现清除，缺来源仍每数据集一条。"""
    entry = fake_nav.nav_root / "按任务/libero_10"
    (entry / "原始数据").unlink()
    with dataset_case(tmp_path / "state", fake_nav) as case:
        enable_storage(case)
        scan(case)
        with session_scope(case.engine, read_only=True) as session:
            assert (
                session.scalar(
                    select(FindingRow.total).where(
                        FindingRow.owner_key == "dataset:dataset-14",
                        FindingRow.rule == "LINK_DECLARATION_MISMATCH",
                    )
                )
                == 1
            )
            assert (
                session.scalar(
                    select(LinkRow.status).where(LinkRow.entry_path == "按任务/libero_10")
                )
                == "missing"
            )
            assert (
                len(
                    tuple(
                        session.scalars(
                            select(FindingRow).where(FindingRow.rule == "PROVENANCE_MISSING")
                        )
                    )
                )
                == 5
            )
        (entry / "原始数据").symlink_to(fake_nav.storage_roots[0].path / "libero_v3/libero_10")
        scan(case)
        with session_scope(case.engine, read_only=True) as session:
            assert (
                session.scalar(
                    select(FindingRow).where(FindingRow.rule == "LINK_DECLARATION_MISMATCH")
                )
                is None
            )
            assert (
                session.scalar(
                    select(LinkRow.status).where(LinkRow.entry_path == "按任务/libero_10")
                )
                == "available"
            )


def test_unlinked_root_content(tmp_path: Path, fake_nav: FakeNavigation) -> None:
    """验收4：按子目录链接的规范入口，未链接未排除的直接子项提示；排除项不报。"""
    root = fake_nav.storage_roots[1].path / "agibot_world_alpha"
    (root / ".venv").mkdir()
    (root / "README.md").write_text("fixture")
    (root / "excluded").mkdir()
    edit_json(
        fake_nav.nav_root / "按任务/agibot_world_alpha/原始路径.json",
        lambda data: data["excluded_from_navigation"].append(str(root / "excluded")),
    )
    with dataset_case(tmp_path / "state", fake_nav) as case:
        enable_storage(case)
        group = next(
            group
            for _, group in scan(case).findings
            if group.diagnostics.rule == "ROOT_CONTENT_UNLINKED"
        )
        assert group.severity is PanelSeverity.NOTICE and group.diagnostics.total == 2
        assert {sample.actual.strip("'") for sample in group.diagnostics.samples} == {
            str(root / ".venv"),
            str(root / "README.md"),
        }


def test_same_rule_across_roots_aggregates(tmp_path: Path, fake_nav: FakeNavigation) -> None:
    """聚合契约：同数据集跨两个根的同规则发现合并，索引不能被最后一根覆盖。"""
    first = fake_nav.storage_roots[0].path / "alpha-extra"
    first.mkdir()
    (first / "unlinked").mkdir()
    second = fake_nav.storage_roots[1].path / "agibot_world_alpha"
    (second / "unlinked").mkdir()
    edit_json(
        fake_nav.nav_root / "按任务/agibot_world_alpha/原始路径.json",
        lambda data: data["dataset_roots"].append(str(first)),
    )
    with dataset_case(tmp_path / "state", fake_nav) as case:
        enable_storage(case)
        groups = [
            group
            for owner, group in scan(case).findings
            if owner == "dataset:dataset-31" and group.diagnostics.rule == "ROOT_CONTENT_UNLINKED"
        ]
        assert len(groups) == 1 and groups[0].diagnostics.total == 2
        with session_scope(case.engine, read_only=True) as session:
            assert (
                session.scalar(
                    select(FindingRow.total).where(
                        FindingRow.owner_key == "dataset:dataset-31",
                        FindingRow.rule == "ROOT_CONTENT_UNLINKED",
                    )
                )
                == 2
            )


def test_stale_references(tmp_path: Path, fake_nav: FakeNavigation) -> None:
    """验收4：排除目录、子任务、Markdown本地链接和summary失效为提示，不检查original_path。"""
    missing = str(fake_nav.storage_roots[0].path / "gone (目录)")
    entry = fake_nav.nav_root / "按任务/libero_10"
    edit_json(entry / "原始路径.json", lambda data: data.update(excluded_from_navigation=[missing]))

    def change_tasks(data: dict[str, Any]) -> None:
        data["tasks"][0].update(evidence=[{"path": missing}], original_path=missing)
        data.update(shared_source_roots=[{"root": missing}])

    edit_json(entry / "子任务.json", change_tasks)
    edit_json(
        entry / "数据集信息.json",
        lambda data: data["fields"][0].update(
            value_markdown=f"[本地](<{missing}>)；[网络](https://example.invalid/no)"
        ),
    )
    with dataset_case(tmp_path / "state", fake_nav) as case:
        enable_storage(case)
        groups = {
            group.diagnostics.rule: group
            for owner, group in scan(case).findings
            if owner == "dataset:dataset-14"
        }
        for rule in (
            "EXCLUDED_PATH_MISSING",
            "TASK_REFERENCE_MISSING",
            "MARKDOWN_REFERENCE_MISSING",
            "SUMMARY_PATH_MISSING",
        ):
            assert rule in groups and groups[rule].severity is PanelSeverity.NOTICE
        assert groups["TASK_REFERENCE_MISSING"].diagnostics.total == 2
        assert groups["SUMMARY_PATH_MISSING"].diagnostics.total == 2


def test_missing_dataset_root(tmp_path: Path, fake_nav: FakeNavigation) -> None:
    """验收4：dataset_roots不存在报需要处理，保留确切字段与路径。"""
    edit_json(
        fake_nav.nav_root / "按任务/libero_10/原始路径.json",
        lambda data: data["dataset_roots"].append(str(fake_nav.storage_roots[0].path / "missing")),
    )
    with dataset_case(tmp_path / "state", fake_nav) as case:
        enable_storage(case)
        result = scan(case)
        group = next(
            group
            for _, group in result.findings
            if group.diagnostics.rule == "DATASET_ROOT_MISSING"
        )
        assert group.diagnostics.total == 1 and group.severity is PanelSeverity.ACTION_REQUIRED
        assert "missing" in str(group.diagnostics.samples[0].actual)


def test_target_outside_dataset_roots(tmp_path: Path, fake_nav: FakeNavigation) -> None:
    """验收4：存储根内但不在dataset_roots分量边界内的目标报需要处理。"""
    edit_json(
        fake_nav.nav_root / "按任务/libero_10/原始路径.json",
        lambda data: data.update(
            dataset_roots=[str(fake_nav.storage_roots[0].path / "libero_v3/libero_1")]
        ),
    )
    with dataset_case(tmp_path / "state", fake_nav) as case:
        enable_storage(case)
        result = scan(case)
        group = next(
            group
            for _, group in result.findings
            if group.diagnostics.rule == "LINK_OUTSIDE_DATASET_ROOTS"
        )
        assert group.diagnostics.total == 1 and group.severity is PanelSeverity.ACTION_REQUIRED


def test_unregistered_target(tmp_path: Path, fake_nav: FakeNavigation) -> None:
    """验收4/L1：词法越界和经真实路径解析后越界都报未登记，不读取越界目标。"""
    outside = tmp_path / "outside"
    outside.mkdir()
    redirect = fake_nav.storage_roots[0].path / "redirect"
    redirect.symlink_to(outside)
    for entry, target in (
        ("按任务/libero_10", outside),
        ("按格式/lerobot/3.0/libero_10", redirect),
    ):
        directory = fake_nav.nav_root / entry
        (directory / "原始数据").unlink()
        (directory / "原始数据").symlink_to(target)
        edit_json(
            directory / "原始路径.json",
            lambda data, target=target: data["links"][0].update(source_path=str(target)),
        )
    with dataset_case(tmp_path / "state", fake_nav) as case:
        enable_storage(case)
        result = scan(case)
        group = next(
            group
            for _, group in result.findings
            if group.diagnostics.rule == "LINK_OUTSIDE_STORAGE"
        )
        assert group.diagnostics.total == 2 and group.severity is PanelSeverity.ACTION_REQUIRED
        assert {
            item.status.value for item in result.links if item.entry_path.endswith("/libero_10")
        } == {"unregistered"}


def test_timeout_discards_partial_results(
    tmp_path: Path, fake_nav: FakeNavigation, monkeypatch: pytest.MonkeyPatch
) -> None:
    """验收3：meta读取超时将整根降为离线，迟到线程结果不能污染已返回快照。"""
    release, finished = Event(), Event()
    original = os.open
    with dataset_case(tmp_path / "state", fake_nav) as case:
        enable_storage(case)

        def blocked(value: Any, *args: Any, **kwargs: Any) -> Any:
            path = Path(value) if isinstance(value, (str, Path)) else Path("/not-a-path")
            if path.name == "info.json" and path.is_relative_to(fake_nav.storage_roots[0].path):
                try:
                    assert release.wait(5)
                finally:
                    finished.set()
            return cast(Any, original(path, *args, **kwargs))

        monkeypatch.setattr(os, "open", blocked)
        try:
            result = scan(case)
            assert result.roots[0].reason is not None and result.roots[0].reason.value == "timeout"
            assert all(
                item.status.value == "offline"
                for item in result.links
                if item.storage_root_name == "dataset1"
            )
            assert not any(group.diagnostics.rule == "LINK_BROKEN" for _, group in result.findings)
        finally:
            release.set()
            assert finished.wait(5)
            for thread in threads():
                if thread.name.startswith("storage-"):
                    thread.join(5)
                    assert not thread.is_alive()


def test_timeout_stops_later_reads(
    tmp_path: Path, fake_nav: FakeNavigation, monkeypatch: pytest.MonkeyPatch
) -> None:
    """超时契约：已开始的系统调用可迟到，但返回后不再访问同根其他数据块。"""
    release, entered = Event(), Event()
    original = os.open
    calls: list[Path] = []
    root = fake_nav.storage_roots[1].path
    with dataset_case(tmp_path / "state", fake_nav) as case:
        enable_storage(case)

        def blocked(value: Any, *args: Any, **kwargs: Any) -> Any:
            path = Path(value) if isinstance(value, (str, Path)) else Path("/not-a-path")
            if path.name == "info.json" and path.is_relative_to(root):
                calls.append(path)
                entered.set()
                assert release.wait(5)
            return cast(Any, original(path, *args, **kwargs))

        monkeypatch.setattr(os, "open", blocked)
        try:
            result = scan(case)
            assert entered.is_set() and result.roots[1].reason is not None
        finally:
            release.set()
            for thread in threads():
                if thread.name.startswith("storage-"):
                    thread.join(5)
                    assert not thread.is_alive()
        assert len(calls) == 1


def test_redirect_timeout_invalidates_root_observations(
    tmp_path: Path, fake_nav: FakeNavigation, monkeypatch: pytest.MonkeyPatch
) -> None:
    """离线契约：跨根补读超时后，该根先前已完成的观察也不能继续标为在线。"""
    target = fake_nav.storage_roots[0].path / "redirect-target"
    (target / "meta").mkdir(parents=True)
    (target / "meta/info.json").write_text('{"fps":30}')
    alias = fake_nav.storage_roots[1].path / "alias"
    alias.symlink_to(target)
    edit_json(
        fake_nav.nav_root / "按任务/libero_10/原始路径.json",
        lambda data: data["sources"][0].update(direct_path=str(alias)),
    )
    release = Event()
    original = os.open
    with dataset_case(tmp_path / "state", fake_nav) as case:
        enable_storage(case)

        def blocked(value: Any, *args: Any, **kwargs: Any) -> Any:
            path = Path(value) if isinstance(value, (str, Path)) else Path("/not-a-path")
            if path == target / "meta/info.json":
                assert release.wait(5)
            return cast(Any, original(path, *args, **kwargs))

        monkeypatch.setattr(os, "open", blocked)
        try:
            result = scan(case)
            assert result.roots[0].reason is not None
            assert all(
                item.status is SourceStatus.OFFLINE
                for item in result.sources
                if item.storage_root_name == "dataset1"
            )
        finally:
            release.set()
            for thread in threads():
                if thread.name.startswith("storage-"):
                    thread.join(5)
                    assert not thread.is_alive()


def test_wrong_disk_skips_access(tmp_path: Path, fake_nav: FakeNavigation) -> None:
    """验收3：挂错设备号不调用数据访问，离线原因保留为source_mismatch。"""
    table = "\n".join(
        f"1 0 9:99 / {root.path} rw - ext4 /dev/wrong rw" for root in fake_nav.storage_roots
    )
    with dataset_case(tmp_path / "state", fake_nav) as case:
        enable_storage(case, table=table)
        checker = case.scanning.storage
        assert checker is not None

        def forbidden(_path: Path) -> None:
            pytest.fail("挂错盘不允许访问")

        case.scanning = replace(case.scanning, storage=replace(checker, access=forbidden))
        result = scan(case)
        assert all(
            root.reason is not None and root.reason.value == "source_mismatch"
            for root in result.roots
        )
        assert all(item.status.value == "offline" for item in result.links)


def test_offline_roots(tmp_path: Path, fake_nav: FakeNavigation) -> None:
    """验收3：没挂载时每根顶部一条、所有链接和数据块离线，无断链，作业带警告成功。"""
    with dataset_case(tmp_path / "state", fake_nav) as case:
        enable_storage(case, table="")
        result = scan(case)
        assert result.warning_count == 2
        assert result.links and all(item.status.value == "offline" for item in result.links)
        assert result.sources and all(item.status.value == "offline" for item in result.sources)
        assert len(result.findings) == 1
        owner, group = result.findings[0]
        assert owner == "global" and group.group is PanelGroup.STORAGE
        assert group.diagnostics.rule == "STORAGE_OFFLINE" and group.diagnostics.total == 2
        record = case.run()
        assert record.summary is not None and not record.summary.aborted
        assert record.summary.warning_count == 2 and record.summary.failed_items == 0


def test_broken_link(tmp_path: Path, fake_nav: FakeNavigation) -> None:
    """验收4：在线盘目标被删除才是断链，两个视图各一条需要处理。"""
    shutil.rmtree(fake_nav.storage_roots[0].path / "libero_v3/libero_10")
    with dataset_case(tmp_path / "state", fake_nav) as case:
        enable_storage(case)
        result = scan(case)
        group = next(
            group for _, group in result.findings if group.diagnostics.rule == "LINK_BROKEN"
        )
        assert group.diagnostics.total == 2 and group.severity is PanelSeverity.ACTION_REQUIRED
        assert {
            item.status.value for item in result.links if item.entry_path.endswith("/libero_10")
        } == {"broken"}


def test_link_declarations(tmp_path: Path, fake_nav: FakeNavigation) -> None:
    """验收4：少链、多链及目标不同分别报告，同类合并且保留入口身份。"""
    task = fake_nav.nav_root / "按任务/libero_10"
    format_entry = fake_nav.nav_root / "按格式/lerobot/3.0/libero_10"
    (task / "原始数据").unlink()
    (format_entry / "原始数据").unlink()
    (format_entry / "原始数据").symlink_to(fake_nav.storage_roots[0].path / "libero_v3")
    (format_entry / "extra").symlink_to(fake_nav.storage_roots[0].path / "libero_v3/libero_10")
    with dataset_case(tmp_path / "state", fake_nav) as case:
        enable_storage(case)
        result = scan(case)
        group = next(
            group
            for _, group in result.findings
            if group.diagnostics.rule == "LINK_DECLARATION_MISMATCH"
        )
        assert group.diagnostics.total == 3
        assert group.group is PanelGroup.DISK and group.severity is PanelSeverity.ACTION_REQUIRED
        assert {
            item.status.value for item in result.links if item.entry_path.endswith("/libero_10")
        } == {"missing", "mismatch"}


def test_meta_version_mismatch(tmp_path: Path, fake_nav: FakeNavigation) -> None:
    """验收4：v前缀不算版本差异，登记3.0而实测v2.1时报需要处理。"""
    with dataset_case(tmp_path / "state", fake_nav) as case:
        enable_storage(case)
        assert not any(
            group.diagnostics.rule == "SOURCE_VERSION_MISMATCH" for _, group in scan(case).findings
        )
        edit_json(
            fake_nav.storage_roots[0].path / "libero_v3/libero_10/meta/info.json",
            lambda data: data.update(codebase_version="v2.1"),
        )
        result = scan(case)
        owner, group = next(
            item
            for item in result.findings
            if item[1].diagnostics.rule == "SOURCE_VERSION_MISMATCH"
        )
        assert owner == "dataset:dataset-14" and group.diagnostics.total == 2
        assert group.severity is PanelSeverity.ACTION_REQUIRED


def test_missing_sources_grouped(tmp_path: Path, fake_nav: FakeNavigation) -> None:
    """验收4：alpha两视图的三个删除副本合并六条发现，保留对象及五段内容。"""
    with dataset_case(tmp_path / "state", fake_nav) as case:
        enable_storage(case)
        result = scan(case)
        owner, group = next(
            item for item in result.findings if item[1].diagnostics.rule == "SOURCE_MISSING"
        )
        assert owner == "dataset:dataset-31"
        assert group.group is PanelGroup.DISK and group.severity is PanelSeverity.ACTION_REQUIRED
        assert group.diagnostics.total == 6
        sample = group.diagnostics.samples[0]
        assert any(obj.key == "dataset_id" and obj.value == "dataset-31" for obj in sample.objects)
        assert sample.actual and sample.expected and sample.consequence and sample.next_step


def test_meta_unknown(tmp_path: Path, fake_nav: FakeNavigation) -> None:
    """验收5：读不到、unknown、null及无效FPS归未知，不能保留上次已知筛选值。"""
    path = fake_nav.storage_roots[0].path / "libero_v3/libero_10/meta/info.json"
    with dataset_case(tmp_path / "state", fake_nav) as case:
        enable_storage(case)
        scan(case)
        for content in (
            '{"robot_type":"unknown","fps":null,"codebase_version":null}',
            '{"robot_type":null,"fps":true,"codebase_version":"unknown"}',
            "broken",
            None,
        ):
            if content is None:
                path.unlink()
            else:
                path.write_text(content)
            result = scan(case)
            source = next(item for item in result.sources if item.entry_path == "按任务/libero_10")
            assert (source.robot_type, source.fps, source.codebase_version) == (None, None, None)
            with session_scope(case.engine, read_only=True) as session:
                row = session.scalar(
                    select(SourceRow).where(SourceRow.entry_path == "按任务/libero_10")
                )
                assert row is not None and row.robot_type is None and row.fps is None


def test_meta_invalid_numbers(tmp_path: Path, fake_nav: FakeNavigation) -> None:
    """验收5：不可信FPS的超大整数、NaN、无穷及负数均归未知，不使扫描失败。"""
    path = fake_nav.storage_roots[0].path / "libero_v3/libero_10/meta/info.json"
    with dataset_case(tmp_path / "state", fake_nav) as case:
        enable_storage(case)
        for value in ("1" + "0" * 400, str(2**63 - 2), "NaN", "Infinity", "-1"):
            path.write_text('{"fps":' + value + "}")
            result = scan(case)
            assert (
                next(item for item in result.sources if item.entry_path == "按任务/libero_10").fps
                is None
            )


def test_meta_is_indexed(tmp_path: Path, fake_nav: FakeNavigation) -> None:
    """验收5：在线LeRobot数据块的型号、FPS、原版本和UTC检查时间进入索引。"""
    with dataset_case(tmp_path / "state", fake_nav) as case:
        enable_storage(case)
        result = scan(case)
        assert result.stage is StorageStage.COMPLETED
        source = next(item for item in result.sources if item.entry_path == "按任务/libero_10")
        assert source.status is SourceStatus.AVAILABLE
        assert (source.robot_type, source.fps, source.codebase_version) == ("franka", 20, "v3.0")
        assert source.meta_checked_at is not None and source.meta_checked_at.utcoffset() is not None
        with session_scope(case.engine, read_only=True) as session:
            row = session.scalar(
                select(SourceRow).where(SourceRow.entry_path == "按任务/libero_10")
            )
            assert row is not None
            assert (row.robot_type, row.fps, row.codebase_version, row.fps_rounded) == (
                "franka",
                20,
                "v3.0",
                20,
            )
