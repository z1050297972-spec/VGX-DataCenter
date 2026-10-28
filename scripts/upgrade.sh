#!/usr/bin/env bash
# 第 11 张升级入口：在同一部署 worktree 更新提交；失败保持服务停止，不自动降级数据库。
set -euo pipefail

# --help 文本：
# 用法：bash scripts/upgrade.sh [--deploy-dir DIR] [--commit REF] [--no-systemd] [--yes] [--help]
# --deploy-dir：默认 $HOME/.local/opt/rdp；必须是安装脚本创建的独立、干净 worktree。
# --commit：默认本地 main；解析完整提交号，不联网更新仓库。
# --yes：跳过有明确旧/新提交摘要的终端确认；不跳过运行中作业或服务停止检查。
# --no-systemd：操作者须先在前台终端停止 Web 和 worker；脚本不复制单元、不调用 systemctl，
# 通过 worker.lock 与配置端口双重检查拒绝仍在运行的实例，不按进程名杀进程。
# 完成后输出 <部署目录>/.venv/bin/rdp web 和 worker，操作者分别前台启动。
# 默认模式先查作业，确认后停 Web/worker，再更新、构建、迁移、启动。
# 失败保留备份和当前部署，明确旧/新提交及失败步骤；服务保持停止，人工处理后重试。
# 若预检发现遗留 running/cancelling，先用旧版本启动恢复并处理到空闲，不跳过检查。
usage() {
    :
}

# 校验目录是本仓库登记的独立 worktree、无本地源码改动；构建信息文件属于部署产物。
# 检查 uv/pnpm/git 与目标提交都可用；拒绝开发目录、相对路径和控制字符，不丢弃用户改动。
validate_inputs() {
    :
}

# 必须使用当前部署的旧 .venv/bin/rdp status --active-jobs。
# 0 才继续；3 为有运行中/正在取消的作业，立即提示并停止；1/2/其他非零均视为检查失败。
# 不能用 “if 查询失败则当作无作业”；此阶段不停止服务、不更新提交。
check_active_jobs() {
    :
}

# 展示旧/新提交、部署目录和停机影响；交互确认或 --yes 授权后才继续，拒绝/EOF 返回非零。
# 无作业检查与停机之间仍可能领新作业，所以停机后必须用旧程序再检查一次。
confirm_upgrade() {
    :
}

# 默认模式先停止 rdp-web.service，再停止 rdp-worker.service，确认两者 inactive。
# 任何失败都不得 checkout 或 migrate；不接触其他单元，不以 force/kill 绕过正常停机。
# --no-systemd 用旧 rdp status --worker-stopped 和 --check-port 检查锁与端口确实空闲，
# 仍活跃则拒绝并提示在前台停止；检查不能阻止外部再次手动启动，维护期间禁止并行启动。
# 停机后再次查 active-jobs；发现竞态留下的运行中记录则保持停止并提示旧版本恢复处理。
stop_and_recheck() {
    :
}

# 两服务已停且二次检查通过，才在部署 worktree git checkout --detach <完整提交>。
# uv sync --frozen → src/web/pnpm install --frozen-lockfile → pnpm exec vite build →
# 原子写 rdp-build.json → 新 .venv/bin/rdp migrate；不 reset --hard，不修改开发目录。
# 任一步失败立即退出；保留迁移备份/构建现场，不启动服务、不自动回滚数据库或源码。
update_and_migrate() {
    :
}

# 默认模式刷新本项目两个模板并 daemon-reload，先启动 worker 再启动 Web，确认启动成功。
# 原单元有 RDP_CONFIG 时须沿用该配置做预检/迁移并保留 Environment；若当前终端指定不同配置，
# 拒绝升级并说明差异，不让旧服务、状态查询和新迁移指向不同数据库。
# 启动部分失败停止已启动的本项目服务，防止把半成功当完成；不触碰无关单元。
# --no-systemd 只给出前台命令。成功输出新 rdp --version；不得只因 checkout 成功就报告完成。
start_services() {
    :
}

# 顺序：校验 → 查活跃作业 → 确认 → 停两个服务 → 二次查作业 → 更新/构建/版本/迁移 → 启动。
main() {
    :
}

# 无可执行升级体时明确失败，防止被自动化当作已升级成功。
exit 78
