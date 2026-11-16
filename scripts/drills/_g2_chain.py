"""G2 真实 bwrap 全链路手动演练；只造本地输入、DB 和导航，仅注入 OS 挂载观察。

所有作业共用同一个临时数据库，按生产登记、提交、领取、执行、成功事务前进。
不复制或改写转换终态，不替换沙箱、检查、入库函数，不放宽四层检查。
"""

# ruff: noqa: S101  # 理由：手动验收通过断言阻止不合约结果继续入库，不用于生产输入校验。

import json
import time
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from threading import Event, Lock
from typing import Any

from _g2_real_support import MODEL, TOOL, archives, prepare_tools
from sqlalchemy import Engine, select

from rdp.infra.config import PlatformConfig, StorageRootConfig
from rdp.infra.db.connection import create_database_engine, session_scope
from rdp.infra.db.migration import migrate
from rdp.infra.state import StatePaths, initialize_state, state_paths
from rdp.jobs.cleaning.job import CleaningDependencies
from rdp.jobs.cleaning.records import read_preview
from rdp.jobs.cleaning.registration import register_cleaning_jobs
from rdp.jobs.conversion.ingest_models import APPLY_TYPE, CHECK_TYPE
from rdp.jobs.conversion.job import ConversionDependencies
from rdp.jobs.conversion.registration import register_conversion_jobs
from rdp.jobs.datasets.models import DatasetRow, EntryRow, SourceRow
from rdp.jobs.datasets.rescan import RescanDependencies
from rdp.jobs.execution import ExecutionWork, ExecutorDependencies, execute_job
from rdp.jobs.navwrite.pipeline import NavWriteDependencies
from rdp.jobs.outcome import JobOutcome
from rdp.jobs.progress import ExecutionMonitor, ExecutionSignals
from rdp.jobs.records import claim_job
from rdp.jobs.registry import JobRegistry, production_registry
from rdp.jobs.service import JobService
from rdp.jobs.types import ExecutionMode, JobClock, JobRecord
from tests.conversion_support import storage_checker
from tests.jobs_scheduling_support import claim_fixture, resources_fixture

_DATASET = "dataset-9000001"
_NAME = "G2合成演练"


@dataclass(frozen=True)
class _Harness:
    """仅显式临时资源组成的完整生产装配，不载入实际配置或现存数据库。

    Attributes:
        engine: 只连接本次演练临时数据库的受管引擎。
        paths: 本次新建状态目录及日志路径。
        scanning: 真实导航扫描能力，仅 OS 挂载观察使用合成值。
        dependencies: 真实持锁入库能力，与扫描共用数据库和路径。
        nav: 本次新建导航根的绝对路径。
    """

    engine: Engine
    paths: StatePaths
    scanning: RescanDependencies
    dependencies: NavWriteDependencies
    nav: Path


@contextmanager
def _harness(root: Path) -> Generator[_Harness]:
    """创建真实迁移数据库、读写根和 OS 挂载替身；业务检查保持生产默认。"""
    roots = (
        StorageRootConfig(
            name="output", path=root / "output", writable=True, nfs_export="drill:/output"
        ),
        StorageRootConfig(name="input", path=root / "input", nfs_export="drill:/input"),
    )
    for storage in roots:
        storage.path.mkdir(exist_ok=True)
    nav = root / "nav"
    nav.mkdir()
    paths = state_paths(PlatformConfig(state_dir=root / "state"), ())
    initialize_state(paths)
    migrate(paths, now=_now())
    engine = create_database_engine(paths.database)
    try:
        scanning = RescanDependencies(engine, nav, roots, storage_checker(roots))
        deps = NavWriteDependencies(scanning, paths, JobService(engine, production_registry()))
        yield _Harness(engine, paths, scanning, deps, nav)
    finally:
        engine.dispose()


