"""M4.5 的 LeRobot 环境入口；仅加载本地数据、删除指定段并输出结果，不负责登记核对。"""

import argparse
import json
import sys
from pathlib import Path

from lerobot.datasets.dataset_tools import delete_episodes
from lerobot.datasets.lerobot_dataset import LeRobotDataset


def _main() -> None:
    """源目录只读，目标必须由 LeRobot 新建；离线环境与沙箱由平台提供。"""
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("target", type=Path)
    parser.add_argument("episodes", type=int, nargs="+")
    args = parser.parse_args()
    dataset = LeRobotDataset("local/source", root=args.source)
    result = delete_episodes(
        dataset, episode_indices=args.episodes, output_dir=args.target, repo_id="local/cleaned"
    )
    sys.stdout.write(
        json.dumps({"total_episodes": result.num_episodes, "total_frames": result.num_frames})
        + "\n"
    )


if __name__ == "__main__":
    _main()
