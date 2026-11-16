"""Alpha 手动演练装配；真实源码、执行器、报告和入库，只替换 OS 挂载在线观察。

不读部署配置，不启动 HTTP 服务；测试资源池和临时库使用现有测试装配。
工具源码原样复制并计算指纹，临时启动器只负责用真实工具解释器的 -I -B 模式加载副本。
"""

import hashlib
import json
import os
import shlex
import shutil
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from threading import Event, Lock

from pydantic import TypeAdapter
from sqlalchemy import Engine

from rdp.infra.config import StorageRootConfig, ToolsConfig
from rdp.infra.db.connection import session_scope
from rdp.infra.state import StatePaths
from rdp.jobs.cleaning.job import CleaningDependencies
from rdp.jobs.cleaning.registration import register_cleaning_jobs
from rdp.jobs.conversion.job import ConversionDependencies
from rdp.jobs.conversion.registration import register_conversion_jobs
from rdp.jobs.datasets.rescan import RescanDependencies
from rdp.jobs.execution import ExecutionWork, ExecutorDependencies, execute_job
from rdp.jobs.navwrite.create_models import INFORMATION_FIELD_NAMES
from rdp.jobs.navwrite.pipeline import NavWriteDependencies
from rdp.jobs.outcome import JobOutcome
from rdp.jobs.progress import ExecutionMonitor, ExecutionSignals
from rdp.jobs.records import claim_job
from rdp.jobs.registry import JobRegistry, production_registry
from rdp.jobs.service import JobService
from rdp.jobs.types import ExecutionMode, JobClock, JobRecord
from rdp.tools.registry import load_tool_registry
from tests.conversion_support import storage_checker
from tests.jobs_scheduling_support import claim_fixture, resources_fixture

# 用户明确授权的只读工具和系统盘样本；不给任意 root 参数，避免误指向真实数据盘。
TOOL_ROOT = Path("/mnt/datasets/工具/agibot2lerobot")
SAMPLE_ROOT = Path("/home/shawn/.cache/agibot_check/src")
DATASET_ID = "dataset-01"
SOURCE_ID = "source-alpha"
DATASET_NAME = "Alpha本地演练"


def require(condition: bool, message: str) -> None:
    """手动验收条件不成立时失败，不能因 Python 优化而关闭验证。

    Args:
        condition: 实际观察是否符合本次验收预期。
        message: 失败原因，不包含敏感信息。

    Returns:
        无。

    Raises:
        AssertionError: condition 为假。

    Side Effects:
        无。

    Time Semantics:
        同步判断，不重试或等待。
    """
    if not condition:
        raise AssertionError(message)


def check_sample_boundary() -> None:
    """先拒绝链接，再只读检查已授权本地样本的两集布局。

    Args:
        无。

    Returns:
        无。

    Raises:
        AssertionError: 未以 -I 启动、样本不存在、包含链接或集数不符。
        OSError: 本地样本目录不可读。

    Side Effects:
        只读样本目录项；不打开观测文件，不解析链接目标。

    Time Semantics:
        每次演练开始检查一次，源样本须在整个演练中保持不变。
    """
    require(bool(sys.flags.isolated), "手动演练必须用 Python -I -B 启动")
    # 由根到叶拒绝链接，不能先 resolve 后才判断是否已越界。
    for path in reversed((SAMPLE_ROOT, *SAMPLE_ROOT.parents)):
        require(not path.is_symlink(), f"样本祖先不能是链接：{path}")
    require(SAMPLE_ROOT.is_dir(), "缺少已授权的本地 src 样本")
    for directory, folders, files in os.walk(SAMPLE_ROOT, followlinks=False):
        for name in (*folders, *files):
            require(not (Path(directory) / name).is_symlink(), "样本内部不能含链接")
    require(
        {p.name for p in (SAMPLE_ROOT / "observations/327").iterdir()} == {"649806", "650435"},
        "演练只支持已授权的两集样本",
    )


