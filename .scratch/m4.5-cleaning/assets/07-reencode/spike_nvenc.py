import json, sys, time
from pathlib import Path
src, dst, eps = Path(sys.argv[1]), Path(sys.argv[2]), [int(x) for x in sys.argv[3].split(",")]
t = time.time()
from lerobot.datasets import dataset_tools
from lerobot.datasets.lerobot_dataset import LeRobotDataset

class ToolEncoder:
    vcodec = "hevc_nvenc"
    pix_fmt = "yuv420p"
    def get_codec_options(self, encoder_threads=None, as_strings=False):
        return {"g": "2", "bf": "0", "rc": "constqp", "qp": "30"}

seen = []
def encoder_for(info):
    seen.append(info.get("video.codec"))
    return ToolEncoder()
dataset_tools.encoder_config_from_video_info = encoder_for
ds = LeRobotDataset("local/spike", root=src)
out = dataset_tools.delete_episodes(ds, episode_indices=eps, output_dir=dst, repo_id="local/spike_cleaned")
print(json.dumps({"episodes": out.meta.total_episodes, "frames": out.meta.total_frames, "s": round(time.time() - t, 1), "seen": seen}))
