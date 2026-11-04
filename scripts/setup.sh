#!/usr/bin/env bash
# 第11张的一键部署编排；只组合工具引导、只读查询和既有install/账号入口，不复制业务规则。
# 工具使用官方发行包，JSON由Node内置JSON解析，文件发布用同盘暂存+原子rename；不引入jq或安装框架。
set -euo pipefail

# 升级版本时必须同时更新版本表和SHA256表；摘要由执行线从官方release资产核对。
# 自动安装版本唯一来源；Python由uv读取目标提交的requires-python/uv.lock，不另设Python版本。
# package.json没有engines/packageManager字段；这里采用负责人提供的已验证工具版本，Node满足锁定Vite/Vitest要求。
declare -Ar SETUP_TOOL_VERSIONS=([node]='22.23.2' [uv]='0.13.5' [pnpm]='11.22.0')
declare -Ar SETUP_TOOL_SHA256=(
    [uv:x86_64]='f68d291c75783122dad58ab77def0e13f3233f358731db5d6d7e8715603b928f'
    [uv:aarch64]='4bb69cf95ed13f23713bb7bc09f241896ea0c75b7c557e615a20604b82f9c403'
    [pnpm:x86_64]='4c592fa410eb23b69691a9efb9bf21c87c15b3e9d88c6ec8acdd354a0eb8de71'
    [pnpm:aarch64]='f1426231f365bdfd46c15fa3d1211c3936ee2c4e557afd304f6c66dbf1b2a8bf'
)
# 仅Linux/glibc；下载名由这两份明确映射构造，不猜未知CPU的兼容二进制。
declare -Ar SETUP_NODE_ARCH=([x86_64]='x64' [aarch64]='arm64')
declare -Ar SETUP_UV_TARGET=([x86_64]='x86_64-unknown-linux-gnu' [aarch64]='aarch64-unknown-linux-gnu')
declare -Ar SETUP_PNPM_ARCH=([x86_64]='x64' [aarch64]='arm64')
readonly SETUP_NODE_ORIGIN='https://nodejs.org'
readonly SETUP_GITHUB_ORIGIN='https://github.com'
# GitHub releases下载的HTTPS重定向白名单；不能使用响应体提供的任意镜像。
readonly SETUP_GITHUB_ASSET_HOSTS='release-assets.githubusercontent.com objects.githubusercontent.com'
# 单位秒；单次下载最多300秒，至多重试2次，每次连接预算10秒，不无限等待。
readonly SETUP_CONNECT_TIMEOUT_S=10 SETUP_DOWNLOAD_TIMEOUT_S=300 SETUP_DOWNLOAD_RETRIES=2
# 元数据最多2MiB，单个工具压缩包最多512MiB，解包总量最多1GiB；超限先拒绝，不执行下载内容。
readonly SETUP_METADATA_MAX_BYTES=2097152 SETUP_ARCHIVE_MAX_BYTES=536870912 SETUP_EXTRACT_MAX_BYTES=1073741824
# 健康检查只走本机，不经过代理；12次各最多5秒，中间间隔1秒，总等待约71秒加进程调度开销。
readonly SETUP_HEALTH_ATTEMPTS=12 SETUP_HEALTH_TIMEOUT_S=5 SETUP_HEALTH_INTERVAL_S=1
# 前台监管停止预算，单位秒，与已批准用户单元相同；超时报告失败并回收本脚本拥有的子进程。
readonly SETUP_WEB_STOP_TIMEOUT_S=360 SETUP_WORKER_STOP_TIMEOUT_S=45

usage() {
    cat <<HELP
用法：bash scripts/setup.sh [--config FILE] [--deploy-dir DIR] [--commit REF]
                           [--yes] [--no-systemd] [--skip-admin] [--help]
--config FILE：配置文件；优先于非空RDP_CONFIG，再优先于\$HOME/.config/rdp/config.toml。
  接受绝对路径或~/前缀，拒绝控制字符；显式指定的文件不存在时，有终端可问答新建，无终端报错。
  已存在配置只读取和校验，绝不覆盖；文件形式/平台校验不合格时停下，不写回修正。
--deploy-dir DIR：默认\$HOME/.local/opt/rdp；安装时透传给install.sh。
  目录须符合install.sh要求；不是完整安装的既有目录拒绝覆盖，保留现场供人工处理。
--commit REF：默认本地main；解析为完整提交后用于校验环境和install.sh，确保使用同一版本。
  从BASH_SOURCE定位仓库；不clone、不fetch、不pull，也不改变当前开发工作区。
  目标提交须含setup_queries只读入口；缺该入口的旧提交会明确拒绝，不借用另一版本的校验器。
--yes：自动同意工具下载安装、启用linger和最后的部署确认；默认逐项询问，默认答案为否。
  不代答配置字段、存储写许可或管理员密码，不允许覆盖既有配置/工具，不把已有部署自动升级。
--no-systemd：不检查或调用systemctl/loginctl，不安装用户单元，不改变linger。
  install.sh仍收到--no-systemd；随后本脚本在前台监管Web/worker两个子进程，健康后持续运行。
  Ctrl+C/SIGTERM传给本脚本拥有的两个子进程并等待收尾；任一意外退出就停止另一个并报失败。
  不使用nohup，不脱离终端留下无人管理的后台服务；请保持本脚本运行。
--skip-admin：显式延后首管理员创建，打印部署目录里的rdp create-admin命令；默认不跳过。
  已有任意管理员（包括停用账号）总是跳过，不重置密码、不再添加操作日志。
--help：只显示帮助，不探测系统、不下载、不写文件。

自动安装仅提供Linux x86_64/aarch64的glibc发行包；其他平台先退出并给手动办法，工具版本自检失败不发布。
必需基础工具：git、curl、tar、sha256sum、findmnt、ip、flock和常用coreutils。
缺这些工具只提示发行版安装办法；默认服务模式还需要可用的systemctl --user和loginctl。
不运行sudo，不自动安装git/systemd，不修改系统服务；可改用--no-systemd。

工具检查顺序：Node、uv、pnpm。PATH已有固定版本就复用；缺失或版本不一致时，
每个工具分别说明版本、官方来源、用户目录和下载副作用，确认后才安装；拒绝则停止并打印手动办法。
Node：官方node-v<版本>-linux-<架构>.tar.gz，SHA256来自同源SHASUMS256.txt。
uv：使用脚本内固定的SHA256，从github.com/astral-sh/uv/releases/download/<版本>/uv-<target>.tar.gz下载。
pnpm：使用脚本内固定的SHA256，从github.com/pnpm/pnpm/releases/download/v<版本>/pnpm-linux-<架构>.tar.gz下载（官方 tar.gz，glibc 版），不依赖corepack。
uv/pnpm：固定摘要按工具和架构维护；升级版本须同步更新版本表和SHA256表。
不请求GitHub API；缺少有效固定摘要就拒绝，绝不跳过校验。
不curl|sh；校验完成前不解包、不执行；官方HTTPS重定向仅允许预设官方域，不接受任意下载地址。
下载遵守HTTPS_PROXY/HTTP_PROXY/ALL_PROXY/NO_PROXY，诊断不打印代理凭据；不使用-k。
安装到\$HOME/.local/opt/rdp-tools/<工具>/<版本>-<平台>/，入口放\$HOME/.local/bin。
只发布本脚本管理的入口，不覆盖该目录下用户已有的其他工具；不修改shell配置。
PATH只在本次脚本及其子进程加入\$HOME/.local/bin；结束时提示如何自行写入shell配置。
Python及项目依赖由uv按目标提交的锁文件下载；前端依赖由install.sh中的pnpm按锁文件下载。

默认模式检查当前用户linger：关闭时说明“退出登录后用户服务可能停止、无法保证开机运行”，
确认后只调用loginctl enable-linger当前用户；拒绝就停下，不静默降级。
查询/启用失败打印可由管理员执行的sudo loginctl enable-linger <当前用户>，本脚本不执行sudo。

无配置时交互询问：监听地址（默认0.0.0.0，明确“局域网明文HTTP，可改成127.0.0.1”）、
端口（默认8600）、导航层绝对目录（必填、无隐藏默认）、状态目录（默认\$HOME/.local/share/rdp）。
findmnt只提供当前挂载快照，列出挂载点、文件系统、UUID/NFS来源及内核只读状态供选择；
不读取存储根内容、不遍历目录、不挂载、不写标记文件。无选择须显式确认空存储根列表。
ext4的UUID来自挂载信息，不让用户猜UUID；不支持的文件系统或缺来源的条目标明原因且不可选。
每个根询问名字，平台写许可默认False；本地盘保持只读，仅可写挂载的NFS专属平台区允许显式选择True。
--yes不能代替这项写许可选择；内核rw不等于平台可写。
有nvidia-smi时以--query-gpu=index --format=csv,noheader,nounits只查询GPU编号供选择；
查询最多5秒，完整十进制编号按平台范围校验，默认空列表；无该命令时写gpus=[]，不安装驱动。
nvidia-smi存在但查询失败时说明原因并要求明确选择不用GPU；无终端则报错，不假装探测成功。
已有配置不因缺nvidia-smi自动改成空GPU；保留原文件并报告与启动环境的冲突。

配置校验：先git archive选定提交到本次临时目录，再uv sync --frozen --no-dev建立临时校验环境，
使用该环境的python -m rdp.ops.setup_queries validate-config校验候选文件。
此环境不迁移、不创建状态目录、不写源仓库.venv；复用uv缓存，后续安装仍调用原install.sh。
新配置仅在校验通过后以0600权限、原子且不覆盖的方式发布；并发出现既有配置时保留对方文件并停止。

非交互必须已有有效配置，且凡需工具安装/linger确认必须带--yes；不会等待stdin。
无首管理员且没有终端时必须显式--skip-admin，否则报缺少安全密码交互条件，不调用create-admin。
不提供明文密码参数、环境变量或自动生成密码；有终端时询问登录名（默认admin）、显示名（默认管理员），
再由已有rdp create-admin终端无回显读取两次密码，账号和审计仍由平台原事务写入。
示例：bash scripts/setup.sh --config /绝对路径/config.toml --yes --no-systemd --skip-admin
  该命令前台监管两个服务；另开终端手工执行打印的create-admin命令后才能登录。

健康检查GET /api/health须返回200和{"status":"ok"}；0.0.0.0用127.0.0.1探测，::用::1。
成功后打印本机地址与各网卡候选HTTP地址；地址列表不代表已检测防火墙或外部连通性。
健康失败非0退出，指出实际状态目录下web.log/worker.log；只收尾本次启动的服务/子进程。

重复运行：完整部署已存在时只报告版本、服务/worker状态和升级命令，不重装、不重启、不自动升级，
不重新询问安装工具或改写配置；有缺陷/无法读状态时非0退出。未完成部署目录明确报错，不能误报已安装。
失败保留已经验证完成的工具、已发布配置、部署目录及迁移备份；清理本次下载/解包/临时校验环境，
校验失败的工具不进入正式目录或PATH入口。修正原因后重新运行；已有部分部署须按install.sh帮助人工处理。
成功0；环境/下载/配置/启动/健康失败1；参数或非交互缺输入2；并发setup占用3；部署阶段拒绝确认/取消130。
前台服务就绪后响应INT/TERM且两个子进程正常退出为0；停止超时或子进程意外失败为1。
固定版本：Node ${SETUP_TOOL_VERSIONS[node]}；uv ${SETUP_TOOL_VERSIONS[uv]}；pnpm ${SETUP_TOOL_VERSIONS[pnpm]}。
HELP
}

