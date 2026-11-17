"""双根 worker 集成：真实临时库、导航事务与子进程，验证检查、入库和删除只使用 B。"""

import json
import time
from dataclasses import replace
from pathlib import Path
from threading import Event, Lock

import pytest
from conversion_ingest_support import product
from conversion_support import storage_checker
from creation_support import creation_case
from jobs_scheduling_support import claim_fixture, resources_fixture
from jobs_storage_support import NOW, job_row
from nav_manifest import FakeNavigation
from sqlalchemy import select

from rdp.infra.config import StorageRootConfig
from rdp.infra.db.connection import session_scope
from rdp.jobs.conversion.ingest_models import APPLY_TYPE, CHECK_TYPE, DELETE_TYPE
from rdp.jobs.execution import ExecutionWork, ExecutorDependencies, execute_job
from rdp.jobs.models import JobRow
from rdp.jobs.navwrite.pipeline import NavWriteDependencies
from rdp.jobs.progress import ExecutionMonitor, ExecutionSignals
from rdp.jobs.records import claim_job
from rdp.jobs.registry import JobRegistry, production_registry
from rdp.jobs.types import ExecutionMode, JobClock, JobRecord, JobState


def _run(
    deps: NavWriteDependencies, identifier: int, registry: JobRegistry | None = None
) -> JobRecord:
    """只走公开的领取和执行接口，保留真实导航锁与进程生命周期。"""
    registry = registry or production_registry(deps.rescan, deps)
    with session_scope(deps.rescan.engine) as session:
        record = claim_job(session, identifier, now=NOW, paths=deps.paths, gpu_index=None)
    execution = ExecutorDependencies(
        deps.rescan.engine,
        registry,
        deps.paths,
        JobClock(lambda: NOW, time.monotonic),
        resources=resources_fixture(registry),
        storage=deps.rescan.storage,
    )
    result = execute_job(
        ExecutionWork(record, ExecutionMode.FRESH, None, claim=claim_fixture(record, execution)),
        execution,
        ExecutionSignals(Event(), Event(), ExecutionMonitor([], None, Lock())),
    )
    assert result is not None and result.summary is not None
    assert not result.summary.aborted, result.diagnostics
    return result


def _seed(deps: NavWriteDependencies, dataset: str, *, legacy: bool) -> Path:
    """历史样本只有 B 实际路径；新样本另带 output_root，回执来自固定已知事实。"""
    stage = product(deps.rescan.roots[-1].path / "暂存/转换/60/cleaned")
    receipt = {
        "job_id": 60,
        "exit_code": 0,
        "output_root": {"name": "b", "path": str(deps.rescan.roots[-1].path)},
        "tool": {"name": "mcap2lerobot", "version": "1", "binary_sha256": "f" * 64},
        "configuration": {"filename": "config.toml", "content": "config", "sha256": "c" * 64},
        "inputs": [
            {
                "dataset_id": dataset,
                "source_id": "source-1",
                "path": str(stage.parent / "input.mcap"),
            }
        ],
    }
    (stage.parent / "转换回执.json").write_text(json.dumps(receipt))
    with session_scope(deps.rescan.engine) as session:
        row = job_row(JobState.COMPLETED, job_id=60)
        row.type_name = "convert_mcap2lerobot"
        row.parameters = {
            "dataset_id": dataset,
            "source_ids": ["source-1"],
            "output_format": "v3.0",
            "robot_model": "r1lite",
        }
        if not legacy:
            row.parameters = {**row.parameters, "output_root": "b"}
        row.outcome = "succeeded"
        row.failed_items = row.warning_count = 0
        row.artifacts = [str(stage.parent), str(stage)]
        assert row.progress is not None and row.summary is not None
        progress = {
            **row.progress,
            "failed_items": 0,
            "warning_count": 0,
            "conversion": {
                "output_path": str(stage),
                "total_episodes": 5,
                "total_frames": 1647,
                "codebase_version": "v3.0",
            },
        }
        if legacy:
            progress = {key: value for key, value in progress.items() if key != "conversion"}
        row.progress = progress
        row.summary = {
            **row.summary,
            "outcome": "succeeded",
            "failed_items": 0,
            "warning_count": 0,
            "progress": row.progress,
            "artifacts": row.artifacts,
        }
        session.add(row)
    return stage


