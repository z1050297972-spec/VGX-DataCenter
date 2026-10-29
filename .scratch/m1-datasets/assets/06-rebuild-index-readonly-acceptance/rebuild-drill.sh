#!/usr/bin/env bash
# 第 06 张验收 1：临时 HOME、nav_root=/mnt/datasets（只读）；worker 在跑时 rebuild-index 应拒绝；停 worker 后重建，前后索引内容（统计大小与运行元数据除外）一致；操作日志有一条"运维"。
set -uo pipefail
WT=/home/shawn/桌面/robot-data-platform.wt/m1-06-rebuild-index-readonly-acceptance
AS=/home/shawn/桌面/robot-data-platform/.scratch/m1-datasets/assets/06-rebuild-index-readonly-acceptance
D=$HOME/.cache/rdp-dispatch/m1-06/drill
rm -rf "$D"; mkdir -p "$D/home/.config/rdp"
export HOME=$D/home
PY=$WT/.venv/bin/python
cat > "$HOME/.config/rdp/config.toml" <<CFG
nav_root = "/mnt/datasets"
[web]
host = "127.0.0.1"
port = 8618
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
DB=$HOME/.local/share/rdp/rdp.sqlite3
step() { printf '\n===== %s =====\n' "$1"; }
export_index() {
  sqlite3 "file:$DB?mode=ro" "
  select 'D',dataset_id,name,canonical_entry_path,fingerprint,data_origin,recorded_size_bytes from datasets order by 2;
  select 'E',path,dataset_id,view,format,version,name,dataset_roots,provenance_present,fingerprint,recorded_size_bytes from dataset_entries order by 2;
  select 'J',entry_path,name,schema_version,sha256 from dataset_documents order by 2,3;
  select 'L',entry_path,ordinal,name,source_path,source_type,derived_entry_path,observed_target,storage_root_name,status from dataset_links order by 2,3;
  select 'S',entry_path,ordinal,source_id,original_path,direct_path,format,version,validation_status,storage_root_name,status,robot_type,fps,fps_rounded,codebase_version from dataset_sources order by 2,3;
  select 'F',owner_key,\"group\",severity,rule,total from dataset_findings where rule <> 'DOWNLOAD_INCOMPLETE' order by 2,3,4,5;"
}
find /mnt/datasets -printf '%p %T@ %s\n' 2>/dev/null | sort > "$D/find-before.txt"
awk '{print $7}' /sys/block/sda/stat /sys/block/sdb/stat > "$D/writes-before.txt"
step "1. 迁移，起 worker（启动时自动扫描建索引）"
"$PY" -m rdp migrate | tail -1
"$PY" -m rdp worker > "$D/worker.out" 2>&1 < /dev/null & WORKER=$!
for _ in $(seq 1 90); do n=$(sqlite3 "file:$DB?mode=ro" "select count(*) from dataset_scans where committed_at is not null" 2>/dev/null); [[ ${n:-0} -ge 1 ]] && break; sleep 1; done; echo "已提交扫描 $n 次"
sleep 2; export_index > "$D/index-before.txt"; wc -l < "$D/index-before.txt"
step "2. worker 在运行时 rebuild-index：应拒绝"
"$PY" -m rdp rebuild-index; echo "[exit $?]"
step "3. 停 worker 后 rebuild-index"
kill -TERM "$WORKER"; wait "$WORKER"; echo "worker exit=$?"
T0=$(date +%s.%N); "$PY" -m rdp rebuild-index; echo "[exit $?] 用时 $(echo "$(date +%s.%N) - $T0" | bc) 秒"
export_index > "$D/index-after.txt"; wc -l < "$D/index-after.txt"
step "4. 前后索引比对（统计大小、运行元数据除外）"
if cmp -s "$D/index-before.txt" "$D/index-after.txt"; then echo "索引内容完全一致"; else diff "$D/index-before.txt" "$D/index-after.txt" | head -20; fi
step "5. 操作日志"
sqlite3 "file:$DB?mode=ro" "select log_id, actor_name, operation, object_type, object_id, outcome from operation_logs order by log_id desc limit 3;" 2>&1
step "6. 只读核对"
find /mnt/datasets -printf '%p %T@ %s\n' 2>/dev/null | sort > "$D/find-after.txt"; cmp "$D/find-before.txt" "$D/find-after.txt" && echo "/mnt/datasets 清单逐字节相同"
awk '{print $7}' /sys/block/sda/stat /sys/block/sdb/stat > "$D/writes-after.txt"; paste "$D/writes-before.txt" "$D/writes-after.txt"; cmp -s "$D/writes-before.txt" "$D/writes-after.txt" && echo "两块数据盘没有写入"
