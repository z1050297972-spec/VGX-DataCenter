"""原型数据导出（一次性）：为决策票「数据集浏览界面」的原型，从导航层只读导出数据。

用法：python3 -I export_data.py /mnt/datasets <输出目录>
      输出目录是原型工作目录里的 src/web/public/data/

只读约束：
- 导航层本身用 os.walk(..., followlinks=False) 遍历，不顺着链接走进数据盘。
- 数据盘上只对具体的路径做 lstat、readlink、du，另外按 11 号票的规则读 LeRobot 数据块的 <direct_path>/meta/info.json。
- 不往 /mnt 下写任何东西；只往输出目录写。

一致性面板的问题按 11 号票 Answer「第一次扫描的预期」手写（1 类需要处理、5 类提示）；
样例里的路径从 JSON 里按已知的删除目录挑出来，并对这几个具体路径做 lstat 核对。
"""

import json
import os
import re
import shutil
import stat
import subprocess
import sys
import time
from datetime import datetime

NAV_ROOT = sys.argv[1]
OUT_DIR = sys.argv[2]
JSON_NAMES = ("原始路径.json", "数据集信息.json", "子任务.json")

# 格式目录登记表（导航层手册第 1 节）：目录名 -> (format, 有没有版本层)
FORMAT_REGISTRY = {
    "lerobot": ("lerobot", True),
    "mcap": ("mcap", False),
    "tar、tar.gz（含分卷）": ("archives", False),
}
# 已登记的存储根（0010 第 4 节的挂载事实）
STORAGE_ROOTS = [
    {"path": "/mnt/dataset1", "device": "/dev/sda", "fstype": "ext4", "uuid": "2d3a48d6-3785-47fe-8c8f-a20857fdc41a", "access": "只读"},
    {"path": "/mnt/dataset2", "device": "/dev/sdb", "fstype": "ext4", "uuid": "35445b14-9e83-4f74-ac73-1551e3db6d63", "access": "只读"},
]
NON_DATASET_DIRS = ["索引", "文档", "工具", "解压样本"]
# 10-17 被删除、JSON 没有同步的 3 个目录（0005「修正 F5」）
DELETED_DIRS = [
    "/mnt/dataset2/agibot_world_alpha/lerobot_v2_output",
    "/mnt/dataset1/agibot_world_2026/extracted",
    "/mnt/dataset1/agibot_world_2026/scripts",
]
SAMPLE_LIMIT = 6


def now_iso():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def log(msg):
    print(f"[{now_iso()}] {msg}", flush=True)


