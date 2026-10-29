#!/usr/bin/env bash
# 第11张的一键部署编排；只组合工具引导、只读查询和既有install/账号入口，不复制业务规则。
# 工具使用官方发行包，JSON由Node内置JSON解析，文件发布用同盘暂存+原子rename；不引入jq或安装框架。
set -euo pipefail

# 自动安装版本唯一来源；Python由uv读取目标提交的requires-python/uv.lock，不另设Python版本。
# package.json没有engines/packageManager字段；这里采用负责人提供的已验证工具版本，Node满足锁定Vite/Vitest要求。
declare -Ar SETUP_TOOL_VERSIONS=([node]='22.23.2' [uv]='0.13.5' [pnpm]='11.22.0')
# 仅Linux/glibc；下载名由这两份明确映射构造，不猜未知CPU的兼容二进制。
declare -Ar SETUP_NODE_ARCH=([x86_64]='x64' [aarch64]='arm64')
declare -Ar SETUP_UV_TARGET=([x86_64]='x86_64-unknown-linux-gnu' [aarch64]='aarch64-unknown-linux-gnu')
declare -Ar SETUP_PNPM_ARCH=([x86_64]='x64' [aarch64]='arm64')
readonly SETUP_NODE_ORIGIN='https://nodejs.org'
readonly SETUP_GITHUB_ORIGIN='https://api.github.com'
# GitHub资产API的HTTPS下载重定向白名单；不能使用响应体提供的任意镜像。
readonly SETUP_GITHUB_ASSET_HOSTS='release-assets.githubusercontent.com objects.githubusercontent.com'
# 单位秒；单次下载最多300秒，至多重试2次，每次连接预算10秒，不无限等待。
readonly SETUP_CONNECT_TIMEOUT_S=10 SETUP_DOWNLOAD_TIMEOUT_S=300 SETUP_DOWNLOAD_RETRIES=2
# 元数据最多2MiB，单个工具压缩包最多512MiB，解包总量最多1GiB；超限先拒绝，不执行下载内容。
readonly SETUP_METADATA_MAX_BYTES=2097152 SETUP_ARCHIVE_MAX_BYTES=536870912 SETUP_EXTRACT_MAX_BYTES=1073741824
# 健康检查只走本机，不经过代理；12次各最多5秒，中间间隔1秒，总等待约71秒加进程调度开销。
readonly SETUP_HEALTH_ATTEMPTS=12 SETUP_HEALTH_TIMEOUT_S=5 SETUP_HEALTH_INTERVAL_S=1
# 前台监管停止预算，单位秒，与已批准用户单元相同；超时报告失败并回收本脚本拥有的子进程。
readonly SETUP_WEB_STOP_TIMEOUT_S=360 SETUP_WORKER_STOP_TIMEOUT_S=45

