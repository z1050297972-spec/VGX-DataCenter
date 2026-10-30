#!/usr/bin/env bash
# 第 07 张验收 1 最后一步：在副本演练留下的"恢复失败"现场（~/.cache/rdp-drill/m1-07）上起 Web 和 worker，用浏览器确认放行。
set -uo pipefail
WT=/home/shawn/桌面/robot-data-platform.wt/m1-07-nav-write-foundation
AS=/home/shawn/桌面/robot-data-platform/.scratch/m1-datasets/assets/07-nav-write-foundation
FEED=/home/shawn/桌面/robot-data-platform/.scratch/m0-foundation/assets/11-ops-entry-systemd/feedpw.py
W=$HOME/.cache/rdp-drill/m1-07
REAL_HOME=$HOME; NODE=$REAL_HOME/.local/bin/node; PY=$WT/.venv/bin/python
mkdir -p "$W/home/.config/rdp" "$AS/drill"
export HOME=$W/home
B=http://127.0.0.1:8621
cat > "$HOME/.config/rdp/config.toml" <<CFG
state_dir = "$W/state"
nav_root = "$W/nav"
[web]
host = "127.0.0.1"
port = 8621
[jobs]
gpus = []
CFG
step() { printf '\n===== %s =====\n' "$1"; }
DB=$W/state/rdp.sqlite3
step "0. 现场"; ls "$W/state/nav-journal"; sqlite3 "file:$DB?mode=ro" "select singleton_id, set_at, job_ids, total_items from nav_recovery_failure"
"$PY" -m rdp migrate | tail -1
"$REAL_HOME/.local/share/uv/python/cpython-3.12.15-linux-x86_64-gnu/bin/python3" -I "$FEED" 'Admin-pass-2026!' "$PY" -m rdp create-admin admin 管理员 | tail -1
"$PY" -m rdp web > "$W/web.out" 2>&1 < /dev/null & WEB=$!
"$PY" -m rdp worker > "$W/worker.out" 2>&1 < /dev/null & WORKER=$!
for _ in $(seq 1 60); do curl -s -m 2 "$B/api/health" > /dev/null && break; sleep 1; done
sleep 3
step "1. worker 启动后的恢复"; grep -E "恢复|recover|mismatch|挡住" "$HOME/.local/share/rdp/logs/worker.log" "$W/state/logs/worker.log" 2>/dev/null | tail -5
step "2. 浏览器"; "$NODE" "$AS/recovery-drill.mjs" "$B" "$AS/drill"; echo "[node exit $?]"
step "3. 确认后的现场"; ls "$W/state/nav-journal"; sqlite3 "file:$DB?mode=ro" "select count(*) from nav_recovery_failure; select log_id, actor_name, operation, object_kind, object_id, result from operation_logs where operation in ('confirm_navigation_recovery','rollback_navigation_write') order by log_id;"; ls "$W/state/nav-changes" | tail -3
kill -TERM "$WEB" "$WORKER"; wait "$WEB"; echo "web exit=$?"; wait "$WORKER"; echo "worker exit=$?"
