"""只读检查：导航层本身的读取耗时，以及 LeRobot 数据块的 meta/info.json（决策票「数据集板块的数据契约」）。

用法：python3 -I read_checks.py /mnt/datasets

第 1 段只读导航层（不跟随软链接）；第 2 段读数据盘上的 meta/info.json。只做 open/read/stat/readlink，不写任何东西。
"""
import json, os, sys, time

ROOT = sys.argv[1]
os.chdir(ROOT)

# 1. 只读导航层本身：遍历两个视图、readlink、解析全部 JSON，不碰数据盘
t = time.monotonic(); n_json = n_link = 0
for view in ("按任务", "按格式"):
    for dp, dn, fn in os.walk(view, followlinks=False):
        for name in fn + dn:
            p = os.path.join(dp, name)
            if os.path.islink(p):
                os.readlink(p); n_link += 1
            elif name.endswith(".json"):
                with open(p, encoding="utf-8") as fh:
                    json.load(fh)
                n_json += 1
print(f"1. 只读导航层：{n_json} 份 JSON，{n_link} 条链接，{time.monotonic() - t:.3f} s")

# 2. LeRobot 数据块的 meta/info.json：覆盖率、robot_type、格式版本是否一致
t = time.monotonic(); total = found = 0; mismatch = []; per = {}
for d in sorted(os.listdir("按任务")):
    with open(os.path.join("按任务", d, "原始路径.json"), encoding="utf-8") as fh:
        j = json.load(fh)
    types = set()
    for s in j["sources"]:
        if s["format"] != "lerobot":
            continue
        total += 1
        f = os.path.join(s["direct_path"], "meta", "info.json")
        if not os.path.exists(f):
            continue
        found += 1
        with open(f, encoding="utf-8") as fh:
            info = json.load(fh)
        types.add(str(info.get("robot_type")))
        if info.get("codebase_version") != f"v{s.get('version')}":
            mismatch.append((d, s["source_id"], s.get("version"), info.get("codebase_version")))
    per[d] = types
print(f"2. LeRobot 数据块 {total} 条，有 info.json 的 {found} 条，格式版本不一致 {len(mismatch)} 条，{time.monotonic() - t:.3f} s")
unknown = sorted(d for d, ts in per.items() if ts and ts <= {"unknown", "None"})
named = sorted(d for d, ts in per.items() if ts and not ts <= {"unknown", "None"})
print(f"   robot_type 有具体值的数据集 {len(named)} 个；只有 unknown/null 的 {len(unknown)} 个：{unknown}")
