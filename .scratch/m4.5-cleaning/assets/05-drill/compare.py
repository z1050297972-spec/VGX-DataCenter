"""M4.5 第 05 张真实对照：工具 `verify -v` 的文字输出与平台清洗报告逐项比对。

用法：python3 -I compare.py <verify.txt> <平台报告 JSON（预览响应或报告本体）>
只比工具 verify 报告里有的项：基准帧数、各非基准话题的容差/|Δt| 平均和最大/复用/坏帧、
坏帧总数、断点、过短丢弃、保留帧数和每个 episode 的起止帧。|Δt| 工具只打三位小数，差在 0.0005 ms 内算一致。
"""

import json
import re
import sys

verify_text = open(sys.argv[1], encoding="utf-8").read()
data = json.load(open(sys.argv[2], encoding="utf-8"))
report = data.get("report", data)
assert len(report["files"]) == 1, "对照只针对单个文件"
file = report["files"][0]
problems: list[str] = []
checked = 0


def same(name: str, tool: object, platform: object, tolerance: float = 0.0) -> None:
    global checked
    checked += 1
    if isinstance(tool, float) or isinstance(platform, float):
        ok = platform is not None and abs(float(tool) - float(platform)) <= tolerance  # type: ignore[arg-type]
    else:
        ok = tool == platform
    print(f"{'✓' if ok else '✗'} {name}: 工具 {tool}  平台 {platform}")
    if not ok:
        problems.append(name)


reference = int(re.search(r"基准帧数\s*:\s*(\d+)", verify_text).group(1))
same("基准帧数", reference, file["reference_frames"])
topics = {t["topic"]: t for t in file["topics"]}
pattern = re.compile(
    r"^\s+[✓!]\s+(\S+)\s+容差\s+([\d.]+)\s+\|Δt\| 平均\s+([\d.]+)\s+最大\s+([\d.]+) ms\s+复用\s+(\d+)\s+坏帧\s+(\d+)",
    re.M,
)
rows = pattern.findall(verify_text)
assert rows, "verify 输出里没有话题对齐行"
for topic, tol, mean, maximum, reused, bad in rows:
    t = topics[topic]
    same(f"{topic} 容差", float(tol), t["tolerance_ms"], 0.05)
    same(f"{topic} |Δt| 平均", float(mean), t["mean_abs_dt_ms"], 0.0005)
    same(f"{topic} |Δt| 最大", float(maximum), t["max_abs_dt_ms"], 0.0005)
    same(f"{topic} 复用", int(reused), t["reused_frames"])
    same(f"{topic} 坏帧", int(bad), t["bad_frames"])
bad_total, gaps, short_count, short_frames = map(
    int, re.search(r"坏帧 (\d+)，基准断点 (\d+)，过短丢弃 (\d+) 段 (\d+) 帧", verify_text).groups()
)
same("坏帧总数", bad_total, file["bad_frames"])
same("基准断点", gaps, file["gaps"])
same("过短丢弃段数", short_count, file["short_segments"])
same("过短丢弃帧数", short_frames, file["short_frames"])
kept, total, count = map(int, re.search(r"保留 (\d+) / (\d+) 帧，切分为 (\d+) 个 episode", verify_text).groups())
same("保留帧数", kept, file["kept_frames"])
same("episode 数", count, len(report["episodes"]))
segments = [tuple(map(int, m)) for m in re.findall(r"#\d+\s+帧\s+(\d+)\.\.(\d+)\s+(\d+) 帧", verify_text)]
platform_segments = [(e["start_frame"], e["end_frame"], e["frame_count"]) for e in report["episodes"]]
for i, (tool_seg, platform_seg) in enumerate(zip(segments, platform_segments, strict=True)):
    same(f"episode #{i} 起止与帧数", tool_seg, platform_seg)
print(f"\n共核对 {checked} 项，不一致 {len(problems)} 项" + (f"：{problems}" if problems else ""))
sys.exit(1 if problems else 0)
