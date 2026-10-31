#!/usr/bin/env bash
# M1.5 第 04 张演练（转码、parquet）；沿用第 01 张演练：只读查看器直接对真实导航层和数据盘（只读），临时状态目录；curl 测接口和 Range，浏览器测预览和视频。
set -uo pipefail
WT=/home/shawn/桌面/robot-data-platform.wt/m15-04-video-parquet
AS=/home/shawn/桌面/robot-data-platform/.scratch/m1.5-edit-view-classify/assets/04-video-parquet
FEED=/home/shawn/桌面/robot-data-platform/.scratch/m0-foundation/assets/11-ops-entry-systemd/feedpw.py
W=$HOME/.cache/rdp-drill/m15-04; REAL_HOME=$HOME; PY=$WT/.venv/bin/python
rm -rf "$W"; mkdir -p "$W/home/.config/rdp" "$AS/drill"; cd "$W"
(cd "$WT/src/web" && node_modules/.bin/vite build > /dev/null 2>&1) || { echo "前端构建失败"; exit 1; }
trap 'rm -rf "$WT/src/web/dist"' EXIT
# 执行线自己的读取（会更新 atime）放在基线之前，基线之后只有平台在读数据盘。
V=$(cd /mnt/dataset1/libero_v3/libero_10 && find videos -name '*.mp4' | sort | head -1); S=$(stat -c %s "/mnt/dataset1/libero_v3/libero_10/$V"); head -c 1024 "/mnt/dataset1/libero_v3/libero_10/$V" > "$W/expect-head.bin"; cp /mnt/dataset1/libero_v3/libero_10/meta/info.json "$W/expect-info.json"
find /mnt/datasets -printf '%p %T@ %s\n' 2>/dev/null | sort > "$W/find-before.txt"; awk '{print $7}' /sys/block/sda/stat /sys/block/sdb/stat > "$W/writes-before.txt"
export HOME=$W/home; B=http://127.0.0.1:8628
cat > "$HOME/.config/rdp/config.toml" <<CFG
nav_root = "/mnt/datasets"
[web]
host = "127.0.0.1"
port = 8628
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
PQ=data/chunk-000/file-000.parquet
step "3. video-info"; api -G "$B/api/datasets/dataset-14/video-info" --data-urlencode "link_name=原始数据" --data-urlencode "path=$V"; echo
step "4. 转码 60% 处 10 秒"; T0=$(date +%s.%N); api -G "$B/api/datasets/dataset-14/video" --data-urlencode "link_name=原始数据" --data-urlencode "path=$V" --data-urlencode start_s=2560 --data-urlencode duration_s=10 -o "$W/seg.mp4" -w "http=%{http_code} 字节=%{size_download} 类型=%{content_type}\n"; echo "用时 $(echo "$(date +%s.%N) - $T0" | bc) 秒"
ffprobe -v error -select_streams v:0 -show_entries stream=codec_name,width,height -show_entries format=duration -of compact "$W/seg.mp4"
step "5a. parquet"; api -G "$B/api/datasets/dataset-14/parquet" --data-urlencode "link_name=原始数据" --data-urlencode "path=$PQ" --data-urlencode offset=0 --data-urlencode limit=3 | head -c 900; echo
step "5. 浏览器"; "$REAL_HOME/.local/bin/node" "$AS/vp-browser-drill.mjs" "$B" "$AS/drill"; echo "[node exit $?]"
kill -TERM "$WEB" "$WORKER"; wait "$WEB"; echo "web exit=$?"; wait "$WORKER"; echo "worker exit=$?"
step "6. 只读核对"; awk '{print $7}' /sys/block/sda/stat /sys/block/sdb/stat > "$W/writes-after.txt"; find /mnt/datasets -printf '%p %T@ %s\n' 2>/dev/null | sort > "$W/find-after.txt"; cmp "$W/find-before.txt" "$W/find-after.txt" && echo "/mnt/datasets 清单逐字节相同"
paste "$W/writes-before.txt" "$W/writes-after.txt"; cmp -s "$W/writes-before.txt" "$W/writes-after.txt" && echo "两块数据盘在平台读取期间没有写入"
grep -c ERROR "$HOME/.local/share/rdp/logs/web.log" | sed 's/^/web.log ERROR /'
