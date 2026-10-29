#!/usr/bin/env bash
# 验收 9：临时 HOME 下用一键脚本从零装起（--no-systemd），联网把 Node、uv、pnpm 装进临时 HOME。
# 用法：bash drill9.sh <含一键脚本的提交>
# PATH 去掉本机用户目录里的 node/uv/pnpm，迫使脚本自己安装；Python 和项目依赖复用本机 uv/pnpm 缓存（不重复下载）。
set -uo pipefail
COMMIT=$1
WT=/home/shawn/桌面/robot-data-platform.wt/m0-11-ops-entry-systemd
AS=/home/shawn/桌面/robot-data-platform/.scratch/m0-foundation/assets/11-ops-entry-systemd
D=$HOME/.cache/rdp-dispatch/m0-11/drill9
OUT=$AS/drill9
REAL_HOME=$HOME
NODE=$REAL_HOME/.local/bin/node
rm -rf "$D" "$OUT"; mkdir -p "$D/home" "$D/nav" "$OUT"
export UV_CACHE_DIR=$REAL_HOME/.cache/uv UV_PYTHON_INSTALL_DIR=$REAL_HOME/.local/share/uv/python
export npm_config_store_dir=$REAL_HOME/.local/share/pnpm/store
export HOME=$D/home
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
unset RDP_CONFIG VIRTUAL_ENV
cd "$HOME"
step() { printf '\n===== %s =====\n' "$1"; }
run() { printf '$ %s\n' "$*"; "$@"; local c=$?; printf '[exit %d]\n' "$c"; return 0; }

step "0. 起点：临时 HOME 里没有工具和配置；PATH 上的 node 版本"
run ls -la "$HOME"
run command -v node uv pnpm
run node --version

step "1. 帮助"
run bash "$WT/scripts/setup.sh" --help

step "2. 一键安装（问答由 drill9-driver.py 在 pty 里回答；--yes 同意下载工具）"
export DRILL_BROWSER="$NODE $AS/drill11.mjs http://127.0.0.1:8614 $OUT"
python3 -I "$AS/drill9-driver.py" "$D/setup-tty.log" "$D/nav" 8614 'Admin-pass-2026!' -- \
    bash "$WT/scripts/setup.sh" --commit "$COMMIT" --yes --no-systemd
cat "$D/setup-tty.log"

step "3. 装好的工具"
run ls -la "$HOME/.local/bin"
run find "$HOME/.local/opt/rdp-tools" -maxdepth 3
for t in node uv pnpm; do run "$HOME/.local/bin/$t" --version; done

step "4. 生成的配置"
run stat -c '%a %n' "$HOME/.config/rdp/config.toml"
run cat "$HOME/.config/rdp/config.toml"

step "5. 日志"
run ls -la "$HOME/.local/share/rdp/logs"
run grep -E '开始运行|结束|ERROR|Traceback' "$HOME/.local/share/rdp/logs/web.log"
run cat "$HOME/.local/share/rdp/logs/worker.log"

step "6. 重复运行：应只报告状态和升级命令"
PATH=$HOME/.local/bin:$PATH run bash "$WT/scripts/setup.sh" --commit "$COMMIT" --yes --no-systemd

step "7. 无终端、无配置：应报错退出 2，不卡住"
HOME=$D/home2 run timeout 120 bash "$WT/scripts/setup.sh" --commit "$COMMIT" --yes --no-systemd < /dev/null

step "8. 清理部署 worktree"
run git -C "$WT" worktree remove --force "$HOME/.local/opt/rdp"
