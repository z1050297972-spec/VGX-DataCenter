"""入库视频检查（M4-04）；ffprobe只读编码头，不逐帧解码，按引用帧数比较时长。"""

import json
import math
import shutil
import sqlite3
import subprocess
from contextlib import closing
from pathlib import Path
from typing import Any

from rdp.jobs.conversion import _check_data as data
from rdp.jobs.conversion.check_models import FeatureInfo, LeRobotInfo

# 单文件探测最多15秒；ffprobe的秒文本有舍入，1微秒以内不作为业务警告。
PROBE_TIMEOUT_S = 15.0
DURATION_ROUNDING_S = 0.000001


def _reference(root: Path, info: LeRobotInfo, key: str, row: dict[str, Any]) -> Path:
    """按版本解释视频引用；模板不能指向暂存产物之外。"""
    index = int(row["episode_index"])
    values: dict[str, str | int] = {
        "video_key": key,
        "episode_index": index,
        "episode_chunk": index // info.chunks_size,
    }
    if info.codebase_version == "v3.0":
        values.update(
            chunk_index=int(row[f"videos/{key}/chunk_index"]),
            file_index=int(row[f"videos/{key}/file_index"]),
        )
    if info.video_path is None:
        raise ValueError("视频特征缺少video_path模板")
    return data.safe(root, info.video_path.format_map(values))


def _probe(path: Path, feature: FeatureInfo, frames: int, fps: float) -> str | None:
    """核对单文件编码、尺寸和时长，失败由视频层统一变成诊断。"""
    result = subprocess.run(  # noqa: S603 # 理由：固定ffprobe只读命令和受控产物路径，无shell。
        (
            shutil.which("ffprobe") or "/usr/bin/ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=codec_name,width,height,duration:format=duration",
            "-of",
            "json",
            str(path),
        ),
        capture_output=True,
        check=True,
        timeout=PROBE_TIMEOUT_S,
    )
    payload = json.loads(result.stdout)
    stream = payload["streams"][0]
    if (
        stream["codec_name"] != feature.info.get("video.codec")
        or (stream["height"], stream["width"]) != feature.shape[:2]
    ):
        raise ValueError(f"视频编码或尺寸与info不一致：{path.name}")
    duration = float(stream.get("duration", payload["format"]["duration"]))
    difference = abs(duration - frames / fps)
    if not math.isfinite(duration) or difference > 1 / fps + DURATION_ROUNDING_S:
        raise ValueError(f"视频时长不一致：{path.name}，实际{duration}s，预期{frames / fps}s")
    return (
        f"视频时长偏差{difference}s（不超过一帧）：{path.name}"
        if difference > DURATION_ROUNDING_S
        else None
    )


def videos(root: Path, info: LeRobotInfo, scratch: Path) -> list[str]:
    """用临时磁盘索引累计每个视频的引用帧数，不依赖元数据分片的枚举顺序。"""
    warnings: list[str] = []
    # 同一个v3视频可被多个元数据分片引用；不能把相邻行分组当成完整文件。
    # 标准库SQLite负责磁盘聚合，内存不随episode或视频文件数增长；父进程管理临时目录。
    with closing(sqlite3.connect(scratch / "videos.sqlite", timeout=1.0)) as index:
        index.execute("CREATE TABLE videos (path TEXT PRIMARY KEY, feature TEXT, frames INTEGER)")
        for row in data.episodes(root, info):
            for key, feature in info.features.items():
                if feature.dtype == "video":
                    path = _reference(root, info, key, row)
                    index.execute(
                        "INSERT INTO videos VALUES (?, ?, ?) "
                        "ON CONFLICT(path) DO UPDATE SET frames=frames+excluded.frames",
                        (str(path), key, int(row["length"])),
                    )
        for path, key, frames in index.execute("SELECT path, feature, frames FROM videos"):
            _append_warning(warnings, _probe(Path(path), info.features[key], frames, info.fps))
    return warnings


def _append_warning(warnings: list[str], warning: str | None) -> None:
    """警告只保留首个样例，避免随文件数量增长；结论仍需要人工确认。"""
    if warning is not None and not warnings:
        warnings.append(warning)