def register_real_tool(root: Path) -> ToolsConfig:
    """把真实源码和配置原样复制到临时工具库，并登记实际文件指纹。

    Args:
        root: 本次独占临时目录，绝对路径，不能位于 bwrap 遮蔽的 /tmp 下。

    Returns:
        全部可写路径位于 root 内的工具配置。

    Raises:
        OSError: 工具源码、解释器或临时目录不能读取或写入。
        AssertionError: 平台实际指纹验证后工具不可用。

    Side Effects:
        只读真实工具；写源码副本、启动器、配置副本及清单，不安装依赖。

    Time Semantics:
        每次全新登记，后续执行器仍重新校验指纹。
    """
    settings = ToolsConfig(
        registry_dir=root / "registry", library_root=root / "library", cache_root=root / "cache"
    )
    package = settings.registry_dir / "agibot2lerobot"
    tool = settings.library_root / "agibot2lerobot"
    package.mkdir(parents=True)
    tool.mkdir(parents=True)
    shutil.copytree(
        TOOL_ROOT / "agibot2lerobot",
        tool / "agibot2lerobot",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    for name in ("agibot_g1.toml", "agibot_g1.cleaning.toml"):
        shutil.copyfile(TOOL_ROOT / "configs" / name, package / name)
    launch = tool / "launch.py"
    launch.write_text(
        "import runpy, sys\n"
        f"sys.path.insert(0, {str(tool)!r})\n"
        'if __name__ == "__main__":\n'
        '    runpy.run_module("agibot2lerobot", run_name="__main__")\n'
    )
    program = tool / "run"
    program.write_text(
        "#!/bin/sh\nexec "
        + shlex.join((str(TOOL_ROOT / ".venv/bin/python"), "-I", "-B", str(launch)))
        + ' "$@"\n'
    )
    program.chmod(0o700)
    _write_manifest(package, tool)
    registry = load_tool_registry(settings.registry_dir, settings.library_root)
    require(len(registry.items) == 1, "临时登记应只有一个真实工具")
    require(registry.items[0].status == "可用", str(registry.items[0].diagnostics))
    return settings


def _write_manifest(package: Path, tool: Path) -> None:
    """按平台定义对实际副本逐文件哈希，命令保留第 04 票要求的缓存占位符。"""
    records: list[bytes] = []
    for path in sorted((tool / "agibot2lerobot").rglob("*.py")):
        relative = str(path.relative_to(tool / "agibot2lerobot"))
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        records.append(relative.encode() + b"\0" + digest.encode() + b"\n")
    source_sha = hashlib.sha256(b"".join(records)).hexdigest()
    program = (tool / "run").read_bytes()
    (package / "tool.toml").write_text(f'''schema_version = 1
[tool]
name = "agibot2lerobot"
version = "0.2.0"
summary = "Alpha 本地真实工具演练"
directory = "agibot2lerobot"
source_note = "已授权工具源码原样副本；临时 -I 启动器"
[program]
path = "run"
size = {len(program)}
sha256 = "{hashlib.sha256(program).hexdigest()}"
tree = "agibot2lerobot"
tree_sha256 = "{source_sha}"
[io]
input_format = "agibot_native"
output_format = "lerobot"
output_versions = ["v3.0"]
[models]
"AgiBot G1" = "agibot_g1.toml"
[cleaning]
"AgiBot G1" = "agibot_g1.cleaning.toml"
[runtime]
needs_gpu = false
progress = "agibot2lerobot-events"
external_programs = ["ffmpeg", "ffprobe"]
space_ratio_percent = 100
[command]
preview = ["--events", "/dev/stderr", "preview", "-c", "{{config}}", "--rules", "{{rules}}", "--index-cache", "{{cache}}", "--result", "{{result}}", "--task-dir", "{{inputs}}", "--no-archive-proprio", "--workers", "1"]
verify = ["check-episodes", "-c", "{{config}}", "--index-cache", "{{cache}}", "{{inputs}}"]
convert = ["--events", "/dev/stderr", "convert-episodes", "-c", "{{config}}", "-o", "{{output}}", "--format", "{{format}}", "--index-cache", "{{cache}}", "{{inputs}}"]
''')


def create_navigation(root: Path) -> Path:
    """建立仅引用已授权本地样本的临时源入口，交真实扫描发布索引。

    Args:
        root: 独占临时目录，不能已有 nav 子目录。

    Returns:
        临时导航层根路径。

    Raises:
        OSError: 新建入口、JSON 或链接失败。

    Side Effects:
        只写 root/nav；源数据只有只读链接，不修改样本。

    Time Semantics:
        在扫描、预览之前创建一次；不预填任何检查或转换结果。
    """
    nav = root / "nav"
    entry = nav / "按任务" / DATASET_NAME
    entry.mkdir(parents=True)
    (nav / "按格式/lerobot/3.0").mkdir(parents=True)
    (nav / "已移除").mkdir()
    source = SAMPLE_ROOT / "observations/327"
    (entry / "原始数据").symlink_to(source, target_is_directory=True)
    identity = {
        "schema_version": 1,
        "dataset_id": DATASET_ID,
        "dataset_name": DATASET_NAME,
        "view": "task",
        "format": None,
        "version": None,
    }
    documents: dict[str, object] = {
        "数据集信息.json": {
            "dataset_id": DATASET_ID,
            "title": DATASET_NAME,
            "data_origin": "开源下载",
            "robot_model": "AgiBot G1",
            "fps": 30,
            "fields": [
                {"number": i, "name": name, "value_markdown": "本地演练"}
                for i, name in enumerate(INFORMATION_FIELD_NAMES, 1)
            ],
        },
        "子任务.json": {**identity, "task_count": 0, "tasks": []},
        "原始路径.json": {
            **identity,
            "dataset_roots": [str(SAMPLE_ROOT)],
            "links": [
                {
                    "name": "原始数据",
                    "source_path": str(source),
                    "entry_path": f"按任务/{DATASET_NAME}/原始数据",
                    "source_type": "directory",
                }
            ],
            "sources": [
                {
                    "source_id": SOURCE_ID,
                    "original_path": str(source),
                    "direct_path": str(source),
                    "format": "agibot_native",
                    "version": None,
                    "entry_path": f"按任务/{DATASET_NAME}/原始数据",
                    "source_role": "data",
                    "validation_status": "unchecked",
                }
            ],
            "notes": [],
            "source_files_modified": False,
        },
    }
    for name, payload in documents.items():
        (entry / name).write_text(json.dumps(payload, ensure_ascii=False))
    return nav


@dataclass(frozen=True)
class Drill:
    """显式装配的单次演练资源；所有写入对象都位于独占临时目录。

    Attributes:
        engine: 临时受管 SQLite 引擎。
        paths: 临时状态、日志和导航事务目录。
        registry: 绑定真实执行器的类型表。
        service: 向同一临时库提交系统作业的服务。
        nav: 临时导航根。
        output: 临时可写存储根。
    """

    engine: Engine
    paths: StatePaths
    registry: JobRegistry
    service: JobService
    nav: Path
    output: Path


def assemble(root: Path, engine: Engine, paths: StatePaths, tools: ToolsConfig) -> Drill:
    """绑定真实预览、转换、四层检查及入库执行能力。

    Args:
        root: 本次独占临时目录。
        engine: 已初始化的临时数据库引擎。
        paths: 同一临时数据库的状态布局。
        tools: 本次真实工具副本登记。

    Returns:
        可以依次提交和执行作业的演练装配。

    Raises:
        OSError: 临时导航或可写存储目录无法建立。
        DefectError: 平台类型登记不合法。

    Side Effects:
        创建临时导航和可写存储目录；仅挂载在线检查使用合成 mountinfo，访问仍是真实只读探测。

    Time Semantics:
        启动时一次性装配，工具和输入在各执行器内再次核对。
    """
    nav = create_navigation(root)
    output = root / "storage"
    output.mkdir()
    roots = (
        StorageRootConfig(name="local_sample", path=SAMPLE_ROOT, nfs_export="local:/sample"),
        StorageRootConfig(
            name="local_output", path=output, writable=True, nfs_export="local:/output"
        ),
    )
    storage = storage_checker(roots)
    scan = RescanDependencies(engine, nav, roots, storage)
    registry = JobRegistry()
    service = JobService(engine, registry)
    nav_deps = NavWriteDependencies(scan, paths, service)
    for definition in production_registry(scan, nav_deps).definitions():
        registry.register(definition)
    # 不传 sandbox 参数；两个执行器始终使用平台默认 bwrap，失败不降级。
    register_cleaning_jobs(registry, tools, CleaningDependencies(engine, tools, roots, storage))
    register_conversion_jobs(
        registry, tools, roots, ConversionDependencies(engine, tools, roots, storage=storage)
    )
    return Drill(engine, paths, registry, service, nav, output)


def run_job(drill: Drill, type_name: str, parameters: dict[str, object]) -> JobRecord:
    """通过真实提交、领取和执行框架运行一项作业，保存实际终态供追溯。

    Args:
        drill: 本次临时演练装配。
        type_name: 已登记的真实作业类型键。
        parameters: 类型模型验证的参数，不接受执行回调替换。

    Returns:
        成功或带警告成功的真实持久化记录。

    Raises:
        AssertionError: 执行未返回记录、失败、取消或存在失败项。
        InputError: 提交参数或临时存储状态不合法。

    Side Effects:
        向临时库提交并执行作业，写临时日志和实际作业产物；失败保留现场。

    Time Semantics:
        使用当前 UTC 和单调时钟；沿用执行器的工具 12 小时、检查 300 秒等上限，不重试。
    """

    def now() -> datetime:
        return datetime.now(UTC)

    queued = drill.service.submit_system(type_name, parameters, now=now())
    sys.stdout.write(f"开始 {type_name}，作业 {queued.job_id}，日志根 {drill.paths.root}\n")
    sys.stdout.flush()
    with session_scope(drill.engine) as session:
        record = claim_job(session, queued.job_id, now=now(), paths=drill.paths, gpu_index=None)
    deps = ExecutorDependencies(
        drill.engine,
        drill.registry,
        drill.paths,
        JobClock(now, time.monotonic),
        resources=resources_fixture(drill.registry),
        storage=None,
    )
    result = execute_job(
        ExecutionWork(record, ExecutionMode.FRESH, None, claim=claim_fixture(record, deps)),
        deps,
        ExecutionSignals(Event(), Event(), ExecutionMonitor([], None, Lock())),
    )
    if result is None:
        raise AssertionError(f"{type_name} 未返回终态，查看 {drill.paths.root}")
    (drill.paths.root / f"drill-{result.job_id}.json").write_bytes(
        TypeAdapter(JobRecord).dump_json(result, indent=2)
    )
    require(
        result.summary is not None
        and result.summary.outcome
        in (
            JobOutcome.SUCCEEDED,
            JobOutcome.SUCCEEDED_WITH_WARNINGS,
        ),
        f"{type_name} 未成功：{result.diagnostics}；日志 {result.log_path}",
    )
    require(
        result.summary is not None and result.summary.failed_items == 0,
        f"{type_name} 有失败项；查看 {result.log_path}",
    )
    return result
