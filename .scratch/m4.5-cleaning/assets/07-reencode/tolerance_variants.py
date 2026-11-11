import re, sys, time
from pathlib import Path
from rdp.jobs.cleaning.report import build_cleaning_report
repo = Path(sys.argv[1]); sample = Path(sys.argv[2]); out = Path(sys.argv[3])
base = (repo / "tools/mcap2lerobot/configs/r1lite.toml").read_text()
rules = repo / "tools/mcap2lerobot/cleaning/r1lite.toml"
def arm(text, ms):
    for side in ("left", "right"):
        old = f'{{ topic = "/motion_target/target_joint_state_arm_{side}", field = "position" }}'
        assert old in text, old
        text = text.replace(old, old[:-2] + f", max_dt_ms = {ms} }}")
    return text
def wrist(text, ms):
    n = len(re.findall(r"^max_dt_ms = 35 ", text, re.M)); assert n == 2, n
    return re.sub(r"^max_dt_ms = 35 ", f"max_dt_ms = {ms} ", text, flags=re.M)
variants = {"现状": base, "手臂目标16": arm(base, 16), "手臂目标16+手腕40": wrist(arm(base, 16), 40)}
for name, text in variants.items():
    cfg = out / f"{name}.toml"; cfg.write_text(text)
    t = time.time()
    r = build_cleaning_report([("s", sample)], cfg, rules, checkpoint=lambda: None, progress=lambda n: None)
    f = r.files[0]
    bad = {t.topic.rsplit("/", 1)[-1] if "camera" not in t.topic else t.topic: (t.tolerance_ms, round(t.max_abs_dt_ms, 2), t.bad_frames) for t in f.topics if t.bad_frames}
    print(f"{name}: 坏帧 {f.bad_frames} 保留 {f.kept_frames}/{f.reference_frames} episode {[e.frame_count for e in r.episodes]} 有坏帧的话题 {bad} ({time.time()-t:.0f}s)", flush=True)
