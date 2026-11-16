"""08 票真实 G2 CLI 验收；factory 和程序只读，输入/数据库/产物均在临时目录。"""

# ruff: noqa: S101  # 理由：显式手动验收用断言核对结果，不作为生产输入校验。

import json
from pathlib import Path

import pytest
from _g2_real_support import MODEL, archives, convert, g2_case

from rdp.jobs.conversion._cleaning_selection import select
from rdp.jobs.conversion.check import check_output
from rdp.jobs.conversion.parameters import ConversionParameters, EpisodeSelection
from rdp.jobs.errors import JobInputError
from rdp.jobs.outcome import JobOutcome
from tests.tool_registry_support import isolated_tool_cache as isolated_tool_cache


def parameters() -> ConversionParameters:
    """最终剔除的身份来自真实报告：b 的源集 0 致命，其余三个源集保留。

    Args:
        无。

    Returns:
        验收结果；测试函数无返回值。

    Raises:
        AssertionError: 真实 CLI、报告、产物或平台行为不满足验收契约。

    Side Effects:
        仅在演练临时目录写输入、报告、DB 和产物，调用真实工具。

    Time Semantics:
        按同步作业顺序运行，工具超时沿用平台受管进程预算。
    """
    return ConversionParameters(
        dataset_id="dataset-preview",
        source_ids=["source-preview", "source-1"],
        robot_model=MODEL,
        cleaning_preview_job_id=71,
        excluded_episodes=[EpisodeSelection(file_index=0, segment_index=0)],
        space_reserve_gib=0,
    )


def test_real_preview_native_exclusion_and_source_mapping(tmp_path: Path) -> None:
    """合成归档经真实报告→剔除致命集→原生转换→四层检查；重复源号和 metadata 不错位。

    Args:
        tmp_path: 本次演练的临时目录或导航夹具。

    Returns:
        验收结果；测试函数无返回值。

    Raises:
        AssertionError: 真实 CLI、报告、产物或平台行为不满足验收契约。

    Side Effects:
        仅在演练临时目录写输入、报告、DB 和产物，调用真实工具。

    Time Semantics:
        按同步作业顺序运行，工具超时沿用平台受管进程预算。
    """
    paths = archives(tmp_path / "input")
    with g2_case(tmp_path, paths) as case:
        result = case.run(("source-preview", "source-1"))
        assert result.summary is not None and result.summary.outcome is JobOutcome.SUCCEEDED
        preview = case.preview()
        report = preview.report
        assert report.source_format == "agibot_lerobot21"
        assert [file.path for file in report.files] == list(map(str, paths))
        assert [(e.file_index, e.segment_index) for e in report.episodes] == [
            (0, 0),
            (0, 1),
            (1, 0),
            (1, 1),
        ]
        assert report.episodes[0].fatal_issues and report.episodes[0].default_action == "exclude"
        assert all(e.stamp_span_s is None and e.start_time_s is None for e in report.episodes)
        with pytest.raises(JobInputError):
            select(preview, parameters().model_copy(update={"excluded_episodes": []}))
        converted = convert(tmp_path, case, parameters())
        assert converted.summary is not None and converted.summary.outcome is JobOutcome.SUCCEEDED
        stage = tmp_path / "output/暂存/转换/71"
        assert json.loads((stage / "exclude.json").read_text()) == [
            {"archive": str(paths[0]), "episode_index": 0}
        ]
        mapping = [
            json.loads(line)
            for line in (stage / "out/meta/agibot_episodes.jsonl").read_text().splitlines()
        ]
        assert [(row["source_archive"], row["source_episode_index"]) for row in mapping] == [
            ("b.tar.gz", 1),
            ("a.tar.gz", 0),
            ("a.tar.gz", 1),
        ]
        assert [row["instruction_segments"]["episode"] for row in mapping] == [1, 0, 1]
        receipt = json.loads((stage / "转换回执.json").read_text())
        assert receipt["cleaning"]["native_exclusion"]
        assert receipt["cleaning"]["task"] == "task_42"
        assert receipt["cleaning"]["lerobot_version"] is None
        assert receipt["cleaning"]["excluded_episodes"][0]["source_archive"] == str(paths[0])
        checked = check_output(stage / "out", "v3.0")
        assert checked.result == "通过", checked.model_dump_json()