# --help完整文本契约（实现时usage输出这些内容，版本数值引用上面的唯一版本表）：
# 用法：bash scripts/setup.sh [--config FILE] [--deploy-dir DIR] [--commit REF]
#                            [--yes] [--no-systemd] [--skip-admin] [--help]
# --config FILE：配置文件；优先于非空RDP_CONFIG，再优先于$HOME/.config/rdp/config.toml。
#   接受绝对路径或~/前缀，拒绝控制字符；显式指定的文件不存在时，有终端可问答新建，无终端报错。
#   已存在配置只读取和校验，绝不覆盖；文件形式/平台校验不合格时停下，不写回修正。
# --deploy-dir DIR：默认$HOME/.local/opt/rdp；安装时透传给install.sh。
#   目录须符合install.sh要求；不是完整安装的既有目录拒绝覆盖，保留现场供人工处理。
# --commit REF：默认本地main；解析为完整提交后用于校验环境和install.sh，确保使用同一版本。
#   从BASH_SOURCE定位仓库；不clone、不fetch、不pull，也不改变当前开发工作区。
#   目标提交须含setup_queries只读入口；缺该入口的旧提交会明确拒绝，不借用另一版本的校验器。
# --yes：自动同意工具下载安装、启用linger和最后的部署确认；默认逐项询问，默认答案为否。
#   不代答配置字段、存储写许可或管理员口令，不允许覆盖既有配置/工具，不把已有部署自动升级。
# --no-systemd：不检查或调用systemctl/loginctl，不安装用户单元，不改变linger。
#   install.sh仍收到--no-systemd；随后本脚本在前台监管Web/worker两个子进程，健康后持续运行。
#   Ctrl+C/SIGTERM传给本脚本拥有的两个子进程并等待收尾；任一意外退出就停止另一个并报失败。
#   不使用nohup，不脱离终端留下无人管理的后台服务；请保持本脚本运行。
# --skip-admin：显式延后首管理员创建，打印部署目录里的rdp create-admin命令；默认不跳过。
#   已有任意管理员（包括停用账号）总是跳过，不重置口令、不再添加操作日志。
# --help：只显示帮助，不探测系统、不下载、不写文件。
#
# 自动安装仅提供Linux x86_64/aarch64的glibc发行包；其他平台先退出并给手动办法，工具版本自检失败不发布。
# 必需基础工具：git、curl、tar、sha256sum、findmnt、ip、flock和常用coreutils。
# 缺这些工具只提示发行版安装办法；默认服务模式还需要可用的systemctl --user和loginctl。
# 不运行sudo，不自动安装git/systemd，不修改系统服务；可改用--no-systemd。
#
# 工具检查顺序：Node、uv、pnpm。PATH已有固定版本就复用；缺失或版本不一致时，
# 每个工具分别说明版本、官方来源、用户目录和下载副作用，确认后才安装；拒绝则停止并打印手动办法。
# Node：官方node-v<版本>-linux-<架构>.tar.gz，SHA256来自同源SHASUMS256.txt。
# uv：astral-sh/uv官方GitHub release的uv-<target>.tar.gz。
# pnpm：pnpm/pnpm官方GitHub release的pnpm-linux-<架构>独立可执行文件，不依赖corepack。
# uv/pnpm：用已就绪的Node内置JSON读取官方GitHub release metadata，精确匹配tag/asset名，
# 采用其非空digest字段中的SHA256，再从同源asset API下载；缺少有效摘要就拒绝，绝不跳过校验。
# 不curl|sh；校验完成前不解包、不执行；官方HTTPS重定向仅允许预设官方域，不接受任意下载地址。
# 下载遵守HTTPS_PROXY/HTTP_PROXY/ALL_PROXY/NO_PROXY，诊断不打印代理凭据；不使用-k。
# 安装到$HOME/.local/opt/rdp-tools/<工具>/<版本>-<平台>/，入口放$HOME/.local/bin。
# 只发布本脚本管理的入口，不覆盖该目录下用户已有的其他工具；不修改shell配置。
# PATH只在本次脚本及其子进程加入$HOME/.local/bin；结束时提示如何自行写入shell配置。
# Python及项目依赖由uv按目标提交的锁文件下载；前端依赖由install.sh中的pnpm按锁文件下载。
#
# 默认模式检查当前用户linger：关闭时说明“退出登录后用户服务可能停止、无法保证开机运行”，
# 确认后只调用loginctl enable-linger当前用户；拒绝就停下，不静默降级。
# 查询/启用失败打印可由管理员执行的sudo loginctl enable-linger <当前用户>，本脚本不执行sudo。
#
# 无配置时交互询问：监听地址（默认0.0.0.0，明确“局域网明文HTTP，可改成127.0.0.1”）、
# 端口（默认8600）、导航层绝对目录（必填、无隐藏默认）、状态目录（默认$HOME/.local/share/rdp）。
# findmnt只提供当前挂载快照，列出挂载点、文件系统、UUID/NFS来源及内核只读状态供选择；
# 不读取存储根内容、不遍历目录、不挂载、不写标记文件。无选择须显式确认空存储根列表。
# ext4的UUID来自挂载信息，不让用户猜UUID；不支持的文件系统或缺来源的条目标明原因且不可选。
# 每个根询问名字，平台写许可默认False；本地盘保持只读，仅可写挂载的NFS专属平台区允许显式选择True。
# --yes不能代替这项写许可选择；内核rw不等于平台可写。
# 有nvidia-smi时以--query-gpu=index --format=csv,noheader,nounits只查询GPU编号供选择；
# 查询最多5秒，完整十进制编号按平台范围校验，默认空列表；无该命令时写gpus=[]，不安装驱动。
# nvidia-smi存在但查询失败时说明原因并要求明确选择不用GPU；无终端则报错，不假装探测成功。
# 已有配置不因缺nvidia-smi自动改成空GPU；保留原文件并报告与启动环境的冲突。
#
# 配置校验：先git archive选定提交到本次临时目录，再uv sync --frozen --no-dev建立临时校验环境，
# 使用该环境的python -m rdp.ops.setup_queries validate-config校验候选文件。
# 此环境不迁移、不创建状态目录、不写源仓库.venv；复用uv缓存，后续安装仍调用原install.sh。
# 新配置仅在校验通过后以0600权限、原子且不覆盖的方式发布；并发出现既有配置时保留对方文件并停止。
#
# 非交互必须已有有效配置，且凡需工具安装/linger确认必须带--yes；不会等待stdin。
# 无首管理员且没有终端时必须显式--skip-admin，否则报缺少安全口令交互条件，不调用create-admin。
# 不提供明文口令参数、环境变量或自动生成口令；有终端时询问登录名（默认admin）、显示名（默认管理员），
# 再由已有rdp create-admin终端无回显读取两次口令，账号和审计仍由平台原事务写入。
# 示例：bash scripts/setup.sh --config /绝对路径/config.toml --yes --no-systemd --skip-admin
#   该命令前台监管两个服务；另开终端手工执行打印的create-admin命令后才能登录。
#
# 健康检查GET /api/health须返回200和{"status":"ok"}；0.0.0.0用127.0.0.1探测，::用::1。
# 成功后打印本机地址与各网卡候选HTTP地址；地址列表不代表已检测防火墙或外部连通性。
# 健康失败非0退出，指出实际状态目录下web.log/worker.log；只收尾本次启动的服务/子进程。
#
# 重复运行：完整部署已存在时只报告版本、服务/worker状态和升级命令，不重装、不重启、不自动升级，
# 不重新询问安装工具或改写配置；有缺陷/无法读状态时非0退出。未完成部署目录明确报错，不能误报已安装。
# 失败保留已经验证完成的工具、已发布配置、部署目录及迁移备份；清理本次下载/解包/临时校验环境，
# 校验失败的工具不进入正式目录或PATH入口。修正原因后重新运行；已有部分部署须按install.sh帮助人工处理。
# 成功0；环境/下载/配置/启动/健康失败1；参数或非交互缺输入2；并发setup占用3；部署阶段拒绝确认/取消130。
# 前台服务就绪后响应INT/TERM且两个子进程正常退出为0；停止超时或子进程意外失败为1。
usage() {
    exit 78
}

