#!/usr/bin/env bash
# 验收 7：临时 HOME 下先装旧提交，再用升级脚本（--no-systemd）升到新提交。
# 用法：bash drill11-upgrade.sh <旧提交> <新提交>
# 覆盖：有运行中作业时升级停下；停服务后升级，版本号变化、数据库在最新版本。
set -uo pipefail
OLD=$1 NEW=$2
WT=/home/shawn/桌面/robot-data-platform.wt/m0-11-ops-entry-systemd
AS=/home/shawn/桌面/robot-data-platform/.scratch/m0-foundation/assets/11-ops-entry-systemd
D=$HOME/.cache/rdp-dispatch/m0-11/drill-upgrade
REAL_HOME=$HOME
rm -rf "$D"; mkdir -p "$D/home" "$D/nav"
export UV_CACHE_DIR=$REAL_HOME/.cache/uv UV_PYTHON_INSTALL_DIR=$REAL_HOME/.local/share/uv/python
export npm_config_store_dir=$REAL_HOME/.local/share/pnpm/store
export HOME=$D/home
cd "$HOME"
B=http://127.0.0.1:8613
step() { printf '\n===== %s =====\n' "$1"; }
run() { printf '$ %s\n' "$*"; "$@"; local c=$?; printf '[exit %d]\n' "$c"; return 0; }
start() {
    "$R" web > "$D/web.out" 2>&1 < /dev/null & WEB=$!
    "$R" worker > "$D/worker.out" 2>&1 < /dev/null & WORKER=$!
    for _ in $(seq 1 60); do curl -s -m 2 "$B/api/health" > /dev/null && break; sleep 1; done
    echo "web pid=$WEB worker pid=$WORKER"
}
stop() { kill -TERM "$WEB" "$WORKER"; wait "$WEB"; echo "web exit=$?"; wait "$WORKER"; echo "worker exit=$?"; }
api() { curl -s -m 10 -b "$D/cj" -c "$D/cj" -H "Origin: $B" -H 'Content-Type: application/json' "$@"; echo; }

mkdir -p "$HOME/.config/rdp"
cat > "$HOME/.config/rdp/config.toml" <<EOF
nav_root = "$D/nav"
[web]
host = "127.0.0.1"
port = 8613
[jobs]
gpus = []
EOF

step "1. 安装旧提交 $OLD（--no-systemd）"
run bash "$WT/scripts/install.sh" --commit "$OLD" --no-systemd > "$D/install.log" 2>&1
tail -6 "$D/install.log"
R=$HOME/.local/opt/rdp/.venv/bin/rdp
run "$R" --version
run "$REAL_HOME/.local/share/uv/python/cpython-3.12.15-linux-x86_64-gnu/bin/python3" -I "$AS/feedpw.py" 'Admin-pass-2026!' "$R" create-admin admin 管理员

step "2. 起服务，提交一个长作业（100 步 × 500 毫秒）"
start
api -d '{"login_name":"admin","password":"Admin-pass-2026!"}' "$B/api/auth/login" | head -c 120; echo
JOB=$(api -d '{"type_name":"example_count","parameters":{"steps":100,"interval_ms":500}}' "$B/api/jobs" | grep -o '"job_id":"[0-9]*"' | grep -o '[0-9]\+'); echo "长作业 job_id=$JOB"
sleep 4
run "$R" status --active-jobs

step "3. 有运行中作业时升级（服务未停）：应停下并提示"
run bash "$WT/scripts/upgrade.sh" --commit "$NEW" --no-systemd --yes
run "$R" --version

step "4. 取消作业、停服务后升级"
api -X POST "$B/api/jobs/$JOB/cancel" | head -c 160; echo
for _ in $(seq 1 30); do s=$(api "$B/api/jobs/$JOB" | grep -o '"state":"[a-z_]*"' | head -1); echo "$s"; [[ $s == *cancelled* ]] && break; sleep 1; done
stop
run "$R" status --active-jobs
run bash "$WT/scripts/upgrade.sh" --commit "$NEW" --no-systemd --yes

step "5. 升级后核对"
run "$R" --version
run cat "$HOME/.local/opt/rdp/rdp-build.json"
run "$R" migrate
start
api -d '{"login_name":"admin","password":"Admin-pass-2026!"}' "$B/api/auth/login" > /dev/null
api "$B/api/version"
api "$B/api/jobs/$JOB" | grep -o '"state":"[a-z_]*"\|"platform_version":"[^"]*"'
stop

step "6. 清理部署 worktree"
run git -C "$WT" worktree remove --force "$HOME/.local/opt/rdp"