@pytest.mark.parametrize("legacy", [False, True])
@pytest.mark.parametrize("action", ["ingest", "delete"])
def test_selected_or_legacy_b_survives_root_order(
    tmp_path: Path, fake_nav: FakeNavigation, legacy: bool, action: str
) -> None:
    """选 B 或历史 B 产物：重排配置后检查/入库/血缘与删除始终在 B，A 不产生目录。"""
    with creation_case(tmp_path, fake_nav) as harness:
        harness.case.run()
        roots = tuple(
            StorageRootConfig(
                name=name, path=tmp_path / name, writable=True, nfs_export=f"nas:/{name}"
            )
            for name in ("a", "b")
        )
        for root in roots:
            root.path.mkdir()
        scanning = replace(
            harness.dependencies.rescan,
            roots=(*fake_nav.storage_roots, *roots),
            storage=storage_checker((*fake_nav.storage_roots, *roots)),
        )
        deps = replace(harness.dependencies, rescan=scanning)
        stage = _seed(deps, harness.dataset, legacy=legacy)
        # 历史和新记录分别在相反顺序执行，不能依赖首个可写根。
        ordered = scanning.roots if legacy else (*fake_nav.storage_roots, *roots[::-1])
        deps = replace(
            deps, rescan=replace(scanning, roots=ordered, storage=storage_checker(ordered))
        )
        submitted = deps.service.submit_system(
            CHECK_TYPE if action == "ingest" else DELETE_TYPE,
            {"conversion_job_id": 60, **({"automatic": True} if action == "ingest" else {})},
            now=NOW,
        )
        checked = _run(deps, submitted.job_id)
        if action == "ingest":
            _assert_ingested(deps, checked, roots[1].path, fake_nav)
        assert not stage.exists()
        assert list(roots[0].path.iterdir()) == []


def _assert_ingested(
    deps: NavWriteDependencies, checked: JobRecord, root: Path, fake: FakeNavigation
) -> None:
    """检查报告、正式产物和两视图血缘都来源于 B 的实际转换。"""
    assert checked.progress is not None and checked.progress.ingest_check is not None
    assert checked.progress.ingest_check.report.result == "通过"
    with session_scope(deps.rescan.engine, read_only=True) as session:
        apply_id = session.scalar(select(JobRow.job_id).where(JobRow.type_name == APPLY_TYPE))
    assert apply_id is not None
    _run(deps, apply_id)
    target = root / "转换/EgoProDemo_lerobot"
    assert target.is_dir()
    for entry in ("按任务/EgoProDemo_lerobot", "按格式/lerobot/3.0/EgoProDemo_lerobot"):
        assert (fake.nav_root / entry / "原始数据").readlink() == target
    lineage = json.loads((fake.nav_root / "按任务/EgoProDemo_lerobot/来源.json").read_text())[
        "lineage"
    ][0]
    assert lineage["job_id"] == 60 and lineage["tool"]["binary_sha256"] == "f" * 64


@pytest.mark.parametrize("legacy", [False, True])
def test_registered_worker_fixes_output_before_execution(
    tmp_path: Path, fake_nav: FakeNavigation, legacy: bool
) -> None:
    """新提交根不随 worker 配置排序改变；无实际产物的旧排队作业在执行边界固化根。"""
    from conversion_cleaning_support import seed_preview
    from conversion_support import fake_converter, no_sandbox, settings

    from rdp.jobs.conversion.job import ConversionDependencies
    from rdp.jobs.conversion.parameters import ConversionParameters
    from rdp.jobs.conversion.registration import register_conversion_jobs
    from rdp.jobs.service import JobService

    files = fake_converter(tmp_path / "tool")
    manifest = files.package / "tool.toml"
    manifest.write_text(manifest.read_text().replace("needs_gpu = true", "needs_gpu = false"))
    roots = tuple(
        StorageRootConfig(name=name, path=tmp_path / name, writable=True, nfs_export=f"nas:/{name}")
        for name in ("a", "b")
    )
    for root in roots:
        root.path.mkdir()
    with creation_case(tmp_path, fake_nav) as harness:
        harness.case.run()
        registry = production_registry()
        register_conversion_jobs(registry, settings(files), roots, None)
        service = JobService(harness.case.engine, registry)
        parameters = seed_preview(
            harness.case.engine,
            files,
            ConversionParameters(
                dataset_id="dataset-35",
                source_ids=["src_01e0bc7e9cc8"],
                robot_model="Galaxea R1 Lite",
            ),
        )
        submitted = service.submit_system(
            "convert_mcap2lerobot", parameters.model_dump(mode="json"), now=NOW
        )
        assert submitted.parameters["output_root"] == "a"
        if legacy:
            with session_scope(harness.case.engine) as session:
                row = session.get(JobRow, submitted.job_id)
                assert row is not None
                row.parameters = {
                    key: value for key, value in row.parameters.items() if key != "output_root"
                }
        ordered = (*fake_nav.storage_roots, *roots[::-1])
        scanning = replace(harness.case.scanning, roots=ordered, storage=storage_checker(ordered))
        deps = replace(harness.dependencies, rescan=scanning)
        worker = production_registry(scanning, deps)
        register_conversion_jobs(
            worker,
            settings(files),
            ordered,
            ConversionDependencies(
                harness.case.engine,
                settings(files),
                ordered,
                no_sandbox,
                storage=storage_checker(ordered),
            ),
        )
        result = _run(deps, submitted.job_id, worker)
        expected = "b" if legacy else "a"
        assert result.parameters["output_root"] == expected
        assert result.progress is not None and result.progress.conversion is not None
        assert result.progress.conversion.output_path == str(
            tmp_path / expected / "暂存/转换" / str(submitted.job_id) / "out"
        )
        assert list((tmp_path / ("a" if legacy else "b")).iterdir()) == []
