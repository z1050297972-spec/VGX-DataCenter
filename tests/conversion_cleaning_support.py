"""M4.5 的成功预览快照和假 LeRobot；只在临时根生成文件，不运行外部真实环境。"""

import hashlib
import sys
import tomllib
from pathlib import Path

from jobs_storage_support import NOW, job_row
from sqlalchemy import Engine
from tool_registry_support import ToolFiles

from rdp.infra.db.connection import session_scope
from rdp.jobs.cleaning.models import (
    CleaningCheckRules,
    CleaningReport,
    CleaningRuleSnapshot,
    CleaningSummary,
    CleaningSyncRules,
    EpisodeReport,
    FileReport,
)
from rdp.jobs.cleaning.records import CleaningPreview, save_preview
from rdp.jobs.conversion.parameters import ConversionParameters, selected_inputs
from rdp.jobs.types import JobState


def seed_preview(
    engine: Engine,
    files: ToolFiles,
    parameters: ConversionParameters,
    *,
    lengths: tuple[tuple[int, ...], ...] | None = None,
) -> ConversionParameters:
    """已合并预览工单的边界快照；帧数由测试明确给出，不调用转换逻辑生成期望。"""
    with session_scope(engine) as session:
        inputs = selected_inputs(session, parameters)
        paths: list[tuple[str, Path]] = []
        for source_id, path in zip(parameters.source_ids, inputs, strict=True):
            if path.is_dir():
                children = sorted(path.rglob("*.mcap"))
                if not children:
                    child = path / "sample.mcap"
                    child.write_bytes(b"sample")
                    children = [child]
            else:
                children = [path]
            paths.extend((source_id, child) for child in children)
        if lengths is None:
            lengths = ((3, 3),) if len(paths) == 1 else tuple((3,) for _ in paths)
        assert len(lengths) == len(paths)
        file_reports = tuple(
            FileReport(
                file_index=index,
                source_id=source_id,
                path=str(path),
                size_bytes=path.stat().st_size,
                mtime_ns=path.stat().st_mtime_ns,
                fatal_issues=(),
                warnings=(),
                reference_frames=sum(lengths[index]),
                kept_frames=sum(lengths[index]),
                bad_frames=0,
                gaps=0,
                short_segments=0,
                short_frames=0,
                topics=(),
                default_excluded=False,
            )
            for index, (source_id, path) in enumerate(paths)
        )
        episodes = tuple(
            EpisodeReport(
                file_index=index,
                segment_index=segment,
                start_frame=0,
                end_frame=length,
                frame_count=length,
                duration_s=length / 30,
                stamp_span_s=length / 30,
                start_time_s=0,
                issues=(),
                default_action="keep",
            )
            for index, segments in enumerate(lengths)
            for segment, length in enumerate(segments)
        )
        manifest = tomllib.loads((files.package / "tool.toml").read_text())
        configuration = files.package / manifest["models"][parameters.robot_model]
        rules = files.package / manifest["cleaning"][parameters.robot_model]
        config_sha, rules_sha = (
            hashlib.sha256(configuration.read_bytes()).hexdigest(),
            hashlib.sha256(rules.read_bytes()).hexdigest(),
        )
        report = CleaningReport(
            tool_config_sha256=config_sha,
            rules_sha256=rules_sha,
            fps=30,
            reference_topic="/camera",
            rules=CleaningRuleSnapshot(
                sync=CleaningSyncRules(
                    default_tolerance_ms=10,
                    max_frame_gap=1.6,
                    max_frame_gap_ms=53.333,
                    min_episode_frames=1,
                ),
                checks=CleaningCheckRules(
                    static_feature="observation.state",
                    long_static_s=3,
                    jump_feature="action",
                    frozen_s=1,
                    sample_interval_s=1,
                    dark_below=10,
                    bright_above=245,
                    sources=(),
                    severe_checks=(),
                ),
            ),
            files=file_reports,
            episodes=episodes,
            summary=CleaningSummary(
                files=len(paths),
                excluded_files=0,
                episodes=len(episodes),
                excluded_episodes=0,
                reference_frames=sum(item.frame_count for item in episodes),
                kept_frames=sum(item.frame_count for item in episodes),
            ),
        )
        row = job_row(JobState.COMPLETED, job_id=59)
        row.parameters = parameters.model_dump(mode="json")
        row.type_name = "cleaning_preview_mcap2lerobot"
        session.add(row)
        session.flush()
        save_preview(
            session,
            CleaningPreview(
                job_id=59,
                dataset_id=parameters.dataset_id,
                tool_name="mcap2lerobot",
                robot_model=parameters.robot_model,
                binary_sha256=manifest["program"]["sha256"],
                config_sha256=config_sha,
                rules_sha256=rules_sha,
                created_at=NOW,
                report=report,
            ),
        )
    return parameters.model_copy(update={"cleaning_preview_job_id": 59})


def fake_lerobot(root: Path) -> tuple[Path, Path]:
    """解释器替身区分 -c 探测与平台脚本，删除时按传入编号输出最小 v3 元数据。"""
    root.mkdir()
    package = root / "package"
    for name in ("configs", "datasets", "utils"):
        (package / name).mkdir(parents=True)
    (package / "datasets/read.py").write_text("# 假数据集库\n")
    digest = hashlib.sha256(
        b"datasets/read.py\0"
        + hashlib.sha256("# 假数据集库\n".encode()).hexdigest().encode()
        + b"\n"
    ).hexdigest()
    (root / "env.toml").write_text(
        f'schema_version = 1\nversion = "0.6.2"\nfingerprint = "{digest}"\nfingerprint_scope = ["configs", "datasets", "utils"]\n'
    )
    program = root / "python"
    program.write_text(f"""#!{sys.executable}
import json, pathlib, sys, os
import pyarrow as pa
import pyarrow.parquet as pq
assert sys.argv[1:3] == ["-I", "-B"]
assert os.environ["HF_HUB_OFFLINE"] == "1"
assert os.environ["PYTHONDONTWRITEBYTECODE"] == "1"
args = sys.argv[3:]
if args[0] == "-c":
    pathlib.Path(args[2]).write_text(json.dumps({{"version": "0.6.2", "package": {str(package)!r}}}))
else:
    assert pathlib.Path(args[0]).name == "delete_episodes.py"
    source, target = pathlib.Path(args[1]), pathlib.Path(args[2])
    excluded = [int(item) for item in args[3:]]
    pathlib.Path(__file__).with_suffix(".calls").write_text(json.dumps(excluded))
    info = json.loads((source / "meta/info.json").read_text())
    rows = pq.read_table(source / "meta/episodes/chunk-000/file-000.parquet").to_pylist()
    rows = [dict(episode_index=index, length=row["length"]) for index, row in enumerate(row for row in rows if row["episode_index"] not in excluded)]
    (target / "meta/episodes/chunk-000").mkdir(parents=True)
    pq.write_table(pa.Table.from_pylist(rows), target / "meta/episodes/chunk-000/file-000.parquet")
    info.update(total_episodes=len(rows), total_frames=sum(row["length"] for row in rows))
    (target / "meta/info.json").write_text(json.dumps(info))
    print(json.dumps({{"total_episodes": info["total_episodes"], "total_frames": info["total_frames"]}}))
""")
    program.chmod(0o700)
    return program, root
