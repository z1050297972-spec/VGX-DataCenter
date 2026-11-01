#!/usr/bin/env bash
# M0 第 13 张副本演练：导航层只读复制到 ~/.cache/rdp-drill/m0-13/nav，临时 HOME，起 Web 和 worker；
# 核对登录页日志降噪、成员提交权限与诊断脱敏、请求体上限、数据库文件权限、antd 下拉框；前后比对 /mnt 清单与写入扇区。
set -uo pipefail
WT=/home/shawn/桌面/robot-data-platform.wt/m0-13-cleanup
AS=/home/shawn/桌面/robot-data-platform/.scratch/m0-foundation/assets/13-followups-cleanup
FEED=/home/shawn/桌面/robot-data-platform/.scratch/m0-foundation/assets/11-ops-entry-systemd/feedpw.py
W=$HOME/.cache/rdp-drill/m0-13
REAL_HOME=$HOME; PY=$WT/.venv/bin/python
case "$W/" in /mnt/*) echo "拒绝"; exit 2;; esac
rm -rf "$W/nav" "$W/home"; mkdir -p "$W/nav" "$W/home/.config/rdp"
cd "$W"
(cd "$WT/src/web" && node_modules/.bin/vite build > /dev/null 2>&1) || { echo "前端构建失败"; exit 1; }
trap 'rm -rf "$WT/src/web/dist"' EXIT
find /mnt/datasets -printf '%p %T@ %s\n' 2>/dev/null | sort > "$W/find-before.txt"; awk '{print $7}' /sys/block/sda/stat /sys/block/sdb/stat > "$W/writes-before.txt"
for item in /mnt/datasets/*; do n=$(basename "$item"); case "$n" in 解压样本|工具|VGX_video) mkdir -p "$W/nav/$n";; *) cp -a --no-dereference -- "$item" "$W/nav/";; esac; done
export HOME=$W/home
B=http://127.0.0.1:8627
cat > "$HOME/.config/rdp/config.toml" <<CFG
nav_root = "$W/nav"
[web]
host = "127.0.0.1"
port = 8627
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
step "1. 浏览器：登录页刷新 10 次、antd 下拉框"
"$REAL_HOME/.local/bin/node" "$AS/cleanup-browser-drill.mjs" "$B" "$AS/drill"; echo "[node exit $?]"
echo "web.log ERROR 行数：$(grep -c ' ERROR ' "$D/logs/web.log")"; grep ' 401 \|status=401\|401' "$D/logs/web.log" | head -2
step "2. 成员提交权限"
api cja -d '{"login_name":"admin","password":"Admin-pass-2026!"}' "$B/api/auth/login" > /dev/null
api cja -d '{"login_name":"member1","display_name":"成员一","password":"Member-pass-2026!","role":"member"}' "$B/api/accounts" | head -c 200; echo
api cjm -d '{"login_name":"member1","password":"Member-pass-2026!"}' "$B/api/auth/login" | head -c 200; echo
api cjm -d '{"current_password":"Member-pass-2026!","new_password":"Member-pass-2026!b"}' "$B/api/auth/password" -o /dev/null -w '改密 HTTP %{http_code}\n'
api cjm -d '{"login_name":"member1","password":"Member-pass-2026!b"}' "$B/api/auth/login" -o /dev/null -w '重新登录 HTTP %{http_code}\n'
n0=$(sqlite3 "file:$D/rdp.sqlite3?mode=ro" "select count(*) from jobs")
for t in purge_errors purge_audit_logs nav_write_apply example_gpu; do api cjm -d "{\"type_name\":\"$t\",\"parameters\":{}}" "$B/api/jobs" -o "$W/r-$t.json" -w "成员提交 $t HTTP %{http_code}\n"; done
api cjm -d '{"type_name":"dataset_rescan","parameters":{}}' "$B/api/jobs" -o "$W/r-rescan.json" -w '成员提交 dataset_rescan HTTP %{http_code}\n'; head -c 300 "$W/r-rescan.json"; echo
n1=$(sqlite3 "file:$D/rdp.sqlite3?mode=ro" "select count(*) from jobs"); echo "作业记录 $n0 → $n1（只应多 1 条 rescan）"
grep -o '"title":"[^"]*"\|"detail":"[^"]*"' "$W/r-nav_write_apply.json" | head -3
step "3. 成员看诊断：取一个失败作业"
fj=$(sqlite3 "file:$D/rdp.sqlite3?mode=ro" "select job_id from jobs where state in ('failed','interrupted') order by job_id desc limit 1"); echo "失败作业：${fj:-无}"
if [ -n "$fj" ]; then api cja "$B/api/jobs/$fj" > "$W/diag-admin.json"; api cjm "$B/api/jobs/$fj" > "$W/diag-member.json"; echo "管理员看到的绝对路径数：$(grep -o '/home/[^" ]*\|/mnt/[^" ]*' "$W/diag-admin.json" | wc -l)；成员：$(grep -o '/home/[^" ]*\|/mnt/[^" ]*' "$W/diag-member.json" | wc -l)"; fi
step "4. 请求体上限"
head -c $((17*1024*1024)) /dev/zero | tr '\0' 'a' > "$W/big.txt"
curl -s -m 30 -b "$W/cjm" -H "Origin: $B" -H 'Content-Type: application/json' --data-binary @"$W/big.txt" "$B/api/jobs" -o "$W/r-big.json" -w '17 MiB 请求 HTTP %{http_code}\n'; head -c 200 "$W/r-big.json"; echo
step "5. 数据库文件权限"
stat -c '%a %n' "$D"/rdp.sqlite3* 
kill -TERM "$WEB" "$WORKER"; wait "$WEB"; echo "web exit=$?"; wait "$WORKER"; echo "worker exit=$?"
echo "web.log ERROR 行数（全程）：$(grep -c ' ERROR ' "$D/logs/web.log")"; grep ' ERROR ' "$D/logs/web.log" | head -3
step "6. 只读核对"
find /mnt/datasets -printf '%p %T@ %s\n' 2>/dev/null | sort > "$W/find-after.txt"; cmp "$W/find-before.txt" "$W/find-after.txt" && echo "/mnt/datasets 清单逐字节相同"
awk '{print $7}' /sys/block/sda/stat /sys/block/sdb/stat | paste "$W/writes-before.txt" -
