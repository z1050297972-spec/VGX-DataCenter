"""转换验收的假外部工具；登记、输入、状态和产物均在临时目录。"""

import hashlib
import sys
import tomllib
from pathlib import Path

from tool_registry_support import ToolFiles, tool_files

from rdp.infra.config import StorageConfig, StorageRootConfig, ToolsConfig
from rdp.infra.storage import DeviceNumber, MountInspector, StorageAccessChecker, read_storage_root
from rdp.jobs.sandbox import SandboxSpec


def fake_converter(
    root: Path, *, verify_code: int = 0, lengths: tuple[int, ...] = (3, 3)
) -> ToolFiles:
    """假程序按真实命令解析参数，仅在终端打印固定进度，并留下可观察的调用记录。"""
    files = tool_files(root)
    content = f"""#!{sys.executable}
import argparse, json, pathlib, sys, time
import pyarrow as pa
import pyarrow.parquet as pq
parser = argparse.ArgumentParser()
parser.add_argument("command", choices=["verify", "convert"])
parser.add_argument("-c", required=True)
parser.add_argument("-o")
parser.add_argument("--format")
parser.add_argument("-y", action="store_true")
parser.add_argument("inputs", nargs="+")
a = parser.parse_args()
assert pathlib.Path(a.c).is_file()
assert all(pathlib.Path(p).exists() for p in a.inputs)
with pathlib.Path(__file__).with_suffix(".calls").open("a") as log:
    log.write(a.command + "\\n")
pathlib.Path(__file__).with_suffix(".inputs").write_text(json.dumps(a.inputs))
if a.command == "verify":
    print("话题核对：缺少右臂目标" if {verify_code} else "话题核对通过", flush=True)
    sys.exit({verify_code})
assert a.y and a.format in ("v3.0", "v2.1")
assert sys.stderr.isatty()
sys.stderr.write("扫描 [===] 4/4 条消息\\n")
sys.stderr.flush()
time.sleep(0.6)
sys.stderr.write("head_left [===] 6/6 帧  完成\\nstate [===] 6/6 帧  完成\\naction [===] 6/6 帧  完成\\n")
output = pathlib.Path(a.o)
(output / "meta").mkdir(parents=True)
lengths = {lengths!r}
(output / "meta/info.json").write_text(json.dumps({{"total_episodes": len(lengths), "total_frames": sum(lengths), "codebase_version": a.format, "fps": 30, "features": {{}}, "data_path": "data/chunk-{{chunk_index:03d}}/file-{{file_index:03d}}.parquet"}}))
rows = [{{"episode_index": i, "length": n}} for i, n in enumerate(lengths)]
if a.format == "v3.0":
    (output / "meta/episodes/chunk-000").mkdir(parents=True)
    pq.write_table(pa.Table.from_pylist(rows), output / "meta/episodes/chunk-000/file-000.parquet")
else:
    (output / "meta/episodes.jsonl").write_text("".join(json.dumps(row) + "\\n" for row in rows))
""".encode()
    manifest_path = files.package / "tool.toml"
    text = manifest_path.read_text()
    manifest = tomllib.loads(text)
    manifest_path.write_text(
        text.replace(str(manifest["program"]["size"]), str(len(content))).replace(
            manifest["program"]["sha256"], hashlib.sha256(content).hexdigest()
        )
    )
    files.program.write_bytes(content)
    files.program.chmod(0o700)
    return files


def no_sandbox(
    argv: tuple[str, ...], spec: SandboxSpec, roots: tuple[Path, ...]
) -> tuple[str, ...]:
    """只替换操作系统沙箱边界，真实进程生命周期仍由平台执行。"""
    return argv


def settings(files: ToolFiles) -> ToolsConfig:
    """把工具库显式指向临时目录，避免默认部署路径。"""
    return ToolsConfig(registry_dir=files.registry, library_root=files.library)


def storage_checker(roots: tuple[StorageRootConfig, ...]) -> StorageAccessChecker:
    """临时目录用合成挂载表，保留真实目录只读访问。"""
    from jobs_storage_support import NOW

    table = "".join(
        f"{20 + i} 1 8:1 / {r.path} rw - "
        + (f"nfs4 {r.nfs_export}" if r.nfs_export else "ext4 /dev/fake")
        + " rw\n"
        for i, r in enumerate(roots)
    )
    return StorageAccessChecker(
        MountInspector(roots, lambda: table, lambda _: DeviceNumber(8, 1), lambda: NOW),
        StorageConfig(),
        read_storage_root,
    )
