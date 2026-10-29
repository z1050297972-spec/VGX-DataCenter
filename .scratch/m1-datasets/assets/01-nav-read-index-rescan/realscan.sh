#!/usr/bin/env bash
# 验收 1：临时状态目录、nav_root=/mnt/datasets，起 Web 和 worker，手动提交一次全量重新扫描；前后对比 /mnt/datasets 的 find 清单。
set -uo pipefail
WT=/home/shawn/桌面/robot-data-platform.wt/m1-01-nav-read-index-rescan
AS=/home/shawn/桌面/robot-data-platform/.scratch/m1-datasets/assets/01-nav-read-index-rescan
FEED=/home/shawn/桌面/robot-data-platform/.scratch/m0-foundation/assets/11-ops-entry-systemd/feedpw.py
D=$HOME/.cache/rdp-dispatch/m1-01/realscan
REAL_HOME=$HOME
rm -rf "$D"; mkdir -p "$D/home/.config/rdp"
export HOME=$D/home
PY=$WT/.venv/bin/python
B=http://127.0.0.1:8615
cat > "$HOME/.config/rdp/config.toml" <<CFG
nav_root = "/mnt/datasets"
[web]
host = "127.0.0.1"
port = 8615
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
api() { curl -s -m 10 -b "$D/cj" -c "$D/cj" -H "Origin: $B" -H 'Content-Type: application/json' "$@"; echo; }
step "0. 扫描前 /mnt/datasets 清单"
find /mnt/datasets -printf '%p %T@ %s\n' 2>/dev/null | sort > "$AS/realscan-find-before.txt"; wc -l < "$AS/realscan-find-before.txt"
step "1. 迁移、建管理员"
"$PY" -m rdp migrate
"$REAL_HOME/.local/share/uv/python/cpython-3.12.15-linux-x86_64-gnu/bin/python3" -I "$FEED" 'Admin-pass-2026!' "$PY" -m rdp create-admin admin 管理员 | tail -2
step "2. 起 Web 和 worker"
"$PY" -m rdp web > "$D/web.out" 2>&1 < /dev/null & WEB=$!
"$PY" -m rdp worker > "$D/worker.out" 2>&1 < /dev/null & WORKER=$!
for _ in $(seq 1 60); do curl -s -m 2 "$B/api/health" > /dev/null && break; sleep 1; done
api -d '{"login_name":"admin","password":"Admin-pass-2026!"}' "$B/api/auth/login" | head -c 100; echo
sleep 8; step "3. 已有作业（含启动时自动提交的）"
api "$B/api/jobs" | head -c 1500; echo
step "4. 手动提交全量重新扫描"
JOB=$(api -d '{"type_name":"dataset_rescan","parameters":{}}' "$B/api/jobs" | tee /dev/stderr | grep -o '"job_id":"[0-9]*"' | grep -o '[0-9]\+'); echo "job_id=$JOB"
for _ in $(seq 1 120); do s=$(api "$B/api/jobs/$JOB" | grep -o '"state":"[a-z_]*"' | head -1); [[ $s == *completed* || $s == *failed* || $s == *cancelled* || $s == *interrupted* ]] && break; sleep 1; done
echo "$s"
api "$B/api/jobs/$JOB"
step "5. 作业日志"
api "$B/api/jobs/$JOB/log" | head -c 4000; echo
step "6. 索引（sqlite3 只读）"
DB=$HOME/.local/share/rdp/rdp.sqlite3
sqlite3 "file:$DB?mode=ro" "select 'datasets',count(*) from datasets; select 'entries',view,count(*) from dataset_entries group by view; select 'links',count(*) from dataset_links; select 'sources',count(*) from dataset_sources; select 'docs',count(*) from dataset_documents; select 'findings',\"group\",severity,rule,total from dataset_findings order by 2,3,4; select 'scan',scan_id,scope,navigation_elapsed_s,lock_held_s,storage_stage from dataset_scans;"
sqlite3 "file:$DB?mode=ro" "select dataset_id,name,recorded_size_bytes from datasets order by dataset_id;" > "$AS/realscan-datasets.txt"; wc -l < "$AS/realscan-datasets.txt"
sqlite3 "file:$DB?mode=ro" "select owner_key,\"group\",severity,rule,total,samples from dataset_findings order by 2,3,4;" > "$AS/realscan-findings.txt"
step "7. 停服务"
kill -TERM "$WEB" "$WORKER"; wait "$WEB"; echo "web exit=$?"; wait "$WORKER"; echo "worker exit=$?"
step "8. 扫描后 /mnt/datasets 清单比对"
find /mnt/datasets -printf '%p %T@ %s\n' 2>/dev/null | sort > "$AS/realscan-find-after.txt"
cmp "$AS/realscan-find-before.txt" "$AS/realscan-find-after.txt" && echo "清单逐字节相同：没有写 /mnt/datasets"
cmp "$AS/baseline-find-before.txt" "$AS/realscan-find-after.txt" && echo "与开票时基线也相同"
step "9. 日志里的扫描行"
grep -E "扫描|rescan|ERROR|WARNING" "$HOME/.local/share/rdp/logs/worker.log" | head -20
