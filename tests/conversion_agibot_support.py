"""AgiBot 转换测试边界：独立构造预览和假程序，仅访问临时导航层、工具库和产物。"""

import hashlib
import sys
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from pathlib import Path

from conversion_support import storage_checker
from datasets_execution_support import dataset_case
from jobs_execution_support import execution_case
from jobs_storage_support import NOW, job_row
from nav_manifest import FakeNavigation
from sqlalchemy import Engine
from tool_registry_support import ToolFiles

from rdp.infra.config import StorageRootConfig, ToolsConfig
from rdp.infra.db.connection import session_scope
from rdp.jobs.cleaning._alpha_snapshot import SnapshotBudget, episode_snapshot
from rdp.jobs.cleaning.models import (
    CleaningCheckRules,
    CleaningReport,
    CleaningRuleSnapshot,
    CleaningSummary,
    EpisodeReport,
    FileReport,
)
from rdp.jobs.cleaning.records import CleaningPreview, save_preview
from rdp.jobs.conversion.job import ConversionDependencies, ConversionExecutor
from rdp.jobs.conversion.parameters import ConversionParameters, selected_inputs
from rdp.jobs.execution import ExecutionContext, execute_job
from rdp.jobs.sandbox import SandboxSpec, sandbox_argv
from rdp.jobs.types import JobRecord, JobState
from rdp.tools.registry import load_tool_registry


def fake_agibot(root: Path, *, lengths: tuple[int, ...] = (2, 5)) -> ToolFiles:
    """假程序按实际命令语法记录两次输入和离线环境，生成最小 v3 元数据。"""
    registry, library = root / "registry", root / "library"
    package = registry / "agibot2lerobot"
    package.mkdir(parents=True)
    program = library / "agibot2lerobot/bin/agibot2lerobot"
    program.parent.mkdir(parents=True)
    program.write_text(f"""#!{sys.executable}
import argparse, json, os, pathlib, sys
import pyarrow as pa
import pyarrow.parquet as pq
parser = argparse.ArgumentParser()
parser.add_argument("--events", required=True)
parser.add_argument("command", choices=["check-episodes", "convert-episodes"])
parser.add_argument("-c", required=True)
parser.add_argument("--index-cache", required=True)
parser.add_argument("-o")
parser.add_argument("--format")
parser.add_argument("inputs", nargs="+")
args = parser.parse_args()
assert args.events == "/dev/stderr"
assert pathlib.Path(args.c).is_file()
assert all(pathlib.Path(path).is_dir() for path in args.inputs)
assert os.environ["HF_HUB_OFFLINE"] == "1"
assert os.environ["PYTHONDONTWRITEBYTECODE"] == "1"
assert pathlib.Path(os.environ["HF_HOME"]) == pathlib.Path.cwd() / "hf-home"
assert "CUDA_VISIBLE_DEVICES" not in os.environ
with (pathlib.Path(args.index_cache) / "calls.jsonl").open("a") as stream:
    stream.write(json.dumps(vars(args)) + "\\n")
if args.command == "check-episodes":
    sys.exit(0)
assert args.format == "v3.0" and sys.stderr.isatty()
print(json.dumps({{"event": "progress", "stage": "data", "done": 2, "total": 2}}), file=sys.stderr)
output = pathlib.Path(args.o)
(output / "meta/episodes/chunk-000").mkdir(parents=True)
lengths = {lengths!r}
(output / "meta/info.json").write_text(json.dumps({{
    "total_episodes": len(lengths), "total_frames": sum(lengths),
    "codebase_version": "v3.0", "fps": 30, "features": {{}},
    "data_path": "data/chunk-{{chunk_index:03d}}/file-{{file_index:03d}}.parquet"
}}))
pq.write_table(pa.Table.from_pylist([
    {{"episode_index": index, "length": length}} for index, length in enumerate(lengths)
]), output / "meta/episodes/chunk-000/file-000.parquet")
""")
    program.chmod(0o700)
    tree = program.parent.parent / "agibot2lerobot"
    tree.mkdir()
    source = "# 临时工具源码指纹样例\n".encode()
    (tree / "__init__.py").write_bytes(source)
    tree_sha = hashlib.sha256(
        b"__init__.py\0" + hashlib.sha256(source).hexdigest().encode() + b"\n"
    ).hexdigest()
    # 特意不用 MCAP 配置形状，确保无剔除阶段不会调用其专用解析器。
    (package / "robot.toml").write_text('robot_type = "agibot_g1"\n')
    (package / "rules.toml").write_text("schema_version = 1\n")
    (package / "tool.toml").write_text(f'''
schema_version = 1
[tool]
name = "agibot2lerobot"
version = "0.2.0"
summary = "临时 AgiBot 工具"
directory = "agibot2lerobot"
[program]
path = "bin/agibot2lerobot"
size = {program.stat().st_size}
sha256 = "{hashlib.sha256(program.read_bytes()).hexdigest()}"
tree = "agibot2lerobot"
tree_sha256 = "{tree_sha}"
[io]
input_format = "agibot_native"
output_format = "lerobot"
output_versions = ["v3.0"]
[models]
"AgiBot G1" = "robot.toml"
[cleaning]
"AgiBot G1" = "rules.toml"
[runtime]
needs_gpu = false
progress = "agibot2lerobot-events"
space_ratio_percent = 130
external_programs = []
[command]
verify = ["--events", "/dev/stderr", "check-episodes", "-c", "{{config}}", "--index-cache", "{{cache}}", "{{inputs}}"]
convert = ["--events", "/dev/stderr", "convert-episodes", "-c", "{{config}}", "-o", "{{output}}", "--format", "{{format}}", "--index-cache", "{{cache}}", "{{inputs}}"]
''')
    return ToolFiles(registry, library, program, package)


