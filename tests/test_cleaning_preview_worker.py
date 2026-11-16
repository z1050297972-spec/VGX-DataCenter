"""无需 HTTP 的 MCAP 预览作业回归，核对新分支不影响原有读取和保存链路。"""

from pathlib import Path

from agibot_preview_support import AgibotPreviewCase, seed_inputs
from cleaning_support import CONFIG, RULES, write_scene
from conversion_support import storage_checker
from jobs_storage_support import job_database
from tool_registry_support import tool_files

from rdp.infra.config import StorageRootConfig, ToolsConfig
from rdp.jobs.cleaning.job import CleaningDependencies
from rdp.jobs.cleaning.registration import register_cleaning_jobs
from rdp.jobs.outcome import JobOutcome
from rdp.jobs.registry import JobRegistry


def test_mcap_worker_keeps_existing_preview_path(tmp_path: Path) -> None:
    """没有 preview 模板的工具继续在平台读 MCAP，保存原有帧数、规则和格式，不创建工具缓存。"""
    storage = tmp_path / "input"
    storage.mkdir()
    source = storage / "sample.mcap"
    write_scene(source)
    files = tool_files(tmp_path / "tool")
    (files.package / "configs/r1lite.toml").write_text(CONFIG)
    (files.package / "cleaning/r1lite.toml").write_text(RULES)
    settings = ToolsConfig(
        registry_dir=files.registry, library_root=files.library, cache_root=tmp_path / "cache"
    )
    roots = (StorageRootConfig(name="input", path=storage, nfs_export="server:/input"),)
    with job_database(tmp_path / "state") as (engine, paths):
        seed_inputs(engine, (source,), input_format="mcap")
        registry = JobRegistry()
        register_cleaning_jobs(
            registry,
            settings,
            CleaningDependencies(engine, settings, roots, storage_checker(roots)),
        )
        case = AgibotPreviewCase(
            engine,
            paths,
            registry,
            settings,
            source,
            [],
            "",
            tool_name="mcap2lerobot",
            robot_model="Galaxea R1 Lite",
        )
        result = case.run()
        assert result.summary is not None and result.summary.outcome is JobOutcome.SUCCEEDED
        report = case.preview().report
        assert report.source_format == "mcap"
        assert report.summary.files == report.summary.episodes == 1
        assert report.summary.reference_frames == report.summary.kept_frames == 120
        assert report.rules.sync is not None
        assert report.files[0].episode_id is None
        assert not case.cache.exists()
