#!/usr/bin/env bash
# 验收 5：临时 HOME 下按安装脚本从零安装（--no-systemd），跑通全过程。
# 用法：bash drill11.sh <实现所在提交或分支>
# 只写临时目录 $D；Python/前端依赖复用本机已有缓存（不改真实 HOME 下的配置和状态）。
set -uo pipefail
COMMIT=$1
WT=/home/shawn/桌面/robot-data-platform.wt/m0-11-ops-entry-systemd
AS=/home/shawn/桌面/robot-data-platform/.scratch/m0-foundation/assets/11-ops-entry-systemd
D=$HOME/.cache/rdp-dispatch/m0-11/drill
OUT=$AS/drill
REAL_HOME=$HOME
rm -rf "$D" "$OUT"; mkdir -p "$D/home" "$D/nav" "$OUT"
export UV_CACHE_DIR=$REAL_HOME/.cache/uv UV_PYTHON_INSTALL_DIR=$REAL_HOME/.local/share/uv/python
export npm_config_store_dir=$REAL_HOME/.local/share/pnpm/store
export HOME=$D/home
cd "$HOME"

step() { printf '\n===== %s =====\n' "$1"; }
run() { printf '$ %s\n' "$*"; "$@"; local c=$?; printf '[exit %d]\n' "$c"; return 0; }

step "0. 配置（按运维手册的配置示例，端口改 8612 避免占用正式 8600）"
mkdir -p "$HOME/.config/rdp"
cat > "$HOME/.config/rdp/config.toml" <<EOF
state_dir = "~/.local/share/rdp"
nav_root = "$D/nav"

[web]
host = "127.0.0.1"
port = 8612

[jobs]
gpus = [0, 1]

[[storage_roots]]
name = "dataset1"
path = "/mnt/dataset1"
uuid = "2d3a48d6-3785-47fe-8c8f-a20857fdc41a"

[[storage_roots]]
name = "dataset2"
path = "/mnt/dataset2"
uuid = "35445b14-9e83-4f74-ac73-1551e3db6d63"
EOF
cat "$HOME/.config/rdp/config.toml"

step "1. 安装脚本帮助"
run bash "$WT/scripts/install.sh" --help

step "2. 从零安装（--no-systemd）"
run bash "$WT/scripts/install.sh" --commit "$COMMIT" --no-systemd
R=$HOME/.local/opt/rdp/.venv/bin/rdp
run cat "$HOME/.local/opt/rdp/rdp-build.json"

step "3. 版本与状态查询"
run "$R" --version
run "$R" status --active-jobs
run "$R" status --worker-stopped
run "$R" status --check-port

step "4. 创建首个管理员（口令从终端输入）"
run "$REAL_HOME/.local/share/uv/python/cpython-3.12.15-linux-x86_64-gnu/bin/python3" -I "$AS/feedpw.py" 'Admin-pass-2026!' "$R" create-admin admin 管理员

step "5. 前台起 Web 和 worker"
"$R" web > "$D/web.stdout" 2> "$D/web.stderr" < /dev/null & WEB=$!
"$R" worker > "$D/worker.stdout" 2> "$D/worker.stderr" < /dev/null & WORKER=$!
echo "web pid=$WEB worker pid=$WORKER"
for _ in $(seq 1 60); do curl -s -m 2 http://127.0.0.1:8612/api/health && break; sleep 1; done; echo
run "$R" status --worker-stopped
run "$R" status --check-port

step "6. 浏览器全过程（登录 → 建成员 → 成员改口令 → 提交示例作业看它完成 → 日志 → 存储根）"
run node "$AS/drill11.mjs" http://127.0.0.1:8612 "$OUT"

step "7. 停止两个服务（SIGTERM）"
kill -TERM "$WEB" "$WORKER"
wait "$WEB"; echo "web exit=$?"
wait "$WORKER"; echo "worker exit=$?"
run "$R" status --worker-stopped

step "8. 日志文件"
run ls -la "$HOME/.local/share/rdp/logs"
run grep -E 'uvicorn|Web|worker|平台' "$HOME/.local/share/rdp/logs/web.log"
run cat "$HOME/.local/share/rdp/logs/worker.log"
echo "web.log 中访问日志行数：$(grep -cE '"(GET|POST) ' "$HOME/.local/share/rdp/logs/web.log")"

step "9. 清理部署 worktree（临时目录保留到负责人验收）"
run git -C "$WT" worktree remove --force "$HOME/.local/opt/rdp"
run git -C "$WT" worktree list
