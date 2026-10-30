#!/usr/bin/env bash
# 第 10 张副本演练：真实导航层只读复制到 ~/.cache/rdp-drill/m1-10/nav，在副本上起 Web 和 worker，
# 走"改数据来源 → 写入 → 筛选 → 撤回"整条 API 流程；跑前跑后比对 /mnt/datasets 清单和两块盘写入扇区数。
set -uo pipefail
WT=/home/shawn/桌面/robot-data-platform.wt/m1-10-data-origin-labeling
AS=/home/shawn/桌面/robot-data-platform/.scratch/m1-datasets/assets/10-data-origin-labeling
FEED=/home/shawn/桌面/robot-data-platform/.scratch/m0-foundation/assets/11-ops-entry-systemd/feedpw.py
W=$HOME/.cache/rdp-drill/m1-10
REAL_HOME=$HOME; PY=$WT/.venv/bin/python
case "$W/" in /mnt/*) echo "拒绝"; exit 2;; esac
rm -rf "$W/nav" "$W/home"; mkdir -p "$W/nav" "$W/home/.config/rdp"
cd "$W"
(cd "$WT/src/web" && node_modules/.bin/vite build > /dev/null 2>&1) || { echo "前端构建失败"; exit 1; }
trap 'rm -rf "$WT/src/web/dist"' EXIT
find /mnt/datasets -printf '%p %T@ %s\n' 2>/dev/null | sort > "$W/find-before.txt"; awk '{print $7}' /sys/block/sda/stat /sys/block/sdb/stat > "$W/writes-before.txt"
for item in /mnt/datasets/*; do n=$(basename "$item"); case "$n" in 解压样本|工具|VGX_video) mkdir -p "$W/nav/$n";; *) cp -a --no-dereference -- "$item" "$W/nav/";; esac; done
export HOME=$W/home
B=http://127.0.0.1:8622
cat > "$HOME/.config/rdp/config.toml" <<CFG
nav_root = "$W/nav"
[web]
host = "127.0.0.1"
port = 8622
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
step "浏览器"; mkdir -p "$AS/drill"; "$REAL_HOME/.local/bin/node" "$AS/origin-browser-drill.mjs" "$B" "$AS/drill"; echo "[node exit $?]"
cat "$W/nav/按任务/libero_10/来源.json"; echo
step "4. 操作日志与变更记录"
sqlite3 "file:$HOME/.local/share/rdp/rdp.sqlite3?mode=ro" "select log_id, actor_name, operation, object_id, result from operation_logs where object_kind='navigation_write' order by log_id;"
ls "$HOME/.local/share/rdp/nav-changes/"
kill -TERM "$WEB" "$WORKER"; wait "$WEB"; echo "web exit=$?"; wait "$WORKER"; echo "worker exit=$?"
step "5. 只读核对"
find /mnt/datasets -printf '%p %T@ %s\n' 2>/dev/null | sort > "$W/find-after.txt"; cmp "$W/find-before.txt" "$W/find-after.txt" && echo "/mnt/datasets 清单逐字节相同"
awk '{print $7}' /sys/block/sda/stat /sys/block/sdb/stat | paste "$W/writes-before.txt" -
grep -c ERROR "$HOME/.local/share/rdp/logs/worker.log" | sed 's/^/worker.log ERROR /'
