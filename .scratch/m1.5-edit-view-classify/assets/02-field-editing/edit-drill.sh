#!/usr/bin/env bash
# M1.5 第 02 张副本演练（字段编辑、撤回）：真实导航层只读复制到 ~/.cache/rdp-drill/m15-02/nav，在副本上起 Web 和 worker，
# 走建链和新增数据集的 预览 → 写入 → 撤回 整条 API 流程；跑前跑后比对 /mnt/datasets 清单和两块盘写入扇区数。
set -uo pipefail
WT=/home/shawn/桌面/robot-data-platform.wt/m15-02-field-editing
FEED=/home/shawn/桌面/robot-data-platform/.scratch/m0-foundation/assets/11-ops-entry-systemd/feedpw.py
W=$HOME/.cache/rdp-drill/m15-02
REAL_HOME=$HOME; PY=$WT/.venv/bin/python
case "$W/" in /mnt/*) echo "拒绝"; exit 2;; esac
rm -rf "$W/nav" "$W/home"; mkdir -p "$W/nav" "$W/home/.config/rdp"
cd "$W"
(cd "$WT/src/web" && node_modules/.bin/vite build > /dev/null 2>&1) || { echo "前端构建失败"; exit 1; }
trap 'rm -rf "$WT/src/web/dist"' EXIT
find /mnt/datasets -printf '%p %T@ %s\n' 2>/dev/null | sort > "$W/find-before.txt"; awk '{print $7}' /sys/block/sda/stat /sys/block/sdb/stat > "$W/writes-before.txt"
for item in /mnt/datasets/*; do n=$(basename "$item"); case "$n" in 解压样本|工具|VGX_video) mkdir -p "$W/nav/$n";; *) cp -a --no-dereference -- "$item" "$W/nav/";; esac; done
export HOME=$W/home
B=http://127.0.0.1:8626
cat > "$HOME/.config/rdp/config.toml" <<CFG
nav_root = "$W/nav"
[web]
host = "127.0.0.1"
port = 8626
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
INFO="$N/按任务/libero_10/数据集信息.json"; SUB="$N/按任务/libero_10/子任务.json"; FINFO="$N/按格式/lerobot/3.0/libero_10/数据集信息.json"
sha256sum "$INFO" "$SUB" "$FINFO" > "$W/before.sha"
step "1. 读可编辑字段"
H1=$(api -G "$B/api/datasets/dataset-14/editable-fields" --data-urlencode "document=数据集信息.json" | python3 -c "import json,sys; print(json.load(sys.stdin)['sha256'])"); echo "信息哈希 $H1"
H2=$(api -G "$B/api/datasets/dataset-14/editable-fields" --data-urlencode "document=子任务.json" --data-urlencode offset=0 --data-urlencode limit=20 | python3 -c "import json,sys; print(json.load(sys.stdin)['sha256'])"); echo "子任务哈希 $H2"
step "2. 编辑预览"
BODY=$(python3 -c "import json,sys; h1,h2=sys.argv[1:]; print(json.dumps({'dataset_id':'dataset-14','changes':[{'document':'数据集信息.json','expected_sha256':h1,'path':['robot_model'],'value':'Franka Panda'},{'document':'数据集信息.json','expected_sha256':h1,'path':['scene'],'value':'tabletop'},{'document':'数据集信息.json','expected_sha256':h1,'path':['tasks'],'value':['pick_place','articulated']},{'document':'数据集信息.json','expected_sha256':h1,'path':['fields',5,'value_markdown'],'value':'人工更新：厨房与桌面操作（演练）'},{'document':'子任务.json','expected_sha256':h2,'path':['tasks',0,'description'],'value':'人工更新的描述（演练）'}]}, ensure_ascii=False))" "$H1" "$H2")
P=$(api -d "$BODY" "$B/api/navigation/fields/preview" | tee "$W/preview-submit.json" | jid); echo "预览作业 $P"; [ -z "$P" ] && head -c 600 "$W/preview-submit.json"; waitjob "$P"
api "$B/api/navigation/previews/$P" | head -c 1800; echo
step "3. 确认"; R=$(api -X POST "$B/api/navigation/fields/previews/$P/apply"); echo "$R" | head -c 300; echo; A=$(echo "$R" | jid); waitjob "$A"
python3 - "$INFO" "$FINFO" "$SUB" <<'PY'
import json,sys
a=json.load(open(sys.argv[1])); b=json.load(open(sys.argv[2])); c=json.load(open(sys.argv[3]))
print("按任务:", a.get('robot_model'), a.get('scene'), a.get('tasks'), a['fields'][5]['value_markdown'])
print("按格式:", b.get('robot_model'), b.get('scene'), b.get('tasks'), b['fields'][5]['value_markdown'])
t=c.get('tasks',[None])[0]; print("子任务[0].description:", (t or {}).get('description'))
PY
sleep 4; api "$B/api/datasets/detail?entry_path=$(python3 -c 'import urllib.parse;print(urllib.parse.quote("按任务/libero_10"))')" | grep -o '"robot_model":"[^"]*"\|"scene":"[^"]*"' | head -3
step "4. 撤回"; RR=$(api -d "{\"type_name\":\"nav_revert_preview\",\"parameters\":{\"target_job_id\":$A}}" "$B/api/jobs" | jid); waitjob "$RR"; RA=$(api -d "{\"type_name\":\"nav_write_apply\",\"parameters\":{\"preview_job_id\":$RR}}" "$B/api/jobs" | jid); waitjob "$RA"
sha256sum "$INFO" "$SUB" "$FINFO" | diff "$W/before.sha" - && echo "撤回后三份文件和编辑前逐字节相同"
step "4. 操作日志与变更记录"
sqlite3 "file:$HOME/.local/share/rdp/rdp.sqlite3?mode=ro" "select log_id, actor_name, operation, object_id, result from operation_logs where object_kind='navigation_write' order by log_id;"
ls "$HOME/.local/share/rdp/nav-changes/"
kill -TERM "$WEB" "$WORKER"; wait "$WEB"; echo "web exit=$?"; wait "$WORKER"; echo "worker exit=$?"
step "5. 只读核对"
find /mnt/datasets -printf '%p %T@ %s\n' 2>/dev/null | sort > "$W/find-after.txt"; cmp "$W/find-before.txt" "$W/find-after.txt" && echo "/mnt/datasets 清单逐字节相同"
awk '{print $7}' /sys/block/sda/stat /sys/block/sdb/stat | paste "$W/writes-before.txt" -
grep -c ERROR "$HOME/.local/share/rdp/logs/worker.log" | sed 's/^/worker.log ERROR /'
