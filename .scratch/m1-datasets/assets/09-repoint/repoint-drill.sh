#!/usr/bin/env bash
# 第 09 张副本演练（改指向、撤回）：真实导航层只读复制到 ~/.cache/rdp-drill/m1-09/nav，在副本上起 Web 和 worker，
# 走建链和新增数据集的 预览 → 写入 → 撤回 整条 API 流程；跑前跑后比对 /mnt/datasets 清单和两块盘写入扇区数。
set -uo pipefail
WT=/home/shawn/桌面/robot-data-platform.wt/m1-09-repoint
FEED=/home/shawn/桌面/robot-data-platform/.scratch/m0-foundation/assets/11-ops-entry-systemd/feedpw.py
W=$HOME/.cache/rdp-drill/m1-09
REAL_HOME=$HOME; PY=$WT/.venv/bin/python
case "$W/" in /mnt/*) echo "拒绝"; exit 2;; esac
rm -rf "$W/nav" "$W/home"; mkdir -p "$W/nav" "$W/home/.config/rdp"
cd "$W"
(cd "$WT/src/web" && node_modules/.bin/vite build > /dev/null 2>&1) || { echo "前端构建失败"; exit 1; }
trap 'rm -rf "$WT/src/web/dist"' EXIT
find /mnt/datasets -printf '%p %T@ %s\n' 2>/dev/null | sort > "$W/find-before.txt"; awk '{print $7}' /sys/block/sda/stat /sys/block/sdb/stat > "$W/writes-before.txt"
for item in /mnt/datasets/*; do n=$(basename "$item"); case "$n" in 解压样本|工具|VGX_video) mkdir -p "$W/nav/$n";; *) cp -a --no-dereference -- "$item" "$W/nav/";; esac; done
export HOME=$W/home
B=http://127.0.0.1:8624
cat > "$HOME/.config/rdp/config.toml" <<CFG
nav_root = "$W/nav"
[web]
host = "127.0.0.1"
port = 8624
[jobs]
gpus = []
[[storage_roots]]
name = "dataset1"
path = "/mnt/dataset1"
uuid = "2d3a48d6-3785-47fe-8c8f-a20857fdc41a"
[[storage_roots]]
name = "dataset2"
path = "/mnt/dataset2"
uuid = "35445b14-9e83-4f74-ac73-1551e3db6d63"
CFG
step() { printf '\n===== %s =====\n' "$1"; }
api() { curl -s -m 30 -b "$W/cj" -c "$W/cj" -H "Origin: $B" -H 'Content-Type: application/json' "$@"; echo; }
waitjob() { for _ in $(seq 1 90); do s=$(api "$B/api/jobs/$1" | grep -o '"state":"[a-z_]*"' | head -1); [[ $s == *completed* || $s == *failed* || $s == *cancelled* || $s == *interrupted* ]] && { echo "作业 $1 $s"; return; }; sleep 1; done; echo "作业 $1 超时"; }
jid() { grep -o '"job_id":"[0-9]*"' | head -1 | grep -o '[0-9]\+'; }
"$PY" -m rdp migrate | tail -1
"$REAL_HOME/.local/share/uv/python/cpython-3.12.15-linux-x86_64-gnu/bin/python3" -I "$FEED" 'Admin-pass-2026!' "$PY" -m rdp create-admin admin 管理员 | tail -1
"$PY" -m rdp web > "$W/web.out" 2>&1 < /dev/null & WEB=$!
"$PY" -m rdp worker > "$W/worker.out" 2>&1 < /dev/null & WORKER=$!
for _ in $(seq 1 60); do curl -s -m 2 "$B/api/health" > /dev/null && break; sleep 1; done
api -d '{"login_name":"admin","password":"Admin-pass-2026!"}' "$B/api/auth/login" > /dev/null
for _ in $(seq 1 60); do n=$(api "$B/api/datasets?limit=1" | grep -o '"total":[0-9]*' | grep -o '[0-9]*'); [[ ${n:-0} -ge 35 ]] && break; sleep 2; done; echo "索引数据集 $n"
N="$W/nav"
pv() { api "$B/api/navigation/previews/$1" | head -c ${2:-1500}; echo; }
step "N. 反例：EgoProStandard 从 dataset1 改到 dataset2（新位置缺路径，应在 worker 里被 L19 拒绝）"
EID=$(api "$B/api/datasets?limit=100" | python3 -c "import json,sys; print([i['dataset_id'] for i in json.load(sys.stdin)['items'] if i['name']=='EgoProStandard'][0])"); echo "EgoProStandard=$EID"
P=$(api -d "{\"dataset_id\":\"$EID\",\"old_prefix\":\"/mnt/dataset1/EgoProStandard\",\"new_prefix\":\"/mnt/dataset2/EgoProStandard\"}" "$B/api/datasets/repoint-previews" | jid); echo "预览作业 $P"; waitjob "$P"
api "$B/api/jobs/$P" | grep -o '"outcome":"[a-z_]*"\|"rule":"[A-Z_0-9]*"\|"actual":"[^"]\{0,160\}' | head -6
step "P1. 正例：libero_10 改指向 libero_goal（结构相同的 LeRobot 3.0 目录）"
P=$(api -d '{"dataset_id":"dataset-14","old_prefix":"/mnt/dataset1/libero_v3/libero_10","new_prefix":"/mnt/dataset1/libero_v3/libero_goal"}' "$B/api/datasets/repoint-previews" | jid); echo "预览作业 $P"; waitjob "$P"
api "$B/api/jobs/$P" | grep -o '"outcome":"[a-z_]*"\|"rule":"[A-Z_0-9]*"\|"actual":"[^"]\{0,200\}' | head -6
pv "$P" 2500
step "P2. 确认写入"; R=$(api -d "{\"preview_job_id\":\"$P\"}" "$B/api/navigation/writes"); echo "$R" | head -c 300; echo; A=$(echo "$R" | jid); [ -n "$A" ] && waitjob "$A"
readlink "$N/按任务/libero_10/原始数据"; readlink "$N/按格式/lerobot/3.0/libero_10/原始数据"; grep -c "libero_goal" "$N/按任务/libero_10/原始路径.json" | sed 's/^/原始路径.json 中 libero_goal 出现次数：/'; grep -c '"original_path": "/mnt/dataset1/libero_v3/libero_10' "$N/按任务/libero_10/原始路径.json" | sed 's/^/original_path 仍为旧值的条数：/'
step "P3. 撤回"; if [ -n "$A" ]; then RR=$(api -X POST "$B/api/jobs/$A/revert-previews" | jid); echo "撤回预览 $RR"; waitjob "$RR"; R2=$(api -d "{\"preview_job_id\":\"$RR\"}" "$B/api/navigation/writes"); RA=$(echo "$R2" | jid); waitjob "$RA"; fi
readlink "$N/按任务/libero_10/原始数据"; grep -c "libero_goal" "$N/按任务/libero_10/原始路径.json" | sed 's/^/撤回后 libero_goal 出现次数：/'
diff <(cd /mnt/datasets/按任务/libero_10 && sha256sum 原始路径.json 数据集信息.json 子任务.json) <(cd "$N/按任务/libero_10" && sha256sum 原始路径.json 数据集信息.json 子任务.json) && echo "撤回后三份 JSON 和真实导航层逐字节相同"
step "4. 操作日志与变更记录"
sqlite3 "file:$HOME/.local/share/rdp/rdp.sqlite3?mode=ro" "select log_id, actor_name, operation, object_id, result from operation_logs where object_kind='navigation_write' order by log_id;"
ls "$HOME/.local/share/rdp/nav-changes/"
kill -TERM "$WEB" "$WORKER"; wait "$WEB"; echo "web exit=$?"; wait "$WORKER"; echo "worker exit=$?"
step "5. 只读核对"
find /mnt/datasets -printf '%p %T@ %s\n' 2>/dev/null | sort > "$W/find-after.txt"; cmp "$W/find-before.txt" "$W/find-after.txt" && echo "/mnt/datasets 清单逐字节相同"
awk '{print $7}' /sys/block/sda/stat /sys/block/sdb/stat | paste "$W/writes-before.txt" -
grep -c ERROR "$HOME/.local/share/rdp/logs/worker.log" | sed 's/^/worker.log ERROR /'
