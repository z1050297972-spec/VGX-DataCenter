"""AgiBot 预览验收装配：临时登记、索引和假工具，不使用 HTTP 或真实数据。"""

import hashlib
import json
import sys
import time
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from threading import Event, Lock

from conversion_support import storage_checker
from jobs_storage_support import NOW, job_database, job_row
from sqlalchemy import Engine

from rdp.infra.config import StorageRootConfig, ToolsConfig
from rdp.infra.db.connection import session_scope
from rdp.infra.state import StatePaths
from rdp.jobs.cleaning.job import CleaningDependencies
from rdp.jobs.cleaning.records import CleaningPreview, read_preview
from rdp.jobs.cleaning.registration import register_cleaning_jobs
from rdp.jobs.datasets.models import DatasetRow, DatasetScanRow, EntryRow, SourceRow
from rdp.jobs.execution import ExecutionWork, ExecutorDependencies, execute_job
from rdp.jobs.progress import ExecutionMonitor, ExecutionSignals
from rdp.jobs.records import StateChange, claim_job, transition_job
from rdp.jobs.registry import JobRegistry
from rdp.jobs.sandbox import SandboxSpec
from rdp.jobs.types import ExecutionMode, JobClock, JobRecord, JobState

CONFIG = 'fps = 30\nrobot_type = "agibot"\n'
RULES = """schema_version = 1
[static]
feature = "observation.state"
long_static_s = 3.0
[jump]
feature = "action"
[[source]]
field = "state/joint/position"
static_threshold = 0.001
jump_threshold = 0.2
limits = [[-1.0, 1.0]]
"""


@dataclass
class AgibotPreviewCase:
    """测试通过真实执行器和报告读取接口观察结果，沙箱仅记录调用后放行假程序。"""

    engine: Engine
    paths: StatePaths
    registry: JobRegistry
    tools: ToolsConfig
    task: Path
    sandbox_calls: list[tuple[tuple[str, ...], SandboxSpec, tuple[Path, ...]]]
    tree_sha256: str
    tool_name: str = "agibot2lerobot"
    robot_model: str = "AgiBot G1"
    dataset_id: str = "dataset-preview"

    @property
    def cache(self) -> Path:
        """本测试唯一工具缓存，位于 tmp 内。"""
        return self.tools.cache_root / self.tool_name

    def run(
        self,
        source_ids: tuple[str, ...] = ("source-preview",),
        *,
        cancel_after_result: bool = False,
    ) -> JobRecord:
        """领取并同步执行真实作业，全部线程由执行器回收。"""
        with session_scope(self.engine) as session:
            row = job_row(JobState.QUEUED)
            row.type_name = "cleaning_preview_" + self.tool_name.replace("-", "")
            row.parameters = {
                "dataset_id": self.dataset_id,
                "source_ids": list(source_ids),
                "robot_model": self.robot_model,
            }
            session.add(row)
        with session_scope(self.engine) as session:
            record = claim_job(session, 71, now=NOW, paths=self.paths, gpu_index=None)
        signals = ExecutionSignals(Event(), Event(), ExecutionMonitor([], None, Lock()))
        cancel_lock = Lock()

        def monotonic() -> float:
            # 时钟是外部边界；看到真实结果文件后触发取消，不替换预览或进程内部方法。
            with cancel_lock:
                if (
                    cancel_after_result
                    and not signals.cancelled.is_set()
                    and (self.cache / "preview-71.json").exists()
                ):
                    with session_scope(self.engine) as session:
                        transition_job(
                            session, 71, StateChange(JobState.RUNNING, JobState.CANCELLING, NOW)
                        )
                    signals.cancelled.set()
            return time.monotonic()

        result = execute_job(
            ExecutionWork(record, ExecutionMode.FRESH, None, claim=None),
            ExecutorDependencies(
                self.engine,
                self.registry,
                self.paths,
                JobClock(lambda: NOW, monotonic),
                resources=None,
                storage=None,
            ),
            signals,
        )
        assert result is not None
        return result

    def preview(self) -> CleaningPreview:
        """经持久化公开接口读取成功快照。"""
        with session_scope(self.engine, read_only=True) as session:
            return read_preview(session, 71)


