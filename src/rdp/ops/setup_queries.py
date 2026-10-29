"""一键部署的只读查询入口（第11张），不安装工具、不创建配置/账号、不迁移或启动服务。

配置复用load_config，账号存在性复用当前数据库版本闸门与sqlite3只读连接；
挂载与网卡输入使用标准库json/uuid/ipaddress解析，不引入配置校验或命令执行框架。
模块只接收findmnt/ip的元数据快照，不访问导航层、存储根内容或探测硬件。
"""

import sys
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Literal, TextIO

from rdp.infra.config import LoadedConfig, WebConfig

# 系统JSON快照的读取上限为2MiB；CLI最多多读一个字节判定超限，不无限读stdin或设备文件。
SETUP_SNAPSHOT_MAX_BYTES = 2 * 1024 * 1024


class AdministratorPresence(StrEnum):
    """管理员存在性快照；未知/损坏数据库不得归入ABSENT。

    Attributes:
        DATABASE_MISSING: 数据库普通文件尚不存在，常见于首次安装；没有创建数据库。
        ABSENT: 已迁移且版本匹配的数据库中没有administrator行。
        PRESENT: 至少有一个administrator，包含停用账号；不返回身份、口令或会话。
    """

    DATABASE_MISSING = "database_missing"
    ABSENT = "absent"
    PRESENT = "present"


@dataclass(frozen=True)
class MountedStorageCandidate:
    """供问答展示的单个挂载事实，不等于已经登记的存储根。

    Attributes:
        path: 挂载点绝对路径，不含控制字符；只作文字值，不resolve/stat或遍历。
        filesystem: findmnt报告的文件系统名，非空且至多64码点。
        uuid: ext4的规范小写UUID，来自findmnt的uuid字段；缺失/非法或其他文件系统为None。
        nfs_export: nfs/nfs4的合法服务器:导出路径，来自source字段；其他文件系统或来源非法为None。
        read_only: 内核挂载选项中的ro/rw观察值；不代表平台写许可，不输出其余挂载选项。
        unavailable_reason: None表示可供配置选择；其他值指出当前平台不支持或缺少可信来源，仍展示该行。
            不自动填造UUID，不把内核rw变成StorageRootConfig.writable=True。
    """

    path: Path
    filesystem: str
    uuid: str | None
    nfs_export: str | None
    read_only: bool
    unavailable_reason: Literal["unsupported_filesystem", "missing_uuid", "invalid_source"] | None


def validate_setup_configuration(config_file: Path, *, home: Path) -> LoadedConfig:
    """用平台唯一配置规则校验选定的已有文件或新配置候选。

    Args:
        config_file: 存在的普通配置文件绝对路径；必须显式提供，不因缺失改用默认配置。
        home: 用于展开配置内~/路径的用户home绝对路径；测试为临时目录。

    Returns:
        load_config的LoadedConfig，source为传入文件，used_defaults=False；保持平台模型及默认值，
        调用方可读取规范化状态路径、Web设置、存储登记及GPU列表，不复制配置验证规则。

    Raises:
        ValueError: 路径形式、TOML、未知字段或任一配置约束非法，沿用load_config的安全字段诊断。
        FileNotFoundError: 显式配置文件不存在，不返回默认配置冒充已通过。
        OSError: 文件不是可读普通文件或读取失败；不自动修复权限或创建目录。

    Side Effects:
        无（只读选定配置）；不initialize_state、不调用git/systemctl/findmnt/nvidia-smi，
        不检查导航层/存储根的实际存在性，不修改文件、环境变量、日志或数据库。

    Time Semantics:
        同步检查一次，规则和缺省值来自运行本函数的目标提交；无时钟、等待或自动重试。
    """
    raise NotImplementedError


def administrator_presence(database: Path) -> AdministratorPresence:
    """只读区分首次安装缺库、无管理员和已有管理员。

    Args:
        database: 已由配置确定的绝对本地SQLite文件路径；不接受目录、软链接或URI文本。

    Returns:
        文件确实不存在为DATABASE_MISSING；已有文件先通过check_database_version，
        有任意administrator行（包括disabled）为PRESENT，否则ABSENT；查询最多取一行。
        空文件、无版本、旧版本、损坏库都不是ABSENT。

    Raises:
        InputError: 数据库路径、版本或存量结构不合法；版本不匹配提示匹配代码并运行migrate。
        ConflictError: 版本检查或只读查询的SQLite锁等待超出既有预算。
        ExternalError: 文件类型、权限或数据库读取I/O失败，不伪装成没有管理员。
        DefectError: 固定查询、迁移图或连接配置错误。

    Side Effects:
        无业务写入；已有库用sqlite3 mode=ro及query_only，finally关闭连接，不创建数据库或表，
        不设journal_mode、不读口令哈希/会话令牌、不更新账号或审计；SQLite可维护自身WAL/SHM协调文件。
        缺失路径先返回显式缺库状态，不打开可写连接。

    Time Semantics:
        单次锁预算复用BUSY_TIMEOUT_MS；结果只代表查询时快照，不预留首管理员创建资格，
        真正创建仍由既有create_first_admin事务再次检查，不按这个布尔事实跳过领域约束。
    """
    raise NotImplementedError


