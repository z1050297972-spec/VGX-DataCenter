#!/usr/bin/env bash
# M4 演练第一部分：导航层副本 + 回环挂载的 ext4 测试可写根，从平台接口提交一次真实转换（不碰数据盘、不碰真实部署）。
set -uo pipefail
R=/home/shawn/桌面/robot-data-platform.wt/m15-19-remove-backfill   # main 的检出
export PYTHONPATH=$R/src
FEED=$R/.scratch/m0-foundation/assets/11-ops-entry-systemd/feedpw.py
W=$HOME/.cache/rdp-drill/m4; REAL_HOME=$HOME; PY=/home/shawn/桌面/robot-data-platform/.venv/bin/python

case "$W/" in /mnt/*) echo 拒绝; exit 2;; esac
step() { printf '\n===== %s =====\n' "$1"; }
step "0. 前置记录"
find /mnt/datasets -printf '%p %T@ %s\n' 2>/dev/null | sort > "$W/find-before.txt"
awk '{print $7}' /sys/block/sda/stat /sys/block/sdb/stat > "$W/writes-before.txt"; paste -sd' ' "$W/writes-before.txt" | sed 's/^/写入扇区 sda sdb: /'
stat -c '工具程序 atime %x' /mnt/datasets/工具/mcap2lerobot/target/release/mcap2lerobot
step "1. 测试可写根（ext4 镜像回环挂载）"
# 每次重建干净的测试根：新数据库的作业号从小数字开始，不能和上次残留的暂存目录撞号。
if OLD=$(findmnt -n -o SOURCE /run/media/shawn/rdpm4drill); then udisksctl unmount --no-user-interaction -b "$OLD" > /dev/null; fi
rm -f "$W/root.img"; truncate -s 12G "$W/root.img" && /usr/sbin/mkfs.ext4 -q -F -L rdpm4drill -E root_owner=1001:1001 "$W/root.img"
LOOP=$(udisksctl loop-setup --no-user-interaction -f "$W/root.img" | grep -o '/dev/loop[0-9]*')
udisksctl mount --no-user-interaction -b "$LOOP" > /dev/null
ROOT=/run/media/shawn/rdpm4drill; LOOP=$(findmnt -n -o SOURCE "$ROOT"); UUID=$(lsblk -no UUID "$LOOP" | tr -d " "); [[ $UUID =~ ^[0-9a-f-]{36}$ ]] || { echo "读不到测试根 UUID"; exit 3; }
echo "根 $ROOT 设备 $LOOP UUID $UUID"; findmnt -n -o TARGET,FSTYPE,SOURCE "$ROOT"
step "2. 导航层副本（不跟随链接，原样）"
rm -rf "$W/nav" "$W/home" "$W/cj"; mkdir -p "$W/nav" "$W/home/.config/rdp"
for item in /mnt/datasets/*; do n=$(basename "$item"); case "$n" in 工具|解压样本|VGX_video) mkdir -p "$W/nav/$n";; *) cp -a --no-dereference -- "$item" "$W/nav/";; esac; done
rm -rf "$W/nav-orig"; cp -a "$W/nav" "$W/nav-orig"
(cd "$R/src/web" && node_modules/.bin/vite build > /dev/null 2>&1) || { echo 前端构建失败; exit 1; }
export HOME=$W/home; B=http://127.0.0.1:8641
cat > "$HOME/.config/rdp/config.toml" <<CFG
nav_root = "$W/nav"
[web]
host = "127.0.0.1"
port = 8641
[jobs]
gpus = [0]
[[storage_roots]]
name = "dataset1"
path = "/mnt/dataset1"
uuid = "2d3a48d6-3785-47fe-8c8f-a20857fdc41a"
[[storage_roots]]
name = "dataset2"
path = "/mnt/dataset2"
uuid = "35445b14-9e83-4f74-ac73-1551e3db6d63"
[[storage_roots]]
name = "drill_platform"
path = "$ROOT"
uuid = "$UUID"
writable = true
CFG
api() { curl -s -m 60 -b "$W/cj" -c "$W/cj" -H "Origin: $B" -H 'Content-Type: application/json' "$@"; echo; }
"$PY" -m rdp migrate | tail -1
"$REAL_HOME/.local/share/uv/python/cpython-3.12.15-linux-x86_64-gnu/bin/python3" -I "$FEED" 'Admin-pass-2026!' "$PY" -m rdp create-admin admin 管理员 | tail -1
"$PY" -m rdp web > "$W/web.out" 2>&1 < /dev/null & WEB=$!
"$PY" -m rdp worker > "$W/worker.out" 2>&1 < /dev/null & WORKER=$!
trap 'kill -TERM $WEB $WORKER 2>/dev/null; rm -rf "$R/src/web/dist"' EXIT
for _ in $(seq 1 60); do curl -s -m 2 "$B/api/health" > /dev/null && break; sleep 1; done
api -d '{"login_name":"admin","password":"Admin-pass-2026!"}' "$B/api/auth/login" > /dev/null
for _ in $(seq 1 120); do n=$(api "$B/api/datasets?limit=1" | grep -o '"total":[0-9]*' | grep -o '[0-9]*'); [[ ${n:-0} -ge 35 ]] && break; sleep 2; done; echo "索引数据集 $n"; sleep 10
step "3. 工具库"
api "$B/api/tools" | python3 -c "import json,sys;[print(t['name'],t['status'],t.get('sha256_prefix') or '') for t in json.load(sys.stdin)['items']]"
DB="file:$HOME/.local/share/rdp/rdp.sqlite3?mode=ro"
SRC=$(sqlite3 "$DB" "select s.source_id from dataset_sources s join datasets d on s.entry_path=d.canonical_entry_path where d.dataset_id='dataset-35' and s.direct_path like '%20261011%';"); echo "数据块 $SRC"
step "4. 提交转换"
RESP=$(api -d "{\"dataset_id\":\"dataset-35\",\"source_ids\":[\"$SRC\"],\"robot_model\":\"Galaxea R1 Lite\"}" "$B/api/jobs/convert/mcap2lerobot"); echo "$RESP" | head -c 400; echo
J=$(echo "$RESP" | grep -o '"job_id":"\?[0-9]*' | head -1 | grep -o '[0-9]\+'); echo "作业 $J" > "$W/convert-job.txt"; cat "$W/convert-job.txt"
[[ -n "$J" ]] || { echo "提交转换失败"; exit 4; }
for _ in $(seq 1 1350); do
  r=$(api "$B/api/jobs/$J"); s=$(echo "$r" | grep -o '"state":"[a-z_]*"' | head -1)
  echo "$r" | python3 -c "
import json,sys,time
d=json.load(sys.stdin); p=d.get('progress') or {}
print(time.strftime('%H:%M:%S'), d.get('state'), p.get('stage_index'), p.get('stage_name'), p.get('done'), p.get('total'), [(x['name'],x['done'],x['total']) for x in p.get('parts',[])])" >> "$W/progress.log"
  [[ $s == *completed* || $s == *failed* || $s == *cancelled* || $s == *interrupted* ]] && break; sleep 2
done
echo "最终 $s"; sed -n '1p;$p' "$W/progress.log"; grep -c . "$W/progress.log" | sed 's/^/进度采样 /'
api "$B/api/jobs/$J" > "$W/convert-final.json"; python3 -c "import json;d=json.load(open('$W/convert-final.json'));print('outcome',d.get('outcome'));print(json.dumps((d.get('progress') or {}).get('conversion'),ensure_ascii=False))"
ls "$ROOT/暂存/转换/$J/" 2>&1; python3 -c "import json;r=json.load(open('$ROOT/暂存/转换/$J/转换回执.json'));print('回执', r['tool'], r['configuration']['sha256'][:12], r['inputs'])" 2>&1
kill -TERM "$WEB" "$WORKER"; wait "$WEB" 2>/dev/null; wait "$WORKER" 2>/dev/null; rm -rf "$R/src/web/dist"; trap - EXIT
step "5. 只读核对"
find /mnt/datasets -printf '%p %T@ %s\n' 2>/dev/null | sort > "$W/find-after.txt"; cmp -s "$W/find-before.txt" "$W/find-after.txt" && echo "/mnt/datasets 清单逐字节相同" || echo "/mnt/datasets 清单有变化"
awk '{print $7}' /sys/block/sda/stat /sys/block/sdb/stat | paste "$W/writes-before.txt" - | sed 's/^/写入扇区 前→后 /'
stat -c '工具程序 atime %x' /mnt/datasets/工具/mcap2lerobot/target/release/mcap2lerobot
diff -r --no-dereference "$W/nav-orig" "$W/nav" > /dev/null && echo "导航层副本未被改动（转换不写导航层）" || echo "导航层副本有变化"
grep -c ERROR "$HOME/.local/share/rdp/logs/worker.log" 2>/dev/null | sed 's/^/worker.log ERROR /'
