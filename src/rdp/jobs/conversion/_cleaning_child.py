"""M4.5 产物核对的受管子进程；复用入库解析器，只读元数据，写小型核对结果。"""

import json
import sys
from pathlib import Path

from pydantic import ValidationError

from rdp.jobs.conversion._check_data import MAX_INFO_BYTES, episodes, safe
from rdp.jobs.conversion.check_models import LeRobotInfo


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


if __name__ == "__main__":
    target = Path(sys.argv[3])
    with safe(target.parent, target.name).open("x") as stream:
        json.dump(
            {"mismatch": _check(Path(sys.argv[1]), json.loads(Path(sys.argv[2]).read_text()))},
            stream,
        )