def seed_agibot_preview(
    engine: Engine, files: ToolFiles
) -> tuple[ConversionParameters, tuple[Path, ...]]:
    """用第 01 张定义的一集一文件报告造成功快照，不依赖第 03 张预览执行器。"""
    parameters = ConversionParameters(
        dataset_id="dataset-31",
        source_ids=["src_73acac5cbe70"],
        robot_model="AgiBot G1",
        excluded_files=[1],
        space_reserve_gib=0,
        cleaning_preview_job_id=59,
    )
    with session_scope(engine) as session:
        task = selected_inputs(session, parameters, input_format="agibot_native")[0]
        paths = tuple(task / name for name in ("2", "3", "10"))
        for path in paths:
            path.mkdir()
            (path / "videos").mkdir()
            (path / "videos/head.mp4").write_bytes(b"video")
            (path / "depth").mkdir()
            (path / "depth/head_000001.png").write_bytes(b"depth")
            if path != paths[-1]:
                h5 = (
                    task.parent.parent
                    / "proprio_stats"
                    / task.name
                    / path.name
                    / "proprio_stats.h5"
                )
                h5.parent.mkdir(parents=True, exist_ok=True)
                h5.write_bytes(b"hdf5")
        shared = task.parent.parent / "proprio_stats/shared.tar"
        shared.write_bytes(b"shared archive")
        metadata = task.parent.parent / f"task_info/task_{task.name}.json"
        metadata.parent.mkdir(exist_ok=True)
        metadata.write_text("[]")
        config_sha = hashlib.sha256((files.package / "robot.toml").read_bytes()).hexdigest()
        rules_sha = hashlib.sha256((files.package / "rules.toml").read_bytes()).hexdigest()
        report = _report(paths, config_sha, rules_sha)
        row = job_row(JobState.COMPLETED, job_id=59)
        row.type_name = "cleaning_preview_agibot2lerobot"
        row.parameters = parameters.model_dump(mode="json")
        session.add(row)
        session.flush()
        tool = load_tool_registry(files.registry, files.library).items[0]
        assert tool.fingerprint is not None
        save_preview(
            session,
            CleaningPreview(
                job_id=59,
                dataset_id=parameters.dataset_id,
                tool_name="agibot2lerobot",
                robot_model=parameters.robot_model,
                binary_sha256=tool.fingerprint,
                config_sha256=config_sha,
                rules_sha256=rules_sha,
                created_at=NOW,
                report=report,
            ),
        )
    return parameters, paths


