#!/usr/bin/env bash
# 第 11 张安装入口：只部署本仓库提交，不配置用户账号、系统 linger 或真实数据目录。
# 任一外部步骤失败立即停止，不安装/启动半成品；错误处理不得自动删除用户已有路径。
set -euo pipefail

# 帮助输出是手册的参数与失败处理依据，只维护这一份文字。
usage() {
    cat <<'HELP'
用法：bash scripts/install.sh [--deploy-dir DIR] [--commit REF] [--no-systemd] [--help]
--deploy-dir：默认 $HOME/.local/opt/rdp；必须是不存在的绝对目录，允许中文和空格。
--help：显示帮助后退出，不修改部署或服务。
--commit：默认本地 main；解析为完整提交号，不 fetch、不 pull。相对调用目录不参与布局推导。
--no-systemd：只构建、迁移、查端口，不复制单元，不调用 systemctl；完成后输出以下前台命令：
  <部署目录>/.venv/bin/rdp create-admin <登录名> <显示名>
  <部署目录>/.venv/bin/rdp web
  <部署目录>/.venv/bin/rdp worker
两个服务在不同终端运行；临时 HOME 演练必须保持 HOME/RDP_CONFIG 一致。
默认模式复制本项目两个用户单元并 enable --now；不更改 linger，不操作无关单元。
先准备好 uv、pnpm、git；脚本不安装这些工具。配置只走 RDP_CONFIG/load_config。
失败保留已建 worktree、构建产物和迁移备份，并输出失败阶段；不自动恢复数据库。
已有部署目录不能直接重新安装：先检查失败现场，可改用新目录重试；
只有人工确认目录无须保留后，才由操作者清理该 worktree。部分启动失败会停止本项目两个服务。
HELP
}

# 先解析 --help/参数，再由脚本自身路径定位源码仓库。
# 校验外部命令、目录和本地提交，拒绝当前源码目录、已有目录、路径换行/控制字符。
# 任何失败发生在 git worktree add 之前；部署目录和提交都不得被当成命令执行。
validate_inputs() {
    _check_absolute "$deploy_dir"
    [[ ! -e $deploy_dir && ! -L $deploy_dir ]] || _die '部署目录已存在；保留原目录，改用新的绝对目录'
    deploy_dir=$(readlink -m -- "$deploy_dir")
    _resolve_release
}

# 两入口共用依赖和本地提交解析，避免安装与升级选择不同的仓库或引用规则。
_resolve_release() {
    local scripts_root
    for tool in git uv pnpm; do command -v "$tool" >/dev/null || _die "缺少工具：$tool"; done
    if ! $no_systemd; then command -v systemctl >/dev/null || _die '缺少 systemctl'; fi
    scripts_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
    source_root=$(git -C "$scripts_root" rev-parse --show-toplevel)
    target_commit=$(git -C "$source_root" rev-parse --verify --end-of-options "${commit_ref}^{commit}")
    [[ $target_commit =~ ^([0-9a-f]{40}|[0-9a-f]{64})$ ]] || _die '目标不是完整提交号'
}

# git worktree add --detach <部署目录> <完整提交>；不 checkout 开发工作区。
# 目录切换后清除继承的 VIRTUAL_ENV，确保 uv 不使用开发环境；任一步失败保留失败目录。
create_deployment() {
    git -C "$source_root" worktree add --detach -- "$deploy_dir" "$target_commit"
}

# 在部署目录 uv sync --frozen；在 src/web 运行 pnpm install --frozen-lockfile、pnpm exec vite build。
# 只在两项构建成功后把完整提交写入 rdp-build.json：UTF-8 JSON，仅 commit 字段，原子替换。
# 失败删除本次临时构建信息文件，保留旧文件；绝不运行迁移或启动后续步骤。
build_release() {
    # uv默认识别当前项目，但显式清理开发环境，避免外部工具误用继承环境。
    unset VIRTUAL_ENV
    stage='uv 构建'
    (cd -- "$deploy_dir" && uv sync --frozen)
    stage='前端依赖'
    (cd -- "$deploy_dir/src/web" && pnpm install --frozen-lockfile)
    stage='前端构建'
    (cd -- "$deploy_dir/src/web" && pnpm exec vite build)
    stage='发布构建信息'
    build_temp=$(mktemp "$deploy_dir/.rdp-build.XXXXXX")
    printf '{"commit":"%s"}\n' "$target_commit" > "$build_temp"
    mv -f -- "$build_temp" "$deploy_dir/rdp-build.json"
    build_temp=''
}

