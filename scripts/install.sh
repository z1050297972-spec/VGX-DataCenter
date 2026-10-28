#!/usr/bin/env bash
# 第 11 张安装入口：只部署本仓库提交，不配置用户账号、系统 linger 或真实数据目录。
# 任一外部步骤失败立即停止，不安装/启动半成品；错误处理不得自动删除用户已有路径。
set -euo pipefail

# --help 文本：
# 用法：bash scripts/install.sh [--deploy-dir DIR] [--commit REF] [--no-systemd] [--help]
# --deploy-dir：默认 $HOME/.local/opt/rdp；必须是不存在的绝对目录，允许中文和空格。
# --commit：默认本地 main；解析为完整提交号，不 fetch、不 pull。相对调用目录不参与布局推导。
# --no-systemd：只构建、迁移、查端口，不复制单元，不调用 systemctl；完成后输出以下前台命令：
#   <部署目录>/.venv/bin/rdp create-admin <登录名> <显示名>
#   <部署目录>/.venv/bin/rdp web
#   <部署目录>/.venv/bin/rdp worker
# 两个服务在不同终端运行；临时 HOME 演练必须保持 HOME/RDP_CONFIG 一致。
# 默认模式复制本项目两个用户单元并 enable --now；不更改 linger，不操作无关单元。
# 先准备好 uv、pnpm、git；脚本不安装这些工具。配置只走 RDP_CONFIG/load_config。
# 失败保留已建 worktree 和构建产物并输出失败阶段；不误报成功，不自动启动服务。
usage() {
    :
}

# 先解析 --help/参数，再由脚本自身路径定位源码仓库。
# 校验外部命令、目录和本地提交，拒绝当前源码目录、已有目录、路径换行/控制字符。
# 任何失败发生在 git worktree add 之前；部署目录和提交都不得被当成命令执行。
validate_inputs() {
    :
}

# git worktree add --detach <部署目录> <完整提交>；不 checkout 开发工作区。
# 目录切换后清除继承的 VIRTUAL_ENV，确保 uv 不使用开发环境；任一步失败保留失败目录。
create_deployment() {
    :
}

# 在部署目录 uv sync --frozen；在 src/web 运行 pnpm install --frozen-lockfile、pnpm exec vite build。
# 只在两项构建成功后把完整提交写入 rdp-build.json：UTF-8 JSON，仅 commit 字段，原子替换。
# 失败删除本次临时构建信息文件，保留旧文件；绝不运行迁移或启动后续步骤。
build_release() {
    :
}

# 用部署目录自己的 .venv/bin/rdp migrate，随后 rdp status --check-port。
# 端口检查读取最终配置，不写死 8600；非零立即退出，提示配置来源和 web.port。
# 迁移失败保留迁移入口的备份，不自动恢复；端口冲突不得继续复制/启用服务。
migrate_and_check_port() {
    :
}

# 仅默认模式：把模板里的 @DEPLOY_DIR@ 换成部署目录，写到 $HOME/.config/systemd/user/。
# 保留模板的双引号，对反斜线、双引号、百分号作 systemd 语法转义；不使用 shell eval。
# 调用环境显式给了 RDP_CONFIG 时，把同一配置路径作为 Environment 指令写入两个单元；
# 未设置时不写该指令，沿用用户默认配置。不能假定 systemd 用户管理器继承当前终端的环境。
# 原子写入 rdp-web.service/rdp-worker.service，不枚举删除其他单元，不写死用户名。
# daemon-reload 后 enable --now 两个明确单元；失败报明阶段，停止已启动的本项目服务，
# 保留部署与单元供排查；不停止、启用或覆盖 egopro-restore.service 等无关单元。
install_units() {
    :
}

# 顺序：参数校验 → 独立 worktree → 构建和版本文件 → 迁移 → 端口检查 → 可选安装单元。
# --no-systemd 全路径跳过所有 systemctl；只输出前台用法，不后台运行服务。
main() {
    :
}

# 无可执行部署体时明确失败，防止被自动化当作已安装成功。
exit 78
