"""M4-07 空间预检验收，经作业执行入口观察结果，只替换磁盘容量边界。"""

import shutil
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from conversion_cleaning_support import seed_preview
from conversion_support import fake_converter, no_sandbox, settings, storage_checker
from datasets_execution_support import dataset_case
from jobs_execution_support import execution_case
from nav_manifest import FakeNavigation
from tool_registry_support import ToolFiles
from tool_registry_support import isolated_tool_cache as isolated_tool_cache

from rdp.infra.config import StorageRootConfig
from rdp.infra.diagnostics import DiagnosticCategory
from rdp.jobs.conversion.job import ConversionDependencies, ConversionExecutor
from rdp.jobs.conversion.parameters import ConversionParameters
from rdp.jobs.execution import ExecutionContext, execute_job
from rdp.jobs.outcome import JobOutcome
from rdp.jobs.types import JobRecord


def test_insufficient_space_fails_without_staging_or_tool(
    tmp_path: Path, fake_nav: FakeNavigation, monkeypatch: pytest.MonkeyPatch
) -> None:
    """验收1：少1字节也以外部失败拒绝，报告四项容量，不创建暂存、不启动工具。"""
    files = fake_converter(tmp_path / "tool")
    _selected_files(fake_nav)

    # 两块合计13字节，用户填50%和0.5 GiB，估算7字节；可用比总需求少1字节。
    def disk_usage(path: Path) -> SimpleNamespace:
        return SimpleNamespace(free=536870918)

    monkeypatch.setattr(shutil, "disk_usage", disk_usage)
    result = _convert(tmp_path, fake_nav, files, space_ratio_percent=50, space_reserve_gib=0.5)
    assert result.summary is not None and result.summary.outcome is JobOutcome.FAILED
    diagnostic = next(
        sample
        for group in result.diagnostics
        for sample in group.samples
        if sample.rule == "conversion.insufficient_space"
    )
    assert diagnostic.category is DiagnosticCategory.EXTERNAL
    assert ("storage_root", "output") in [(obj.key, obj.value) for obj in diagnostic.objects]
    for value in (
        "输入 13 字节（0.00 GiB）",
        "估算产物 7 字节（0.00 GiB）",
        "预留 536870912 字节（0.50 GiB）",
        "可用 536870918 字节（0.50 GiB）",
        "50%",
        "偏置 0.5 GiB",
    ):
        assert value in diagnostic.actual
    assert diagnostic.expected == "可用空间不少于估算产物与预留之和"
    assert diagnostic.consequence == "未开始转换，未建暂存目录"
    assert diagnostic.next_step == "释放可写根空间后重新提交"
    assert not (tmp_path / "output/暂存/转换/71").exists()
    assert not files.program.with_suffix(".calls").exists()


def test_space_estimate_only_counts_selected_sources(
    tmp_path: Path, fake_nav: FakeNavigation, monkeypatch: pytest.MonkeyPatch
) -> None:
    """验收2：忽略同数据集未选的大块，可用恰好等于所需时正常转换成功。"""
    files = fake_converter(tmp_path / "tool")
    _selected_files(fake_nav)
    unselected = (
        fake_nav.storage_roots[1].path
        / "R1_lite_table_withdrawing_mcap/20261011_table_withdrawing/large.mcap"
    )
    # 稀疏文件提供8 GiB表观大小，不实际分配数据；只统计选中13字节应恰好够用。
    with unselected.open("wb") as stream:
        stream.truncate(8 * 1024**3)

    def disk_usage(path: Path) -> SimpleNamespace:
        return SimpleNamespace(free=1073741828)

    monkeypatch.setattr(shutil, "disk_usage", disk_usage)
    result = _convert(tmp_path, fake_nav, files)
    assert result.summary is not None and result.summary.outcome is JobOutcome.SUCCEEDED
    assert (tmp_path / "output/暂存/转换/71/out/meta/info.json").is_file()
    assert files.program.with_suffix(".calls").read_text() == "verify\nconvert\n"


def _selected_files(fake: FakeNavigation) -> None:
    """两个已登记数据块分别放5和8字节，期望值独立于遍历实现。"""
    root = fake.storage_roots[1].path / "R1_lite_table_withdrawing_mcap"
    (root / "20261009_table_withdrawing/first.mcap").write_bytes(b"first")
    (root / "20261010_table_withdrawing/second.mcap").write_bytes(b"12345678")


def _convert(
    root: Path,
    fake: FakeNavigation,
    files: ToolFiles,
    *,
    space_ratio_percent: int = 25,
    space_reserve_gib: float = 1,
) -> JobRecord:
    """复用真实索引和执行器，所有工具、输入、存储及状态路径都在tmp。"""
    output = root / "output"
    output.mkdir()
    roots = (
        *fake.storage_roots,
        StorageRootConfig(name="output", path=output, nfs_export="server:/output", writable=True),
    )
    with dataset_case(root / "index", fake) as scan:
        scan.run()
        dependencies = ConversionDependencies(
            scan.engine, settings(files), roots, no_sandbox, storage=storage_checker(roots)
        )
        parameters = ConversionParameters(
            dataset_id="dataset-35",
            source_ids=["src_01e0bc7e9cc8", "src_d5edab567d18"],
            robot_model="Galaxea R1 Lite",
            output_format="v3.0",
            space_ratio_percent=space_ratio_percent,
            space_reserve_gib=space_reserve_gib,
        )

        parameters = seed_preview(scan.engine, files, parameters)

        def execute(context: ExecutionContext) -> None:
            ConversionExecutor("mcap2lerobot", dependencies).execute(
                replace(context, parameters=parameters)
            )

        with execution_case(root / "state", {"steps": 1, "interval_ms": 0}, execute) as (
            work,
            deps,
            signals,
        ):
            result = execute_job(work, deps, signals)
            assert result is not None
            return result
