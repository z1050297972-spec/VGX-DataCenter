#!/usr/bin/env bash
# 第 11 张升级入口：在同一部署 worktree 更新提交；失败保持服务停止，不自动降级数据库。
set -euo pipefail
# 共用安装脚本的构建、单元渲染与参数处理；source不会执行安装main。
source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)/install.sh"

# 帮助输出是手册的参数与失败处理依据，只维护这一份文字。
usage() {
    cat <<'HELP'
用法：bash scripts/upgrade.sh [--deploy-dir DIR] [--commit REF] [--no-systemd] [--yes] [--help]
--deploy-dir：默认 $HOME/.local/opt/rdp；必须是安装脚本创建的独立、干净 worktree。
--help：显示帮助后退出，不修改部署或服务。
--commit：默认本地 main；解析完整提交号，不联网更新仓库。
--yes：跳过有明确旧/新提交摘要的终端确认；不跳过运行中作业或服务停止检查。
--no-systemd：操作者须先在前台终端停止 Web 和 worker；脚本不复制单元、不调用 systemctl，
通过 worker.lock 与配置端口双重检查拒绝仍在运行的实例，不按进程名杀进程。
完成后分别在两个终端运行：
  <部署目录>/.venv/bin/rdp web
  <部署目录>/.venv/bin/rdp worker
前台运行及重试时保持 HOME/RDP_CONFIG 一致。
默认模式先查作业，确认后停 Web/worker，再更新、构建、迁移、启动。
失败保留备份和当前部署，明确旧/新提交及失败步骤；已停止的服务不会自动重启。
停止命令失败时请人工核实服务状态。构建或迁移失败后保持停机，先处理日志中的原因和备份；
若版本闸门阻止再次预检，须人工完成迁移或匹配代码与数据库版本，不得跳过活跃作业检查。
原单元的 RDP_CONFIG 会沿用；终端配置冲突会拒绝升级。无法解析的环境指令须人工核实。
若预检发现遗留 running/cancelling，先用旧版本启动恢复并处理到空闲，不跳过检查。
HELP
}

# 校验目录是本仓库登记的独立 worktree、无本地源码改动；构建信息文件属于部署产物。
# 检查 uv/pnpm/git 与目标提交都可用；拒绝开发目录、相对路径和控制字符，不丢弃用户改动。
validate_inputs() {
    _check_absolute "$deploy_dir"
    [[ -d $deploy_dir && ! -L $deploy_dir ]] || _die '部署必须是已存在的独立 worktree 目录'
    deploy_dir=$(readlink -m -- "$deploy_dir")
    _resolve_release
    _check_registered_worktree
    _check_clean_worktree
    _inherit_configuration
    [[ -x $deploy_dir/.venv/bin/rdp && -f $deploy_dir/rdp-build.json ]] || _die '部署缺少旧 rdp 或构建信息；请核实安装目录'
    old_commit=$(git -C "$deploy_dir" rev-parse HEAD)
}

# 必须使用当前部署的旧 .venv/bin/rdp status --active-jobs。
# 0 才继续；3 为有运行中/正在取消的作业，立即提示并停止；1/2/其他非零均视为检查失败。
# 不能用 “if 查询失败则当作无作业”；此阶段不停止服务、不更新提交。
check_active_jobs() {
    local code
    if "$deploy_dir/.venv/bin/rdp" status --active-jobs; then return; else code=$?; fi
    if ((code == 3)); then
        _die '仍有运行中或正在取消的作业；保持当前服务状态，用旧版本恢复并处理至空闲后重试'
    fi
    _die "活跃作业检查失败（退出码 $code），无法确认空闲，拒绝升级"
}

# 展示旧/新提交、部署目录和停机影响；交互确认或 --yes 授权后才继续，拒绝/EOF 返回非零。
# 无作业检查与停机之间仍可能领新作业，所以停机后必须用旧程序再检查一次。
confirm_upgrade() {
    local answer
    printf '部署：%s\n旧提交：%s\n新提交：%s\n将停止 Web 和 worker；失败不自动回滚。\n' "$deploy_dir" "$old_commit" "$target_commit"
    if $assume_yes; then return; fi
    printf '确认升级？输入 y 继续：'
    IFS= read -r answer || _die '未收到确认，取消升级'
    [[ $answer == y || $answer == Y ]] || _die '已取消升级'
}