def test_changed_archive_rejected_before_staging(tmp_path: Path) -> None:
    """归档预览后变动，即使仍是普通 tar.gz 也不得启动转换或创建暂存。

    Args:
        tmp_path: 本次演练的临时目录或导航夹具。

    Returns:
        验收结果；测试函数无返回值。

    Raises:
        AssertionError: 真实 CLI、报告、产物或平台行为不满足验收契约。

    Side Effects:
        仅在演练临时目录写输入、报告、DB 和产物，调用真实工具。

    Time Semantics:
        按同步作业顺序运行，工具超时沿用平台受管进程预算。
    """
    paths = archives(tmp_path / "input")
    with g2_case(tmp_path, paths) as case:
        preview_result = case.run(("source-preview", "source-1"))
        assert (
            preview_result.summary is not None
            and preview_result.summary.outcome is JobOutcome.SUCCEEDED
        )
        with paths[1].open("ab") as stream:
            stream.write(b"changed")
        result = convert(tmp_path, case, parameters())
        assert result.summary is not None and result.summary.outcome is JobOutcome.FAILED
        assert not (tmp_path / "output/暂存").exists()


def test_cross_task_selection_rejected(tmp_path: Path) -> None:
    """同属 archives 但跨 task 目录的数据块在提交输入校验处拒绝。

    Args:
        tmp_path: 本次演练的临时目录或导航夹具。

    Returns:
        验收结果；测试函数无返回值。

    Raises:
        AssertionError: 真实 CLI、报告、产物或平台行为不满足验收契约。

    Side Effects:
        仅在演练临时目录写输入、报告、DB 和产物，调用真实工具。

    Time Semantics:
        按同步作业顺序运行，工具超时沿用平台受管进程预算。
    """
    paths = archives(tmp_path / "input")
    other = tmp_path / "input/task_43"
    other.mkdir()
    moved = paths[1].rename(other / paths[1].name)
    with g2_case(tmp_path, (paths[0], moved)) as case:
        result = case.run(("source-preview", "source-1"))
        assert result.summary is not None and result.summary.outcome is JobOutcome.FAILED
        assert any(
            item.rule == "cleaning.g2_inputs"
            for group in result.diagnostics
            for item in group.samples
        )
        assert not case.sandbox_calls


def test_real_g2_ingest_preserves_lineage(tmp_path: Path) -> None:
    """真实报告和产物完成四层检查、持锁入库，两视图建链，规范副本血缘保留归档、源集剔除和完整身份。

    Args:
        tmp_path: 本次演练的临时目录或导航夹具。

    Returns:
        验收结果；测试函数无返回值。

    Raises:
        AssertionError: 真实 CLI、报告、产物或平台行为不满足验收契约。

    Side Effects:
        仅在演练临时目录写输入、报告、DB 和产物，调用真实工具。

    Time Semantics:
        按同步作业顺序运行，工具超时沿用平台受管进程预算。
    """
    from _g2_chain import run_chain

    run_chain(tmp_path)


def test_bad_archive_is_visible_and_excluded_from_conversion(tmp_path: Path) -> None:
    """真实坏 tar 仍生成完整成功报告；必须剔整归档，转换只接收剩余归档。

    Args:
        tmp_path: 本次演练的临时目录或导航夹具。

    Returns:
        验收结果；测试函数无返回值。

    Raises:
        AssertionError: 真实 CLI、报告、产物或平台行为不满足验收契约。

    Side Effects:
        仅在演练临时目录写输入、报告、DB 和产物，调用真实工具。

    Time Semantics:
        按同步作业顺序运行，工具超时沿用平台受管进程预算。
    """
    paths = archives(tmp_path / "input")
    bad = paths[0].parent / "bad.tar.gz"
    bad.write_bytes(b"not gzip")
    with g2_case(tmp_path, (*paths, bad)) as case:
        result = case.run(("source-preview", "source-1", "source-2"))
        assert result.summary is not None and result.summary.outcome is JobOutcome.SUCCEEDED
        preview = case.preview()
        assert preview.report.files[2].fatal_issues
        options = parameters().model_copy(
            update={"source_ids": ["source-preview", "source-1", "source-2"]}
        )
        with pytest.raises(JobInputError):
            select(preview, options)
        options = options.model_copy(update={"excluded_files": [2]})
        result = convert(tmp_path, case, options)
        assert result.summary is not None and result.summary.outcome is JobOutcome.SUCCEEDED
        receipt = json.loads((tmp_path / "output/暂存/转换/71/转换回执.json").read_text())
        assert str(bad) not in receipt["commands"]["convert"]
        assert receipt["cleaning"]["excluded_files"][0]["path"] == str(bad)