# 解析上述参数并固定优先级；只读取argv，不探测工具/文件，不读取口令；未知/缺值退出2，--help先于副作用。
parse_arguments() {
    exit 78
}

# 由BASH_SOURCE定位仓库并解析本地完整提交；检查操作系统/CPU、绝对路径及控制字符。
# 读git元数据和工具清单，不fetch、不改检出；基础工具缺失打印手动办法，未知平台或不可信路径退出1/2。
resolve_repository_and_environment() {
    exit 78
}

# 先只读识别已有完整部署（登记worktree、rdp入口、有效构建信息），调用旧rdp/status展示状态与upgrade命令。
# 不以“目录存在”冒充完整安装；已有完整部署直接结束，不再进入下载/写配置/启动；部分目录保留并退出1。
report_existing_installation() {
    exit 78
}

# 新安装在用户状态目录持非阻塞flock，冲突退出3；创建本次0700暂存目录并登记所有本次拥有的资源。
# 不chmod已有用户目录；EXIT/INT/TERM统一清理仅本次暂存与子进程，不删除正式部署、配置或完整工具。
acquire_setup_workspace() {
    exit 78
}

# Args: 工具名、固定版本、来源、目标路径；有TTY逐项问默认否，--yes直接同意，无TTY且无--yes退出2。
# 拒绝或EOF打印与该工具对应的手动下载/校验/用户目录安装办法并退出130，不能继续依赖它的步骤。
confirm_tool_installation() {
    exit 78
}