def preview_result(task: Path) -> dict[str, object]:
    """三集手算样本：体检失败、严重非有限值和仅提示长静止各一集。"""
    episodes: list[dict[str, object]] = []
    for identifier, frames, check in (
        ("2", 0, None),
        ("10", 60, "non_finite"),
        ("20", 120, "long_static"),
    ):
        episode = task / identifier
        episode.mkdir(parents=True)
        issues = (
            []
            if check is None
            else [
                {
                    "check": check,
                    "feature": "observation.state",
                    "count": 1,
                    "first_time_s": 0.0,
                    "ranges": [[0.0, 3.0]] if check == "long_static" else [],
                }
            ]
        )
        episodes.append(
            {
                "episode_id": identifier,
                "observation_dir": str(episode),
                "observation_mtime_ns": episode.stat().st_mtime_ns,
                "proprio": None
                if check is None
                else {
                    "path": str(task.parent.parent / "proprio_stats/1.tar"),
                    "offset": 512,
                    "size": 1024,
                },
                "size_bytes": 1000,
                "frames": frames,
                "problems": ["缺少视频", "维度不符"] if check is None else [],
                "issues": issues,
                # 真实工具对未标注的观测集返回 null，不会伪造空任务文本。
                "task": None if check is None else "整理桌面",
            }
        )
    return {
        "schema_version": 1,
        "tool_version": "0.2.0",
        "task_id": "327",
        "task_name": "整理桌面",
        "dataset_name": "测试数据",
        "fps": 30,
        "robot_config": {
            "path": "configs/g1.toml",
            "sha256": hashlib.sha256(CONFIG.encode()).hexdigest(),
        },
        "feature_names": {"observation.state": ["joint_1"]},
        "episodes": episodes,
    }


def fake_tool(root: Path, payload: dict[str, object], exit_code: int) -> tuple[ToolsConfig, str]:
    """按工具 README 的参数协议写结果，只触碰测试的缓存目录。"""
    tools = ToolsConfig(
        registry_dir=root / "registry", library_root=root / "library", cache_root=root / "cache"
    )
    package = tools.registry_dir / "agibot2lerobot"
    package.mkdir(parents=True)
    (package / "config.toml").write_text(CONFIG)
    (package / "rules.toml").write_text(RULES)
    tool = tools.library_root / "agibot2lerobot"
    tree = tool / "source"
    tree.mkdir(parents=True)
    (tree / "main.py").write_text("# 假源码指纹\n")
    tree_sha = hashlib.sha256(
        b"main.py\0" + hashlib.sha256((tree / "main.py").read_bytes()).hexdigest().encode() + b"\n"
    ).hexdigest()
    script = f"""#!{sys.executable}
import argparse, json, os, pathlib, sys
p = argparse.ArgumentParser()
p.add_argument("--events", required=True)
p.add_argument("command", choices=["preview"])
p.add_argument("-c", required=True)
p.add_argument("--rules", required=True)
p.add_argument("--index-cache", required=True)
p.add_argument("--result", required=True)
p.add_argument("--task-dir", required=True)
a = p.parse_args()
assert a.events == "/dev/stderr" and sys.stderr.isatty()
assert os.environ["HF_HUB_OFFLINE"] == "1"
assert os.environ["PYTHONDONTWRITEBYTECODE"] == "1"
assert os.environ["HF_HOME"] == str(pathlib.Path(a.index_cache) / "hf-home")
pathlib.Path(a.index_cache, "arguments.json").write_text(json.dumps(vars(a)))
with pathlib.Path(a.result).open("x") as stream:
    stream.write({json.dumps(payload)!r})
sys.stderr.write('{{"event":"progress","stage":"preview","done":3,"total":3}}\\n')
sys.exit({exit_code})
"""
    (tool / "preview").write_text(script)
    (tool / "preview").chmod(0o700)
    (package / "tool.toml").write_text(f'''schema_version = 1
[tool]
name = "agibot2lerobot"
version = "0.2.0"
summary = "测试预览"
directory = "agibot2lerobot"
[program]
path = "preview"
size = {len(script.encode())}
sha256 = "{hashlib.sha256(script.encode()).hexdigest()}"
tree = "source"
tree_sha256 = "{tree_sha}"
[io]
input_format = "agibot_native"
output_format = "lerobot"
output_versions = ["v3.0"]
[models]
"AgiBot G1" = "config.toml"
[cleaning]
"AgiBot G1" = "rules.toml"
[runtime]
needs_gpu = false
progress = "agibot2lerobot-events"
external_programs = []
[command]
verify = ["check-episodes", "-c", "{{config}}", "{{inputs}}"]
convert = ["convert-episodes", "-c", "{{config}}", "-o", "{{output}}", "--format", "{{format}}", "{{inputs}}"]
preview = ["--events", "/dev/stderr", "preview", "-c", "{{config}}", "--rules", "{{rules}}", "--index-cache", "{{cache}}", "--result", "{{result}}", "--task-dir", "{{inputs}}"]
''')
    return tools, tree_sha


