#!/usr/bin/env bash
# 第 03 张浏览器演练：在探针工作目录里起 Web 和 worker（空导航层、端口 8633、独立 HOME），
# 用无头 Chrome 走"登录 → 下载页填表 → 高级参数展开 → 提交预览 → 显示诊断 → 暂存区 → token 设置"并截图。
# 只对 hf-mirror.com 发探测请求（预览作业）；不提交真正的下载作业。dataset1 在演练配置里登记为可写，
# 只为让表单能选到目标根；预览只读，不写盘（跑前跑后比对两块盘写入扇区数）。
set -uo pipefail
WT=${1:?probe worktree}
AS=/home/shawn/桌面/robot-data-platform/.scratch/m2-downloads/assets/03-download-page
FEED=/home/shawn/桌面/robot-data-platform/.scratch/m0-foundation/assets/11-ops-entry-systemd/feedpw.py
W=$HOME/.cache/rdp-drill/m2-03
REAL_HOME=$HOME; PY=$WT/.venv/bin/python
rm -rf "$W"; mkdir -p "$W/nav/按任务" "$W/nav/按格式" "$W/home/.config/rdp"
(cd "$WT/src/web" && node_modules/.bin/vite build > /dev/null 2>&1) || { echo "前端构建失败"; exit 1; }
awk '{print $7}' /sys/block/sda/stat /sys/block/sdb/stat > "$W/writes-before.txt"
export HOME=$W/home
B=http://127.0.0.1:8633
cat > "$HOME/.config/rdp/config.toml" <<CFG
nav_root = "$W/nav"
[web]
host = "127.0.0.1"
port = 8633
[jobs]
gpus = []
aria2c_path = "/home/shawn/miniconda3/bin/aria2c"
[[storage_roots]]
name = "dataset1"
path = "/mnt/dataset1"
uuid = "2d3a48d6-3785-47fe-8c8f-a20857fdc41a"
writable = true
CFG
"$PY" -m rdp migrate | tail -1
"$REAL_HOME/.local/share/uv/python/cpython-3.12.15-linux-x86_64-gnu/bin/python3" -I "$FEED" 'Admin-pass-2026!' "$PY" -m rdp create-admin admin 管理员 | tail -1
"$PY" -m rdp web > "$W/web.out" 2>&1 < /dev/null & WEB=$!
"$PY" -m rdp worker > "$W/worker.out" 2>&1 < /dev/null & WORKER=$!
for _ in $(seq 1 60); do curl -s -m 2 "$B/api/health" > /dev/null && break; sleep 1; done
"$REAL_HOME/.local/bin/node" "$AS/browser-drill.mjs" "$B" "$AS/drill"; echo "[node exit $?]"
sqlite3 "file:$HOME/.local/share/rdp/rdp.sqlite3?mode=ro" "select log_id, actor_name, operation, object_kind, result from operation_logs order by log_id;"
grep -c "hf_token_drill_secret" "$W/web.out" "$W/worker.out" $HOME/.local/share/rdp/logs/*.log 2>/dev/null | sed 's/^/token 明文出现次数 /'
kill -TERM "$WEB" "$WORKER"; wait "$WEB"; wait "$WORKER"
rm -rf "$WT/src/web/dist"
awk '{print $7}' /sys/block/sda/stat /sys/block/sdb/stat | paste "$W/writes-before.txt" - | sed 's/^/写入扇区 前后 /'
grep -c ERROR "$HOME/.local/share/rdp/logs/worker.log" | sed 's/^/worker.log ERROR /'