def _source_navigation(nav: Path, paths: tuple[Path, ...]) -> None:
    """初始化本地合成导航输入，随后由真实扫描器建索引；不伪造任何作业终态。"""
    sample = Path(__file__).parents[2] / "tests/fixtures/nav/samples/nav/按任务/EgoProDemo"
    info: dict[str, Any] = json.loads((sample / "数据集信息.json").read_text())
    info = {
        "dataset_id": _DATASET,
        "title": _NAME,
        "fields": [
            dict(field, value_markdown="本地 factory 合成演练数据") for field in info["fields"]
        ],
        "robot_model": MODEL,
        "fps": 30,
    }
    for relative, view, format_name in (
        (f"按任务/{_NAME}", "task", None),
        (f"按格式/tar、tar.gz（含分卷）/{_NAME}", "format", "archives"),
    ):
        entry = nav / relative
        entry.mkdir(parents=True)
        (entry / "原始数据").symlink_to(paths[0].parent, target_is_directory=True)
        common = {
            "schema_version": 1,
            "dataset_id": _DATASET,
            "dataset_name": _NAME,
            "view": view,
            "format": format_name,
            "version": None,
        }
        originals = dict(
            common,
            dataset_roots=[str(paths[0].parent)],
            links=[
                {
                    "name": "原始数据",
                    "source_path": str(paths[0].parent),
                    "entry_path": f"{relative}/原始数据",
                    "source_type": "directory",
                }
            ],
            sources=[
                {
                    "source_id": f"g2-source-{index}",
                    "original_path": str(path),
                    "direct_path": str(path),
                    "format": "archives",
                    "version": None,
                    "entry_path": f"{relative}/原始数据/{path.name}",
                    "source_role": "data",
                }
                for index, path in enumerate(paths)
            ],
            notes=[],
            source_files_modified=False,
        )
        for filename, value in (
            ("原始路径.json", originals),
            ("数据集信息.json", info),
            ("子任务.json", dict(common, task_count=0, tasks=[])),
        ):
            (entry / filename).write_text(json.dumps(value, ensure_ascii=False))


def _now() -> datetime:
    """演练用真实 UTC 时钟，不依赖真实服务或注入固定终态时间。"""
    return datetime.now(UTC)


def _run(harness: _Harness, registry: JobRegistry, record: JobRecord) -> JobRecord:
    """真实资源领取和执行器；任何失败立即保留诊断并终止链路，绝不降级沙箱。"""
    with session_scope(harness.engine) as session:
        claimed = claim_job(session, record.job_id, now=_now(), paths=harness.paths, gpu_index=None)
    dependencies = ExecutorDependencies(
        harness.engine,
        registry,
        harness.paths,
        JobClock(_now, time.monotonic),
        resources=resources_fixture(registry),
        storage=harness.scanning.storage,
    )
    result = execute_job(
        ExecutionWork(
            claimed, ExecutionMode.FRESH, None, claim=claim_fixture(claimed, dependencies)
        ),
        dependencies,
        ExecutionSignals(Event(), Event(), ExecutionMonitor([], None, Lock())),
    )
    assert result is not None
    assert result.summary is not None and result.summary.outcome is JobOutcome.SUCCEEDED, repr(
        result
    )
    return result


def _registry(harness: _Harness, root: Path) -> JobRegistry:
    """工具与转换均使用生产默认沙箱，只读配置副本和临时合成挂载表。"""
    tools = prepare_tools(root)
    roots = harness.scanning.roots
    assert harness.scanning.storage is not None
    registry = production_registry(harness.scanning, harness.dependencies)
    register_cleaning_jobs(
        registry,
        tools,
        CleaningDependencies(harness.engine, tools, roots, harness.scanning.storage),
    )
    register_conversion_jobs(
        registry,
        tools,
        roots,
        ConversionDependencies(harness.engine, tools, roots, storage=harness.scanning.storage),
    )
    return registry


