"""G2 平台常规回归：临时假工具、固定真实报告格式，不读取本机工具或数据。"""

from pathlib import Path

import pytest
from g2_platform_support import MODEL, archives, g2_case
from tool_registry_support import isolated_tool_cache as isolated_tool_cache

from rdp.infra.diagnostics import InputError
from rdp.jobs.conversion._cleaning import check_files
from rdp.jobs.conversion._cleaning_selection import select
from rdp.jobs.conversion.parameters import ConversionParameters, EpisodeSelection
from rdp.jobs.errors import JobInputError, JobNotFoundError
from rdp.jobs.outcome import JobOutcome
from rdp.jobs.types import JobState


def parameters() -> ConversionParameters:
    """最终剔除来自固定报告：坏归档2、归档0的致命源集0；其余三个源集保留。"""
    return ConversionParameters(
        dataset_id="dataset-preview",
        source_ids=["source-preview", "source-1", "source-2"],
        robot_model=MODEL,
        cleaning_preview_job_id=71,
        excluded_files=[2],
        excluded_episodes=[EpisodeSelection(file_index=0, segment_index=0)],
    )


def test_g2_report_selection_and_changed_input(tmp_path: Path) -> None:
    """真实 worker 保存归档/源集身份；致命归档和集不可保留；归档变化后必须重新预览。"""
    paths = archives(tmp_path / "input")
    with g2_case(tmp_path, paths) as case:
        result = case.run(tuple(parameters().source_ids))
        assert result.summary is not None and result.summary.outcome is JobOutcome.SUCCEEDED
        preview = case.preview()
        assert preview.report.source_format == "agibot_lerobot21"
        assert [(e.file_index, e.segment_index) for e in preview.report.episodes] == [
            (0, 0),
            (0, 1),
            (1, 0),
            (1, 1),
        ]
        assert all(
            e.start_time_s is None and e.stamp_span_s is None for e in preview.report.episodes
        )
        for field in ("excluded_files", "excluded_episodes"):
            with pytest.raises(JobInputError):
                select(preview, parameters().model_copy(update={field: []}))
        selection = select(preview, parameters())
        assert selection.excluded_indices == (0,)
        assert [file.path for file in selection.files] == list(map(str, paths[:2]))
        check_files(selection, lambda: False)
        paths[1].write_bytes(b"changed")
        with pytest.raises(InputError):
            check_files(selection, lambda: False)


@pytest.mark.parametrize("failure", ["cancelled", "nonzero"])
def test_failed_or_cancelled_g2_has_no_preview(tmp_path: Path, failure: str) -> None:
    """结果文件存在也不能覆盖非零退出或取消；不保存可供转换和入库的预览。"""
    paths = archives(tmp_path / "input")
    with g2_case(tmp_path, paths, exit_code=int(failure == "nonzero")) as case:
        result = case.run(
            tuple(parameters().source_ids), cancel_after_result=failure == "cancelled"
        )
        assert (
            result.state is JobState.CANCELLED
            if failure == "cancelled"
            else (result.summary is not None and result.summary.outcome is JobOutcome.FAILED)
        )
        with pytest.raises(JobNotFoundError):
            case.preview()


def test_cross_task_g2_never_starts_tool(tmp_path: Path) -> None:
    """不同任务的登记数据块即使都是归档，worker 也在执行临时程序前拒绝。"""
    paths = archives(tmp_path / "input")
    other = tmp_path / "input/task_43"
    other.mkdir()
    moved = paths[1].rename(other / paths[1].name)
    with g2_case(tmp_path, (paths[0], moved)) as case:
        result = case.run(("source-preview", "source-1"))
        assert result.summary is not None and result.summary.outcome is JobOutcome.FAILED
        assert not case.sandbox_calls
