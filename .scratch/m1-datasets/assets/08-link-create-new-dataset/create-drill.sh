#!/usr/bin/env bash
# 第 08 张副本演练（建链、新增数据集、撤回）：真实导航层只读复制到 ~/.cache/rdp-drill/m1-08/nav，在副本上起 Web 和 worker，
# 走建链和新增数据集的 预览 → 写入 → 撤回 整条 API 流程；跑前跑后比对 /mnt/datasets 清单和两块盘写入扇区数。
set -uo pipefail
WT=/home/shawn/桌面/robot-data-platform.wt/m1-08-link-create-new-dataset
FEED=/home/shawn/桌面/robot-data-platform/.scratch/m0-foundation/assets/11-ops-entry-systemd/feedpw.py
W=$HOME/.cache/rdp-drill/m1-08
REAL_HOME=$HOME; PY=$WT/.venv/bin/python
case "$W/" in /mnt/*) echo "拒绝"; exit 2;; esac
rm -rf "$W/nav" "$W/home"; mkdir -p "$W/nav" "$W/home/.config/rdp"
cd "$W"
(cd "$WT/src/web" && node_modules/.bin/vite build > /dev/null 2>&1) || { echo "前端构建失败"; exit 1; }
trap 'rm -rf "$WT/src/web/dist"' EXIT
find /mnt/datasets -printf '%p %T@ %s\n' 2>/dev/null | sort > "$W/find-before.txt"; awk '{print $7}' /sys/block/sda/stat /sys/block/sdb/stat > "$W/writes-before.txt"
for item in /mnt/datasets/*; do n=$(basename "$item"); case "$n" in 解压样本|工具|VGX_video) mkdir -p "$W/nav/$n";; *) cp -a --no-dereference -- "$item" "$W/nav/";; esac; done
export HOME=$W/home
B=http://127.0.0.1:8623
cat > "$HOME/.config/rdp/config.toml" <<CFG
nav_root = "$W/nav"
[web]
host = "127.0.0.1"
port = 8623
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
step "0. 前"; ls -la "$N/按任务/libero_10/"; ls "$N/按任务" | tail -3
step "A1. 建链预览：libero_10 → /mnt/dataset1/libero_v3/libero_goal"
P=$(api -d '{"dataset_id":"dataset-14","link":{"name":"演练链接","target_path":"/mnt/dataset1/libero_v3/libero_goal","fallback_format":null},"format_entries":[{"format":"lerobot","version":"3.0"}]}' "$B/api/datasets/link-previews" | jid); echo; echo "预览作业 $P"; waitjob "$P"
api "$B/api/datasets/creation-previews/$P" | head -c 2500; echo
step "A2. 确认写入"; R=$(api -d "{\"preview_job_id\":\"$P\",\"acknowledged_queue_job_ids\":[]}" "$B/api/datasets/creation-writes"); echo "$R" | head -c 600; echo; A=$(echo "$R" | jid); waitjob "$A"
ls -la "$N/按任务/libero_10/"; readlink "$N/按任务/libero_10/演练链接"; ls -la "$N/按格式/lerobot/3.0/libero_10/" | grep 演练
python3 -c "import json,sys; d=json.load(open(sys.argv[1])); print('links', [l.get('name') for l in d.get('links',[])]); print('sources', len(d.get('sources',[]))); print('dataset_roots', d.get('dataset_roots'))" "$N/按任务/libero_10/原始路径.json"
step "B1. 新增数据集预览：M1_08_演练 → /mnt/dataset1/lerobot（空目录，mcap）"
P2=$(api -d '{"dataset_name":"M1_08_演练","data_origin":"开源下载","link":{"name":"原始数据","target_path":"/mnt/dataset1/lerobot","fallback_format":"mcap"},"format_entries":[{"format":"mcap","version":null}]}' "$B/api/datasets/creation-previews" | jid); echo; echo "预览作业 $P2"; waitjob "$P2"
api "$B/api/datasets/creation-previews/$P2" | head -c 2500; echo
step "B2. 确认写入"; R2=$(api -d "{\"preview_job_id\":\"$P2\",\"acknowledged_queue_job_ids\":[]}" "$B/api/datasets/creation-writes"); echo "$R2" | head -c 600; echo; A2=$(echo "$R2" | jid); waitjob "$A2"
ls -la "$N/按任务/M1_08_演练/" "$N/按格式/mcap/M1_08_演练/" 2>&1
cat "$N/按任务/M1_08_演练/数据集信息.json" 2>/dev/null | head -c 600; echo; cat "$N/按任务/M1_08_演练/来源.json" 2>/dev/null; echo
sleep 4; api "$B/api/datasets?limit=1" | grep -o '"total":[0-9]*'
step "C. 撤回两次写入"
for T in $A2 $A; do RP=$(api -d "{\"type_name\":\"nav_revert_preview\",\"parameters\":{\"target_job_id\":$T}}" "$B/api/jobs" | jid); waitjob "$RP"; RA=$(api -d "{\"type_name\":\"nav_write_apply\",\"parameters\":{\"preview_job_id\":$RP}}" "$B/api/jobs" | jid); waitjob "$RA"; done
ls "$N/按任务/M1_08_演练" 2>&1 | head -2; ls "$N/按任务/libero_10/"; sleep 4; api "$B/api/datasets?limit=1" | grep -o '"total":[0-9]*'
step "4. 操作日志与变更记录"
sqlite3 "file:$HOME/.local/share/rdp/rdp.sqlite3?mode=ro" "select log_id, actor_name, operation, object_id, result from operation_logs where object_kind='navigation_write' order by log_id;"
ls "$HOME/.local/share/rdp/nav-changes/"
kill -TERM "$WEB" "$WORKER"; wait "$WEB"; echo "web exit=$?"; wait "$WORKER"; echo "worker exit=$?"
step "5. 只读核对"
find /mnt/datasets -printf '%p %T@ %s\n' 2>/dev/null | sort > "$W/find-after.txt"; cmp "$W/find-before.txt" "$W/find-after.txt" && echo "/mnt/datasets 清单逐字节相同"
awk '{print $7}' /sys/block/sda/stat /sys/block/sdb/stat | paste "$W/writes-before.txt" -
grep -c ERROR "$HOME/.local/share/rdp/logs/worker.log" | sed 's/^/worker.log ERROR /'
