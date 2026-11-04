#!/usr/bin/env bash
# M1.5 第 05 张副本演练：管理员改 libero_10 的数据来源，确认后留在数据集页，作业卡片显示运行中和成功，关闭卡片不取消作业；核对副本来源.json，前后比对 /mnt 清单与写入扇区。
# 核对登录页日志降噪、成员提交权限与诊断脱敏、请求体上限、数据库文件权限、antd 下拉框；前后比对 /mnt 清单与写入扇区。
set -uo pipefail
WT=/home/shawn/桌面/robot-data-platform.wt/m15-05-job-card
AS=/home/shawn/桌面/robot-data-platform/.scratch/m1.5-edit-view-classify/assets/05-job-card
FEED=/home/shawn/桌面/robot-data-platform/.scratch/m0-foundation/assets/11-ops-entry-systemd/feedpw.py
W=$HOME/.cache/rdp-drill/m15-05
REAL_HOME=$HOME; PY=$WT/.venv/bin/python
case "$W/" in /mnt/*) echo "拒绝"; exit 2;; esac
rm -rf "$W/nav" "$W/home"; mkdir -p "$W/nav" "$W/home/.config/rdp"
cd "$W"
(cd "$WT/src/web" && node_modules/.bin/vite build > /dev/null 2>&1) || { echo "前端构建失败"; exit 1; }
trap 'rm -rf "$WT/src/web/dist"' EXIT
find /mnt/datasets -printf '%p %T@ %s\n' 2>/dev/null | sort > "$W/find-before.txt"; awk '{print $7}' /sys/block/sda/stat /sys/block/sdb/stat > "$W/writes-before.txt"
for item in /mnt/datasets/*; do n=$(basename "$item"); case "$n" in 解压样本|工具|VGX_video) mkdir -p "$W/nav/$n";; *) cp -a --no-dereference -- "$item" "$W/nav/";; esac; done
export HOME=$W/home
B=http://127.0.0.1:8629
cat > "$HOME/.config/rdp/config.toml" <<CFG
nav_root = "$W/nav"
[web]
host = "127.0.0.1"
port = 8629
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
api() { local j=$1; shift; curl -s -m 30 -b "$W/$j" -c "$W/$j" -H "Origin: $B" -H 'Content-Type: application/json' "$@"; echo; }
D=$HOME/.local/share/rdp
"$PY" -m rdp migrate | tail -1
"$REAL_HOME/.local/share/uv/python/cpython-3.12.15-linux-x86_64-gnu/bin/python3" -I "$FEED" 'Admin-pass-2026!' "$PY" -m rdp create-admin admin 管理员 | tail -1
"$PY" -m rdp web > "$W/web.out" 2>&1 < /dev/null & WEB=$!
"$PY" -m rdp worker > "$W/worker.out" 2>&1 < /dev/null & WORKER=$!
for _ in $(seq 1 60); do curl -s -m 2 "$B/api/health" > /dev/null && break; sleep 1; done
for _ in $(seq 1 60); do api cja -d '{"login_name":"admin","password":"Admin-pass-2026!"}' "$B/api/auth/login" > /dev/null; n=$(api cja "$B/api/datasets?limit=1" -X GET | grep -o '"total":[0-9]*' | grep -o '[0-9]*'); [[ ${n:-0} -ge 35 ]] && break; sleep 2; done; echo "索引数据集 $n"
N="$W/nav/按任务/libero_10/来源.json"; grep -o '"data_origin": *"[^"]*"' "$N" | head -1 | sed 's/^/改前：/'
step "1. 浏览器：改数据来源"
"$REAL_HOME/.local/bin/node" "$AS/jobcard-browser-drill.mjs" "$B" "$AS/drill"; echo "[node exit $?]"
grep -o '"data_origin": *"[^"]*"' "$N" | head -1 | sed 's/^/改后（副本）：/'
sqlite3 "file:$D/rdp.sqlite3?mode=ro" "select job_id, type_name, state from jobs where type_name like 'nav_%' order by job_id"
kill -TERM "$WEB" "$WORKER"; wait "$WEB"; echo "web exit=$?"; wait "$WORKER"; echo "worker exit=$?"
echo "web.log ERROR 行数：$(grep -c ' ERROR ' "$D/logs/web.log")"
step "2. 只读核对"
find /mnt/datasets -printf '%p %T@ %s\n' 2>/dev/null | sort > "$W/find-after.txt"; cmp "$W/find-before.txt" "$W/find-after.txt" && echo "/mnt/datasets 清单逐字节相同"
awk '{print $7}' /sys/block/sda/stat /sys/block/sdb/stat | paste "$W/writes-before.txt" -
