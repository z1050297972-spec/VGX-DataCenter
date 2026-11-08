#!/usr/bin/env bash
# M4 演练第二部分：沿用第一部分的副本、测试根和数据库，用第 04 张的代码对作业 6 的真实产物做"检查并入库"。
set -uo pipefail
R=${R:?需要指定代码目录}; export PYTHONPATH=$R/src
W=$HOME/.cache/rdp-drill/m4; PY=/home/shawn/桌面/robot-data-platform/.venv/bin/python; ROOT=/run/media/shawn/rdpm4drill; CJ=6
case "$W/" in /mnt/*) echo 拒绝; exit 2;; esac
step() { printf '\n===== %s =====\n' "$1"; }
step "0. 前置记录"
findmnt -n "$ROOT" > /dev/null || { echo "测试根没挂载"; exit 3; }
find /mnt/datasets -printf '%p %T@ %s\n' 2>/dev/null | sort > "$W/find-before-ingest.txt"
awk '{print $7}' /sys/block/sda/stat /sys/block/sdb/stat > "$W/writes-before-ingest.txt"; paste -sd' ' "$W/writes-before-ingest.txt" | sed 's/^/写入扇区 sda sdb: /'
ls "$ROOT/暂存/转换/$CJ/"; du -sh "$ROOT/暂存/转换/$CJ/out" 2>/dev/null
rm -rf "$W/nav-before-ingest"; cp -a "$W/nav" "$W/nav-before-ingest"
[ -e "$R/src/web/node_modules" ] || ln -s /home/shawn/桌面/robot-data-platform/src/web/node_modules "$R/src/web/node_modules"
(cd "$R/src/web" && node_modules/.bin/vite build > /dev/null 2>&1) || { echo 前端构建失败; exit 1; }
export HOME=$W/home; B=http://127.0.0.1:8641
api() { curl -s -m 60 -b "$W/cj" -c "$W/cj" -H "Origin: $B" -H 'Content-Type: application/json' "$@"; echo; }
waitjob() { for _ in $(seq 1 900); do s=$(api "$B/api/jobs/$1" | grep -o '"state":"[a-z_]*"' | head -1); [[ $s == *completed* || $s == *failed* || $s == *cancelled* || $s == *interrupted* ]] && { o=$(api "$B/api/jobs/$1" | grep -o '"outcome":"[a-z_]*"' | head -1); echo "作业 $1 $s $o"; return; }; sleep 2; done; echo "作业 $1 超时"; }
jid() { grep -o '"job_id":"\?[0-9]*' | head -1 | grep -o '[0-9]\+'; }
"$PY" -m rdp migrate | tail -1
"$PY" -m rdp web > "$W/web-ingest.out" 2>&1 < /dev/null & WEB=$!
"$PY" -m rdp worker > "$W/worker-ingest.out" 2>&1 < /dev/null & WORKER=$!
trap 'kill -TERM $WEB $WORKER 2>/dev/null; rm -rf "$R/src/web/dist"' EXIT
for _ in $(seq 1 60); do curl -s -m 2 "$B/api/health" > /dev/null && break; sleep 1; done
api -d '{"login_name":"admin","password":"Admin-pass-2026!"}' "$B/api/auth/login" > /dev/null; sleep 5
step "1. 检查并预览（作业 $CJ 的产物）"
P=$(api -d '{}' "$B/api/jobs/$CJ/conversion-ingest-preview" | jid); echo "预览作业 $P"; waitjob "$P"
api "$B/api/jobs/$P" > "$W/ingest-preview-job.json"
python3 -c "
import json;d=json.load(open('$W/ingest-preview-job.json'));p=(d.get('summary') or {}).get('progress') or d.get('progress') or {}
c=p.get('ingest_check') or {};r=c.get('report') or {}
print('检查结果',r.get('result'),'警告',r.get('warning_count'),'自动就绪',c.get('automatic_ready'),'大小',c.get('size_bytes'))
for l in r.get('layers',[]): print('  ',l)
print('诊断',json.dumps(d.get('diagnostics'),ensure_ascii=False)[:600])"
api "$B/api/jobs/$P/conversion-ingest-preview" > "$W/ingest-preview.json"; python3 -c "
import json;d=json.load(open('$W/ingest-preview.json'));print({k:d[k] for k in d if k in ('dataset_name','target_subdir','format_entries','checks','notices')})
for f in (d.get('information') or {}).get('fields',[])[:14]: print('  第',f.get('number'),'项',f.get('title'),'：',str(f.get('value_markdown'))[:80])" 2>&1 | head -24
step "2. 确认入库"
A=$(api -d "{\"preview_job_id\":\"$P\"}" "$B/api/jobs/conversion-ingest" | jid); echo "入库作业 $A"; waitjob "$A"
api "$B/api/jobs/$A" | python3 -c "import json,sys;d=json.load(sys.stdin);print('诊断',json.dumps(d.get('diagnostics'),ensure_ascii=False)[:600])"
step "3. 核对导航层副本与测试根"
NAME=$(python3 -c "import json;print(json.load(open('$W/ingest-preview.json'))['dataset_name'])"); echo "新数据集 $NAME"
ls -la "$W/nav/按任务/$NAME/" 2>&1; find "$W/nav/按格式" -maxdepth 3 -name "$NAME" -printf '%p\n'
python3 - "$W/nav/按任务/$NAME" <<'PY'
import json,sys,os
d=sys.argv[1]
info=json.load(open(os.path.join(d,'数据集信息.json'))); src=json.load(open(os.path.join(d,'来源.json')))
print('dataset_id',info.get('dataset_id'),'data_origin',info.get('data_origin'),'robot_model',info.get('robot_model'),'有collection键','collection' in info)
for rec in src.get('lineage',[]):
    print('血缘',rec['kind'],rec['status'],rec['recorded_by']['kind'],rec['inputs'],rec['outputs'],rec['tool'],{k:(v if k!='text' else f'{len(v)} 字') for k,v in (rec['config'] or {}).items()},rec['job_id'],rec['ingest_check'])
for l in os.scandir(d):
    if l.is_symlink(): print('链接',l.name,'->',os.readlink(l.path))
PY
ls "$ROOT/暂存/转换/$CJ/" ; ls "$ROOT/转换/" 2>&1
step "4. 详情上下游（M3 第 05 张的投影）"
sleep 20
NEWID=$(python3 -c "import json;print(json.load(open('$W/nav/按任务/$NAME/数据集信息.json'))['dataset_id'])")
api "$B/api/datasets/$NEWID" | python3 -c "import json,sys;d=json.load(sys.stdin);print('新数据集上下游',json.dumps(d.get('lineage'),ensure_ascii=False)[:400])"
api "$B/api/datasets/dataset-35" | python3 -c "import json,sys;d=json.load(sys.stdin);print('dataset-35 上下游',json.dumps(d.get('lineage'),ensure_ascii=False)[:400])"
step "5. 转换暂存列表"
api "$B/api/conversions/staging" | head -c 800; echo
kill -TERM "$WEB" "$WORKER"; wait "$WEB" 2>/dev/null; wait "$WORKER" 2>/dev/null; rm -rf "$R/src/web/dist"; trap - EXIT
step "6. 只读核对"
find /mnt/datasets -printf '%p %T@ %s\n' 2>/dev/null | sort > "$W/find-after-ingest.txt"; cmp -s "$W/find-before-ingest.txt" "$W/find-after-ingest.txt" && echo "/mnt/datasets 清单逐字节相同" || echo "/mnt/datasets 清单有变化"
awk '{print $7}' /sys/block/sda/stat /sys/block/sdb/stat | paste "$W/writes-before-ingest.txt" - | sed 's/^/写入扇区 前→后 /'
diff -rq --no-dereference "$W/nav-before-ingest" "$W/nav" | head -20
echo "worker.log ERROR $(grep -c ERROR "$HOME/.local/share/rdp/logs/worker.log")"