def test_g2_cancelled_preview_has_no_saved_report(tmp_path: Path) -> None:
    """真实 CLI 写出结果后取消，平台不保存报告，也不产生可入库回执。

    Args:
        tmp_path: 本次演练的临时目录或导航夹具。

    Returns:
        验收结果；测试函数无返回值。

    Raises:
        AssertionError: 真实 CLI、报告、产物或平台行为不满足验收契约。

    Side Effects:
        仅在演练临时目录写输入、报告、DB 和产物，调用真实工具。

    Time Semantics:
        按同步作业顺序运行，工具超时沿用平台受管进程预算。
    """
    from rdp.jobs.errors import JobNotFoundError
    from rdp.jobs.types import JobState

    paths = archives(tmp_path / "input")
    with g2_case(tmp_path, paths) as case:
        result = case.run(("source-preview", "source-1"), cancel_after_result=True)
        assert result.state is JobState.CANCELLED
        with pytest.raises(JobNotFoundError):
            case.preview()
        assert not (tmp_path / "output").exists()


def test_g2_mapping_mismatch_with_equal_lengths_is_rejected(tmp_path: Path) -> None:
    """等长源集换位后帧数仍正确，平台必须凭 archive+source_episode_index 拒绝产物。

    Args:
        tmp_path: 本次演练的临时目录或导航夹具。

    Returns:
        验收结果；测试函数无返回值。

    Raises:
        AssertionError: 真实 CLI、报告、产物或平台行为不满足验收契约。

    Side Effects:
        仅在演练临时目录写输入、报告、DB 和产物，调用真实工具。

    Time Semantics:
        按同步作业顺序运行，工具超时沿用平台受管进程预算。
    """
    from rdp.jobs.conversion._cleaning import check_output as check_selection_output
    from rdp.jobs.execution import ExecutionContext, execute_job
    from tests.jobs_execution_support import execution_case

    paths = archives(tmp_path / "input")
    with g2_case(tmp_path, paths) as case:
        case.run(("source-preview", "source-1"))
        result = convert(tmp_path, case, parameters())
        assert result.summary is not None and result.summary.outcome is JobOutcome.SUCCEEDED
    stage = tmp_path / "output/暂存/转换/71"
    mapping = stage / "out/meta/agibot_episodes.jsonl"
    rows = [json.loads(line) for line in mapping.read_text().splitlines()]
    rows[1]["source_episode_index"], rows[2]["source_episode_index"] = 1, 0
    mapping.write_text("".join(json.dumps(row) + "\n" for row in rows))
    scratch = tmp_path / "mapping-check"
    scratch.mkdir()

    def execute(context: ExecutionContext) -> None:
        check_selection_output(
            context,
            scratch,
            stage / "out",
            (5, 5, 5),
            source_episodes=(("b.tar.gz", 1), ("a.tar.gz", 0), ("a.tar.gz", 1)),
        )

    with execution_case(tmp_path / "mapping-state", {"steps": 1, "interval_ms": 0}, execute) as (
        work,
        deps,
        signals,
    ):
        checked = execute_job(work, deps, signals)
        assert (
            checked is not None
            and checked.summary is not None
            and checked.summary.outcome is JobOutcome.FAILED
        )
        assert any(
            item.rule == "cleaning.output_mismatch"
            for group in checked.diagnostics
            for item in group.samples
        )


def test_noncontinuous_source_episode_exclusion(tmp_path: Path) -> None:
    """真实归档含源集0、7时，排除7必须原生跳过7，不能解释为第七个连续产物编号。

    Args:
        tmp_path: 本次演练的临时目录或导航夹具。

    Returns:
        验收结果；测试函数无返回值。

    Raises:
        AssertionError: 真实 CLI、报告、产物或平台行为不满足验收契约。

    Side Effects:
        仅在演练临时目录写输入、报告、DB 和产物，调用真实工具。

    Time Semantics:
        按同步作业顺序运行，工具超时沿用平台受管进程预算。
    """
    from _g2_archive_variants import sparse_episode

    paths = archives(tmp_path / "input")
    sparse_episode(paths[1])
    with g2_case(tmp_path, paths) as case:
        previewed = case.run(("source-preview", "source-1"))
        assert previewed.summary is not None and previewed.summary.outcome is JobOutcome.SUCCEEDED
        assert [e.segment_index for e in case.preview().report.episodes if e.file_index == 1] == [
            0,
            7,
        ]
        options = parameters().model_copy(
            update={
                "excluded_episodes": [
                    EpisodeSelection(file_index=0, segment_index=0),
                    EpisodeSelection(file_index=1, segment_index=7),
                ]
            }
        )
        result = convert(tmp_path, case, options)
        assert result.summary is not None and result.summary.outcome is JobOutcome.SUCCEEDED
        stage = tmp_path / "output/暂存/转换/71"
        rows = [
            json.loads(line)
            for line in (stage / "out/meta/agibot_episodes.jsonl").read_text().splitlines()
        ]
        assert [(row["source_archive"], row["source_episode_index"]) for row in rows] == [
            ("b.tar.gz", 1),
            ("a.tar.gz", 0),
        ]