def seed_inputs(
    engine: Engine,
    inputs: tuple[Path, ...],
    *,
    input_format: str = "agibot_native",
    dataset_id: str = "dataset-preview",
) -> None:
    """为 worker 装配当前索引，路径和格式都来自本测试临时目录。"""
    with session_scope(engine) as session:
        session.add(
            DatasetScanRow(
                scan_id=1,
                job_id=None,
                scope="all",
                requested_dataset_id=None,
                started_at=NOW,
                navigation_finished_at=NOW,
                committed_at=NOW,
                navigation_elapsed_s=0,
                lock_held_s=0,
                storage_stage="not_run",
                is_current=True,
            )
        )
        session.flush()
        session.add(
            DatasetRow(
                dataset_id=dataset_id,
                name="预览样本",
                canonical_entry_path="按任务/预览样本",
                scan_id=1,
                fingerprint={},
                data_origin="real",
            )
        )
        session.flush()
        session.add(
            EntryRow(
                path="按任务/预览样本",
                dataset_id=dataset_id,
                scan_id=1,
                view="task",
                name="预览样本",
                dataset_roots=[str(inputs[0].parent)],
                provenance_present=False,
                fingerprint={},
            )
        )
        session.flush()
        for index, path in enumerate(inputs):
            session.add(
                SourceRow(
                    entry_path="按任务/预览样本",
                    ordinal=index,
                    source_id="source-preview" if index == 0 else f"source-{index}",
                    original_path=str(path),
                    direct_path=str(path),
                    derived_entry_path=str(path),
                    format=input_format,
                    status="unchecked",
                )
            )


@contextmanager
def agibot_case(
    root: Path,
    payload: dict[str, object],
    *,
    exit_code: int = 0,
    inputs: tuple[Path, ...] | None = None,
) -> Generator[AgibotPreviewCase]:
    """用可注入沙箱边界执行临时假工具，保留真实终态事务和结果校验。"""
    task = root / "input/observations/327"
    tools, tree_sha = fake_tool(root, payload, exit_code)
    roots = (StorageRootConfig(name="input", path=root / "input", nfs_export="server:/input"),)
    calls: list[tuple[tuple[str, ...], SandboxSpec, tuple[Path, ...]]] = []

    def sandbox(
        argv: tuple[str, ...], spec: SandboxSpec, readonly: tuple[Path, ...]
    ) -> tuple[str, ...]:
        calls.append((argv, spec, readonly))
        return argv

    with job_database(root / "state") as (engine, paths):
        seed_inputs(engine, inputs or (task,))
        registry = JobRegistry()
        register_cleaning_jobs(
            registry,
            tools,
            CleaningDependencies(engine, tools, roots, storage_checker(roots), sandbox=sandbox),
        )
        yield AgibotPreviewCase(engine, paths, registry, tools, task, calls, tree_sha)
