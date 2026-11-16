"""M4.5 产物核对的受管子进程；复用入库解析器，只读元数据，写小型核对结果。"""

import json
import sys
from pathlib import Path

from pydantic import BaseModel, ConfigDict, ValidationError

from rdp.jobs.conversion._check_data import MAX_INFO_BYTES, episodes, safe
from rdp.jobs.conversion.check_models import LeRobotInfo


class _Expectation(BaseModel):
    """父进程写入的预览核对契约，缺映射仅用于 MCAP/Alpha。"""

    model_config = ConfigDict(extra="forbid", strict=True)
    frames: list[int]
    source_episodes: list[tuple[str, int]] | None = None


def _check(root: Path, expected: list[int]) -> str | None:
    """按产物编号比对每段帧数，拒绝重复或缺失编号并返回第一处差异。"""
    try:
        with safe(root, "meta/info.json").open("rb") as stream:
            info = LeRobotInfo.model_validate_json(stream.read(MAX_INFO_BYTES))
        if info.total_episodes != len(expected):
            return f"episode 数 {info.total_episodes}，预览 {len(expected)}"
        seen: set[int] = set()
        for episode in episodes(root, info):
            index, length = int(episode["episode_index"]), int(episode["length"])
            if index in seen or not 0 <= index < len(expected):
                return f"episode 编号重复或越界：{index}"
            if length != expected[index]:
                return f"episode {index} 帧数 {length}，预览 {expected[index]}"
            seen.add(index)
        if len(seen) != len(expected):
            return f"episode 元数据数 {len(seen)}，预览 {len(expected)}"
        if info.total_frames != sum(expected):
            return f"总帧数 {info.total_frames}，预览 {sum(expected)}"
    except (OSError, ValueError, KeyError, ValidationError) as error:
        return f"产物元数据无法核对：{error}"
    return None


def _mapping(root: Path, expected: list[tuple[str, int]]) -> str | None:
    """逐行核对真实工具的来源映射；同长度集调换也必须拒绝。"""
    try:
        with safe(root, "meta/agibot_episodes.jsonl").open("rb") as stream:
            for index, (archive, episode) in enumerate(expected):
                # 附加原始标注允许较大行，8 MiB 是单行防护预算，超限不得截断接受。
                line = stream.readline(8 * 1024 * 1024 + 1)
                if len(line) > 8 * 1024 * 1024:
                    return "源集映射单行超过 8 MiB"
                row = json.loads(line)
                if (
                    type(row.get("episode_index")) is not int
                    or type(row.get("source_episode_index")) is not int
                    or (
                        row["episode_index"],
                        row.get("source_archive"),
                        row["source_episode_index"],
                    )
                    != (index, archive, episode)
                ):
                    return f"episode {index} 来源映射与预览不符"
            if stream.read(1):
                return "源集映射存在多余记录"
    except (OSError, ValueError, KeyError, TypeError) as error:
        return f"源集映射无法核对：{error}"
    return None


if __name__ == "__main__":
    target = Path(sys.argv[3])
    expectation = _Expectation.model_validate_json(Path(sys.argv[2]).read_bytes())
    mismatch = _check(Path(sys.argv[1]), expectation.frames)
    if mismatch is None and expectation.source_episodes is not None:
        mismatch = _mapping(Path(sys.argv[1]), expectation.source_episodes)
    with safe(target.parent, target.name).open("x") as stream:
        json.dump(
            {"mismatch": mismatch},
            stream,
        )
