#!/usr/bin/env bash
# 第 04 张验收 1：临时状态目录、真实导航层和两块数据盘（只读），起 Web 和 worker，用无头浏览器走一遍布局 A。
set -uo pipefail
WT=/home/shawn/桌面/robot-data-platform.wt/m1-04-browser-widgets-layout-a
AS=/home/shawn/桌面/robot-data-platform/.scratch/m1-datasets/assets/04-browser-widgets-layout-a
FEED=/home/shawn/桌面/robot-data-platform/.scratch/m0-foundation/assets/11-ops-entry-systemd/feedpw.py
D=$HOME/.cache/rdp-dispatch/m1-04/drill
REAL_HOME=$HOME; NODE=$REAL_HOME/.local/bin/node
rm -rf "$D"; mkdir -p "$D/home/.config/rdp" "$AS/drill"
export HOME=$D/home
PY=$WT/.venv/bin/python
B=http://127.0.0.1:8619
cat > "$HOME/.config/rdp/config.toml" <<CFG
nav_root = "/mnt/datasets"
[web]
host = "127.0.0.1"
port = 8619
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
find /mnt/datasets -printf '%p %T@ %s\n' 2>/dev/null | sort > "$D/find-before.txt"
awk '{print $7}' /sys/block/sda/stat /sys/block/sdb/stat > "$D/writes-before.txt"
"$PY" -m rdp migrate | tail -1
"$REAL_HOME/.local/share/uv/python/cpython-3.12.15-linux-x86_64-gnu/bin/python3" -I "$FEED" 'Admin-pass-2026!' "$PY" -m rdp create-admin admin 管理员 | tail -1
"$PY" -m rdp web > "$D/web.out" 2>&1 < /dev/null & WEB=$!
"$PY" -m rdp worker > "$D/worker.out" 2>&1 < /dev/null & WORKER=$!
DB=$HOME/.local/share/rdp/rdp.sqlite3
for _ in $(seq 1 120); do n=$(sqlite3 "file:$DB?mode=ro" "select count(*) from dataset_scans where storage_stage='completed'" 2>/dev/null); [[ ${n:-0} -ge 1 ]] && break; sleep 1; done; echo "两段扫描完成 $n 次"
"$NODE" "$AS/browser-drill.mjs" "$B" "$AS/drill"; echo "[node exit $?]"
kill -TERM "$WEB" "$WORKER"; wait "$WEB"; echo "web exit=$?"; wait "$WORKER"; echo "worker exit=$?"
find /mnt/datasets -printf '%p %T@ %s\n' 2>/dev/null | sort > "$D/find-after.txt"; cmp "$D/find-before.txt" "$D/find-after.txt" && echo "/mnt/datasets 清单逐字节相同"
awk '{print $7}' /sys/block/sda/stat /sys/block/sdb/stat > "$D/writes-after.txt"; cmp -s "$D/writes-before.txt" "$D/writes-after.txt" && echo "两块数据盘没有写入" || paste "$D/writes-before.txt" "$D/writes-after.txt"
grep -cE "ERROR" "$HOME/.local/share/rdp/logs/web.log" | sed 's/^/web.log ERROR 行数：/'
