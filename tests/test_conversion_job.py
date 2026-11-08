"""M4-03 转换作业关键验收，经真实执行器观察最终结果和暂存产物。"""

import json
from dataclasses import replace
from datetime import datetime
from pathlib import Path

from conversion_support import fake_converter, no_sandbox, settings, storage_checker
from datasets_execution_support import dataset_case
from jobs_execution_support import execution_case
from nav_manifest import FakeNavigation
from tool_registry_support import ToolFiles
from tool_registry_support import isolated_tool_cache as isolated_tool_cache

from rdp.infra.config import StorageRootConfig
from rdp.jobs.conversion.job import ConversionDependencies, ConversionExecutor
from rdp.jobs.conversion.parameters import ConversionParameters
from rdp.jobs.execution import ExecutionContext, execute_job
from rdp.jobs.outcome import JobOutcome
from rdp.jobs.progress import ExecutionSignals
from rdp.jobs.types import JobClock, JobRecord


def test_conversion_success(tmp_path: Path, fake_nav: FakeNavigation) -> None:
    """验收1：执行五阶段转换，最终帧数、产物及可复现回执一起保存。"""
    files = fake_converter(tmp_path / "tool")
    output = tmp_path / "output"
    output.mkdir()
    with dataset_case(tmp_path / "index", fake_nav) as scan:
        scan.run()
        dependencies = ConversionDependencies(
            scan.engine,
            settings(files),
            (
                *fake_nav.storage_roots,
                StorageRootConfig(
                    name="output", path=output, nfs_export="server:/output", writable=True
                ),
            ),
            no_sandbox,
        )
        dependencies = replace(dependencies, storage=storage_checker(dependencies.roots))
        parameters = ConversionParameters(
            dataset_id="dataset-35",
            source_ids=["src_01e0bc7e9cc8"],
            robot_model="Galaxea R1 Lite",
            output_format="v3.0",
        )

        def execute(context: ExecutionContext) -> None:
            ConversionExecutor("mcap2lerobot", dependencies).execute(
                replace(context, parameters=parameters)
            )

        with execution_case(tmp_path / "state", {"steps": 1, "interval_ms": 0}, execute) as (
            work,
            deps,
            signals,
        ):
            stages: list[tuple[int, int, str]] = []
            deps = replace(deps, clock=_observing_clock(deps.clock, signals, stages))
            result = execute_job(work, deps, signals)
            assert (
                result is not None
                and result.summary is not None
                and result.summary.outcome is JobOutcome.SUCCEEDED
            )
            assert result.progress is not None
            assert result.progress.stage_index == result.progress.stage_count == 5
            assert result.progress.stage_name == "收尾"
            assert stages == [
                (1, 5, "核对工具"),
                (2, 5, "核对输入"),
                (3, 5, "扫描"),
                (4, 5, "转换"),
                (5, 5, "收尾"),
            ]
            assert [(part.name, part.done, part.total) for part in result.progress.parts] == [
                ("head_left", 6, 6),
                ("state", 6, 6),
                ("action", 6, 6),
            ]
            assert result.progress.conversion is not None
            assert result.progress.conversion.total_episodes == 2
            assert result.progress.conversion.total_frames == 6
            stage = output / "暂存/转换/71"
            assert (stage / "out/meta/info.json").is_file()
            receipt = json.loads((stage / "转换回执.json").read_text())
            assert receipt["tool"]["name"] == "mcap2lerobot"
            assert receipt["tool"]["version"] == "0.1.0"
            assert len(receipt["tool"]["binary_sha256"]) == 64
            assert receipt["configuration"]["filename"] == "configs/r1lite.toml"
            assert len(receipt["configuration"]["sha256"]) == 64
            assert receipt["commands"]["verify"][1] == "verify"
            assert receipt["commands"]["convert"][1] == "convert"
            assert receipt["inputs"][0]["source_id"] == "src_01e0bc7e9cc8"
            assert receipt["started_at"].endswith("+00:00")
            assert receipt["ended_at"].endswith("+00:00")
            assert receipt["exit_code"] == 0
            assert all(not thread.is_alive() for thread in signals.monitor.threads)


def test_fingerprint_failure_never_starts_tool(tmp_path: Path, fake_nav: FakeNavigation) -> None:
    """验收2：指纹不符在第一阶段失败，外部程序没有留下任何调用记录。"""
    files = fake_converter(tmp_path / "tool")
    files.program.write_text(files.program.read_text() + "# changed\n")
    result = _failed_conversion(tmp_path, fake_nav, files)
    assert result.progress is not None and result.progress.stage_index == 1
    assert not files.program.with_suffix(".calls").exists()


def test_verify_failure_reports_stdout_without_conversion(
    tmp_path: Path, fake_nav: FakeNavigation
) -> None:
    """验收3：verify失败保留标准输出诊断，convert不运行。"""
    files = fake_converter(tmp_path / "tool", verify_code=1)
    result = _failed_conversion(tmp_path, fake_nav, files)
    assert result.progress is not None and result.progress.stage_index == 2
    assert files.program.with_suffix(".calls").read_text() == "verify\n"
    assert any(
        "话题核对：缺少右臂目标" in obj.value
        for group in result.diagnostics
        for sample in group.samples
        for obj in sample.objects
    )


def _failed_conversion(tmp_path: Path, fake_nav: FakeNavigation, files: ToolFiles) -> JobRecord:
    """仅替换沙箱边界，执行器负责把异常变成持久化失败结果。"""
    output = tmp_path / "output"
    output.mkdir()
    with dataset_case(tmp_path / "index", fake_nav) as scan:
        scan.run()
        dependencies = ConversionDependencies(
            scan.engine,
            settings(files),
            (
                *fake_nav.storage_roots,
                StorageRootConfig(
                    name="output", path=output, nfs_export="server:/output", writable=True
                ),
            ),
            no_sandbox,
        )
        dependencies = replace(dependencies, storage=storage_checker(dependencies.roots))
        parameters = ConversionParameters(
            dataset_id="dataset-35",
            source_ids=["src_01e0bc7e9cc8"],
            robot_model="Galaxea R1 Lite",
            output_format="v3.0",
        )

        def execute(context: ExecutionContext) -> None:
            ConversionExecutor("mcap2lerobot", dependencies).execute(
                replace(context, parameters=parameters)
            )

        with execution_case(tmp_path / "state", {"steps": 1, "interval_ms": 0}, execute) as (
            work,
            deps,
            signals,
        ):
            result = execute_job(work, deps, signals)
            assert result is not None and result.summary is not None
            assert result.summary.outcome is JobOutcome.FAILED
            assert all(not thread.is_alive() for thread in signals.monitor.threads)
            return result


def _observing_clock(
    clock: JobClock, signals: ExecutionSignals, stages: list[tuple[int, int, str]]
) -> JobClock:
    """在时钟边界读取公开快照，避免轮询漏过短阶段，也不替换进度上报。"""

    def observe_now() -> datetime:
        reporter = signals.monitor.reporter
        progress = reporter.snapshot().progress if reporter is not None else None
        if progress is not None:
            stage = (progress.stage_index, progress.stage_count, progress.stage_name)
            if not stages or stages[-1] != stage:
                stages.append(stage)
        return clock.now()

    return JobClock(observe_now, clock.monotonic)