def load_json(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def lexists(path):
    """只对具体路径做 lstat，不跟随。"""
    try:
        os.lstat(path)
        return True
    except OSError:
        return False


def under(path, root):
    return path == root or path.startswith(root.rstrip("/") + "/")


def storage_root_of(path):
    for r in STORAGE_ROOTS:
        if under(path, r["path"]):
            return r["path"]
    return None


def entry_key(view, fmt, version, name):
    if view == "task":
        key = f"task__{name}"
    elif version:
        key = f"format__{fmt}__{version}__{name}"
    else:
        key = f"format__{fmt}__{name}"
    assert re.fullmatch(r"[A-Za-z0-9_.\-]+", key), key
    return key


def find_entries():
    """遍历两个视图，返回 (相对路径, view, format, format_dir, version, 目录名)。followlinks=False。"""
    found = []
    versions_on_disk = {}
    for view_dir, view in (("按任务", "task"), ("按格式", "format")):
        base = os.path.join(NAV_ROOT, view_dir)
        for dirpath, dirnames, filenames in os.walk(base, followlinks=False):
            rel = os.path.relpath(dirpath, NAV_ROOT)
            parts = rel.split(os.sep)
            # 记下 按格式/<有版本层的格式目录>/ 下的版本目录（含空目录，例如 lerobot/2.0）
            if view == "format" and len(parts) == 2 and parts[1] in FORMAT_REGISTRY and FORMAT_REGISTRY[parts[1]][1]:
                versions_on_disk[parts[1]] = sorted(d for d in dirnames if not os.path.islink(os.path.join(dirpath, d)))
            if "原始路径.json" not in filenames:
                continue
            name = parts[-1]
            if view == "task":
                found.append((rel, "task", None, None, None, name))
            else:
                fmt_dir = parts[1]
                fmt, has_ver = FORMAT_REGISTRY[fmt_dir]
                version = parts[2] if has_ver else None
                found.append((rel, "format", fmt, fmt_dir, version, name))
            dirnames[:] = []  # 入口目录下只有链接和 JSON，不再往下走
    return sorted(found), versions_on_disk


DU_CACHE = {}


def du_bytes(target):
    """按链接目标统计表观字节数；同一个目标只算一次（两个视图常指向同一处）。"""
    if target in DU_CACHE:
        return DU_CACHE[target]
    t0 = time.monotonic()
    proc = subprocess.run(
        ["ionice", "-c3", "nice", "-n19", "timeout", "1800", "du", "-sb", target],
        capture_output=True, text=True,
    )
    dur = round(time.monotonic() - t0, 2)
    first = proc.stdout.strip().split("\t")[0] if proc.stdout.strip() else ""
    res = {
        "bytes": int(first) if first.isdigit() else None,
        "measured_at": now_iso(),
        "duration_s": dur,
        "error": None if proc.returncode == 0 else f"du 退出码 {proc.returncode}：{proc.stderr.strip()[-300:]}",
    }
    DU_CACHE[target] = res
    log(f"du {target}: {res['bytes']} B，{dur} s，rc={proc.returncode}")
    return res


def main():
    t_start = time.monotonic()
    scan_started = now_iso()
    os.makedirs(os.path.join(OUT_DIR, "entries"), exist_ok=True)

    # 1. 存储根：只读挂载表
    roots_out = []
    for r in STORAGE_ROOTS:
        proc = subprocess.run(["findmnt", "-J", "-o", "TARGET,SOURCE,FSTYPE,UUID", "--mountpoint", r["path"]],
                              capture_output=True, text=True)
        fs = json.loads(proc.stdout)["filesystems"][0] if proc.returncode == 0 and proc.stdout.strip() else None
        online = bool(fs) and fs.get("uuid") == r["uuid"]
        roots_out.append({
            "path": r["path"],
            "mount_source": f"UUID={r['uuid']}",
            "device": r["device"],
            "fstype": r["fstype"],
            "access": r["access"],
            "online": online,
            "mounted_source": fs.get("source") if fs else None,
            "checked_at": now_iso(),
        })
        log(f"存储根 {r['path']}: {'在线' if online else '离线'}（{fs}）")

    # 2. 两个视图的入口
    found, versions_on_disk = find_entries()
    log(f"入口 {len(found)} 个")
    entries = []
    canonical = {}
    for rel, view, fmt, fmt_dir, version, name in found:
        d = os.path.join(NAV_ROOT, rel)
        key = entry_key(view, fmt, version, name)
        docs = {n: load_json(os.path.join(d, n)) for n in JSON_NAMES}
        raw = docs["原始路径.json"]
        files = {}
        for n in JSON_NAMES:
            st = os.lstat(os.path.join(d, n))
            files[n] = {"bytes": st.st_size, "mtime": datetime.fromtimestamp(st.st_mtime).astimezone().isoformat(timespec="seconds")}
        json_links = {l["name"]: l for l in raw.get("links", [])}
        links = []
        with os.scandir(d) as it:
            disk = sorted((e for e in it if e.is_symlink()), key=lambda e: e.name)
        for e in disk:
            target = os.readlink(e.path)
            exists = lexists(target)
            jl = json_links.get(e.name)
            links.append({
                "name": e.name,
                "target": target,
                "target_exists": exists,
                "target_type": ("directory" if stat.S_ISDIR(os.lstat(target).st_mode) else "file") if exists else None,
                "storage_root": storage_root_of(target),
                "in_json": jl is not None,
                "json_source_path": jl.get("source_path") if jl else None,
                "checked_at": now_iso(),
            })
        disk_names = {l["name"] for l in links}
        json_only = [n for n in json_links if n not in disk_names]
        entry = {
            "key": key,
            "view": view,
            "format": fmt,
            "format_dir": fmt_dir,
            "version": version,
            "dataset_id": raw.get("dataset_id"),
            "dataset_name": raw.get("dataset_name"),
            "dir_name": name,
            "path": rel,
            "files": files,
            "links": links,
            "json_links_missing_on_disk": json_only,
            "source_count": len(raw.get("sources", [])),
            "dataset_roots": raw.get("dataset_roots", []),
        }
        entries.append((entry, docs))
        if view == "task":
            canonical[entry["dataset_id"]] = (entry, docs)
        # 三份 JSON 原样复制
        out = os.path.join(OUT_DIR, "entries", key)
        os.makedirs(out, exist_ok=True)
        for n in JSON_NAMES:
            shutil.copyfile(os.path.join(d, n), os.path.join(out, n))
    scan_finished = now_iso()
    log("导航层读完，开始读 meta/info.json")

    # 3. 数据集：记录大小、robot_type、fps
    datasets = []
    for ds_id, (entry, docs) in sorted(canonical.items(), key=lambda kv: kv[1][0]["dataset_name"].lower()):
        info = docs["数据集信息.json"]
        rec = None
        for f in info.get("fields", []):
            if f.get("number") == 4:
                m = re.search(r"（([\d,]+) B；", f.get("value_markdown", ""))
                rec = int(m.group(1).replace(",", "")) if m else None
        raw_types, fps, cbv = set(), set(), set()
        ler_total = ler_found = 0
        for s in docs["原始路径.json"].get("sources", []):
            if s.get("format") != "lerobot":
                continue
            ler_total += 1
            p = os.path.join(s["direct_path"], "meta", "info.json")
            try:
                ij = load_json(p)
            except (OSError, ValueError):
                continue
            ler_found += 1
            raw_types.add(ij.get("robot_type"))
            if isinstance(ij.get("fps"), (int, float)):
                fps.add(ij["fps"])
            if ij.get("codebase_version"):
                cbv.add(ij["codebase_version"])
        known = sorted(t for t in raw_types if t not in (None, "unknown"))
        datasets.append({
            "dataset_id": ds_id,
            "dataset_name": entry["dataset_name"],
            "title": info.get("title"),
            "canonical_entry": entry["key"],
            "entries": [e["key"] for e, _ in entries if e["dataset_id"] == ds_id],
            "recorded_size_bytes": rec,
            "recorded_size_date": info.get("snapshot_date"),
            "robot_types": known,
            "robot_types_raw": sorted("null" if t is None else t for t in raw_types),
            "fps": sorted(fps),
            "codebase_versions": sorted(cbv),
            "lerobot_sources": ler_total,
            "lerobot_info_found": ler_found,
        })
    n_known = sum(1 for d in datasets if d["robot_types"])
    log(f"数据集 {len(datasets)} 个：robot_type 有具体值 {n_known} 个，未知 {len(datasets) - n_known} 个")

    # 4. 大小：按链接目标 du（小的先算，alpha 的 observations 放最后）
    log("开始统计大小")
    targets = sorted({l["target"] for e, _ in entries for l in e["links"] if l["target_exists"]},
                     key=lambda t: ("agibot_world_alpha/observations" in t, t))
    for t in targets:
        du_bytes(t)
    for e, _ in entries:
        per = []
        for l in e["links"]:
            r = DU_CACHE.get(l["target"]) if l["target_exists"] else None
            per.append({"name": l["name"], "target": l["target"], **(r or {"bytes": None, "measured_at": None, "duration_s": None, "error": "目标不存在"})})
        ok = per and all(p["bytes"] is not None for p in per)
        e["size"] = {
            "bytes": sum(p["bytes"] for p in per) if ok else None,
            "measured_at": max(p["measured_at"] for p in per) if ok else None,
            "per_link": per,
        }

    # 5. 一致性面板：按「第一次扫描的预期」手写，样例从 JSON 里挑
    for p in DELETED_DIRS:
        if lexists(p):
            log(f"警告：{p} 现在存在，和 0005 的事实不符")
    name_of = {d["dataset_id"]: d["dataset_name"] for d in datasets}

    def ds_ref(ds_id):
        return {"dataset_id": ds_id, "dataset_name": name_of.get(ds_id)}

    def deleted_root(path):
        return next((r for r in DELETED_DIRS if under(path, r)), None)

    src_missing, excl_missing, summary_missing, sub_md_missing = [], [], [], []
    for e, docs in entries:
        raw = docs["原始路径.json"]
        for s in raw.get("sources", []):
            if deleted_root(s["direct_path"]) and not lexists(s["direct_path"]):
                src_missing.append((e, s))
        for x in raw.get("excluded_from_navigation", []):
            if not lexists(x):
                excl_missing.append((e, x))
        sp = docs["数据集信息.json"].get("summary_path")
        if sp and not lexists(sp):
            summary_missing.append((e, sp))
        for t in docs["子任务.json"].get("tasks", []):
            for s in t.get("sources", []):
                for field in ("root", "entry_path"):
                    v = s.get(field)
                    if isinstance(v, str) and deleted_root(v):
                        sub_md_missing.append((e, "子任务.json", f"tasks[{t['task_key']}].sources[].{field}", v))
                for ev in s.get("evidence", []):
                    v = ev.get("path")
                    if isinstance(v, str) and deleted_root(v):
                        sub_md_missing.append((e, "子任务.json", f"tasks[{t['task_key']}].sources[].evidence[].path", v))
        for f in docs["数据集信息.json"].get("fields", []):
            for m in re.finditer(r"\]\(<([^>]*)>\)", f.get("value_markdown", "")):
                if deleted_root(m.group(1)):
                    sub_md_missing.append((e, "数据集信息.json", f"第 {f['number']} 项「{f['name']}」的本地链接", m.group(1)))

    def uniq_ds(items):
        return [ds_ref(i) for i in sorted({it[0]["dataset_id"] for it in items}, key=lambda x: name_of.get(x, x))]

    alpha_root = "/mnt/dataset2/agibot_world_alpha"
    unlinked = [(".venv_lerobot_v2", "目录，338 MB"), (".venv_lerobot_v2_v21_v3", "目录，2.35 GB"),
                ("scripts", "目录，156 KB"), ("README.md", "文件，15 KB")]
    incomplete = [
        ("dataset-30", "/mnt/dataset1/agibot_world_2026/ReinforcementLearning/Industry/task_6767/1648454_1698836.tar.gz.aria2"),
        ("dataset-33", "/mnt/dataset2/EgoProDemo/.cache/huggingface/download/EgoProStandard-body/lerobot/Portion Nuts into Small Resealable Bags/35a5a6ce-4ccb-45c1-846c-3bc1b256e897/videos/observation.images.right_wrist/chunk-000/7wRApOINIM-BFSSFbGUIdqNun_Q=.acd3bd124f18a42fe3f99760860dd386488e28e5f9d7b95089ed1a1a92919694.bdd7e483.incomplete"),
        ("dataset-33", "/mnt/dataset2/EgoProDemo/.cache/huggingface/download/EgoProStandard-body/lerobot/Portion Nuts into Small Resealable Bags/bb0454f1-86af-4908-a739-e32a414c5488/videos/observation.images.left_wrist/chunk-000/7wRApOINIM-BFSSFbGUIdqNun_Q=.a3a97db376690f987b1bf4cb7a1ede548c1fda0f8057ebd264cfa017fd5c5932.01309a48.incomplete"),
        ("dataset-33", "/mnt/dataset2/EgoProDemo/.cache/huggingface/download/EgoProStandard-body/lerobot/Portion Nuts into Small Resealable Bags/bb0454f1-86af-4908-a739-e32a414c5488/videos/observation.images.head_left/chunk-000/7wRApOINIM-BFSSFbGUIdqNun_Q=.0bbff61af1902f66ef934a912c28459ea96c17f680050131d0a8959e33b615dd.74f04b4b.incomplete"),
    ]
    for _, p in incomplete:
        if not lexists(p):
            log(f"警告：未下载完的文件样例 {p} 不存在")
    for n, _ in unlinked:
        if not lexists(os.path.join(alpha_root, n)):
            log(f"警告：alpha 根目录下的 {n} 不存在")

    issues = [
        {
            "id": "source_direct_path_missing",
            "group": 3, "group_name": "JSON 和磁盘之间", "level": "action", "rule_no": 11,
            "title": "数据块的 direct_path 不存在",
            "rule": "原始路径.json 里每个数据块的 direct_path 必须存在",
            "found_by": "重新扫描",
            "datasets": uniq_ds(src_missing),
            "total": len(src_missing),
            "storage_roots": sorted({storage_root_of(s["direct_path"]) for _, s in src_missing}),
            "consequence": "这几个数据块读不到；依赖它们的浏览、转换会失败。同一数据集的其他数据块不受影响。",
            "next_step": "把数据恢复回来；或者先改规范副本，从 sources[] 里去掉这几个数据块，再同步按格式入口。",
            "samples": [{
                "entry": e["key"], "entry_path": e["path"],
                "object": f"数据块 {s['source_id']}（{s.get('format')} {s.get('version') or ''}，validation_status={s.get('validation_status')}）".replace(" ，", "，"),
                "actual": f"{s['direct_path']} 不存在",
                "expected": "路径存在",
                "path": s["direct_path"], "storage_root": storage_root_of(s["direct_path"]),
            } for e, s in src_missing[:SAMPLE_LIMIT]],
        },
        {
            "id": "summary_path_missing",
            "group": 3, "group_name": "JSON 和磁盘之间", "level": "info", "rule_no": 11,
            "title": "summary_path 指向的汇总文档不存在",
            "rule": "数据集信息.json 的 summary_path 应当指向存在的文件",
            "found_by": "重新扫描",
            "datasets": uniq_ds(summary_missing),
            "total": len(summary_missing),
            "storage_roots": [],
            "consequence": "只影响追溯 14 项的出处，数据本身可以正常使用。",
            "next_step": "了解即可；需要时找回汇总文档，或者更新 summary_path。",
            "samples": [{
                "entry": e["key"], "entry_path": e["path"],
                "object": f"{e['path']}/数据集信息.json 的 summary_path",
                "actual": f"{sp} 不存在", "expected": "文件存在",
                "path": sp, "storage_root": None,
            } for e, sp in summary_missing[:SAMPLE_LIMIT]],
        },
        {
            "id": "excluded_dir_missing",
            "group": 3, "group_name": "JSON 和磁盘之间", "level": "info", "rule_no": 11,
            "title": "登记的排除目录已不存在",
            "rule": "excluded_from_navigation 里登记的目录应当存在",
            "found_by": "重新扫描",
            "datasets": uniq_ds(excl_missing),
            "total": len(excl_missing),
            "storage_roots": sorted({storage_root_of(x) for _, x in excl_missing}),
            "consequence": "排除记录已经过期；不影响链接和数据块。",
            "next_step": "了解即可；需要时从 excluded_from_navigation 里去掉这些目录（先改规范副本）。",
            "samples": [{
                "entry": e["key"], "entry_path": e["path"],
                "object": f"{e['path']}/原始路径.json 的 excluded_from_navigation",
                "actual": f"{x} 不存在", "expected": "目录存在",
                "path": x, "storage_root": storage_root_of(x),
            } for e, x in excl_missing[:SAMPLE_LIMIT]],
        },
        {
            "id": "subtask_markdown_ref_missing",
            "group": 3, "group_name": "JSON 和磁盘之间", "level": "info", "rule_no": 11,
            "title": "子任务和 14 项正文里引用的路径已不存在",
            "rule": "子任务.json 里的路径、14 项 Markdown 里的本地链接应当存在",
            "found_by": "重新扫描",
            "datasets": uniq_ds(sub_md_missing),
            "total": len(sub_md_missing),
            "storage_roots": sorted({storage_root_of(it[3]) for it in sub_md_missing}),
            "consequence": "这些说明和子任务引用了已删除的数据，按它们去找会找不到；其余内容可以正常使用。",
            "next_step": "了解即可；需要时更新子任务.json 或 14 项正文（先改规范副本）。",
            "samples": [{
                "entry": e["key"], "entry_path": e["path"],
                "object": f"{e['path']}/{fname} 的 {where}",
                "actual": f"{v} 不存在", "expected": "路径存在",
                "path": v, "storage_root": storage_root_of(v),
            } for e, fname, where, v in sorted(sub_md_missing, key=lambda it: (it[1] != "数据集信息.json", it[0]["path"]))[:SAMPLE_LIMIT]],
        },
        {
            "id": "incomplete_download",
            "group": 4, "group_name": "存储状况", "level": "info", "rule_no": 15,
            "title": "有没下载完的文件",
            "rule": "存储根上不应留有 .aria2、.incomplete 这类未下载完的文件",
            "found_by": "统计大小",
            "datasets": [ds_ref("dataset-30"), ds_ref("dataset-33")],
            "total": 9,
            "storage_roots": ["/mnt/dataset1", "/mnt/dataset2"],
            "consequence": "对应的归档或视频可能不完整：agibot_world_2026 有 1 个 .aria2（旁边的归档 53.5 GB），EgoProDemo 有 8 个 .incomplete（在 .cache/huggingface/download/ 下）。",
            "next_step": "确认下载是否完成，必要时重新下载或清理。",
            "samples": [{
                "entry": f"task__{name_of[ds]}", "entry_path": f"按任务/{name_of[ds]}",
                "object": f"{name_of[ds]} 的文件",
                "actual": f"{p} 是未下载完的文件", "expected": "没有未下载完的文件",
                "path": p, "storage_root": storage_root_of(p),
            } for ds, p in incomplete],
        },
        {
            "id": "root_unlinked_content",
            "group": 3, "group_name": "JSON 和磁盘之间", "level": "info", "rule_no": 13,
            "title": "根目录下有没被链接的内容",
            "rule": "按子目录链接的数据集，根目录下的内容要么被链接，要么登记为排除",
            "found_by": "重新扫描",
            "datasets": [ds_ref("dataset-31")],
            "total": len(unlinked),
            "storage_roots": ["/mnt/dataset2"],
            "consequence": "这些内容在导航层里看不到，也查不到被排除的记录；不计入统计大小。",
            "next_step": "了解即可；需要时建链接，或者登记到 excluded_from_navigation。",
            "samples": [{
                "entry": "task__agibot_world_alpha", "entry_path": "按任务/agibot_world_alpha",
                "object": f"{alpha_root}/{n}（{desc}）",
                "actual": "既没被链接，也没登记为排除", "expected": "被链接，或者登记为排除",
                "path": f"{alpha_root}/{n}", "storage_root": "/mnt/dataset2",
            } for n, desc in unlinked],
        },
    ]

    index = {
        "generated_at": now_iso(),
        "generated_by": "export_data.py（原型数据：从 /mnt/datasets 只读导出；一致性面板按 11 号票「第一次扫描的预期」手写）",
        "nav_root": NAV_ROOT,
        "scan": {"started_at": scan_started, "finished_at": scan_finished},
        "sizing": {"finished_at": now_iso(), "command": "ionice -c3 nice -n19 timeout 1800 du -sb <链接目标>"},
        "storage_roots": roots_out,
        "format_registry": [
            {"dir": d, "format": f, "has_version": hv, "versions_on_disk": versions_on_disk.get(d, []) if hv else []}
            for d, (f, hv) in FORMAT_REGISTRY.items()
        ],
        "non_dataset_dirs": NON_DATASET_DIRS,
        "validation_status_labels": {
            "path_exists_only": "只核对了路径存在",
            "archive_not_opened": "归档没有打开核对",
            "metadata_and_references_pass": "元数据和引用都核对通过",
            "attention_required": "需要关注",
            "download_state_only": "只有下载控制文件",
        },
        "datasets": datasets,
        "entries": [e for e, _ in entries],
        "issues": issues,
    }
    with open(os.path.join(OUT_DIR, "index.json"), "w", encoding="utf-8") as fh:
        json.dump(index, fh, ensure_ascii=False, indent=1)
    for it in issues:
        log(f"问题 {it['id']}：级别 {it['level']}，{len(it['datasets'])} 个数据集，共 {it['total']} 处")
    log(f"完成，用时 {time.monotonic() - t_start:.1f} s")


if __name__ == "__main__":
    main()