# 默认模式先停止 rdp-web.service，再停止 rdp-worker.service，确认两者 inactive。
# 任何失败都不得 checkout 或 migrate；不接触其他单元，不以 force/kill 绕过正常停机。
# --no-systemd 用旧 rdp status --worker-stopped 和 --check-port 检查锁与端口确实空闲，
# 仍活跃则拒绝并提示在前台停止；检查不能阻止外部再次手动启动，维护期间禁止并行启动。
# 停机后再次查 active-jobs；发现竞态留下的运行中记录则保持停止并提示旧版本恢复处理。
stop_and_recheck() {
    if $no_systemd; then
        stage='检查前台 worker 停止'
        "$deploy_dir/.venv/bin/rdp" status --worker-stopped || _die '请先在前台终端停止 worker，维护期间禁止并行启动'
        stage='检查前台 Web 停止'
        "$deploy_dir/.venv/bin/rdp" status --check-port || _die '请先在前台终端停止 Web，并检查配置 web.port'
    else
        stage='停止 Web'
        systemctl --user stop rdp-web.service
        stage='停止 worker'
        systemctl --user stop rdp-worker.service
        stage='核实服务停止'
        _service_state rdp-web.service inactive
        _service_state rdp-worker.service inactive
    fi
    stage='停机后二次检查活跃作业'
    check_active_jobs
}

# 两服务已停且二次检查通过，才在部署 worktree git checkout --detach <完整提交>。
# uv sync --frozen → src/web/pnpm install --frozen-lockfile → pnpm exec vite build →
# 原子写 rdp-build.json → 新 .venv/bin/rdp migrate；不 reset --hard，不修改开发目录。
# 任一步失败立即退出；保留迁移备份/构建现场，不启动服务、不自动回滚数据库或源码。
update_and_migrate() {
    stage='更新部署提交'
    git -C "$deploy_dir" checkout --detach "$target_commit"
    build_release
    stage='数据库迁移'
    "$deploy_dir/.venv/bin/rdp" migrate
}

# 默认模式刷新本项目两个模板并 daemon-reload，先启动 worker 再启动 Web，确认启动成功。
# 原单元有 RDP_CONFIG 时须沿用该配置做预检/迁移并保留 Environment；若当前终端指定不同配置，
# 拒绝升级并说明差异，不让旧服务、状态查询和新迁移指向不同数据库。
# 启动部分失败停止已启动的本项目服务，防止把半成功当完成；不触碰无关单元。
# --no-systemd 只给出前台命令。成功输出新 rdp --version；不得只因 checkout 成功就报告完成。
start_services() {
    if $no_systemd; then _foreground_commands; return; fi
    _write_units
    stage='重载用户单元'
    systemctl --user daemon-reload
    stage='启动 worker'
    cleanup_services=true
    systemctl --user start rdp-worker.service
    _service_state rdp-worker.service active
    stage='启动 Web'
    systemctl --user start rdp-web.service
    _service_state rdp-web.service active
}

# 顺序：校验 → 查活跃作业 → 确认 → 停两个服务 → 二次查作业 → 更新/构建/版本/迁移 → 启动。
main() {
    operation=upgrade
    deploy_dir=${HOME}/.local/opt/rdp
    commit_ref=main
    no_systemd=false
    assume_yes=false
    _parse_arguments "$@"
    _initialize
    validate_inputs
    stage='停机前检查活跃作业'
    check_active_jobs
    stage='确认升级'
    confirm_upgrade
    stop_and_recheck
    update_and_migrate
    start_services
    stage='核对升级版本'
    "$deploy_dir/.venv/bin/rdp" --version
    printf '升级完成：%s\n' "$deploy_dir"
    cleanup_services=false
}

# 查询命令失败同样终止；不把未知、failed或activating状态猜成已停止/已启动。
_service_state() {
    local actual
    actual=$(systemctl --user show --property=ActiveState --value "$1")
    [[ $actual == "$2" ]] || _die "服务 $1 状态为 $actual，期望 $2；请人工检查"
}