# 用部署目录自己的 .venv/bin/rdp migrate，随后 rdp status --check-port。
# 端口检查读取最终配置，不写死 8600；非零立即退出，提示配置来源和 web.port。
# 迁移失败保留迁移入口的备份，不自动恢复；端口冲突不得继续复制/启用服务。
migrate_and_check_port() {
    stage='数据库迁移'
    "$deploy_dir/.venv/bin/rdp" migrate
    stage='端口检查'
    "$deploy_dir/.venv/bin/rdp" status --check-port || _die "端口检查失败；检查配置 ${RDP_CONFIG:-$HOME/.config/rdp/config.toml} 的 web.port，再重试"
}

# 仅默认模式：把模板里的 @DEPLOY_DIR@ 换成部署目录，写到 $HOME/.config/systemd/user/。
# WorkingDirectory按整行路径读取，不加引号且只转义百分号；ExecStart/Environment的双引号值
# 对反斜线、双引号和百分号作systemd转义；不使用shell eval。
# 调用环境显式给了 RDP_CONFIG 时，把同一配置路径作为 Environment 指令写入两个单元；
# 未设置时不写该指令，沿用用户默认配置。不能假定 systemd 用户管理器继承当前终端的环境。
# 原子写入 rdp-web.service/rdp-worker.service，不枚举删除其他单元，不写死用户名。
# daemon-reload 后 enable --now 两个明确单元；失败报明阶段，停止已启动的本项目服务，
# 保留部署与单元供排查；不停止、启用或覆盖 egopro-restore.service 等无关单元。
install_units() {
    _write_units
    stage='重载用户单元'
    systemctl --user daemon-reload
    stage='启用并启动服务'
    cleanup_services=true
    systemctl --user enable --now rdp-worker.service rdp-web.service
}

# 顺序：参数校验 → 独立 worktree → 构建和版本文件 → 迁移 → 端口检查 → 可选安装单元。
# --no-systemd 全路径跳过所有 systemctl；只输出前台用法，不后台运行服务。
main() {
    operation=install
    deploy_dir=${HOME}/.local/opt/rdp
    commit_ref=main
    no_systemd=false
    assume_yes=false
    _parse_arguments "$@"
    _initialize
    validate_inputs
    stage='创建独立 worktree'
    create_deployment
    build_release
    migrate_and_check_port
    if $no_systemd; then _foreground_commands; else install_units; fi
    printf '安装完成：%s\n' "$deploy_dir"
    cleanup_services=false
}

# 用bash的%q输出可复制命令，保持含空格路径和显式配置在前台运行时一致。
_foreground_commands() {
    local command
    printf '请保持相同配置，在不同终端前台运行：\n'
    for command in create-admin web worker; do
        if [[ $command == create-admin && $operation != install ]]; then continue; fi
        printf 'HOME=%q ' "$HOME"
        if [[ -n ${RDP_CONFIG:-} ]]; then printf 'RDP_CONFIG=%q ' "$RDP_CONFIG"; fi
        printf '%q %s' "$deploy_dir/.venv/bin/rdp" "$command"
        if [[ $command == create-admin ]]; then printf ' <登录名> <显示名>'; fi
        printf '\n'
    done
}

# 共用生命周期只清理本次临时文件，不删除部署目录、备份或用户单元。
_initialize() {
    stage='参数与依赖检查'
    target_commit='未解析'
    old_commit='无'
    build_temp=''
    unit_temp=''
    worktree_temp=''
    cleanup_services=false
    trap '_finish "$?"' EXIT
    trap 'exit 130' INT
    trap 'exit 143' TERM
    _check_absolute "$HOME"
    [[ ! $commit_ref =~ [[:cntrl:]] ]] || _die '提交引用不能含控制字符'
    if [[ -n ${RDP_CONFIG:-} ]]; then
        if [[ $RDP_CONFIG == '~' ]]; then RDP_CONFIG=$HOME;
        elif [[ $RDP_CONFIG == '~/'* ]]; then RDP_CONFIG=$HOME/${RDP_CONFIG:2}; fi
        _check_absolute "$RDP_CONFIG"
        export RDP_CONFIG
    fi
}

