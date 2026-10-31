#!/usr/bin/env bash
# M1.5 第 01 张演练：只读查看器直接对真实导航层和数据盘（只读），临时状态目录；curl 测接口和 Range，浏览器测预览和视频。
set -uo pipefail
WT=/home/shawn/桌面/robot-data-platform.wt/m15-01-file-viewer
AS=/home/shawn/桌面/robot-data-platform/.scratch/m1.5-edit-view-classify/assets/01-file-viewer
FEED=/home/shawn/桌面/robot-data-platform/.scratch/m0-foundation/assets/11-ops-entry-systemd/feedpw.py
W=$HOME/.cache/rdp-drill/m15-01; REAL_HOME=$HOME; PY=$WT/.venv/bin/python
rm -rf "$W"; mkdir -p "$W/home/.config/rdp" "$AS/drill"; cd "$W"
(cd "$WT/src/web" && node_modules/.bin/vite build > /dev/null 2>&1) || { echo "前端构建失败"; exit 1; }
trap 'rm -rf "$WT/src/web/dist"' EXIT
# 执行线自己的读取（会更新 atime）放在基线之前，基线之后只有平台在读数据盘。
V=$(cd /mnt/dataset1/libero_v3/libero_10 && find videos -name '*.mp4' | sort | head -1); S=$(stat -c %s "/mnt/dataset1/libero_v3/libero_10/$V"); head -c 1024 "/mnt/dataset1/libero_v3/libero_10/$V" > "$W/expect-head.bin"; cp /mnt/dataset1/libero_v3/libero_10/meta/info.json "$W/expect-info.json"
find /mnt/datasets -printf '%p %T@ %s\n' 2>/dev/null | sort > "$W/find-before.txt"; awk '{print $7}' /sys/block/sda/stat /sys/block/sdb/stat > "$W/writes-before.txt"
export HOME=$W/home; B=http://127.0.0.1:8625
cat > "$HOME/.config/rdp/config.toml" <<CFG
nav_root = "/mnt/datasets"
[web]
host = "127.0.0.1"
port = 8625
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
api() { curl -s -m 30 -b "$W/cj" -c "$W/cj" -H "Origin: $B" "$@"; }
"$PY" -m rdp migrate | tail -1
"$REAL_HOME/.local/share/uv/python/cpython-3.12.15-linux-x86_64-gnu/bin/python3" -I "$FEED" 'Admin-pass-2026!' "$PY" -m rdp create-admin admin 管理员 | tail -1
"$PY" -m rdp web > "$W/web.out" 2>&1 < /dev/null & WEB=$!
"$PY" -m rdp worker > "$W/worker.out" 2>&1 < /dev/null & WORKER=$!
for _ in $(seq 1 60); do curl -s -m 2 "$B/api/health" > /dev/null && break; sleep 1; done
api -H 'Content-Type: application/json' -d '{"login_name":"admin","password":"Admin-pass-2026!"}' "$B/api/auth/login" > /dev/null
for _ in $(seq 1 60); do n=$(api "$B/api/datasets?limit=1" | grep -o '"total":[0-9]*' | grep -o '[0-9]*'); [[ ${n:-0} -ge 35 ]] && break; sleep 2; done; echo "索引数据集 $n"
step "1. 列目录 meta"; api -G "$B/api/datasets/dataset-14/files" --data-urlencode "link_name=原始数据" --data-urlencode "path=meta" | head -c 600; echo
step "2. 读 meta/info.json"; api -G "$B/api/datasets/dataset-14/file" --data-urlencode "link_name=原始数据" --data-urlencode "path=meta/info.json" -o "$W/info.json" -w "http=%{http_code} 字节=%{size_download}\n"; cmp "$W/info.json" "$W/expect-info.json" && echo "和原文件逐字节相同"
step "3. 越界：path=../libero_goal/meta/info.json 与绝对路径"; for p in "../libero_goal/meta/info.json" "/etc/passwd" "meta/../../libero_goal"; do api -G "$B/api/datasets/dataset-14/file" --data-urlencode "link_name=原始数据" --data-urlencode "path=$p" -o /dev/null -w "$p → http=%{http_code}\n"; done
step "4. 视频 Range"; echo "视频 $V 大小 $S"
api -G "$B/api/datasets/dataset-14/file" --data-urlencode "link_name=原始数据" --data-urlencode "path=$V" -H "Range: bytes=0-1023" -D "$W/h1.txt" -o "$W/r1.bin" -w "http=%{http_code} 字节=%{size_download}\n"; grep -i "content-range\|content-type\|accept-ranges" "$W/h1.txt"
api -G "$B/api/datasets/dataset-14/file" --data-urlencode "link_name=原始数据" --data-urlencode "path=$V" -H "Range: bytes=$((S-100))-" -o "$W/r2.bin" -w "尾部 http=%{http_code} 字节=%{size_download}\n"
api -G "$B/api/datasets/dataset-14/file" --data-urlencode "link_name=原始数据" --data-urlencode "path=$V" -H "Range: bytes=$((S+10))-" -o /dev/null -w "越界 Range http=%{http_code}\n"
cmp "$W/r1.bin" "$W/expect-head.bin" && echo "首 1024 字节相同"
step "5. 浏览器"; "$REAL_HOME/.local/bin/node" "$AS/viewer-browser-drill.mjs" "$B" "$AS/drill"; echo "[node exit $?]"
kill -TERM "$WEB" "$WORKER"; wait "$WEB"; echo "web exit=$?"; wait "$WORKER"; echo "worker exit=$?"
step "6. 只读核对"; awk '{print $7}' /sys/block/sda/stat /sys/block/sdb/stat > "$W/writes-after.txt"; find /mnt/datasets -printf '%p %T@ %s\n' 2>/dev/null | sort > "$W/find-after.txt"; cmp "$W/find-before.txt" "$W/find-after.txt" && echo "/mnt/datasets 清单逐字节相同"
paste "$W/writes-before.txt" "$W/writes-after.txt"; cmp -s "$W/writes-before.txt" "$W/writes-after.txt" && echo "两块数据盘在平台读取期间没有写入"
grep -c ERROR "$HOME/.local/share/rdp/logs/web.log" | sed 's/^/web.log ERROR /'