# 解析上述参数并固定优先级；只读取argv，不探测工具/文件，不读取密码；未知/缺值退出2，--help先于副作用。
parse_arguments() {
    for arg in "$@"; do
        if [[ $arg == --help ]]; then usage; exit 0; fi
    done
    config_file=${RDP_CONFIG:-$HOME/.config/rdp/config.toml}
    deploy_dir=$HOME/.local/opt/rdp
    commit_ref=main
    assume_yes=false no_systemd=false skip_admin=false
    while (( $# )); do
        case $1 in
            --config|--deploy-dir|--commit)
                (( $# >= 2 )) && [[ -n $2 && $2 != --* ]] || _setup_die 2 '参数缺少值'
                case $1 in
        \
            --config) config_file=$2 ;;
        \
            --deploy-dir) deploy_dir=$2 ;;
        \
            --commit) commit_ref=$2 ;;
                esac
                shift 2 ;;
            --yes) assume_yes=true; shift ;;
            --no-systemd) no_systemd=true; shift ;;
            --skip-admin) skip_admin=true; shift ;;
            *) _setup_die 2 '未知参数；请查看--help' ;;
        esac
    done
}

# 由BASH_SOURCE定位仓库并解析本地完整提交；检查操作系统/CPU、绝对路径及控制字符。
# 读git元数据和工具清单，不fetch、不改检出；基础工具缺失打印手动办法，未知平台或不可信路径退出1/2。
resolve_repository_and_environment() {
    local scripts_root tool
    for tool in git curl tar sha256sum findmnt ip flock timeout uname getconf dirname readlink mktemp mkdir rm mv ln chmod stat head awk wc id cp; do
        command -v "$tool" >/dev/null || _setup_die 1 "缺少 $tool；请按发行版手动安装基础工具"
    done
    [[ $(uname -s) == Linux ]] || _setup_die 1 '仅支持Linux；请手动准备工具'
    platform=$(uname -m)
    [[ -n ${SETUP_NODE_ARCH[$platform]:-} ]] || _setup_die 1 'CPU不支持；请手动准备工具'
    [[ $(getconf GNU_LIBC_VERSION) == glibc* ]] || _setup_die 1 '需要glibc；请手动准备工具'
    for tool in HOME config_file deploy_dir; do
        local value=${!tool}
        if [[ $value == '~/'* ]]; then value=$HOME/${value:2}; fi
        [[ $value == /* && ! $value =~ [[:cntrl:]] && /$value/ != */../* ]] || _setup_die 2 '需要无控制字符的绝对路径'
        printf -v "$tool" '%s' "$value"
    done
    [[ ! $commit_ref =~ [[:cntrl:]] ]] || _setup_die 2 '提交引用不能含控制字符'
    scripts_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
    source_root=$(git -C "$scripts_root" rev-parse --show-toplevel)
    target_commit=$(git -C "$source_root" rev-parse --verify --end-of-options "${commit_ref}^{commit}")
    [[ $target_commit =~ ^([0-9a-f]{40}|[0-9a-f]{64})$ ]] || _setup_die 1 '目标不是完整提交'

}

# 先只读识别已有完整部署（登记worktree、rdp入口、有效构建信息），调用旧rdp/status展示状态与upgrade命令。
# 不以“目录存在”冒充完整安装；已有完整部署直接结束，不再进入下载/写配置/启动；部分目录保留并退出1。
report_existing_installation() {
    [[ -e $deploy_dir || -L $deploy_dir ]] || return 0
    [[ -x $deploy_dir/.venv/bin/rdp && -f $deploy_dir/rdp-build.json && ! -L $deploy_dir ]] ||
        _setup_die 1 '未完成部署；保留现场，请按install.sh帮助人工处理'
    local entry registered=false listing
    listing=$(git -C "$source_root" worktree list --porcelain)
    while IFS= read -r entry; do
        [[ $entry != "worktree $deploy_dir" ]] || registered=true
    done <<< "$listing"
    $registered || _setup_die 1 '未完成部署：不是登记的worktree；保留现场'
    export RDP_CONFIG=$config_file
    "$deploy_dir/.venv/bin/rdp" --version
    _report_existing_status --worker-stopped 'worker 已停止（锁未被持有）' 'worker 在线（锁被持有）'
    _report_existing_status --active-jobs '无活跃作业' '存在活跃作业'
    if ! $no_systemd; then
        local service_result
        # is-active的3是未活动状态，仍可正常报告；总线/参数等故障不能冒充状态。
        if systemctl --user is-active rdp-web.service rdp-worker.service; then
            :
        else
            service_result=$?
            (( service_result == 3 )) || _setup_die 1 "用户服务状态查询失败（退出码$service_result）"
        fi
    fi
    printf '已有完整部署；升级命令：bash %q --deploy-dir %q --commit <本地提交>\n' "$source_root/scripts/upgrade.sh" "$deploy_dir"
    exit 0
}

# 两项只读状态的3表示正常的业务状态，不是命令失败；其余非零码保留为检查失败。
_report_existing_status() {
    local check=$1 absent=$2 present=$3 result
    if "$deploy_dir/.venv/bin/rdp" status "$check"; then
        printf '%s\n' "$absent"
    else
        result=$?
        if (( result == 3 )); then
            printf '%s\n' "$present"
        else
            _setup_die 1 "状态检查失败：$check（退出码$result），请检查配置、数据库或运行日志"
        fi
    fi
}

# 新安装在用户状态目录持非阻塞flock，冲突退出3；创建本次0700暂存目录并登记所有本次拥有的资源。
# 不chmod已有用户目录；EXIT/INT/TERM统一清理仅本次暂存与子进程，不删除正式部署、配置或完整工具。
acquire_setup_workspace() {
    umask 077
    mkdir -p -- "$HOME/.local/state/rdp"
    [[ ! -L $HOME/.local/state/rdp/setup.lock ]] || _setup_die 1 '部署锁不能是软链接'
    exec {setup_lock}>"$HOME/.local/state/rdp/setup.lock"
    flock -n "$setup_lock" || _setup_die 3 'setup已被另一进程占用'
    workspace=$(mktemp -d "${TMPDIR:-/tmp}/rdp-setup.XXXXXXXX")
    stage='准备工具'
    trap 'finish_setup "$?"' EXIT
    trap 'exit 130' INT TERM
}

# Args: 工具名、固定版本、来源、目标路径；有TTY逐项问默认否，--yes直接同意，无TTY且无--yes退出2。
# 拒绝或EOF打印与该工具对应的手动下载/校验/用户目录安装办法并退出130，不能继续依赖它的步骤。
confirm_tool_installation() {
    local tool=$1 version=$2 source=$3 destination=$4 answer
    printf '安装%s %s：官方来源%s；下载并写入%s。\n' "$tool" "$version" "$source" "$destination"
    if $assume_yes; then return 0; fi
    [[ -t 0 ]] || _setup_die 2 '无终端；工具安装确认需要--yes，或手动准备固定版本'
    printf '是否继续？[y/N] '
    if ! read -r answer || [[ $answer != y && $answer != Y ]]; then
        _setup_die 130 "已拒绝$tool；手动从$source下载$version，核对SHA256后放入$destination及用户.local/bin，重新运行"
    fi
}

# 先确保Node：只读检查node --version；不符固定版本时先确认，再下载官方tar和同源SHASUMS256.txt。
# 精确匹配归档名及唯一64位摘要、按上限读取，校验后才检查归档条目和解包；失败不执行包内node。
# 成功输出/保存可用Node绝对路径，后续JSON解析不依赖尚未发布的全局PATH。
ensure_node() {
    if _tool_version_matches node node; then return 0; fi
    confirm_tool_installation node "${SETUP_TOOL_VERSIONS[node]}" "$SETUP_NODE_ORIGIN" "$HOME/.local/opt/rdp-tools/node"
    local archive="node-v${SETUP_TOOL_VERSIONS[node]}-linux-${SETUP_NODE_ARCH[$platform]}.tar.gz"
    local origin="$SETUP_NODE_ORIGIN/dist/v${SETUP_TOOL_VERSIONS[node]}"
    _fetch_official "$origin/SHASUMS256.txt" "$workspace/node.sums" "$SETUP_METADATA_MAX_BYTES"
    local hash name extra matches=0 digest=''
    while read -r hash name extra; do
        if [[ $name == "$archive" ]]; then
            [[ $hash =~ ^[0-9a-fA-F]{64}$ && -z $extra ]] || _setup_die 1 'Node摘要格式不合法'
            digest=$hash
            matches=$((matches + 1))
        fi
    done < "$workspace/node.sums"
    (( matches == 1 )) || _setup_die 1 'Node摘要未唯一匹配归档名'
    download_and_verify_tool node "$origin/$archive" "$digest"
    publish_user_tool node "$HOME/.local/opt/rdp-tools/node/${SETUP_TOOL_VERSIONS[node]}-$platform"
}

# Args: uv或pnpm、平台；从顶部固定表选取SHA256，版本/架构确定tag与glibc归档名。
# 只下载官方releases/download地址，不请求API元数据；缺少有效摘要先拒绝，不能降级跳过校验。
read_official_release_digest() {
    local tool=$1 machine=$2 repo tag asset digest
    case $tool in
        uv)
            repo=astral-sh/uv tag=${SETUP_TOOL_VERSIONS[uv]}
            asset="uv-${SETUP_UV_TARGET[$machine]}.tar.gz" ;;
        pnpm)
            repo=pnpm/pnpm tag="v${SETUP_TOOL_VERSIONS[pnpm]}"
            asset="pnpm-linux-${SETUP_PNPM_ARCH[$machine]}.tar.gz" ;;
        *) _setup_die 1 '未知工具，拒绝下载' ;;
    esac
    digest=${SETUP_TOOL_SHA256["$tool:$machine"]:-}
    download_and_verify_tool "$tool" "$SETUP_GITHUB_ORIGIN/$repo/releases/download/$tag/$asset" "$digest"
    publish_user_tool "$tool" "$HOME/.local/opt/rdp-tools/$tool/${SETUP_TOOL_VERSIONS[$tool]}-$machine"
}

# Args: 工具名、官方URL、期望SHA256；curl仅写本次暂存，保留代理环境且不输出凭据。
# 限制HTTPS域、重定向、时间、大小和重试；sha256sum不符时删除本次下载，退出1，不解包/执行/发布。
download_and_verify_tool() {
    local tool=$1 url=$2 digest=$3
    [[ $digest =~ ^[0-9a-fA-F]{64}$ ]] || _setup_die 1 'SHA256摘要格式非法'
    _fetch_official "$url" "$workspace/$tool.download" "$SETUP_ARCHIVE_MAX_BYTES"
    printf '%s  %s\n' "$digest" "$workspace/$tool.download" | sha256sum --check --status ||
        _setup_die 1 'SHA256校验失败；不解包、不执行、不发布工具'
}

# Args: 已校验工具、目标目录；只在暂存检查条目路径、链接逃逸、解包大小、可执行文件及--version。
# 完整内容同盘原子发布，权限不扩大；仅替换带本脚本归属记录的入口，碰到用户自有文件即停止。
# 发布失败清理本次半成品，保留旧工具/入口；不删除已成功安装的其他工具，不改shell rc或系统目录。
publish_user_tool() {
    local tool=$1 destination=$2 parent current
    parent=$(dirname -- "$destination")
    mkdir -p -- "$parent" "$HOME/.local/bin"
    current="$HOME/.local/bin/$tool"
    if [[ -e $current || -L $current ]]; then
        [[ -L $current && $(readlink -- "$current") == "$HOME/.local/opt/rdp-tools/$tool/"* ]] ||
            _setup_die 1 '用户自有工具入口，拒绝覆盖'
        [[ -f $(dirname -- "$(dirname -- "$(readlink -- "$current")")")/.rdp-setup-tool ]] ||
            _setup_die 1 '工具没有本脚本归属记录，拒绝覆盖'
    fi
    [[ ! -e $destination && ! -L $destination ]] || _setup_die 1 '工具版本目录已存在；请检查现场'
    tool_stage=$(mktemp -d "$parent/.incoming.XXXXXXXX")
    if [[ $tool == pnpm ]]; then
        # pnpm发行包存在根目录及单层目录两种布局；检查和解包使用同一不剥层坐标。
        _check_tool_archive "$workspace/$tool.download" "$tool_stage" 0
        tar --extract --gzip --file "$workspace/$tool.download" --directory "$tool_stage" \
            --no-same-owner --no-same-permissions
        _locate_pnpm_entry "$tool_stage"
    else
        _check_tool_archive "$workspace/$tool.download" "$tool_stage"
        tar --extract --gzip --file "$workspace/$tool.download" --directory "$tool_stage" \
            --strip-components=1 --no-same-owner --no-same-permissions
        if [[ $tool == uv ]]; then
            mkdir -p -- "$tool_stage/bin"
            ln -s ../uv "$tool_stage/bin/uv"
        fi
    fi
    [[ -x $tool_stage/bin/$tool ]] || _setup_die 1 '工具包缺少可执行入口'
    _tool_version_matches "$tool" "$tool_stage/bin/$tool" ||
        _setup_die 1 '工具版本自检失败'
    printf '%s\n' "$tool" > "$tool_stage/.rdp-setup-tool"
    mv -T -n -- "$tool_stage" "$destination"
    [[ ! -e $tool_stage ]] || _setup_die 1 '工具发布发生竞争，保留对方目录'
    tool_stage=''
    entry_temp="$HOME/.local/bin/.$tool.rdp-setup-$$"
    ln -s "$destination/bin/$tool" "$entry_temp"
    mv -Tf -- "$entry_temp" "$current"
    entry_temp=''
    export PATH="$HOME/.local/bin:$PATH"
    hash -r
}

# 只接受解包根或下一层的唯一普通可执行文件；未知/歧义布局不猜测，不执行候选。
_locate_pnpm_entry() {
    local directory=$1 executable
    local -a candidates=()
    for executable in "$directory/pnpm" "$directory"/*/pnpm "$directory"/.[!.]*/pnpm; do
        if [[ -f $executable && -x $executable && ! -L $executable && ! -L ${executable%/*} ]]; then
            candidates+=("$executable")
        fi
    done
    (( ${#candidates[@]} == 1 )) || _setup_die 1 'pnpm归档结构不符合预期：根目录或下一层必须恰有一个普通可执行pnpm'
    executable=${candidates[0]}
    if [[ $executable != "$directory/bin/pnpm" ]]; then
        [[ ! -L $directory/bin ]] || _setup_die 1 'pnpm归档bin目录不能为链接'
        mkdir -p -- "$directory/bin"
        [[ ! -e $directory/bin/pnpm && ! -L $directory/bin/pnpm ]] || _setup_die 1 'pnpm归档入口冲突'
        ln -s "../${executable#"$directory/"}" "$directory/bin/pnpm"
    fi
}

# 自检与PATH复用共用版本边界：只接受完整版本token，允许空格后的平台说明，不接受相近补丁号或预发行后缀。
_tool_version_matches() {
    local tool=$1 executable=$2 output expected
    if ! output=$(timeout 5 "$executable" --version 2>/dev/null); then return 1; fi
    expected=${SETUP_TOOL_VERSIONS[$tool]}
    if [[ $tool == node ]]; then expected="v$expected";
    elif [[ $tool == uv ]]; then expected="uv $expected"; fi
    [[ $output == "$expected" || $output == "$expected "* ]]
}

# 按Node、uv、pnpm顺序逐个询问并选择固定版本；Node供后续配置问答解析JSON。
# uv/pnpm均用官方tar.gz包；Python留给uv按锁文件安装，不自行选择Python版本。
ensure_user_toolchain() {
    # 重试必须先发现上次完成的用户工具；不能再次下载后因同版本目录存在而失败。
    export PATH="$HOME/.local/bin:$PATH"
    hash -r
    ensure_node
    local tool
    for tool in uv pnpm; do
        if _tool_version_matches "$tool" "$tool"; then continue; fi
        confirm_tool_installation "$tool" "${SETUP_TOOL_VERSIONS[$tool]}" "$SETUP_GITHUB_ORIGIN" "$HOME/.local/opt/rdp-tools/$tool"
        read_official_release_digest "$tool" "$platform"
    done
    export PATH="$HOME/.local/bin:$PATH"
}

# 默认模式读systemctl --user与loginctl当前用户Linger；--no-systemd完全跳过这两个命令。
# 缺命令/用户总线不可用只提示；Linger=no说明后果后确认，--yes可授权enable-linger当前用户。
# 拒绝停止；失败打印管理员命令并退出1，不运行sudo、不操作其他用户或系统服务。
ensure_user_service_environment() {
    if $no_systemd; then return 0; fi
    stage='用户服务环境'
    command -v systemctl >/dev/null && command -v loginctl >/dev/null ||
        _setup_die 1 '缺少systemd工具；请手动安装或使用--no-systemd'
    systemctl --user show-environment >/dev/null 2>&1 ||
        _setup_die 1 '用户服务总线不可用；检查登录会话，或使用--no-systemd'
    local current_user linger
    current_user=$(id -un)
    linger=$(loginctl show-user "$current_user" --property=Linger --value) ||
        _setup_die 1 "无法查询linger；请管理员执行：sudo loginctl enable-linger $current_user"
    if [[ $linger == yes ]]; then return 0; fi
    [[ $linger == no ]] || _setup_die 1 "linger状态未知；请管理员执行：sudo loginctl enable-linger $current_user"
    printf 'linger关闭：退出登录后用户服务可能停止，无法保证开机运行。\n'
    if ! $assume_yes; then
        [[ -t 0 ]] || _setup_die 2 '无终端；启用linger需要--yes'
        local answer
        printf '为当前用户启用linger？[y/N] '
        read -r answer && [[ $answer == y || $answer == Y ]] || _setup_die 130 '已拒绝启用linger'
    fi
    loginctl enable-linger "$current_user" ||
        _setup_die 1 "启用linger失败；请管理员执行：sudo loginctl enable-linger $current_user"
}

# git archive所选完整提交到本次临时目录，uv按该提交pyproject/uv.lock建隔离的无dev依赖校验环境。
# 显式UV_PROJECT_ENVIRONMENT指向临时目录，清VIRTUAL_ENV，不改源仓库.venv；Python由uv自动取得。
# 只运行该提交的setup_queries模块，缺模块/锁不一致/同步失败则停止；不偷用另一提交的校验规则。
prepare_validation_runtime() {
    stage='目标提交配置校验环境'
    git -C "$source_root" archive --format=tar --output "$workspace/validation.tar" "$target_commit" ||
        _setup_die 1 '目标提交归档失败'
    mkdir -- "$workspace/source"
    tar -xf "$workspace/validation.tar" -C "$workspace/source"
    [[ -f $workspace/source/src/rdp/ops/setup_queries.py ]] || _setup_die 1 '目标提交缺少setup_queries，不能用其他版本校验'
    unset VIRTUAL_ENV
    (cd -- "$workspace/source" && UV_PROJECT_ENVIRONMENT="$workspace/venv" uv sync --frozen --no-dev) ||
        _setup_die 1 '目标提交锁定依赖的校验环境构建失败'
    validation_python="$workspace/venv/bin/python"
    [[ -x $validation_python ]] || _setup_die 1 '校验环境缺少Python入口'
}

# 读取--config/RDP_CONFIG/默认文件的选定来源；存在只校验，不写回，不把显式缺失文件静默当默认配置。
# 缺失且无TTY退出2；有TTY按help问host/port/nav/state，findmnt JSON经只读查询解析，GPU用有界只读查询。
# findmnt与ip输出只写本次有界快照文件（最多2MiB加一字节判超限），命令最多5秒，不等待存储响应。
# 所有读取仅限配置、系统挂载元数据和工具输出，不触碰导航层/存储根内容；失败保留既有配置。
collect_configuration_answers() {
    stage='配置读取'
    new_config=false
    if [[ -e $config_file || -L $config_file ]]; then
        [[ -f $config_file && ! -L $config_file ]] || _setup_die 1 '配置必须为普通文件'
        candidate=$config_file
        return 0
    fi
    [[ -t 0 ]] || _setup_die 2 '无终端且配置缺失；请提供已有有效配置'
    new_config=true
    printf '监听地址 [0.0.0.0]（局域网明文HTTP，可改成127.0.0.1）：'
    read -r answer_host || _setup_die 130 '配置输入取消'
    answer_host=${answer_host:-0.0.0.0}
    printf '端口 [8600]：'
    read -r answer_port || _setup_die 130 '配置输入取消'
    answer_port=${answer_port:-8600}
    printf '导航层绝对目录（必填）：'
    read -r answer_nav || _setup_die 130 '配置输入取消'
    [[ -n $answer_nav ]] || _setup_die 2 '导航层目录必填，没有默认值'
    printf '状态目录 [%s/.local/share/rdp]：' "$HOME"
    read -r answer_state || _setup_die 130 '配置输入取消'
    answer_state=${answer_state:-$HOME/.local/share/rdp}
    timeout 5 findmnt --json --list --output TARGET,SOURCE,FSTYPE,UUID,OPTIONS |
        head -c "$((SETUP_METADATA_MAX_BYTES + 1))" > "$workspace/mounts.json" ||
        _setup_die 1 '挂载元数据读取失败'
    "$validation_python" -m rdp.ops.setup_queries mounts --input "$workspace/mounts.json" > "$workspace/candidates.json" ||
        _setup_die 1 '挂载快照校验失败'
    node -e 'const rows=JSON.parse(require("node:fs").readFileSync(process.argv[1],"utf8")).items; rows.forEach((r,i)=>console.log(i+1, r.path, r.filesystem, r.uuid||r.nfs_export||"", r.read_only?"内核只读":"内核可写", (r.unavailable_reason==="stacked_mount"?"叠加挂载，无法确认哪一层可见":r.unavailable_reason||"可选")));' "$workspace/candidates.json"
    printf '选择存储根编号（逗号分隔，空为不选）：'
    read -r answer_roots || _setup_die 130 '配置输入取消'
    printf '[]' > "$workspace/roots.json"
    if [[ -z $answer_roots ]]; then
        local empty_answer
        printf '确认使用空存储根列表？[y/N] '
        read -r empty_answer && [[ $empty_answer == y || $empty_answer == Y ]] ||
            _setup_die 130 '未确认空存储根'
    else
        _collect_storage_roots
    fi
    _collect_gpu_answers
    node - "$answer_host" "$answer_port" "$answer_nav" "$answer_state" "$workspace" > "$workspace/answers.json" <<'JS'
const fs = require("node:fs");
const [host, port, nav_root, state_dir, directory] = process.argv.slice(2);
console.log(JSON.stringify({host, port: /^\d+$/.test(port) ? Number(port) : port, nav_root, state_dir,
  roots: JSON.parse(fs.readFileSync(directory+"/roots.json","utf8")),
  gpus: JSON.parse(fs.readFileSync(directory+"/gpus.json","utf8"))}));
JS
    candidate="$workspace/config.toml"
}

# Args: 问答快照；Node JSON.stringify负责TOML基本字符串转义，不拼接可执行shell文本。
# 写本次0600候选文件，平台load_config做唯一权威校验；成功后原子“不覆盖”发布到选定配置路径。
# 发布前后保持同一候选，目标竞争/校验失败不覆盖任何已有文件；不mkdir导航层或存储根。
validate_and_publish_configuration() {
    stage='平台配置校验'
    if $new_config; then
        node - "$workspace/answers.json" > "$candidate" <<'JS'
const fs = require("node:fs");
const a = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
const text = JSON.stringify;
console.log("state_dir = "+text(a.state_dir));
console.log("nav_root = "+text(a.nav_root));
if(a.roots.length===0) console.log("storage_roots = []");
console.log("[web]\nhost = "+text(a.host)+"\nport = "+text(a.port));
console.log("[jobs]\ngpus = "+text(a.gpus));
for(const r of a.roots) {
 console.log("[[storage_roots]]");
 for(const key of ["name","path","uuid","nfs_export","writable"])
   if(r[key] !== null && r[key] !== undefined) console.log(key+" = "+text(r[key]));
}
JS
    fi
    "$validation_python" -m rdp.ops.setup_queries validate-config --config "$candidate" > "$workspace/config.json" ||
        _setup_die 1 '配置未通过平台校验，未发布'
    if ! $new_config && node -e 'process.exit(JSON.parse(require("node:fs").readFileSync(process.argv[1],"utf8")).gpus.length ? 0:1)' "$workspace/config.json"; then
        command -v nvidia-smi >/dev/null || _setup_die 1 '已有配置要求GPU，但缺少nvidia-smi；保留配置，请修正环境'
        _read_gpu_indices || _setup_die 1 'GPU查询失败或编号非法；保留已有配置，请修正环境'
        node -e 'const fs=require("node:fs");const wanted=JSON.parse(fs.readFileSync(process.argv[1],"utf8")).gpus;const available=JSON.parse(fs.readFileSync(process.argv[2],"utf8"));process.exit(wanted.every(x=>available.includes(x))?0:1)' "$workspace/config.json" "$workspace/available-gpus.json" ||
            _setup_die 1 '已有配置中的GPU编号不在当前硬件列表中；保留配置'
    fi
    state_dir=$(node -e 'console.log(JSON.parse(require("node:fs").readFileSync(process.argv[1], "utf8")).state_dir)' "$workspace/config.json")
    if $new_config; then
        mkdir -p -- "$(dirname -- "$config_file")"
        config_temp=$(mktemp "$(dirname -- "$config_file")/.rdp-config.XXXXXXXX")
        cp -- "$candidate" "$config_temp"
        chmod 600 "$config_temp"
        ln -T -- "$config_temp" "$config_file" || _setup_die 1 '配置发布发生竞争，保留对方文件'
        rm -f -- "$config_temp"
        config_temp=''
    fi
    export RDP_CONFIG=$config_file
}

# 用临时校验环境只读查询管理员状态，missing_database与absent明确区分；停用管理员也算present。
# 无TTY且需要首号又未--skip-admin时，在调用install.sh前报错，不把--yes当密码输入授权。
# 不查询密码哈希、不创建账号、不写会话/审计；坏库/版本错误不当作“没有管理员”。
check_administrator_input_requirements() {
    stage='管理员输入条件'
    _administrator_status "$validation_python"
    if [[ $admin_status != present ]] && ! $skip_admin && [[ ! -t 0 ]]; then
        _setup_die 2 '无终端且尚无管理员；请显式--skip-admin，之后在终端执行create-admin'
    fi
}

# 以argv数组调用仓库的install.sh，透传--deploy-dir、解析后的--commit以及--no-systemd；
# RDP_CONFIG明确指向已验证的选定文件，同一配置用于迁移、服务和后续只读查询。
# 不改变install.sh语义，不自行再建worktree/迁移/写单元；非零立即停，保留其失败现场和备份。
# 默认模式在install成功时即登记本次服务拥有关系，确保后续建管理员失败也能收尾已启动服务。
install_platform() {
    stage='安装平台'
    if ! $assume_yes; then
        [[ -t 0 ]] || _setup_die 2 '无终端；部署确认需要--yes'
        local answer
        printf '开始安装平台到%s？[y/N] ' "$deploy_dir"
        read -r answer && [[ $answer == y || $answer == Y ]] || _setup_die 130 '已取消部署'
    fi
    local -a args=(--deploy-dir "$deploy_dir" --commit "$target_commit")
    if $no_systemd; then args+=(--no-systemd); fi
    bash "$source_root/scripts/install.sh" "${args[@]}" ||
        _setup_die 1 'install.sh失败；保留部署与备份，请按install.sh --help人工处理'
    if ! $no_systemd; then owns_services=true; fi
}

# 安装后用部署自身的setup_queries再查管理员；present跳过，absent且未skip才询问名字并调用已有create-admin。
# 密码由该命令在TTY里无回显读两次，不经argv/env/日志；失败停止，不新增第二条审计，不自动重置账号。
# 数据库意外缺失或损坏属于失败；并发创建仍由既有账号事务裁决，不把任意失败当“已有人创建”。
ensure_first_administrator() {
    stage='首管理员'
    _administrator_status "$deploy_dir/.venv/bin/python"
    if [[ $admin_status == present ]]; then printf '已有管理员，跳过创建。\n'; return 0; fi
    [[ $admin_status == absent ]] || _setup_die 1 '安装后数据库仍缺失，请检查迁移'
    if $skip_admin; then
        printf '已延后首管理员；另开终端执行：HOME=%q RDP_CONFIG=%q %q create-admin <登录名> <显示名>\n' "$HOME" "$config_file" "$deploy_dir/.venv/bin/rdp"
        return 0
    fi
    [[ -t 0 ]] || _setup_die 2 '建管理员需要终端，或使用--skip-admin'
    local login display
    printf '管理员登录名 [admin]：'
    read -r login || _setup_die 130 '管理员输入取消'
    printf '管理员显示名 [管理员]：'
    read -r display || _setup_die 130 '管理员输入取消'
    "$deploy_dir/.venv/bin/rdp" create-admin "${login:-admin}" "${display:-管理员}" ||
        _setup_die 1 '创建管理员失败；请查看操作诊断，不自动重试或重置账号'
}

# 默认模式确认本次安装的两个用户服务状态；--no-systemd才启动部署自己的web/worker并保留PID及拥有关系。
# 子进程使用同一HOME/RDP_CONFIG/PATH，不安装真实信号处理器到测试进程；启动失败只停止本次拥有的服务。
start_platform_services() {
    stage='确认服务启动'
    if $no_systemd; then
        "$deploy_dir/.venv/bin/rdp" web --no-stderr &
        web_pid=$!
        "$deploy_dir/.venv/bin/rdp" worker --no-stderr &
        worker_pid=$!
        trap 'if ${foreground_ready:-false}; then exit 0; else exit 130; fi' INT TERM
        return 0
    fi
    local service
    for service in rdp-web.service rdp-worker.service; do
        systemctl --user is-active --quiet "$service" || _setup_die 1 "服务启动失败：$service"
    done
}

# 对配置对应本机地址GET /api/health，禁用代理仅用于这个本机探测；有限次数/单次超时见顶部常量。
# 校验HTTP 200和JSON status=ok后才打印成功；失败退出1，明确web.log/worker.log实际位置并收尾本次启动。
verify_platform_health() {
    stage='本机健康检查'
    printf '[]' > "$workspace/local-interfaces.json"
    "$deploy_dir/.venv/bin/python" -m rdp.ops.setup_queries urls --config "$config_file" \
        --input "$workspace/local-interfaces.json" > "$workspace/local-urls.json" ||
        _setup_die 1 '本机访问地址生成失败'
    local_url=$(node -e 'console.log(JSON.parse(require("node:fs").readFileSync(process.argv[1],"utf8")).urls[0])' "$workspace/local-urls.json")
    local attempt status
    for ((attempt=0; attempt<SETUP_HEALTH_ATTEMPTS; attempt++)); do
        _check_foreground_children
        status=$(curl --silent --show-error --noproxy '*' --proto '=http' --connect-timeout "$SETUP_HEALTH_TIMEOUT_S" \
            --max-time "$SETUP_HEALTH_TIMEOUT_S" --max-filesize "$SETUP_METADATA_MAX_BYTES" \
            --output "$workspace/health.json" --write-out '%{http_code}' "${local_url}api/health" 2>"$workspace/health.error") || status=failed
        if [[ $status == 200 && $(stat -c %s -- "$workspace/health.json") -le $SETUP_METADATA_MAX_BYTES ]] &&
            node -e 'try {const x=JSON.parse(require("node:fs").readFileSync(process.argv[1],"utf8")); process.exit(x.status==="ok" && Object.keys(x).length===1 ? 0:1)}catch{process.exit(1)}' "$workspace/health.json"; then
            return 0
        fi
        if (( attempt + 1 < SETUP_HEALTH_ATTEMPTS )); then sleep "$SETUP_HEALTH_INTERVAL_S"; fi
    done
    _setup_die 1 "健康检查失败；请查看$state_dir/logs/web.log 和 $state_dir/logs/worker.log"
}

# ip -j address show结果交setup_queries urls；按实际监听范围打印本机及各网卡候选地址。
# 不把0.0.0.0或::作为访问URL，不进行公网探测/防火墙修改；枚举失败返回1，说明原因和本机地址，
# 交统一失败边界收尾本次服务，不伪报已列出全部网卡或外部可达。
print_access_and_upgrade_commands() {
    stage='访问地址'
    if ! timeout 5 ip -j address show | head -c "$((SETUP_METADATA_MAX_BYTES + 1))" > "$workspace/interfaces.json"; then
        _setup_die 1 "网卡枚举失败；本机地址$local_url；未确认外部连通性"
    fi
    "$deploy_dir/.venv/bin/python" -m rdp.ops.setup_queries urls --config "$config_file" \
        --input "$workspace/interfaces.json" > "$workspace/urls.json" ||
        _setup_die 1 "网卡快照无效；本机地址$local_url"
    node -e 'for(const url of JSON.parse(require("node:fs").readFileSync(process.argv[1],"utf8")).urls)console.log(url)' "$workspace/urls.json"
    _check_foreground_children
    foreground_ready=true
    printf '部署健康；以上是候选地址，未检测防火墙或外部连通性。\n'
    printf '升级命令：bash %q --deploy-dir %q --commit <本地提交>\n' "$source_root/scripts/upgrade.sh" "$deploy_dir"
    printf '本次PATH已加入用户工具目录；可自行把 export PATH="$HOME/.local/bin:$PATH" 写入shell配置。\n'
}

# 仅--no-systemd：保持前台等待本次两个子进程；不做后台daemon，不重启失败进程。
# INT/TERM请求正常停机，按顶部预算等待，超时强制回收并返回失败；其他子进程/服务不受影响。
supervise_foreground_services() {
    stage='前台监管'
    # wait由信号中断时trap负责正常停止；任何自然退出（即使0）都表示组合服务不再完整。
    if wait -n "$web_pid" "$worker_pid"; then
        _setup_die 1 '前台服务意外退出'
    else
        _setup_die 1 '前台服务运行失败'
    fi
}

# 保留原失败码和阶段；清本次暂存/候选/校验环境、释放锁；按拥有关系收尾子进程，不掩盖首个错误。
# 成功默认模式保留服务；前台模式正常停止后才清理；不撤销linger，不删除已发布配置、工具、部署或备份。
finish_setup() {
    local result=$1
    trap - EXIT INT TERM
    set +e
    if [[ -n ${web_pid:-} || -n ${worker_pid:-} ]]; then
        _stop_foreground || { if (( result == 0 )); then result=1; fi; }
    fi
    if (( result != 0 )) && ${owns_services:-false}; then
        systemctl --user stop rdp-web.service rdp-worker.service ||
            printf '本次服务停止失败，请检查用户服务状态。\n' >&2
    fi
    if [[ -n ${config_temp:-} ]]; then rm -f -- "$config_temp"; fi
    if [[ -n ${tool_stage:-} ]]; then rm -rf -- "$tool_stage"; fi
    if [[ -n ${entry_temp:-} ]]; then rm -f -- "$entry_temp"; fi
    if [[ -n ${workspace:-} ]]; then rm -rf -- "$workspace"; fi
    if (( result != 0 )); then
        printf '部署停止：%s（退出码%s）；保留已完成工具、配置和部署，请修正原因后重试。\n' "${stage:-预检}" "$result" >&2
    fi
    exit "$result"
}

# 顺序：解析/只读预检与已安装识别 → 独占暂存 → 工具确认安装 → 用户服务/linger → 临时校验环境 →
# 配置问答/校验/不覆盖发布 → 非交互首号条件检查 → install.sh → 首管理员 → 服务/健康/地址 → 可选前台监管。
# 所有实现经以上函数分阶段；本入口本身不复制账号、迁移或配置校验业务。
main() {
    parse_arguments "$@"
    resolve_repository_and_environment
    report_existing_installation
    # 非交互缺配置在任何工具下载/暂存之前拒绝；管理员条件仍由目标版本校验后判断。
    if [[ ! -t 0 && ! -e $config_file ]]; then
        _setup_die 2 '无终端且配置缺失；请提供已有有效配置'
    fi
    acquire_setup_workspace
    ensure_user_toolchain
    ensure_user_service_environment
    prepare_validation_runtime
    collect_configuration_answers
    validate_and_publish_configuration
    check_administrator_input_requirements
    install_platform
    ensure_first_administrator
    start_platform_services
    verify_platform_health
    print_access_and_upgrade_commands
    if $no_systemd; then supervise_foreground_services; fi
}

# 硬件输出只接受完整编号；范围和重复规则直接调用现有JobsConfig，不维护第二份配置规则。
_read_gpu_indices() {
    timeout 5 nvidia-smi --query-gpu=index --format=csv,noheader,nounits 2>"$workspace/gpu.error" |
        head -c "$((SETUP_METADATA_MAX_BYTES + 1))" > "$workspace/gpus.raw" || return 1
    "$validation_python" -c '
import json, re, sys
from pathlib import Path
from rdp.infra.config import JobsConfig
raw = Path(sys.argv[1]).read_bytes()
if len(raw) > int(sys.argv[2]): sys.exit(1)
lines = raw.decode("utf-8").splitlines()
if any(re.fullmatch(r"[0-9]+", line.strip()) is None for line in lines): sys.exit(1)
model = JobsConfig(gpus=[int(line.strip()) for line in lines])
print(json.dumps(model.gpus))
' "$workspace/gpus.raw" "$SETUP_METADATA_MAX_BYTES" > "$workspace/available-gpus.json" 2>"$workspace/gpu-validation.error"
}

# 只有新配置允许明确选用空GPU；探测故障绝不自动改写已有配置。
_collect_gpu_answers() {
    printf '[]' > "$workspace/gpus.json"
    command -v nvidia-smi >/dev/null || return 0
    local answer_gpu
    if ! _read_gpu_indices; then
        printf 'GPU查询失败或编号非法；是否明确不用GPU？[y/N] '
        read -r answer_gpu && [[ $answer_gpu == y || $answer_gpu == Y ]] ||
            _setup_die 1 '未确认不用GPU，停止配置'
        return 0
    fi
    printf '可用GPU编号：'
    cat "$workspace/available-gpus.json"
    printf '选择GPU编号（逗号分隔，默认空）：'
    read -r answer_gpu || _setup_die 130 'GPU输入取消'
    node - "$workspace/available-gpus.json" "$answer_gpu" > "$workspace/gpus.json" <<'JS' ||
const fs=require("node:fs");
const available=JSON.parse(fs.readFileSync(process.argv[2],"utf8"));
const input=process.argv[3].trim();
const parts=input ? input.split(/[ ,]+/) : [];
if(parts.some(x=>!/^\d+$/.test(x))) process.exit(1);
const chosen=parts.map(Number);
if(new Set(chosen).size!==chosen.length || chosen.some(x=>!available.includes(x))) process.exit(1);
console.log(JSON.stringify(chosen));
JS
        _setup_die 1 'GPU选择不属于已确认的硬件编号'
}

# 用户只选择元数据候选编号；来源不可编辑，最终登记规则仍由平台配置模型检查。
_collect_storage_roots() {
    local -a indices
    local index name write_permission
    local -A selected=()
    IFS=', ' read -r -a indices <<< "$answer_roots"
    for index in "${indices[@]}"; do
        [[ $index =~ ^[1-9][0-9]*$ && -z ${selected[$index]:-} ]] || _setup_die 2 '存储根编号非法或重复'
        selected[$index]=yes
        node - "$workspace/candidates.json" "$index" > "$workspace/selected-root.json" <<'JS' ||
const fs = require("node:fs");
const i = Number(process.argv[3]);
const rows = JSON.parse(fs.readFileSync(process.argv[2],"utf8")).items;
if(!Number.isSafeInteger(i) || i < 1 || i > rows.length || rows[i-1].unavailable_reason !== null) process.exit(1);
console.log(JSON.stringify(rows[i-1]));
JS
            _setup_die 1 '所选存储根不可选；请根据展示原因修正'
        printf '存储根%s的名字：' "$index"
        read -r name || _setup_die 130 '存储根输入取消'
        write_permission=false
        if node -e 'const r=JSON.parse(require("node:fs").readFileSync(process.argv[1],"utf8"));process.exit(r.nfs_export && !r.read_only ? 0:1)' "$workspace/selected-root.json"; then
            local answer_write
            printf '确认这是NFS专属平台区并允许平台写入？[y/N] '
            read -r answer_write || _setup_die 130 '存储写许可输入取消'
            if [[ $answer_write == y || $answer_write == Y ]]; then write_permission=true; fi
        else
            printf '本地盘或内核只读挂载保持平台只读。\n'
        fi
        node - "$workspace/selected-root.json" "$name" "$write_permission" "$workspace/roots.json" <<'JS'
const fs = require("node:fs");
const [file,name,write,output]=process.argv.slice(2);
const r=JSON.parse(fs.readFileSync(file,"utf8"));
const roots=JSON.parse(fs.readFileSync(output,"utf8"));
roots.push({name,path:r.path,uuid:r.uuid,nfs_export:r.nfs_export,writable:write==="true"});
fs.writeFileSync(output, JSON.stringify(roots));
JS
    done
}

# Web健康接口不能代表worker存活；报告组合服务健康前检查本次两个子进程。
_check_foreground_children() {
    if $no_systemd; then
        kill -0 "$web_pid" 2>/dev/null && kill -0 "$worker_pid" 2>/dev/null ||
            _setup_die 1 "前台服务提前退出；请查看$state_dir/logs/web.log 和 $state_dir/logs/worker.log"
    fi
}

# 只向本次保存的PID发送停止信号；先通知两个进程，随后分别按用户单元预算回收。
_stop_foreground() {
    local result=0
    if [[ -n ${web_pid:-} ]]; then kill -TERM "$web_pid" 2>/dev/null || true; fi
    if [[ -n ${worker_pid:-} ]]; then kill -TERM "$worker_pid" 2>/dev/null || true; fi
    if [[ -n ${worker_pid:-} ]]; then _wait_owned "$worker_pid" "$SETUP_WORKER_STOP_TIMEOUT_S" || result=1; fi
    if [[ -n ${web_pid:-} ]]; then _wait_owned "$web_pid" "$SETUP_WEB_STOP_TIMEOUT_S" || result=1; fi
    web_pid='' worker_pid=''
    return "$result"
}

# SECONDS只用于经过秒数；超预算先kill再wait，绝不把停止超时报告为成功。
_wait_owned() {
    local pid=$1 budget=$2 start=$SECONDS
    while kill -0 "$pid" 2>/dev/null; do
        if (( SECONDS - start >= budget )); then
            printf '前台子进程停止超时，强制回收：%s\n' "$pid" >&2
            kill -KILL "$pid" 2>/dev/null || true
            wait "$pid" 2>/dev/null || true
            return 1
        fi
        sleep 0.1
    done
    wait "$pid"
}

# 仅解析明确的三态结果，错误和未知值不能当作尚无管理员。
_administrator_status() {
    "$1" -m rdp.ops.setup_queries administrator --database "$state_dir/rdp.sqlite3" > "$workspace/admin.json" ||
        _setup_die 1 '管理员只读查询失败；请检查数据库版本与权限'
    admin_status=$(node -e 'const x=JSON.parse(require("node:fs").readFileSync(process.argv[1],"utf8")); if(!["present","absent","database_missing"].includes(x.status))process.exit(1); console.log(x.status)' "$workspace/admin.json") ||
        _setup_die 1 '管理员状态响应无效'
}

# curl不自动跟随重定向：逐跳核验HTTPS官方域，避免第三方URL借重定向绕过来源约束。
_fetch_official() {
    local url=$1 destination=$2 limit=$3 response code redirect host allowed curl_result
    local started=$SECONDS remaining redirects=0 retries=0
    while (( redirects < 4 )); do
        [[ $url =~ ^https://([^/]+)/ ]] || _setup_die 1 '下载仅允许官方HTTPS'
        host=${BASH_REMATCH[1]}
        allowed=false
        if [[ $host == "${SETUP_NODE_ORIGIN#https://}" || $host == "${SETUP_GITHUB_ORIGIN#https://}" ]]; then allowed=true; fi
        local asset_host
        for asset_host in $SETUP_GITHUB_ASSET_HOSTS; do
            if [[ $host == "$asset_host" ]]; then allowed=true; fi
        done
        $allowed || _setup_die 1 '拒绝非官方下载域'
        remaining=$((SETUP_DOWNLOAD_TIMEOUT_S - (SECONDS - started)))
        (( remaining > 0 )) || _setup_die 1 '下载总时间超过预算'
        curl_result=0
        # 手动分类重试；关闭curl自身重试，避免叠加次数。HTTP状态只用于安全诊断，不回显响应体。
        response=$(timeout "$remaining" curl --disable --silent --show-error --proto '=https' --proto-redir '=https' \
            --connect-timeout "$SETUP_CONNECT_TIMEOUT_S" --max-time "$remaining" --retry 0 \
            --max-filesize "$limit" --max-redirs 0 \
            --header 'Accept: application/octet-stream' --output "$destination" \
            --write-out $'%{http_code}\n%{redirect_url}' "$url" 2>"$workspace/download.error") || curl_result=$?
        code=${response%%$'\n'*}
        redirect=${response#*$'\n'}
        if _retryable_download_failure "$curl_result" "$code" && (( retries < SETUP_DOWNLOAD_RETRIES )); then
            retries=$((retries + 1))
            remaining=$((SETUP_DOWNLOAD_TIMEOUT_S - (SECONDS - started)))
            (( remaining > 0 )) || _setup_die 1 '下载总时间超过预算'
            printf '官方请求暂时失败，重试 %s/%s。\n' "$retries" "$SETUP_DOWNLOAD_RETRIES" >&2
            timeout "$remaining" sleep 1 || _setup_die 1 '下载总时间超过预算'
            continue
        fi
        (( curl_result == 0 )) || _setup_die 1 "官方文件下载失败（curl退出码$curl_result）；重试预算已用尽或错误不可重试，请检查网络、代理或手动安装"
        [[ $(stat -c %s -- "$destination") -le $limit ]] || _setup_die 1 '下载超过大小上限'
        if [[ $code == 403 || $code == 429 ]]; then
            _setup_die 1 "官方下载被拒绝或限流（HTTP $code）；请检查网络/代理或稍后重试，也可手动安装固定版本并核验SHA256，未发布工具"
        fi
        if [[ $code == 200 ]]; then return 0; fi
        [[ $code =~ ^30[12378]$ && $redirect != "$response" ]] || _setup_die 1 "官方下载HTTP状态$code；未发布工具，请检查来源或手动安装"
        url=$redirect
        redirects=$((redirects + 1))
    done
    _setup_die 1 '下载重定向超过上限'
}

# 仅重试传输/握手类故障和选定5xx；证书校验失败、其他本地错误及所有4xx立即停止。
_retryable_download_failure() {
    [[ $2 != 4?? ]] || return 1
    case "$1:$2" in
        5:*|6:*|7:*|18:*|28:*|35:*|52:*|55:*|56:*|92:*|0:500|0:502|0:503|0:504) return 0 ;;
        *) return 1 ;;
    esac
}

# Node尚未可用时使用GNU tar只读清单；路径与链接必须留在解包根，大小先累计后解包。
_check_tool_archive() {
    local archive=$1 destination=$2 strip=${3:-1} name line mode target resolved total
    timeout "$SETUP_DOWNLOAD_TIMEOUT_S" tar -tzf "$archive" | head -c "$((SETUP_METADATA_MAX_BYTES + 1))" > "$workspace/archive.names" || _setup_die 1 '归档清单不可读'
    [[ $(stat -c %s -- "$workspace/archive.names") -le $SETUP_METADATA_MAX_BYTES ]] || _setup_die 1 '归档清单过大'
    while IFS= read -r name; do
        [[ $name =~ ^[A-Za-z0-9_./+@-]+$ && $name != /* && /$name/ != */../* ]] ||
            _setup_die 1 '归档路径越界或含不支持字符'
    done < "$workspace/archive.names"
    timeout "$SETUP_DOWNLOAD_TIMEOUT_S" tar -tvzf "$archive" | head -c "$((SETUP_METADATA_MAX_BYTES + 1))" > "$workspace/archive.details" || _setup_die 1 '归档结构不可读'
    [[ $(stat -c %s -- "$workspace/archive.details") -le $SETUP_METADATA_MAX_BYTES ]] || _setup_die 1 '归档明细过大'
    total=$(awk '{sum += $3} END {printf "%.0f", sum}' "$workspace/archive.details")
    [[ $total =~ ^[0-9]+$ && $total -le $SETUP_EXTRACT_MAX_BYTES ]] || _setup_die 1 '归档解包大小超限'
    while IFS= read -r line; do
        mode=${line:0:1}
        case $mode in
            -|d) ;;
            l|h)
                name=$(awk '{print $6}' <<< "$line")
                # 链接核验与各工具实际解包的剥层数保持一致，防止少算一层逃逸。
                if (( strip == 1 )); then name=${name#*/}; fi
                if [[ $mode == l ]]; then
                    target=${line#* -> }
                    [[ $target != /* ]] || _setup_die 1 '归档链接越界'
                    resolved=$(readlink -m -- "$destination/$(dirname -- "$name")/$target")
                else
                    target=${line#* link to }
                    [[ $target != /* ]] || _setup_die 1 '归档链接越界'
                    if (( strip == 1 )); then target=${target#*/}; fi
                    resolved=$(readlink -m -- "$destination/$target")
                fi
                [[ $resolved == "$destination/"* ]] || _setup_die 1 '归档链接越界'
                ;;
            *) _setup_die 1 '归档包含设备或特殊文件' ;;
        esac
    done < "$workspace/archive.details"
}

# 错误只包含固定阶段与修复说明，不回显环境凭据。
_setup_die() {
    printf '%s\n' "$2" >&2
    exit "$1"
}

main "$@"
