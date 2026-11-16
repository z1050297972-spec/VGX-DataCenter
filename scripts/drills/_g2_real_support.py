"""G2 验收只生成临时归档；报告与转换均调用真实工具，不手造 CLI JSON。"""

# ruff: noqa: S101  # 理由：手动验收装配用断言阻止不合约结果继续执行。

import hashlib
import re
import shutil
import subprocess
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path

from rdp.infra.config import StorageRootConfig, ToolsConfig
from rdp.jobs.cleaning.job import CleaningDependencies
from rdp.jobs.cleaning.registration import register_cleaning_jobs
from rdp.jobs.conversion.job import ConversionDependencies, ConversionExecutor
from rdp.jobs.conversion.parameters import ConversionParameters
from rdp.jobs.execution import ExecutionContext, execute_job
from rdp.jobs.registry import JobRegistry
from rdp.jobs.sandbox import SandboxSpec, sandbox_argv
from rdp.jobs.types import JobRecord
from tests.agibot_preview_support import AgibotPreviewCase, seed_inputs
from tests.conversion_support import storage_checker
from tests.jobs_execution_support import execution_case
from tests.jobs_storage_support import job_database

# 用户明确授权的工具源码；测试数据和缓存只放 tmp_path，不读取真实导航层或数据盘。
TOOL = Path("/mnt/datasets/工具/agibot2lerobot-g2")
PYTHON = Path("/home/shawn/miniconda3/envs/lerobot/bin/python")
MODEL = "AgiBot G2（g2a）"


def archives(root: Path) -> tuple[Path, ...]:
    """真实 factory 造两个同任务归档，含重复源集号及一个缺视频的致命集。"""
    script = (
        "import importlib.util, pathlib\n"
        f"s=importlib.util.spec_from_file_location('g2_factory', {str(TOOL / 'tests/factory.py')!r})\n"
        "m=importlib.util.module_from_spec(s); s.loader.exec_module(m)\n"
        f"root=pathlib.Path({str(root)!r})\n"
        "m.make_dataset(root/'task_42/b', count=2, missing=(0,m.CAMERAS[0]))\n"
        "m.make_dataset(root/'task_42/a', count=2, tasks=['整理','搬运'])\n"
    )
    result = subprocess.run(  # noqa: S603  # 理由：固定授权解释器与 factory，仅生成 tmp 归档。
        [str(PYTHON), "-I", "-B", "-c", script],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return root / "task_42/b.tar.gz", root / "task_42/a.tar.gz"


@contextmanager
def g2_case(
    root: Path, paths: tuple[Path, ...], *, dataset_id: str = "dataset-preview"
) -> Generator[AgibotPreviewCase]:
    """真实工具、bwrap、临时登记和数据库；宿主 namespace 拒绝即失败，不降级。"""
    settings = prepare_tools(root)
    roots = (StorageRootConfig(name="input", path=root / "input", nfs_export="test:/input"),)
    calls: list[tuple[tuple[str, ...], SandboxSpec, tuple[Path, ...]]] = []

    def sandbox(
        argv: tuple[str, ...], spec: SandboxSpec, readonly: tuple[Path, ...]
    ) -> tuple[str, ...]:
        calls.append((argv, spec, readonly))
        return sandbox_argv(argv, spec, readonly_roots=readonly)

    with job_database(root / "state") as (engine, state):
        seed_inputs(engine, paths, input_format="archives", dataset_id=dataset_id)
        registry = JobRegistry()
        register_cleaning_jobs(
            registry,
            settings,
            CleaningDependencies(
                engine,
                settings,
                roots,
                storage_checker(roots),
                sandbox=sandbox,
            ),
        )
        yield AgibotPreviewCase(
            engine, state, registry, settings, paths[0], calls, "", TOOL.name, MODEL, dataset_id
        )


def convert(
    root: Path,
    case: AgibotPreviewCase,
    parameters: ConversionParameters,
    *,
    output_root: Path | None = None,
) -> JobRecord:
    """在真实执行器内调用 G2 转换；全部输出限于临时可写根。"""
    output = output_root or root / "output"
    output.mkdir(exist_ok=True)
    roots = (
        StorageRootConfig(name="input", path=root / "input", nfs_export="test:/input"),
        StorageRootConfig(name="output", path=output, nfs_export="test:/output", writable=True),
    )

    def sandbox(
        argv: tuple[str, ...], spec: SandboxSpec, readonly: tuple[Path, ...]
    ) -> tuple[str, ...]:
        case.sandbox_calls.append((argv, spec, readonly))
        return sandbox_argv(argv, spec, readonly_roots=readonly)

    dependencies = ConversionDependencies(
        case.engine, case.tools, roots, sandbox, storage=storage_checker(roots)
    )

    def execute(context: ExecutionContext) -> None:
        ConversionExecutor(TOOL.name, dependencies).execute(replace(context, parameters=parameters))

    with execution_case(root / "conversion-state", {"steps": 1, "interval_ms": 0}, execute) as (
        work,
        deps,
        signals,
    ):
        result = execute_job(work, deps, signals)
        assert result is not None
        return result


def prepare_tools(root: Path) -> ToolsConfig:
    """仅刷新临时登记包的配置与真实指纹，不与执行线争写工作树登记或工具源码。"""
    registry = root / "registry"
    package = registry / TOOL.name
    shutil.copytree(Path(__file__).parents[2] / "tools" / TOOL.name, package)
    shutil.copyfile(TOOL / "configs/agibot_g2.toml", package / "configs/agibot_g2.toml")
    shutil.copyfile(TOOL / "configs/agibot_g2.cleaning.toml", package / "cleaning/agibot_g2.toml")
    tree = TOOL / "agibot2lerobot_g2"
    digest = hashlib.sha256()
    for path in sorted(tree.rglob("*.py")):
        digest.update(
            path.relative_to(tree).as_posix().encode()
            + b"\0"
            + hashlib.sha256(path.read_bytes()).hexdigest().encode()
            + b"\n"
        )
    launcher = TOOL / "bin/agibot2lerobot-g2"
    manifest = package / "tool.toml"
    text = manifest.read_text()
    for key, value in {
        "tree_sha256": f'"{digest.hexdigest()}"',
        "sha256": f'"{hashlib.sha256(launcher.read_bytes()).hexdigest()}"',
        "size": str(launcher.stat().st_size),
    }.items():
        text = re.sub(rf"^{key} = .*$", f"{key} = {value}", text, flags=re.MULTILINE)
    manifest.write_text(text)
    return ToolsConfig(registry_dir=registry, library_root=TOOL.parent, cache_root=root / "cache")
