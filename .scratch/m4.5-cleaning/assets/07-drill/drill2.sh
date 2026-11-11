#!/usr/bin/env bash
# M4.5 第 06、07 张复验（由第 05 张演练 drill.sh 改写）：worker 不带 TERM；剔除用工具编码器（GPU）。
# 导航层副本 + 两个回环挂载的 ext4 测试根（样本输入只读、平台区可写）。
# 输入只用 M5 的真实样本副本（系统盘），不读两块数据盘；不碰真实部署。
set -uo pipefail
R=/home/shawn/桌面/robot-data-platform.wt/m4.5-cleaning   # 集成分支检出，自带 .venv
export PYTHONPATH=$R/src
FEED=$R/.scratch/m0-foundation/assets/11-ops-entry-systemd/feedpw.py
W=$HOME/.cache/rdp-drill/m4.5; REAL_HOME=$HOME; PY=$R/.venv/bin/python
SAMPLE=$HOME/.cache/rdp-m5-offline/sample/r1lite_20261011_52s.mcap
EV=$R/.scratch/m4.5-cleaning/assets/07-drill; mkdir -p "$EV"
case "$W/" in /mnt/*) echo 拒绝; exit 2;; esac
step() { printf '\n===== %s =====\n' "$1"; }
mountimg() { # 名字 大小 → 打印挂载点 UUID
  local name=$1 size=$2 img=$W/$1.img old loop root uuid
  if old=$(findmnt -n -o SOURCE "/run/media/shawn/$name"); then udisksctl unmount --no-user-interaction -b "$old" > /dev/null; fi
  rm -f "$img"; truncate -s "$size" "$img" && /usr/sbin/mkfs.ext4 -q -F -L "$name" -E root_owner=1001:1001 "$img"
  loop=$(udisksctl loop-setup --no-user-interaction -f "$img" | grep -o '/dev/loop[0-9]*')
  udisksctl mount --no-user-interaction -b "$loop" > /dev/null
  root=/run/media/shawn/$name; uuid=$(lsblk -no UUID "$(findmnt -n -o SOURCE "$root")" | tr -d ' ')
  echo "$root $uuid"
}

step "0. 前置记录"
find /mnt/datasets -printf '%p %T@ %s\n' 2>/dev/null | sort > "$W/find-before.txt"
awk '{print $7}' /sys/block/sda/stat /sys/block/sdb/stat > "$W/writes-before.txt"; paste -sd' ' "$W/writes-before.txt" | sed 's/^/写入扇区 sda sdb: /'
stat -c '工具程序 atime %x' /mnt/datasets/工具/mcap2lerobot/target/release/mcap2lerobot

step "1. 测试根：样本输入（只读登记）与平台区（可写）"
read -r IN_ROOT IN_UUID < <(mountimg rdpm45in 2G)
mkdir -p "$IN_ROOT/20261011_sample" && cp "$SAMPLE" "$IN_ROOT/20261011_sample/" && sync
read -r OUT_ROOT OUT_UUID < <(mountimg rdpm45out 4G)
echo "输入根 $IN_ROOT $IN_UUID；平台根 $OUT_ROOT $OUT_UUID"; ls -la "$IN_ROOT/20261011_sample"

step "2. 导航层副本，起 web / worker（worker 不带 TERM，模拟 systemd 服务）"
rm -rf "$W/nav" "$W/home" "$W/cj"; mkdir -p "$W/nav" "$W/home/.config/rdp"
for item in /mnt/datasets/*; do n=$(basename "$item"); case "$n" in 工具|解压样本|VGX_video) mkdir -p "$W/nav/$n";; *) cp -a --no-dereference -- "$item" "$W/nav/";; esac; done
(cd "$R/src/web" && node_modules/.bin/vite build > /dev/null 2>&1) || { echo 前端构建失败; exit 1; }
export HOME=$W/home; B=http://127.0.0.1:8645
cat > "$HOME/.config/rdp/config.toml" <<CFG
nav_root = "$W/nav"
[web]
host = "127.0.0.1"
port = 8645
[jobs]
gpus = [0]
[tools]
lerobot_python = "/home/shawn/miniconda3/envs/lerobot/bin/python"
[[storage_roots]]
name = "dataset1"
path = "/mnt/dataset1"
uuid = "2d3a48d6-3785-47fe-8c8f-a20857fdc41a"
[[storage_roots]]
name = "dataset2"
path = "/mnt/dataset2"
uuid = "35445b14-9e83-4f74-ac73-1551e3db6d63"
[[storage_roots]]
name = "drill_input"
path = "$IN_ROOT"
uuid = "$IN_UUID"
[[storage_roots]]
name = "drill_platform"
path = "$OUT_ROOT"
uuid = "$OUT_UUID"
writable = true
CFG
api() { curl -s -m 60 -b "$W/cj" -c "$W/cj" -H "Origin: $B" -H 'Content-Type: application/json' "$@"; echo; }
jid() { grep -o '"job_id":"\?[0-9]*' | head -1 | grep -o '[0-9]\+'; }
waitjob() { local s; for _ in $(seq 1 900); do s=$(api "$B/api/jobs/$1" | grep -o '"state":"[a-z_]*"' | head -1); [[ $s == *completed* || $s == *failed* || $s == *cancelled* || $s == *interrupted* ]] && { echo "作业 $1 $s"; return; }; sleep 2; done; echo "作业 $1 超时"; }
"$PY" -m rdp migrate | tail -1
"$REAL_HOME/.local/share/uv/python/cpython-3.12.15-linux-x86_64-gnu/bin/python3" -I "$FEED" 'Admin-pass-2026!' "$PY" -m rdp create-admin admin 管理员 | tail -1
"$PY" -m rdp web > "$W/web.out" 2>&1 < /dev/null & WEB=$!
env -u TERM "$PY" -m rdp worker > "$W/worker.out" 2>&1 < /dev/null & WORKER=$!
trap 'kill -TERM $WEB $WORKER 2>/dev/null; rm -rf "$R/src/web/dist"' EXIT
sleep 1; echo "worker 环境里的 TERM 条数：$(tr '\0' '\n' < /proc/$WORKER/environ | grep -c '^TERM=')"
for _ in $(seq 1 60); do curl -s -m 2 "$B/api/health" > /dev/null && break; sleep 1; done
api -d '{"login_name":"admin","password":"Admin-pass-2026!"}' "$B/api/auth/login" > /dev/null
for _ in $(seq 1 120); do n=$(api "$B/api/datasets?limit=1" | grep -o '"total":[0-9]*' | grep -o '[0-9]*'); [[ ${n:-0} -ge 35 ]] && break; sleep 2; done; echo "索引数据集 $n"; sleep 10
DB="file:$HOME/.local/share/rdp/rdp.sqlite3?mode=ro"

step "3. 工具库与 LeRobot 环境"
api "$B/api/tools" | python3 -I -c "import json,sys;d=json.load(sys.stdin);[print(t['name'],t['status'],'清洗型号',t['cleaning_models']) for t in d['items']];e=d['lerobot_environment'];print('LeRobot',e['status'],e['actual_version'],(e['actual_fingerprint'] or '')[:12],e['message'])"

step "4. 给 dataset-35 建链到样本副本（输入根）"
L=$(api -d "{\"dataset_id\":\"dataset-35\",\"link\":{\"name\":\"20261011_sample\",\"target_path\":\"$IN_ROOT/20261011_sample\",\"fallback_format\":\"mcap\"},\"format_entries\":[]}" "$B/api/datasets/link-previews" | tee "$W/link-preview.json" | jid); echo "建链预览 $L"; [ -z "$L" ] && head -c 600 "$W/link-preview.json"; waitjob "$L"
LA=$(api -d "{\"preview_job_id\":\"$L\"}" "$B/api/datasets/creation-writes" | tee "$W/link-apply.json" | jid); [ -z "$LA" ] && head -c 600 "$W/link-apply.json"; waitjob "$LA"
for _ in $(seq 1 60); do SRC=$(sqlite3 "$DB" "select s.source_id from dataset_sources s join datasets d on s.entry_path=d.canonical_entry_path where d.dataset_id='dataset-35' and s.direct_path like '%rdpm45in%';"); [ -n "$SRC" ] && break; sleep 2; done; echo "样本数据块 $SRC"
[ -n "$SRC" ] || { echo 没有样本数据块; exit 4; }

step "5. 清洗预览"
P=$(api -d "{\"dataset_id\":\"dataset-35\",\"source_ids\":[\"$SRC\"],\"robot_model\":\"Galaxea R1 Lite\"}" "$B/api/jobs/cleaning-preview/mcap2lerobot" | tee "$W/preview-submit.json" | jid); echo "预览作业 $P"; [ -z "$P" ] && head -c 600 "$W/preview-submit.json"; waitjob "$P"
api "$B/api/cleaning-previews/$P" > "$W/preview.json"
python3 -I -c "import json;r=json.load(open('$W/preview.json'))['report'];print('汇总',r['summary']);print('episode',[(e['segment_index'],e['frame_count']) for e in r['episodes']])"

step "6. 进行转换：手动剔除 (0, 2)"
rm -f "$W/progress-1.log" "$W/progress-2.log"
C=$(api -d '{"space_ratio_percent":25,"space_reserve_gib":1,"excluded_files":[],"excluded_episodes":[{"file_index":0,"segment_index":2}]}' "$B/api/cleaning-previews/$P/convert" | tee "$W/convert-submit.json" | jid); echo "转换作业 $C"; [ -z "$C" ] && head -c 600 "$W/convert-submit.json"
for _ in $(seq 1 900); do r=$(api "$B/api/jobs/$C"); s=$(echo "$r" | grep -o '"state":"[a-z_]*"' | head -1); echo "$r" | python3 -I -c "import json,sys,time;d=json.load(sys.stdin);p=d.get('progress') or {};print(time.strftime('%H:%M:%S'),d.get('state'),p.get('stage_index'),p.get('stage_count'),p.get('stage_name'),p.get('done'),p.get('total'),json.dumps([(x.get('name'),x.get('done'),x.get('total')) for x in (p.get('parts') or [])],ensure_ascii=False))" >> "$W/progress-1.log"; [[ $s == *completed* || $s == *failed* || $s == *cancelled* || $s == *interrupted* ]] && break; sleep 2; done
echo "转换 $s"; awk '{print $4,$5}' "$W/progress-1.log" | uniq | tr '\n' ' '; echo
cp "$W/progress-1.log" "$EV/progress-1.log"
echo "转换阶段带逐帧进度的采样：$(awk '$3==4 && $8!="[]"' "$W/progress-1.log" | wc -l) / $(awk '$3==4' "$W/progress-1.log" | wc -l)；示例：$(awk '$3==4 && $8!="[]"' "$W/progress-1.log" | sed -n '4p')"
echo "剔除阶段首末采样时间：$(awk '$3==5' "$W/progress-1.log" | sed -n '1p;$p' | awk '{print $1}' | tr '\n' ' ')"
api "$B/api/jobs/$C" > "$W/convert-final.json"; python3 -I -c "import json;d=json.load(open('$W/convert-final.json'));print('结果',json.dumps((d.get('progress') or {}).get('conversion'),ensure_ascii=False));print('诊断',json.dumps(d.get('diagnostics'),ensure_ascii=False)[:600])"
LOG=$HOME/.local/share/rdp/$(python3 -I -c "import json;print(json.load(open('$W/convert-final.json')).get('log_path') or '')"); echo "作业日志 $LOG"
[ -f "$LOG" ] && { echo "日志里'未解析出进度'条数：$(grep -c '未解析出进度' "$LOG")"; grep -m3 '帧' "$LOG"; cp "$LOG" "$EV/convert-job.log"; }
python3 -I -c "import json;r=json.load(open('$OUT_ROOT/暂存/转换/$C/转换回执.json'));print('回执 cleaning',json.dumps(r.get('cleaning'),ensure_ascii=False)[:1400])" 2>&1; cp "$OUT_ROOT/暂存/转换/$C/转换回执.json" "$EV/convert-receipt.json" 2>/dev/null
python3 -I -c "import json;i=json.load(open('$OUT_ROOT/暂存/转换/$C/cleaned/meta/info.json'));print('cleaned',i['total_episodes'],'episode',i['total_frames'],'帧')" 2>&1

step "7. 自动检查与自动入库"
for _ in $(seq 1 600); do st=$(sqlite3 "$DB" "select group_concat(type_name||':'||state, ' ') from jobs where job_id > $C;"); echo "$st" | grep -q "conversion_ingest_apply:completed" && break; echo "$st" | grep -q 'failed' && break; sleep 3; done
sqlite3 "$DB" "select job_id, type_name, state from jobs where job_id > $C order by job_id;"
sleep 20
NAME=R1_lite_table_withdrawing_lerobot_$C; [ -d "$W/nav/按任务/$NAME" ] || { echo "没有 $NAME"; ls "$W/nav/按任务" | grep lerobot; exit 5; }; echo "新数据集 $NAME"
python3 -I - "$W/nav/按任务/$NAME" "$OUT_ROOT" <<'PY'
import json,sys,os
d,allowed=sys.argv[1],sys.argv[2]
src=json.load(open(os.path.join(d,'来源.json'))); rec=src['lineage'][-1]
print('血缘',rec['kind'],rec['status'],rec['recorded_by']['kind'],rec['job_id'])
print('血缘 parameters',json.dumps({k:v for k,v in (rec.get('parameters') or {}).items() if 'clean' in k or 'lerobot' in k},ensure_ascii=False))
for l in os.scandir(d):
    if l.is_symlink():
        t=os.readlink(l.path); print('链接',l.name,'->',t)
        if not t.startswith(allowed+'/'): print('  不在平台测试根，不打开'); continue
        info=os.path.join(t,'meta','info.json')
        if os.path.exists(info): i=json.load(open(info)); print('入库产物',i['total_episodes'],'episode',i['total_frames'],'帧')
PY

step "7b. 视频对照：工具原产物 out 与入库的清洗产物"
PRODUCT=""; for l in "$W/nav/按任务/$NAME"/*; do [ -L "$l" ] || continue; t=$(readlink "$l"); case "$t" in "$OUT_ROOT"/*) PRODUCT=$t;; esac; done
ORIG="$OUT_ROOT/暂存/转换/$C/out"; echo "清洗产物 $PRODUCT；原产物 $ORIG"
python3 -I -c "import json;r=json.load(open('$EV/convert-receipt.json'));print('回执 encoder',json.dumps(r['cleaning']['encoder'],ensure_ascii=False))"
"$PY" -I "$W/video_compare.py" "$ORIG" "$PRODUCT" "$EV/video-compare.txt"

step "8. 同一预览再转一次，不剔除（剔除阶段应跳过）"
C2=$(api -d '{"space_ratio_percent":25,"space_reserve_gib":1,"excluded_files":[],"excluded_episodes":[]}' "$B/api/cleaning-previews/$P/convert" | jid); echo "转换作业 $C2"
for _ in $(seq 1 900); do r=$(api "$B/api/jobs/$C2"); s=$(echo "$r" | grep -o '"state":"[a-z_]*"' | head -1); echo "$r" | python3 -I -c "import json,sys,time;d=json.load(sys.stdin);p=d.get('progress') or {};print(time.strftime('%H:%M:%S'),d.get('state'),p.get('stage_index'),p.get('stage_count'),p.get('stage_name'))" >> "$W/progress-2.log"; [[ $s == *completed* || $s == *failed* || $s == *cancelled* || $s == *interrupted* ]] && break; sleep 2; done
echo "转换 $s"; awk '{print $4,$5}' "$W/progress-2.log" | uniq | tr '\n' ' '; echo
python3 -I -c "import json;r=json.load(open('$OUT_ROOT/暂存/转换/$C2/转换回执.json'));c=r.get('cleaning') or {};print('回执 剔除',c.get('excluded_episodes'),'命令',c.get('command'),'encoder',c.get('encoder'))" 2>&1

kill -TERM "$WEB" "$WORKER"; wait "$WEB" 2>/dev/null; wait "$WORKER" 2>/dev/null; rm -rf "$R/src/web/dist"; trap - EXIT
step "9. 只读核对"
find /mnt/datasets -printf '%p %T@ %s\n' 2>/dev/null | sort > "$W/find-after.txt"; cmp -s "$W/find-before.txt" "$W/find-after.txt" && echo "/mnt/datasets 清单逐字节相同" || echo "/mnt/datasets 清单有变化"
awk '{print $7}' /sys/block/sda/stat /sys/block/sdb/stat | paste "$W/writes-before.txt" - | sed 's/^/写入扇区 前→后 /'
stat -c '工具程序 atime %x' /mnt/datasets/工具/mcap2lerobot/target/release/mcap2lerobot
grep -c ERROR "$HOME/.local/share/rdp/logs/worker.log" 2>/dev/null | sed 's/^/worker.log ERROR /'
