"""只读检查导航层 JSON 的几个设计问题（决策票「数据集板块的数据契约」）。

用法：python3 -I schema_check.py /mnt/datasets

只遍历导航层本身，不跟随软链接进入数据盘；只做 open/read，不写任何东西。
"""
import collections, hashlib, json, os, sys

ROOT = sys.argv[1]
os.chdir(ROOT)
KINDS = ("原始路径.json", "数据集信息.json", "子任务.json")


def nav_jsons(kind=None):
    """列出两个视图下的导航 JSON；followlinks=False，避免顺着链接走进数据盘。"""
    for view in ("按任务", "按格式"):
        for dp, _dn, fn in os.walk(view, followlinks=False):
            for f in fn:
                if f in KINDS and (kind is None or f == kind):
                    yield os.path.join(dp, f)


def load(p):
    with open(p, encoding="utf-8") as fh:
        return json.load(fh)


# (a) 改指向的改写范围：数据盘绝对路径在三种 JSON 里出现的次数
per_ds = collections.Counter(); total = collections.Counter()
for p in nav_jsons():
    with open(p, encoding="utf-8") as fh:
        t = fh.read()
    n = t.count("/mnt/dataset1/") + t.count("/mnt/dataset2/")
    total[os.path.basename(p)] += n
    ds = os.path.basename(os.path.dirname(p))
    if ds in ("agibot_world_2026", "agibot_world_alpha"):
        per_ds[(ds, p.split("/")[0], os.path.basename(p))] += n
print("(a) 两个视图合计出现次数：", dict(total))
for k, v in sorted(per_ds.items()):
    print("(a)  ", k, v)
md = collections.Counter()
for p in nav_jsons("数据集信息.json"):
    if p.startswith("按任务/"):
        for f in load(p)["fields"]:
            if "/mnt/dataset" in f["value_markdown"]:
                md[(f["number"], f["name"])] += 1
print("(a) value_markdown 含数据盘路径的项（按任务视图）：", sorted(md.items()))

# (b) source_id 是否等于 "src_" + sha256(original_path) 前 12 位
hit = tot = 0; ids = collections.Counter()
for p in nav_jsons("原始路径.json"):
    if not p.startswith("按任务/"):
        continue
    for s in load(p)["sources"]:
        tot += 1; ids[s["source_id"]] += 1
        hit += s["source_id"] == "src_" + hashlib.sha256(s["original_path"].encode()).hexdigest()[:12]
print("(b) source_id 与 sha256(original_path) 吻合：", hit, "/", tot, "；重复的 source_id：", sum(v > 1 for v in ids.values()))
same = sum(s["original_path"] == s["direct_path"] for p in nav_jsons("原始路径.json") if p.startswith("按任务/") for s in load(p)["sources"])
print("(b) original_path == direct_path：", same, "/", tot)

# (c) 14 项的 number/name/顺序 是否 35 份一致
shapes = collections.Counter(tuple((f["number"], f["name"]) for f in load(p)["fields"]) for p in nav_jsons("数据集信息.json") if p.startswith("按任务/"))
print("(c) 14 项结构的种类数：", len(shapes), "各自份数：", list(shapes.values()))

# (e) sources[].entry_path 能否由 links 推出：link.entry_path + (direct_path 去掉 link.source_path 前缀)
ok = bad = absolute = 0
for p in nav_jsons("原始路径.json"):
    j = load(p)
    for s in j["sources"]:
        if s["entry_path"].startswith("/"):
            absolute += 1
            continue
        derived = next((l["entry_path"] + s["direct_path"][len(l["source_path"]):] for l in j["links"]
                        if s["direct_path"] == l["source_path"] or s["direct_path"].startswith(l["source_path"] + "/")), None)
        ok += derived == s["entry_path"]; bad += derived != s["entry_path"]
print("(e) sources[].entry_path 可推出：", ok, "推不出：", bad, "写成绝对路径：", absolute)

# (f) JSON 里的 view/format/version 与目录位置是否一致（不做格式目录登记表映射）
mismatch = []
for p in nav_jsons("原始路径.json"):
    parts = p.split("/"); j = load(p)
    exp = ("task", None, None) if parts[0] == "按任务" else ("format", parts[1], parts[2] if len(parts) == 5 else None)
    if (j["view"], j["format"], j["version"]) != exp:
        mismatch.append((p, (j["view"], j["format"], j["version"])))
print("(f) view/format/version 与目录名不同：", len(mismatch), "/ 70", [m[0] for m in mismatch])