# 先确保Node：只读检查node --version；不符固定版本时先确认，再下载官方tar和同源SHASUMS256.txt。
# 精确匹配归档名及唯一64位摘要、按上限读取，校验后才检查归档条目和解包；失败不执行包内node。
# 成功输出/保存可用Node绝对路径，后续JSON解析不依赖尚未发布的全局PATH。
ensure_node() {
    exit 78
}

# Args: uv或pnpm、平台；用Node内置JSON解析官方release metadata（<=2MiB），精确校验tag、asset名、
# digest的sha256算法/64位值及下载URL归属；不执行JSON、不正则猜hash，缺摘要/歧义/HTTP错误立即失败。
# metadata路径为/repos/astral-sh/uv/releases/tags/<版本>与/repos/pnpm/pnpm/releases/tags/v<版本>；
# 下载精确匹配asset的同源API URL并使用Accept: application/octet-stream，不信任任意body URL。
read_official_release_digest() {
    exit 78
}

# Args: 工具名、官方URL、期望SHA256；curl仅写本次暂存，保留代理环境且不输出凭据。
# 限制HTTPS域、重定向、时间、大小和重试；sha256sum不符时删除本次下载，退出1，不解包/执行/发布。
download_and_verify_tool() {
    exit 78
}

# Args: 已校验工具、目标目录；只在暂存检查条目路径、链接逃逸、解包大小、可执行文件及--version。
# 完整内容同盘原子发布，权限不扩大；仅替换带本脚本归属记录的入口，碰到用户自有文件即停止。
# 发布失败清理本次半成品，保留旧工具/入口；不删除已成功安装的其他工具，不改shell rc或系统目录。
publish_user_tool() {
    exit 78
}

# Node先于uv/pnpm元数据解析；逐个询问且仅选择顶部固定版本，全部成功后仅给本次进程树加PATH。
# uv用官方tar包，pnpm用官方独立二进制；Python留给uv按锁文件安装，不自行选择Python版本。
ensure_user_toolchain() {
    exit 78
}

# 默认模式读systemctl --user与loginctl当前用户Linger；--no-systemd完全跳过这两个命令。
# 缺命令/用户总线不可用只提示；Linger=no说明后果后确认，--yes可授权enable-linger当前用户。
# 拒绝停止；失败打印管理员命令并退出1，不运行sudo、不操作其他用户或系统服务。
ensure_user_service_environment() {
    exit 78
}

# git archive所选完整提交到本次临时目录，uv按该提交pyproject/uv.lock建隔离的无dev依赖校验环境。
# 显式UV_PROJECT_ENVIRONMENT指向临时目录，清VIRTUAL_ENV，不改源仓库.venv；Python由uv自动取得。
# 只运行该提交的setup_queries模块，缺模块/锁不一致/同步失败则停止；不偷用另一提交的校验规则。
prepare_validation_runtime() {
    exit 78
}

# 读取--config/RDP_CONFIG/默认文件的选定来源；存在只校验，不写回，不把显式缺失文件静默当默认配置。
# 缺失且无TTY退出2；有TTY按help问host/port/nav/state，findmnt JSON经只读查询解析，GPU用有界只读查询。
# findmnt与ip输出只写本次有界快照文件（最多2MiB加一字节判超限），命令最多5秒，不等待存储响应。
# 所有读取仅限配置、系统挂载元数据和工具输出，不触碰导航层/存储根内容；失败保留既有配置。
collect_configuration_answers() {
    exit 78
}