# NUL分隔避免中文、空格和引号影响登记匹配；先完整读取并确认git成功，不能把查询失败当空列表。
_check_registered_worktree() {
    local field first='' selected=false registered=false
    worktree_temp=$(mktemp)
    git -C "$source_root" worktree list --porcelain -z > "$worktree_temp"
    while IFS= read -r -d '' field; do
        if [[ $field == 'worktree '* ]]; then
            if [[ -z $first ]]; then first=${field#worktree }; fi
            selected=false
            if [[ ${field#worktree } == "$deploy_dir" ]]; then selected=true; fi
        elif [[ $field == detached ]] && $selected; then
            registered=true
        fi
    done < "$worktree_temp"
    rm -f -- "$worktree_temp"
    worktree_temp=''
    [[ $first != "$deploy_dir" ]] && $registered || _die '拒绝开发目录或未登记的 detached worktree'
}

# 只豁免唯一已知的未跟踪构建产物；源码、重命名和其他未跟踪文件都不能被升级覆盖。
_check_clean_worktree() {
    local change
    worktree_temp=$(mktemp)
    git -C "$deploy_dir" status --porcelain --untracked-files=all -z > "$worktree_temp"
    while IFS= read -r -d '' change; do
        [[ $change == '?? rdp-build.json' ]] || _die '部署 worktree 有本地改动；请先人工处理，升级不会丢弃修改'
    done < "$worktree_temp"
    rm -f -- "$worktree_temp"
    worktree_temp=''
}

# 在任何旧rdp调用前确定配置，避免状态检查与新版本迁移落到不同数据库。
_inherit_configuration() {
    local unit_dir=$HOME/.config/systemd/user name configured
    local -a values=()
    if [[ ! -e $unit_dir/rdp-web.service && ! -e $unit_dir/rdp-worker.service ]]; then return; fi
    for name in rdp-web.service rdp-worker.service; do
        [[ -f $unit_dir/$name ]] || _die '原用户单元不完整，无法确认配置一致性'
        configured=$(_read_unit_config "$unit_dir/$name")
        values+=("$configured")
    done
    [[ ${values[0]} == "${values[1]}" ]] || _die '两个原单元的 RDP_CONFIG 不一致，拒绝升级'
    configured=${values[0]}
    if [[ -n ${RDP_CONFIG:-} && $RDP_CONFIG != "$configured" ]]; then
        _die "终端 RDP_CONFIG 与原单元不一致：终端=$RDP_CONFIG；原单元=${configured:-默认配置}"
    fi
    if [[ -n $configured ]]; then
        _check_absolute "$configured"
        export RDP_CONFIG=$configured
    else
        unset RDP_CONFIG
    fi
}

# 只解析本项目生成的单一Environment赋值；不能可靠解释的配置拒绝，绝不source/eval单元内容。
_read_unit_config() {
    local line value='' found=false service=false
    [[ -r $1 ]] || _die '原用户单元不可读，无法确认配置'
    while IFS= read -r line || [[ -n $line ]]; do
        line=${line#"${line%%[![:space:]]*}"}
        if [[ $line == '[Service]' ]]; then service=true; continue; fi
        if [[ $line == '['* ]]; then service=false; fi
        if ! $service; then continue; fi
        if [[ $line == EnvironmentFile=* ]]; then _die '原单元使用 EnvironmentFile，无法确认 RDP_CONFIG；请人工核实'; fi
        if [[ $line == Environment=* ]]; then
            [[ $line == 'Environment="RDP_CONFIG='*'"' ]] && ! $found || _die '原单元环境指令无法唯一解析，拒绝升级'
            value=${line#'Environment="RDP_CONFIG='}
            value=${value%\"}
            # 命令替换默认不继承errexit，必须显式传播解码失败，不能当成默认配置。
            value=$(_decode_unit_value "$value") || return "$?"
            found=true
        fi
    done < "$1" || return "$?"
    printf '%s' "$value"
}

# 只逆转安装器写出的转义，不使用shell或systemd变量展开。
_decode_unit_value() {
    local value=$1 output='' char next index=0
    while ((index < ${#value})); do
        char=${value:index:1}
        [[ $char != '"' ]] || _die '原单元含未转义的引号，无法确认配置路径'
        if [[ $char == '\' || $char == '%' ]]; then
            index=$((index + 1))
            next=${value:index:1}
            if [[ $char == '\' ]]; then
                [[ $next == '\' || $next == '"' ]] || _die '原单元存在无法解析的转义'
            else
                [[ $next == '%' ]] || _die '原单元存在动态specifier，无法确认配置路径'
            fi
            char=$next
        fi
        output+=$char
        index=$((index + 1))
    done
    printf '%s' "$output"
}

main "$@"
