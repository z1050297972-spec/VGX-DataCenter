"""M4-04 临时产物：保留真实 info/stats，缺失的 parquet 在 tmp 中合成，不改样本。"""

import importlib
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any


def product(path: Path, *, nan: bool = False) -> Path:
    """复制登记样本元信息，补五个 episode 和三路低分辨率视频。"""
    shutil.copytree(Path(__file__).parent / "fixtures/mcap2lerobot/lerobot-v3", path)
    arrow = importlib.import_module("pyarrow")
    parquet = importlib.import_module("pyarrow.parquet")
    info = json.loads((path / "meta/info.json").read_text())
    lengths = [300, 300, 300, 300, 447]
    episodes: list[dict[str, Any]] = []
    offset = 0
    for index, length in enumerate(lengths):
        row: dict[str, int | float] = {
            "episode_index": index,
            "length": length,
            "data/chunk_index": 0,
            "data/file_index": 0,
            "dataset_from_index": offset,
            "dataset_to_index": offset + length,
        }
        for key, feature in info["features"].items():
            if feature["dtype"] == "video":
                row.update(
                    {
                        f"videos/{key}/chunk_index": 0,
                        f"videos/{key}/file_index": 0,
                        f"videos/{key}/from_timestamp": offset / 30,
                        f"videos/{key}/to_timestamp": (offset + length) / 30,
                    }
                )
        episodes.append(row)
        offset += length
    (path / "meta/episodes/chunk-000").mkdir(parents=True)
    parquet.write_table(
        arrow.Table.from_pylist(episodes), path / "meta/episodes/chunk-000/file-000.parquet"
    )
    parquet.write_table(
        arrow.table({"task_index": [0], "task": ["收桌子"]}), path / "meta/tasks.parquet"
    )
    (path / "data/chunk-000").mkdir(parents=True)
    states = [[0.25] * 14 for _ in range(1647)]
    if nan:
        states[700][3] = float("nan")
    parquet.write_table(
        arrow.table(
            {
                "episode_index": [i for i, n in enumerate(lengths) for _ in range(n)],
                "observation.state": states,
                "action": [[0.5] * 14] * 1647,
            }
        ),
        path / "data/chunk-000/file-000.parquet",
    )
    for key, feature in info["features"].items():
        if feature["dtype"] != "video":
            continue
        feature["shape"] = [16, 32, 3]
        feature["info"].update({"video.codec": "h264", "video.height": 16, "video.width": 32})
        video = path / f"videos/{key}/chunk-000/file-000.mp4"
        video.parent.mkdir(parents=True)
        subprocess.run(  # noqa: S603 # 理由：固定系统ffmpeg，只写tmp副本。
            [
                shutil.which("ffmpeg") or "/usr/bin/ffmpeg",
                "-v",
                "error",
                "-f",
                "lavfi",
                "-i",
                "color=s=32x16:r=30",
                "-frames:v",
                "1647",
                "-c:v",
                "libx264",
                "-threads",
                "1",
                str(video),
            ],
            check=True,
            timeout=30,
        )
    (path / "meta/info.json").write_text(json.dumps(info))
    return path


def version_two(path: Path) -> None:
    """把tmp中的同一组合成帧按v2.1布局重排；不改只读登记样本。"""
    parquet = importlib.import_module("pyarrow.parquet")
    info = json.loads((path / "meta/info.json").read_text())
    info.update(
        codebase_version="v2.1",
        data_path="data/chunk-{episode_chunk:03d}/episode_{episode_index:06d}.parquet",
        video_path="videos/chunk-{episode_chunk:03d}/{video_key}/episode_{episode_index:06d}.mp4",
    )
    table = parquet.read_table(path / "data/chunk-000/file-000.parquet")
    lengths = [300, 300, 300, 300, 447]
    offset = 0
    episodes: list[dict[str, Any]] = []
    for index, length in enumerate(lengths):
        parquet.write_table(
            table.slice(offset, length), path / f"data/chunk-000/episode_{index:06d}.parquet"
        )
        episodes.append({"episode_index": index, "length": length, "tasks": ["收桌子"]})
        offset += length
        for key, feature in info["features"].items():
            if feature["dtype"] != "video":
                continue
            target = path / f"videos/chunk-000/{key}/episode_{index:06d}.mp4"
            target.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run(  # noqa: S603 # 理由：固定本机ffmpeg，输出在tmp副本内。
                [
                    shutil.which("ffmpeg") or "/usr/bin/ffmpeg",
                    "-v",
                    "error",
                    "-f",
                    "lavfi",
                    "-i",
                    "color=s=32x16:r=30",
                    "-frames:v",
                    str(length),
                    "-c:v",
                    "libx264",
                    "-threads",
                    "1",
                    str(target),
                ],
                check=True,
                timeout=30,
            )
    (path / "data/chunk-000/file-000.parquet").unlink()
    (path / "meta/episodes.jsonl").write_text("".join(json.dumps(row) + "\n" for row in episodes))
    (path / "meta/tasks.jsonl").write_text(json.dumps({"task_index": 0, "task": "收桌子"}) + "\n")
    (path / "meta/info.json").write_text(json.dumps(info))