# Args: 问答快照；Node JSON.stringify负责TOML基本字符串转义，不拼接可执行shell文本。
# 写本次0600候选文件，平台load_config做唯一权威校验；成功后原子“不覆盖”发布到选定配置路径。
# 发布前后保持同一候选，目标竞争/校验失败不覆盖任何已有文件；不mkdir导航层或存储根。
validate_and_publish_configuration() {
    exit 78
}

# 用临时校验环境只读查询管理员状态，missing_database与absent明确区分；停用管理员也算present。
# 无TTY且需要首号又未--skip-admin时，在调用install.sh前报错，不把--yes当口令输入授权。
# 不查询口令哈希、不创建账号、不写会话/审计；坏库/版本错误不当作“没有管理员”。
check_administrator_input_requirements() {
    exit 78
}

# 以argv数组调用仓库的install.sh，透传--deploy-dir、解析后的--commit以及--no-systemd；
# RDP_CONFIG明确指向已验证的选定文件，同一配置用于迁移、服务和后续只读查询。
# 不改变install.sh语义，不自行再建worktree/迁移/写单元；非零立即停，保留其失败现场和备份。
# 默认模式在install成功时即登记本次服务拥有关系，确保后续建管理员失败也能收尾已启动服务。
install_platform() {
    exit 78
}

# 安装后用部署自身的setup_queries再查管理员；present跳过，absent且未skip才询问名字并调用已有create-admin。
# 密码由该命令在TTY里无回显读两次，不经argv/env/日志；失败停止，不新增第二条审计，不自动重置账号。
# 数据库意外缺失或损坏属于失败；并发创建仍由既有账号事务裁决，不把任意失败当“已有人创建”。
ensure_first_administrator() {
    exit 78
}

# 默认模式确认本次安装的两个用户服务状态；--no-systemd才启动部署自己的web/worker并保留PID及拥有关系。
# 子进程使用同一HOME/RDP_CONFIG/PATH，不安装真实信号处理器到测试进程；启动失败只停止本次拥有的服务。
start_platform_services() {
    exit 78
}

# 对配置对应本机地址GET /api/health，禁用代理仅用于这个本机探测；有限次数/单次超时见顶部常量。
# 校验HTTP 200和JSON status=ok后才打印成功；失败退出1，明确web.log/worker.log实际位置并收尾本次启动。
verify_platform_health() {
    exit 78
}

# ip -j address show结果交setup_queries urls；按实际监听范围打印本机及各网卡候选地址。
# 不把0.0.0.0或::作为访问URL，不进行公网探测/防火墙修改；枚举失败返回1，说明原因和本机地址，
# 交统一失败边界收尾本次服务，不伪报已列出全部网卡或外部可达。
print_access_and_upgrade_commands() {
    exit 78
}

# 仅--no-systemd：保持前台等待本次两个子进程；不做后台daemon，不重启失败进程。
# INT/TERM请求正常停机，按顶部预算等待，超时强制回收并返回失败；其他子进程/服务不受影响。
supervise_foreground_services() {
    exit 78
}

# 保留原失败码和阶段；清本次暂存/候选/校验环境、释放锁；按拥有关系收尾子进程，不掩盖首个错误。
# 成功默认模式保留服务；前台模式正常停止后才清理；不撤销linger，不删除已发布配置、工具、部署或备份。
finish_setup() {
    exit 78
}

# 顺序：解析/只读预检与已安装识别 → 独占暂存 → 工具确认安装 → 用户服务/linger → 临时校验环境 →
# 配置问答/校验/不覆盖发布 → 非交互首号条件检查 → install.sh → 首管理员 → 服务/健康/地址 → 可选前台监管。
# 所有实现经以上函数分阶段；本入口本身不复制账号、迁移或配置校验业务。
main() {
    exit 78
}

main "$@"