# 所有用户路径保持单个参数；拒绝控制字符，防止单元指令和终端诊断被注入。
_check_absolute() {
    [[ $1 == /* && ! $1 =~ [[:cntrl:]] ]] || _die '路径必须是无控制字符的绝对路径'
}

_finish() {
    local code=$1 temporary
    for temporary in "$build_temp" "$unit_temp" "$worktree_temp"; do
        if [[ -n $temporary ]]; then
            rm -f -- "$temporary" || printf '临时文件清理失败：%s，请人工核实\n' "$temporary" >&2
        fi
    done
    if ((code != 0)); then
        if $cleanup_services && ! $no_systemd; then
            # 只在尝试启动后收回本项目服务；预检失败不得停止仍正常运行的旧服务。
            local service
            for service in rdp-web.service rdp-worker.service; do
                systemctl --user stop "$service" || printf '清理服务失败：%s，请人工停止\n' "$service" >&2
            done
        fi
        printf '失败阶段：%s；部署：%s；旧提交：%s；目标：%s。保留现场与备份，修正原因后重试，不自动回滚。\n' "$stage" "$deploy_dir" "$old_commit" "$target_commit" >&2
    fi
}

_die() {
    printf '%s\n' "$1" >&2
    exit 1
}

# 安装与升级共用单元渲染；只写两个明确文件，逐个原子替换。
_write_units() {
    stage='写入用户单元'
    local unit_dir=$HOME/.config/systemd/user name line escaped config_escaped replacement
    escaped=$(_systemd_escape "$deploy_dir")
    config_escaped=$(_systemd_escape "${RDP_CONFIG:-}")
    mkdir -p -- "$unit_dir"
    for name in rdp-web.service rdp-worker.service; do
        unit_temp=$(mktemp "$unit_dir/.${name}.XXXXXX")
        while IFS= read -r line || [[ -n $line ]]; do
            if [[ $line == WorkingDirectory=*'@DEPLOY_DIR@'* ]]; then
                # 此指令不使用ExecStart的词法引号；同时兼容目标提交里曾带引号的模板。
                replacement=${deploy_dir//%/%%}
                line="WorkingDirectory=$replacement"
            elif [[ $line == *'@DEPLOY_DIR@'* ]]; then
                replacement=$escaped
                # ExecStart单独解释美元符号；Environment保留其字面值。
                if [[ $line == ExecStart=* ]]; then replacement=${replacement//\$/\$\$}; fi
                line=${line%%@DEPLOY_DIR@*}${replacement}${line#*@DEPLOY_DIR@}
            fi
            printf '%s\n' "$line"
            if [[ $line == '[Service]' && -n ${RDP_CONFIG:-} ]]; then
                printf 'Environment="RDP_CONFIG=%s"\n' "$config_escaped"
            fi
        done < "$deploy_dir/scripts/systemd/$name" > "$unit_temp"
        mv -f -- "$unit_temp" "$unit_dir/$name"
        unit_temp=''
    done
}

# systemd双引号值的转义；百分号必须翻倍，避免部署路径被解释成specifier。
_systemd_escape() {
    local value=$1
    value=${value//\\/\\\\}
    value=${value//\"/\\\"}
    value=${value//%/%%}
    printf '%s' "$value"
}

# 参数解析不读配置、不调用外部工具；帮助与错误可在尚未安装依赖时使用。
_parse_arguments() {
    while (($#)); do
        case $1 in
            --help) usage; exit 0 ;;
            --deploy-dir|--commit)
                if (($# < 2)) || [[ -z $2 ]]; then
                    printf '参数缺少值：%s\n' "$1" >&2
                    exit 2
                fi
                if [[ $1 == --deploy-dir ]]; then deploy_dir=$2; else commit_ref=$2; fi
                shift 2
                ;;
            --no-systemd) no_systemd=true; shift ;;
            --yes)
                if [[ $operation != upgrade ]]; then printf '安装不接受 --yes\n' >&2; exit 2; fi
                assume_yes=true; shift
                ;;
            *) printf '未知参数：%s\n' "$1" >&2; exit 2 ;;
        esac
    done
}

if [[ ${BASH_SOURCE[0]} == "$0" ]]; then
    main "$@"
fi
