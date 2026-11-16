"""常规 G2 单测只使用临时假工具和固定真实格式报告，不依赖机器上的工具或解释器。

preview-v1.json 来自真实 factory 两归档加坏 tar 的 report-only 输出；仅路径被替换为
占位符。临时实例只重绑定路径、stat 和配置身份，不改变质量事实。真实 CLI 在 drills 验收。
"""

import hashlib
import json
import shutil
import sys
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from agibot_preview_support import AgibotPreviewCase, seed_inputs
from conversion_support import storage_checker
from jobs_storage_support import job_database

from rdp.infra.config import StorageRootConfig, ToolsConfig
from rdp.jobs.cleaning.job import CleaningDependencies
from rdp.jobs.cleaning.registration import register_cleaning_jobs
from rdp.jobs.registry import JobRegistry
from rdp.jobs.sandbox import SandboxSpec, sandbox_argv

MODEL = "AgiBot G2（g2a）"
TOOL_NAME = "agibot2lerobot-g2"
FIXTURE = Path(__file__).parent / "fixtures/g2/preview-v1.json"


def archives(root: Path) -> tuple[Path, ...]:
    """只造三个临时路径占位，不冒充可解压的真实归档。"""
    task = root / "task_42"
    task.mkdir(parents=True)
    paths = tuple(task / name for name in ("b.tar.gz", "a.tar.gz", "bad.tar.gz"))
    for path in paths:
        path.write_bytes(b"unit test archive placeholder")
    return paths


def report_payload(paths: tuple[Path, ...], config: Path) -> dict[str, Any]:
    """固定真实 CLI 质量事实只重绑定临时输入身份，允许调用方损坏字段验证拒绝路径。"""
    payload: dict[str, Any] = json.loads(FIXTURE.read_text())
    payload["config_sha256"] = hashlib.sha256(config.read_bytes()).hexdigest()
    payload["archives"] = payload["archives"][: len(paths)]
    for item, path in zip(payload["archives"], paths, strict=True):
        info = path.stat()
        item.update(path=str(path), size_bytes=info.st_size, mtime_ns=info.st_mtime_ns)
    return payload


def fake_tool(root: Path, paths: tuple[Path, ...], *, exit_code: int = 0) -> ToolsConfig:
    """临时程序严格解析真实 preview 参数，结果用固定报告；不会运行真实转换或读取数据。"""
    tools = ToolsConfig(
        registry_dir=root / "registry", library_root=root / "library", cache_root=root / "cache"
    )
    package = tools.registry_dir / TOOL_NAME
    shutil.copytree(Path(__file__).parents[1] / "tools" / TOOL_NAME, package)
    program = tools.library_root / TOOL_NAME / "preview"
    program.parent.mkdir(parents=True)
    payload = report_payload(paths, package / "configs/agibot_g2.toml")
    content = f"""#!{sys.executable}
import argparse, json, pathlib, sys
p = argparse.ArgumentParser()
p.add_argument("--events", required=True)
p.add_argument("command", choices=["preview"])
p.add_argument("--report-only", action="store_true", required=True)
p.add_argument("-c", required=True)
p.add_argument("--rules", required=True)
p.add_argument("--result", required=True)
p.add_argument("inputs", nargs="+")
a = p.parse_args()
payload = json.loads({json.dumps(payload)!r})
assert a.inputs == [item["path"] for item in payload["archives"]]
with pathlib.Path(a.result).open("x") as output:
    json.dump(payload, output)
sys.stderr.write('{{"event":"progress","stage":"preview","done":3,"total":3}}\\n')
sys.exit({exit_code})
"""
    program.write_text(content)
    program.chmod(0o700)
    manifest = package / "tool.toml"
    text = manifest.read_text()
    before, rest = text.split("[program]\n", 1)
    _, after = rest.split("[io]\n", 1)
    manifest.write_text(
        before + f'[program]\npath = "preview"\nsize = {program.stat().st_size}\n'
        f'sha256 = "{hashlib.sha256(program.read_bytes()).hexdigest()}"\n[io]\n' + after
    )
    return tools


@contextmanager
def g2_case(
    root: Path, paths: tuple[Path, ...], *, exit_code: int = 0
) -> Generator[AgibotPreviewCase]:
    """平台 worker 和事务真实执行；仅临时假程序绕过 OS 沙箱，参数仍校验沙箱边界。"""
    tools = fake_tool(root, paths, exit_code=exit_code)
    roots = (StorageRootConfig(name="input", path=root / "input", nfs_export="test:/input"),)
    calls: list[tuple[tuple[str, ...], SandboxSpec, tuple[Path, ...]]] = []

    def sandbox(argv: tuple[str, ...], spec: SandboxSpec, readonly: tuple[Path, ...]):
        sandbox_argv(argv, spec, readonly_roots=readonly)
        calls.append((argv, spec, readonly))
        return argv

    with job_database(root / "state") as (engine, state):
        seed_inputs(engine, paths, input_format="archives")
        registry = JobRegistry()
        register_cleaning_jobs(
            registry,
            tools,
            CleaningDependencies(engine, tools, roots, storage_checker(roots), sandbox=sandbox),
        )
        yield AgibotPreviewCase(
            engine, state, registry, tools, paths[0], calls, "", TOOL_NAME, MODEL
        )