def _report(paths: tuple[Path, ...], config_sha: str, rules_sha: str) -> CleaningReport:
    """使用不同帧数和非字典序 ID；报告存储顺序也打乱，以验证 file_index 决定顺序。"""
    lengths = (2, 3, 5)
    files = tuple(
        FileReport(
            file_index=index,
            source_id="src_73acac5cbe70",
            path=str(path),
            episode_id=path.name,
            alpha_input_snapshot=episode_snapshot(path, SnapshotBudget(lambda: None)),
            size_bytes=100,
            mtime_ns=path.stat().st_mtime_ns,
            fatal_issues=(),
            warnings=(),
            reference_frames=lengths[index],
            kept_frames=lengths[index],
            bad_frames=0,
            gaps=0,
            short_segments=0,
            short_frames=0,
            topics=(),
            default_excluded=False,
        )
        for index, path in enumerate(paths)
    )
    episodes = tuple(
        EpisodeReport(
            file_index=index,
            segment_index=0,
            start_frame=0,
            end_frame=length,
            frame_count=length,
            duration_s=length / 30,
            stamp_span_s=length / 30,
            start_time_s=0,
            issues=(),
            default_action="keep",
        )
        for index, length in enumerate(lengths)
    )
    return CleaningReport(
        source_format="agibot_native",
        tool_config_sha256=config_sha,
        rules_sha256=rules_sha,
        fps=30,
        reference_topic=None,
        rules=CleaningRuleSnapshot(
            sync=None,
            checks=CleaningCheckRules(
                static_feature="observation.state",
                long_static_s=3,
                jump_feature="action",
                frozen_s=None,
                sample_interval_s=None,
                dark_below=None,
                bright_above=None,
                sources=(),
                severe_checks=(),
            ),
        ),
        files=tuple(reversed(files)),
        episodes=tuple(reversed(episodes)),
        summary=CleaningSummary(
            files=3,
            excluded_files=0,
            episodes=3,
            excluded_episodes=0,
            reference_frames=10,
            kept_frames=10,
        ),
    )


@dataclass
class AgibotConversionCase:
    """执行器测试的临时依赖和可观察的系统边界。"""

    root: Path
    files: ToolFiles
    parameters: ConversionParameters
    inputs: tuple[Path, ...]
    dependencies: ConversionDependencies
    sandboxes: list[SandboxSpec]

    @property
    def stage(self) -> Path:
        """固定测试作业的暂存位置。"""
        return self.root / "output/暂存/转换/71"

    @property
    def calls_path(self) -> Path:
        """假程序在工具缓存中留下的调用记录。"""
        return self.dependencies.tools.cache_root / "agibot2lerobot/calls.jsonl"

    def run(self) -> JobRecord:
        """真实执行框架使用 gpu_index=None，失败仍返回持久化诊断。"""

        def execute(context: ExecutionContext) -> None:
            ConversionExecutor("agibot2lerobot", self.dependencies).execute(
                replace(context, parameters=self.parameters)
            )

        with execution_case(self.root / "execution", {"steps": 1, "interval_ms": 0}, execute) as (
            work,
            dependencies,
            signals,
        ):
            result = execute_job(work, dependencies, signals)
            assert result is not None
            assert all(not thread.is_alive() for thread in signals.monitor.threads)
            return result


@contextmanager
def agibot_case(
    root: Path,
    fake: FakeNavigation,
    *,
    lengths: tuple[int, ...] = (2, 5),
) -> Generator[AgibotConversionCase]:
    """真实索引、目录元数据和子进程；只替换操作系统隔离和存储挂载边界。"""
    files = fake_agibot(root / "tool", lengths=lengths)
    output = root / "output"
    output.mkdir()
    roots = (
        *fake.storage_roots,
        StorageRootConfig(
            name="output",
            path=output,
            nfs_export="server:/output",
            writable=True,
        ),
    )
    sandboxes: list[SandboxSpec] = []

    def sandbox(
        argv: tuple[str, ...], spec: SandboxSpec, readonly: tuple[Path, ...]
    ) -> tuple[str, ...]:
        sandbox_argv(argv, spec, readonly_roots=readonly)
        sandboxes.append(spec)
        return argv

    with dataset_case(root / "index", fake) as scan:
        scan.run()
        parameters, inputs = seed_agibot_preview(scan.engine, files)
        dependencies = ConversionDependencies(
            scan.engine,
            ToolsConfig(
                registry_dir=files.registry,
                library_root=files.library,
                cache_root=root / "cache",
                lerobot_python=None,
            ),
            roots,
            sandbox,
            storage=storage_checker(roots),
        )
        yield AgibotConversionCase(root, files, parameters, inputs, dependencies, sandboxes)