def _lineage(harness: _Harness, paths: tuple[Path, ...]) -> None:
    """血缘只读 DatasetRow 指定规范入口；两个视图分别验证真实链接和一致目标。"""
    with session_scope(harness.engine, read_only=True) as session:
        dataset = session.scalars(
            select(DatasetRow).where(DatasetRow.name == _NAME + "_lerobot")
        ).one()
        assert dataset.canonical_entry_path is not None
        canonical = harness.nav / dataset.canonical_entry_path
        entries = list(
            session.scalars(select(EntryRow).where(EntryRow.dataset_id == dataset.dataset_id))
        )
    assert {entry.view for entry in entries} == {"task", "format"}
    target = harness.scanning.roots[0].path / "转换" / (_NAME + "_lerobot")
    assert target.is_dir()
    for entry in entries:
        assert (harness.nav / entry.path / "原始数据").readlink() == target
    provenance = json.loads((canonical / "来源.json").read_text())
    lineage = provenance["lineage"][0]
    details = json.loads(lineage["parameters"]["cleaning_details"])
    assert details["task"] == "task_42" and details["native_exclusion"]
    assert details["excluded_episodes"][0]["source_archive"] == str(paths[0])
    assert details["excluded_episodes"][0]["segment_index"] == 0
    assert details["excluded_episodes"][0]["reason"]
    assert len(lineage["parameters"]["tool_launcher_sha256"]) == 64
    assert len(lineage["parameters"]["tool_source_tree_sha256"]) == 64
    mapping = [
        json.loads(line)
        for line in (target / "meta/agibot_episodes.jsonl").read_text().splitlines()
    ]
    assert [(row["source_archive"], row["source_episode_index"]) for row in mapping] == [
        ("b.tar.gz", 1),
        ("a.tar.gz", 0),
        ("a.tar.gz", 1),
    ]
    assert [row["instruction_segments"]["episode"] for row in mapping] == [1, 0, 1]


def run_chain(root: Path) -> None:
    """两归档经真实 preview/转换/四层检查/入库；仅注入临时存储的 OS 挂载观察。"""
    # 生产 bwrap 把 /tmp 替换为私有 tmpfs；把临时演练目录放在 scripts/drills 下，不能拆掉隔离。
    if root.is_relative_to(Path("/tmp")):  # noqa: S108  # 理由：仅拒绝被 bwrap 隐藏的宿主临时目录，不在此写文件。
        raise ValueError("请用 scripts/drills 下新建的 --basetemp 目录，bwrap 会隔离宿主 /tmp")
    paths = archives(root / "input")
    with _harness(root) as harness:
        _source_navigation(harness.nav, paths)
        registry = _registry(harness, root)
        service = JobService(harness.engine, registry)
        _run(
            harness,
            registry,
            service.submit_system("dataset_rescan", {"dataset_id": None}, now=_now()),
        )
        with session_scope(harness.engine, read_only=True) as session:
            dataset = session.get(DatasetRow, _DATASET)
            assert dataset is not None
            sources = list(
                session.scalars(
                    select(SourceRow)
                    .where(SourceRow.entry_path == dataset.canonical_entry_path)
                    .order_by(SourceRow.ordinal)
                )
            )
        assert [source.direct_path for source in sources] == list(map(str, paths))
        parameters: dict[str, object] = {
            "dataset_id": _DATASET,
            "source_ids": [source.source_id for source in sources],
            "robot_model": MODEL,
        }
        preview = _run(
            harness,
            registry,
            service.submit_system(
                "cleaning_preview_" + TOOL.name.replace("-", ""), parameters, now=_now()
            ),
        )
        with session_scope(harness.engine, read_only=True) as session:
            report = read_preview(session, preview.job_id).report
        assert report.files[0].path == str(paths[0]) and report.episodes[0].fatal_issues
        converted = _run(
            harness,
            registry,
            service.submit_system(
                "convert_" + TOOL.name.replace("-", ""),
                parameters
                | {
                    "cleaning_preview_job_id": preview.job_id,
                    "output_format": "v3.0",
                    "excluded_episodes": [{"file_index": 0, "segment_index": 0}],
                },
                now=_now(),
            ),
        )
        checked = _run(
            harness,
            registry,
            service.submit_system(CHECK_TYPE, {"conversion_job_id": converted.job_id}, now=_now()),
        )
        assert checked.progress is not None and checked.progress.ingest_check is not None
        assert checked.progress.ingest_check.report.result == "通过"
        _run(
            harness,
            registry,
            service.submit_system(APPLY_TYPE, {"preview_job_id": checked.job_id}, now=_now()),
        )
        _lineage(harness, paths)
