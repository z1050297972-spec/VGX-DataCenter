"""清洗进度回归：通过真实执行上下文和上报器校验累计事实，只使用临时库。"""

from contextlib import ExitStack
from dataclasses import replace
from pathlib import Path

import pytest
from agibot_preview_support import agibot_case, preview_result
from cleaning_progress_support import silent_preview_clock
from g2_platform_support import archives, g2_case
from jobs_execution_support import execution_case
from jobs_progress_support import MutableClock

# 工单09明确指定这两个内部进度适配边界，必须连接真实上报器验证累计约束。
from rdp.jobs.cleaning.job import _ReadingProgress, _stage  # pyright: ignore[reportPrivateUsage]
from rdp.jobs.execution import ExecutionContext, execute_job
from rdp.jobs.outcome import JobOutcome
from rdp.jobs.types import JobClock, JobProgress, JobState


@pytest.mark.parametrize(
    ("counts", "files", "expected_total"),
    [((0, 0, 1), 0, 0), ((7, 2, 0), 3, 7), ((7, 2, 1), 9, 9), ((0, 0, 0), 3, 3)],
)
def test_report_stage_preserves_cumulative_counts(
    tmp_path: Path,
    counts: tuple[int, int, int],
    files: int,
    expected_total: int,
) -> None:
    """阶段3→4可重置局部done，但警告/失败不清零，总条目只按更大的报告计数更新。"""
    total_items, failed_items, warning_count = counts
    clock = MutableClock()

    def execute(context: ExecutionContext) -> None:
        context.reporter.report(
            JobProgress(
                stage_index=3,
                stage_count=4,
                stage_name="读取文件",
                done=1,
                total=None,
                unit="项",
                warning_count=warning_count,
                failed_items=failed_items,
                total_items=total_items,
            )
        )
        _stage(context, 4, files=files)

    with execution_case(tmp_path, {"steps": 1, "interval_ms": 0}, execute) as (
        work,
        deps,
        signals,
    ):
        result = execute_job(
            work, replace(deps, clock=JobClock(clock.now, clock.monotonic)), signals
        )
        assert result is not None and result.summary is not None
        assert not result.summary.aborted
        assert result.progress is not None
        assert (result.progress.stage_index, result.progress.done, result.progress.total) == (
            4,
            0,
            None,
        )
        assert (
            result.summary.total_items,
            result.summary.failed_items,
            result.summary.warning_count,
        ) == (expected_total, failed_items, warning_count)


@pytest.mark.parametrize("g2", [False, True], ids=["alpha", "g2"])
def test_silent_preview_persists_report_with_warning(tmp_path: Path, g2: bool) -> None:
    """两类工具真实终端降级后退出0，累计警告保留到报告事务，结果为带警告成功。"""
    with ExitStack() as stack:
        if g2:
            case = stack.enter_context(g2_case(tmp_path, archives(tmp_path / "input")))
            source_ids = ("source-preview", "source-1", "source-2")
        else:
            payload = preview_result(tmp_path / "input/observations/327")
            case = stack.enter_context(agibot_case(tmp_path, payload))
            source_ids = ("source-preview",)
        result = case.run(source_ids, clock=silent_preview_clock(case))
        assert result.summary is not None
        assert result.summary.tool_exit_code == 0
        assert result.summary.warning_count == 1
        assert len(result.diagnostics) == 1 and result.diagnostics[0].warning_count == 1
        assert result.state is JobState.COMPLETED
        assert result.summary.outcome is JobOutcome.SUCCEEDED_WITH_WARNINGS
        assert not result.summary.aborted
        preview = case.preview()
        assert preview.job_id == result.job_id
        assert preview.report.summary.files == 3
        assert preview.report.source_format == ("agibot_lerobot21" if g2 else "agibot_native")
        assert result.progress is not None and result.progress.stage_index == 4
        assert result.summary.total_items == 3 and result.summary.failed_items == 0
        assert not (case.cache / "preview-71.json").exists()


@pytest.mark.parametrize(("total_items", "failed_items", "warning_count"), [(0, 0, 1), (7, 2, 0)])
def test_reading_preserves_latest_cumulative_counts(
    tmp_path: Path, total_items: int, failed_items: int, warning_count: int
) -> None:
    """读取开始、字节推进和换文件均保留最新累计值，包括适配器创建后新增的警告。"""
    clock = MutableClock()

    def execute(context: ExecutionContext) -> None:
        context.reporter.report(
            JobProgress(
                stage_index=3,
                stage_count=4,
                stage_name="读取文件",
                done=0,
                total=None,
                unit="字节",
                total_items=total_items,
                failed_items=failed_items,
                warning_count=warning_count,
            )
        )
        reading = _ReadingProgress(context)
        reading.start_file(1, 2, 10)
        reading.bytes_read(4)
        latest = context.reporter.snapshot().progress
        assert latest is not None
        context.reporter.report(latest.model_copy(update={"warning_count": warning_count + 1}))
        reading.start_file(2, 2, 10)
        reading.bytes_read(8)

    with execution_case(tmp_path, {"steps": 1, "interval_ms": 0}, execute) as (
        work,
        deps,
        signals,
    ):
        result = execute_job(
            work, replace(deps, clock=JobClock(clock.now, clock.monotonic)), signals
        )
        assert result is not None and result.summary is not None
        assert not result.summary.aborted
        assert result.progress is not None
        assert (result.progress.stage_index, result.progress.done, result.progress.total) == (
            3,
            8,
            10,
        )
        assert (
            result.summary.total_items,
            result.summary.failed_items,
            result.summary.warning_count,
        ) == (total_items, failed_items, warning_count + 1)
