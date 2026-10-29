#!/usr/bin/env bash
# 第 03 张验收 1：用第 01 张对真实导航层只读建的索引起 Web；存储根路径改成不存在的目录；curl 取树、列表、筛选、详情、最大的子任务.json。
set -uo pipefail
WT=/home/shawn/桌面/robot-data-platform.wt/m1-03-dataset-api
AS=/home/shawn/桌面/robot-data-platform/.scratch/m1-datasets/assets/03-dataset-api
FEED=/home/shawn/桌面/robot-data-platform/.scratch/m0-foundation/assets/11-ops-entry-systemd/feedpw.py
D=$HOME/.cache/rdp-dispatch/m1-03/apidrill
REAL_HOME=$HOME
rm -rf "$D"; mkdir -p "$D/home/.config/rdp" "$D/nostorage"
export HOME=$D/home
PY=$WT/.venv/bin/python
B=http://127.0.0.1:8617
cat > "$HOME/.config/rdp/config.toml" <<CFG
nav_root = "/mnt/datasets"
[web]
host = "127.0.0.1"
port = 8617
[jobs]
gpus = []
[[storage_roots]]
name = "dataset1"
path = "$D/nostorage/dataset1"
uuid = "2d3a48d6-3785-47fe-8c8f-a20857fdc41a"
[[storage_roots]]
name = "dataset2"
path = "$D/nostorage/dataset2"
uuid = "35445b14-9e83-4f74-ac73-1551e3db6d63"
CFG
step() { printf '\n===== %s =====\n' "$1"; }
api() { curl -s -m 60 -b "$D/cj" -c "$D/cj" -H "Origin: $B" -H 'Content-Type: application/json' "$@"; }
find /mnt/datasets -printf '%p %T@ %s\n' 2>/dev/null | sort > "$D/find-before.txt"
"$PY" -m rdp migrate > /dev/null
"$REAL_HOME/.local/share/uv/python/cpython-3.12.15-linux-x86_64-gnu/bin/python3" -I "$FEED" 'Admin-pass-2026!' "$PY" -m rdp create-admin admin 管理员 | tail -1
"$PY" -m rdp web > "$D/web.out" 2>&1 < /dev/null & WEB=$!
"$PY" -m rdp worker > "$D/worker.out" 2>&1 < /dev/null & WORKER=$!
for _ in $(seq 1 60); do curl -s -m 2 "$B/api/health" > /dev/null && break; sleep 1; done
api -d '{"login_name":"admin","password":"Admin-pass-2026!"}' "$B/api/auth/login" > /dev/null
step "1. 等 worker 启动时的扫描建好索引"
for _ in $(seq 1 60); do n=$(api "$B/api/datasets?limit=1" | python3 -c "import json,sys; print(json.load(sys.stdin).get('total',0))" 2>/dev/null); [[ ${n:-0} -ge 35 ]] && break; sleep 2; done; echo "total=$n"
timed() { local name=$1; shift; curl -s -m 60 -b "$D/cj" -H "Origin: $B" -o "$D/$name" -w "$name http=%{http_code} 字节=%{size_download} 耗时=%{time_total}s\n" "$@"; }
step "2. 各接口"
timed trees.json "$B/api/datasets/trees"
timed list.json "$B/api/datasets?limit=100"
timed filters.json "$B/api/datasets/filters"
timed panel.json "$B/api/datasets/panel"
E=$(python3 -c "import urllib.parse; print(urllib.parse.quote('按任务/agibot_world_2026'))")
timed detail.json "$B/api/datasets/detail?entry_path=$E"
for i in 1 2 3; do timed subtasks-$i.txt -D "$D/subtasks-headers.txt" "$B/api/datasets/subtasks?entry_path=$E"; done
grep -iE "content-type|content-length|x-index-stale|x-document-sha256" "$D/subtasks-headers.txt"
sha256sum "/mnt/datasets/按任务/agibot_world_2026/子任务.json" "$D/subtasks-1.txt" | awk '{print $1}' | uniq | wc -l | sed 's/^1$/子任务.json 逐字节相同/'
step "3. 摘要"
python3 - "$D" <<'PY'
import json,sys,pathlib
d=pathlib.Path(sys.argv[1])
t=json.loads((d/"trees.json").read_text()); print("trees keys:", list(t)[:5])
l=json.loads((d/"list.json").read_text()); print("list total:", l.get("total"), "items:", len(l.get("items",[])))
f=json.loads((d/"filters.json").read_text()); print("filters:", {k:(v if not isinstance(v,list) else len(v)) for k,v in f.items()})
x=json.loads((d/"detail.json").read_text()); print("detail keys:", sorted(x)[:12], "index_stale:", x.get("index_stale"))
PY
kill -TERM "$WEB" "$WORKER"; wait "$WEB"; echo "web exit=$?"; wait "$WORKER"; echo "worker exit=$?"
find /mnt/datasets -printf '%p %T@ %s\n' 2>/dev/null | sort > "$D/find-after.txt"; cmp "$D/find-before.txt" "$D/find-after.txt" && echo "清单逐字节相同：没有写 /mnt/datasets"
ls "$D/nostorage"
