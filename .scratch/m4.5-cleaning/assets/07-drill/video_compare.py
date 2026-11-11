"""M4.5 第 07 张复验：工具原产物与清洗后产物逐路对照视频流参数、GOP 和 PSNR。

用法：python -I video_compare.py <原产物 out 目录> <清洗产物目录> <结果文本>
剔除的是原产物 episode 2；保留帧段按原产物 episodes 元数据换算。只读两个产物目录。
"""

import json
import subprocess
import sys
from pathlib import Path

import pyarrow.parquet as pq

orig, prod, out = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
info = json.loads((orig / "meta/info.json").read_text())
fps = info["fps"]
rows = pq.read_table(orig / "meta/episodes/chunk-000/file-000.parquet").to_pylist()
keys = [k for k, v in info["features"].items() if v["dtype"] == "video"]
fields = "codec_name,profile,level,pix_fmt,color_range,has_b_frames,time_base,r_frame_rate,nb_frames"


def probe(path: Path) -> str:
    return subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=" + fields,
         "-of", "compact=nk=0", str(path)],
        capture_output=True, text=True, check=True,
    ).stdout.strip()


lines = []
for key in keys:
    rel = f"videos/{key}/chunk-000/file-000.mp4"
    keep = [
        (round(r[f"videos/{key}/from_timestamp"] * fps), round(r[f"videos/{key}/to_timestamp"] * fps))
        for r in rows
        if r["episode_index"] != 2
    ]
    expr = "+".join(f"between(n\\,{s}\\,{e - 1})" for s, e in keep)
    stderr = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats", "-i", str(prod / rel), "-i", str(orig / rel),
         "-filter_complex", f"[1:v]select='{expr}',setpts=N/{fps}/TB[r];[0:v][r]psnr", "-f", "null", "-"],
        capture_output=True, text=True,
    ).stderr
    psnr = [line for line in stderr.splitlines() if "PSNR" in line][-1].split("PSNR ")[-1]
    gop = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "frame=pict_type",
         "-of", "csv=p=0", "-read_intervals", "%+#8", str(prod / rel)],
        capture_output=True, text=True,
    ).stdout.split()
    lines += [
        f"== {key} 保留帧段 {keep}",
        f"  原产物 {probe(orig / rel)}  {(orig / rel).stat().st_size} 字节",
        f"  清洗后 {probe(prod / rel)}  {(prod / rel).stat().st_size} 字节",
        f"  清洗后前 8 帧类型 {' '.join(gop)}",
        f"  PSNR（清洗后 vs 原产物对应帧）{psnr}",
    ]
out.write_text("\n".join(lines) + "\n")
print("\n".join(lines))