def mounted_storage_candidates(findmnt_json: str) -> tuple[MountedStorageCandidate, ...]:
    """把findmnt元数据转换为可展示的挂载候选，不访问候选路径。

    Args:
        findmnt_json: findmnt --json --list --output TARGET,SOURCE,FSTYPE,UUID,OPTIONS的完整UTF-8文本快照；
            编码后至多SETUP_SNAPSHOT_MAX_BYTES，filesystems为数组，最多4096行；每行必须有完整字段。
            不接受缺失或相互矛盾的ro/rw选项；UUID与来源只允许从输入元数据取得。

    Returns:
        按挂载点文字排序的不可变元组，允许空；每个挂载点唯一，重复记录拒绝而不猜叠层关系。
        ext4有合法UUID、nfs/nfs4有合法导出来源才可选择；其他文件系统和缺来源仍显示不可选原因。
        UUID仅规范化大小写/标准连字符表示，不从设备名、路径或哈希推导；其余挂载选项不返回。

    Raises:
        ValueError: JSON形状、大小、数量、路径、字段类型或ro/rw不合法；消息只指出字段和规则，
            不回显完整JSON、挂载选项或不可信来源文本。

    Side Effects:
        无；纯解析，不调用findmnt、不读取/proc、不stat挂载点，不写配置或登记存储根。
        只提供内核只读事实；平台可写许可由用户显式选择并由原配置模型校验。

    Time Semantics:
        不读时钟；候选仅代表采集时刻，不能替代worker执行前的挂载身份检查。
    """
    raise NotImplementedError


def accessible_urls(settings: WebConfig, interface_json: str) -> tuple[str, ...]:
    """按实际监听范围生成本机和网卡候选HTTP地址，不探测网络可达性。

    Args:
        settings: 平台已校验的WebConfig，port为1-65535；不接受浏览器传入地址或额外协议。
        interface_json: ip -j address show的JSON数组快照，编码后至多SETUP_SNAPSHOT_MAX_BYTES、
            最多4096个地址；使用ifname和addr_info中的family/local/scope，忽略其他字段。

    Returns:
        不重复的http://地址:端口/元组；本机回环优先，其余按地址族和IP数值排序。
        0.0.0.0返回127.0.0.1及有效IPv4单播网卡地址，::返回::1及有效IPv6单播地址；
        不把未指定地址或组播地址当访问地址。显式IP/主机名只返回该监听地址，不把其他网卡假装可达。
        IPv6带方括号，链路本地地址含百分号编码的接口scope；主机名不做DNS解析。
        列表不承诺路由、防火墙或远端连通性；没有非回环地址仍保留本机访问入口。

    Raises:
        ValueError: JSON大小、数量、结构、接口名或地址与family不符，或host不能形成合法URL；
            不把异常快照当成“机器没有网卡”，不回显完整输入。

    Side Effects:
        无；纯映射，不调用ip、不解析DNS、不创建socket、不发HTTP请求、不修改防火墙。

    Time Semantics:
        同步生成当前快照的候选地址；不等待、不重试，不缓存跨次部署的网卡信息。
    """
    raise NotImplementedError


def run_setup_query(argv: Sequence[str], *, home: Path, stdout: TextIO, stderr: TextIO) -> int:
    """把部署需要的只读查询暴露为稳定JSON命令，不扩展业务CLI。

    Args:
        argv: 不含程序名的参数；命令为validate-config --config FILE、administrator --database FILE、
            mounts --input FILE或urls --config FILE --input FILE；各命令及顶层支持--help。
        home: 显式绝对home，供配置路径展开；不从另一个账号发现路径。
        stdout: 帮助或成功JSON输出流；不含口令、哈希、cookie或整个环境。
        stderr: 参数/失败诊断流；没有日志配置也可使用，不把原始JSON或配置全文带入异常文本。

    Returns:
        成功/帮助0、参数错误2、查询或校验失败1，不调用sys.exit。
        成功输出一行UTF-8 JSON加换行：validate-config仅含config_file/state_dir/nav_root/web/
        gpus/storage_roots安全白名单；administrator为{"status":枚举值}；mounts为{"items":候选数组}；
        urls为{"urls":地址数组}。Path转文字，枚举转值，None转null；失败stdout不输出半份结果。

    Raises:
        OSError: stdout/stderr自身写入失败，调用方决定进程失败，不假报查询成功。
        BaseException: 进程终止/中断原样传播；不把取消伪装成不存在管理员。

    Side Effects:
        仅解析argv、读取明确配置/数据库/JSON快照并输出；输入文件最多有界读取上限加一字节，
        不等待stdin，不创建目录、下载依赖、迁移、启动服务或执行业务写入。
        错误沿用平台诊断类别或安全校验说明，未知故障只给类别，不输出秘密载荷。

    Time Semantics:
        配置/快照同步读取；数据库预算沿用administrator_presence；无无限等待或自动重试。
    """
    raise NotImplementedError


def main(argv: Sequence[str] | None = None) -> int:
    """为python -m rdp.ops.setup_queries绑定本地只读查询的进程输入输出。

    Args:
        argv: 不含程序名的参数；None读取sys.argv[1:]，显式空序列不回退到进程参数。

    Returns:
        run_setup_query的原样退出码，由模块包装器sys.exit交还shell。

    Raises:
        OSError: 标准流或home解析失败；不创建替代路径。
        BaseException: 查询入口未处理的进程级终止原样传播。

    Side Effects:
        调用时绑定Path.home与标准流；导入模块不访问home或文件。
        除查询契约允许的只读文件/数据库访问外，不安装或配置平台，不改变环境变量。

    Time Semantics:
        只运行一次，不后台化、不轮询；查询返回后立即交还退出码。
    """
    raise NotImplementedError


if __name__ == "__main__":
    sys.exit(main())
