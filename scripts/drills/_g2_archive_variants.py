"""仅改写临时合成 tar 的源集编号，用非连续编号验证平台不按连续下标猜测身份。"""

# ruff: noqa: S101  # 理由：手动验收装配用断言阻止不合约结果继续执行。

import copy
import importlib
import io
import json
import tarfile
from pathlib import Path
from typing import Any


def sparse_episode(path: Path) -> None:
    """把 factory 生成的源集 1 改为 7；元信息、parquet 和成员路径同步改写。"""
    pa = importlib.import_module("pyarrow")
    pq = importlib.import_module("pyarrow.parquet")
    destination = path.with_suffix(".new")
    with tarfile.open(path, "r:gz") as source, tarfile.open(destination, "w:gz") as target:
        for member in source:
            stream = source.extractfile(member)
            assert stream is not None
            payload = stream.read()
            if member.name.endswith("episode_000001.parquet"):
                table = pq.read_table(pa.BufferReader(payload))
                index = table.schema.get_field_index("episode_index")
                table = table.set_column(
                    index, "episode_index", pa.array([7] * len(table), type=pa.int64())
                )
                output = io.BytesIO()
                pq.write_table(table, output)
                payload = output.getvalue()
            elif member.name.endswith(("episodes.jsonl", "episodes_stats.jsonl")):
                rows = [json.loads(line) for line in payload.splitlines()]
                for row in rows:
                    if row["episode_index"] == 1:
                        row["episode_index"] = 7
                payload = ("".join(json.dumps(row) + "\n" for row in rows)).encode()
            elif member.name.endswith("info.json"):
                metadata: dict[str, Any] = json.loads(payload)
                for field in (
                    "instruction_segments",
                    "key_frame",
                    "take_over",
                    "h5_path",
                    "camera_parameters",
                ):
                    metadata[field]["7"] = metadata[field].pop("1")
                payload = json.dumps(metadata).encode()
            header = copy.copy(member)
            header.name = header.name.replace("episode_000001", "episode_000007")
            header.size = len(payload)
            target.addfile(header, io.BytesIO(payload))
    destination.replace(path)
