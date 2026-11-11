"""M4.5 的 LeRobot 环境入口；加载本地数据并按工具编码参数删除指定段。

临时替换依赖 _keep_episodes_from_video_with_av 只读取 vcodec、pix_fmt 和
get_codec_options 三个成员；这份源码由运行前的环境指纹核对锁定。
不修改 info.json 的编码信息，仍保留工具写入的内容；不负责登记核对和沙箱。
"""

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

from lerobot.datasets import dataset_tools
from lerobot.datasets.lerobot_dataset import LeRobotDataset


@dataclass(frozen=True)
class _ToolEncoder:
    """适配已锁定的 PyAV 调用面，避免 LeRobot 再按流编码名挑选 CPU 编码器。

    Attributes:
        vcodec: 工具配置的编码器名，不在此处设置白名单。
        pix_fmt: 工具配置的输出像素格式。
        options: 按工具顺序排列的字符串选项表。
    """

    vcodec: str
    pix_fmt: str
    options: dict[str, str]

    def get_codec_options(
        self, encoder_threads: int | None = None, as_strings: bool = False
    ) -> dict[str, str]:
        """返回选项副本；线程数和字符串开关不改变平台已换算好的工具参数。"""
        return self.options.copy()


def _main() -> None:
    """源目录只读，目标必须由 LeRobot 新建；离线环境与沙箱由平台提供。"""
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("target", type=Path)
    parser.add_argument("episodes", type=int, nargs="+")
    parser.add_argument("--encoder", required=True, type=json.loads)
    args = parser.parse_args()
    encoder = _ToolEncoder(**args.encoder)
    dataset = LeRobotDataset("local/source", root=args.source)

    def encoder_for_info(_info: object) -> _ToolEncoder:
        return encoder

    original = dataset_tools.encoder_config_from_video_info
    # 仅覆盖删除调用；失败同样恢复，避免后续调用继承这次作业的配置。
    dataset_tools.encoder_config_from_video_info = encoder_for_info
    try:
        result = dataset_tools.delete_episodes(
            dataset, episode_indices=args.episodes, output_dir=args.target, repo_id="local/cleaned"
        )
    finally:
        dataset_tools.encoder_config_from_video_info = original
    sys.stdout.write(
        json.dumps({"total_episodes": result.num_episodes, "total_frames": result.num_frames})
        + "\n"
    )


if __name__ == "__main__":
    _main()
