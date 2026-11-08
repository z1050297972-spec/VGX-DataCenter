"""LeRobot 版本布局与流式 parquet 读取（M4-04）。

标准库不能解析 parquet，使用已批准的 pyarrow；只在适配边界消费其动态接口。
逐批读取 episode 元数据和内容，不把全部帧物化；目录模板始终限制在产物内。
"""

import json
import os
from collections.abc import Iterator
from fnmatch import fnmatchcase
from importlib import import_module
from pathlib import Path
from typing import Any, cast

from rdp.jobs.conversion.check_models import LeRobotInfo

# 一批1024行限制Arrow转Python对象的内存；JSONL单行最多4MiB，与info预算相同。
BATCH_ROWS = 1024
MAX_INFO_BYTES = 4 * 1024 * 1024


def safe(root: Path, relative: str) -> Path:
    """格式模板、目录枚举都必须落在本产物目录内，拒绝目录链上的软链接。"""
    path = root / relative
    if not path.is_relative_to(root) or ".." in path.relative_to(root).parts:
        raise ValueError(f"产物路径越界：{relative}")
    for part in (path, *path.parents):
        if part == root.parent:
            break
        if part.is_symlink():
            raise ValueError(f"产物包含软链接：{relative}")
    return path


def files(root: Path, pattern: str) -> Iterator[Path]:
    """只枚举固定层级的匹配文件；Path.glob会先跟随中间链接，故逐层使用scandir。"""
    safe(root, ".")
    yield from _glob(root, tuple(pattern.split("/")))


def _glob(parent: Path, parts: tuple[str, ...]) -> Iterator[Path]:
    """每次只持有当前目录迭代器，进入子目录之前拒绝软链接。"""
    with os.scandir(parent) as entries:
        for entry in entries:
            if not fnmatchcase(entry.name, parts[0]):
                continue
            if entry.is_symlink():
                raise ValueError(f"产物包含软链接：{entry.path}")
            if len(parts) == 1:
                yield Path(entry.path)
            elif entry.is_dir(follow_symlinks=False):
                yield from _glob(Path(entry.path), parts[1:])


def rows(path: Path, columns: list[str] | None = None) -> Iterator[dict[str, Any]]:
    """pyarrow为无类型第三方边界，每批转换至多1024行。"""
    parquet = import_module("pyarrow.parquet")
    with path.open("rb") as stream:
        file = parquet.ParquetFile(stream)
        for batch in file.iter_batches(batch_size=BATCH_ROWS, columns=columns):
            yield from batch.to_pylist()


def episodes(root: Path, info: LeRobotInfo) -> Iterator[dict[str, Any]]:
    """按版本读取episode记录；v2.1用JSONL，v3.0用parquet批读取。"""
    if info.codebase_version == "v3.0":
        for path in files(root, "meta/episodes/chunk-*/file-*.parquet"):
            yield from rows(path)
    else:
        with safe(root, "meta/episodes.jsonl").open("rb") as stream:
            while line := stream.readline(MAX_INFO_BYTES + 1):
                if len(line) > MAX_INFO_BYTES:
                    raise ValueError("episode元数据行超过4MiB")
                yield json.loads(line)


def data_path(root: Path, info: LeRobotInfo, episode: dict[str, Any]) -> Path:
    """v3文件由episode引用；v2文件由episode编号及chunk大小推导。"""
    index = int(episode["episode_index"])
    values = {"episode_index": index, "episode_chunk": index // info.chunks_size}
    if info.codebase_version == "v3.0":
        values.update(
            chunk_index=int(episode["data/chunk_index"]), file_index=int(episode["data/file_index"])
        )
    return safe(root, info.data_path.format_map(values))


def structure(root: Path, expected: str) -> tuple[LeRobotInfo, list[str]]:
    """检查必须文件及data引用；视频引用在视频层给出对应诊断。"""
    with safe(root, "meta/info.json").open("rb") as stream:
        raw = stream.read(MAX_INFO_BYTES + 1)
    if len(raw) > MAX_INFO_BYTES:
        raise ValueError("meta/info.json超过4MiB")
    info = LeRobotInfo.model_validate_json(raw)
    if info.codebase_version != expected:
        raise ValueError("codebase_version与转换参数不一致")
    required = ["meta/stats.json", "data"]
    required += (
        ["meta/tasks.parquet", "meta/episodes"]
        if info.codebase_version == "v3.0"
        else ["meta/tasks.jsonl", "meta/episodes.jsonl"]
    )
    for relative in required:
        if not safe(root, relative).exists():
            raise ValueError(f"缺少必需文件或目录：{relative}")
    for key in ("observation.state", "action"):
        if key not in info.features:
            raise ValueError(f"缺少特征：{key}")
    found = False
    for episode in episodes(root, info):
        found = True
        if not data_path(root, info, episode).is_file():
            raise ValueError(f"episode {episode['episode_index']} 缺少data文件")
    if not found:
        raise ValueError("没有episode元数据")
    extras = sorted(info.model_extra or {})
    return info, [f"未知info顶层字段：{', '.join(extras)}"] if extras else []


def counts(root: Path, info: LeRobotInfo) -> list[str]:
    """计数只读data parquet footer；episode长度由元数据流式求和。"""
    count = length = total = 0
    for episode in episodes(root, info):
        count += 1
        length += int(episode["length"])
    parquet = import_module("pyarrow.parquet")
    pattern = "data/chunk-*/*.parquet"
    for path in files(root, pattern):
        with path.open("rb") as stream:
            total += parquet.ParquetFile(stream).metadata.num_rows
    if count != info.total_episodes or length != info.total_frames or total != info.total_frames:
        raise ValueError(
            f"计数不一致：episodes={count}/{info.total_episodes}，长度和={length}，parquet行数={total}，声明帧数={info.total_frames}"
        )
    return []


def content(root: Path, info: LeRobotInfo) -> list[str]:
    """全量逐批检查维度，仅首/中/末episode检查有限值；不读取视频帧。"""
    import math

    keys = ("observation.state", "action")
    selected = {0, info.total_episodes // 2, info.total_episodes - 1}
    for path in files(root, "data/chunk-*/*.parquet"):
        for row in rows(path, ["episode_index", *keys]):
            for key in keys:
                vector = row[key]
                if not isinstance(vector, list):
                    raise ValueError(f"{key}不是向量，episode={row['episode_index']}")
                values = cast(list[float], vector)
                if (len(values),) != info.features[key].shape:
                    raise ValueError(f"{key}维度不一致，episode={row['episode_index']}")
                if row["episode_index"] in selected and any(
                    not math.isfinite(value) for value in values
                ):
                    raise ValueError(f"{key}包含NaN/Inf，episode={row['episode_index']}")
    return []
