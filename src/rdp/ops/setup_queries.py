"""一键部署的只读查询入口（第11张），不安装工具、不创建配置/账号、不迁移或启动服务。

配置复用load_config，账号存在性复用当前数据库版本闸门与sqlite3只读连接；
挂载与网卡输入使用标准库json/uuid/ipaddress解析，不引入配置校验或命令执行框架。
模块只接收findmnt/ip的元数据快照，不访问导航层、存储根内容或探测硬件。
"""

import argparse
import json
import os
import re
import sqlite3
import stat
import sys
from collections import Counter
from collections.abc import Sequence
from contextlib import closing, redirect_stderr, redirect_stdout
from dataclasses import asdict, dataclass, replace
from enum import StrEnum
from ipaddress import IPv4Address, IPv6Address, ip_address
from pathlib import Path
from typing import Any, Literal, TextIO, cast
from urllib.parse import quote
from uuid import UUID

from rdp.infra.config import LoadedConfig, PlatformConfig, StorageRootConfig, WebConfig, load_config
from rdp.infra.db._errors import database_path_error, database_problem
from rdp.infra.db.connection import BUSY_TIMEOUT_MS, translate_database_error
from rdp.infra.db.migration import check_database_version
from rdp.infra.diagnostics import (
    ConflictError,
    DefectError,
    ExternalError,
    InputError,
    render_diagnostic,
)

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
            同一挂载点重复出现时为stacked_mount，所有层均不可选。
            不自动填造UUID，不把内核rw变成StorageRootConfig.writable=True。
    """

    path: Path
    filesystem: str
    uuid: str | None
    nfs_export: str | None
    read_only: bool
    unavailable_reason: (
        Literal["unsupported_filesystem", "missing_uuid", "invalid_source", "stacked_mount"] | None
    )


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
    PlatformConfig.validate_state_dir(config_file)
    PlatformConfig.validate_state_dir(home)
    if not stat.S_ISREG(config_file.lstat().st_mode):
        raise OSError("配置必须为普通文件", str(config_file))
    return load_config(environ={"RDP_CONFIG": str(config_file)}, home=home)


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
    if problem := database_path_error(database):
        raise problem
    try:
        try:
            mode = database.lstat().st_mode
        except FileNotFoundError:
            return AdministratorPresence.DATABASE_MISSING
        if not stat.S_ISREG(mode):
            problem = translate_database_error(
                OSError("数据库必须为普通文件"), database=database, operation="检查数据库类型"
            )
            raise problem
        check_database_version(database)
        with closing(
            sqlite3.connect(
                database.as_uri() + "?mode=ro", uri=True, timeout=BUSY_TIMEOUT_MS / 1000
            )
        ) as connection:
            connection.execute("PRAGMA query_only=ON")
            # 版本匹配仍不能把缺失业务表解释成没有管理员。
            columns = connection.execute("PRAGMA table_info(accounts)").fetchall()
            if not any(row[1] == "role" for row in columns):
                problem = database_problem(InputError, database, "查询管理员结构", 0)
                raise problem
            row = connection.execute(
                "SELECT 1 FROM accounts WHERE role='administrator' LIMIT 1"
            ).fetchone()
        return AdministratorPresence.PRESENT if row else AdministratorPresence.ABSENT
    except (sqlite3.Error, OSError) as error:
        problem = translate_database_error(error, database=database, operation="查询管理员")
        raise problem from error


def mounted_storage_candidates(findmnt_json: str) -> tuple[MountedStorageCandidate, ...]:
    """把findmnt元数据转换为可展示的挂载候选，不访问候选路径。

    Args:
        findmnt_json: findmnt --json --list --output TARGET,SOURCE,FSTYPE,UUID,OPTIONS的完整UTF-8文本快照；
            编码后至多SETUP_SNAPSHOT_MAX_BYTES，filesystems为数组，最多4096行；每行必须有完整字段。
            不接受缺失或相互矛盾的ro/rw选项；UUID与来源只允许从输入元数据取得。

    Returns:
        按挂载点文字排序的不可变元组，允许空；重复挂载点的所有记录均保留并标为stacked_mount，
        不猜测哪一层可见，同一挂载点内保持快照顺序。
        未叠加时，ext4有合法UUID、nfs/nfs4有合法导出来源才可选择；其他文件系统和缺来源仍显示不可选原因。
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
    data = _snapshot(findmnt_json)
    if not isinstance(data, dict):
        raise ValueError("挂载快照必须为对象")
    rows = _rows(cast(dict[str, Any], data).get("filesystems"))
    roots = tuple(_mount_candidate(_mount_row(row)) for row in rows)
    # 先完成每行校验，再标记全部叠加层；不能因不可选就吞掉坏字段，也不能猜测最后一行可见。
    counts = Counter(root.path for root in roots)
    candidates = (
        replace(root, unavailable_reason="stacked_mount") if counts[root.path] > 1 else root
        for root in roots
    )
    return tuple(sorted(candidates, key=lambda root: str(root.path)))


def _snapshot(text: str) -> Any:
    """限制快照字节数，并且不将原始载荷带入错误。"""
    if len(text.encode("utf-8")) > SETUP_SNAPSHOT_MAX_BYTES:
        raise ValueError("快照超过2MiB")
    try:
        return json.loads(text)
    except (ValueError, RecursionError) as error:
        raise ValueError("快照不是合法JSON") from error


def _rows(value: Any) -> list[Any]:
    """系统行数有界，避免元数据占用无限内存或CPU。"""
    if not isinstance(value, list) or len(cast(list[Any], value)) > 4096:
        raise ValueError("快照数组至多4096项")
    return cast(list[Any], value)


def _mount_row(value: Any) -> dict[str, Any]:
    """在来源模型前检查快照完整性，避免把坏快照误报为不可选盘。"""
    if (
        not isinstance(value, dict)
        or not {"target", "source", "fstype", "uuid", "options"} <= value.keys()
    ):
        raise ValueError("挂载字段不完整")
    value = cast(dict[str, Any], value)
    for field in ("target", "fstype", "options"):
        if (
            not isinstance(value[field], str)
            or not value[field]
            or re.search(r"[\x00-\x1f\x7f]", value[field])
        ):
            raise ValueError("挂载文字字段非法")
    for field in ("uuid", "source"):
        if value[field] is not None and not isinstance(value[field], str):
            raise ValueError("挂载来源类型非法")
    path = Path(value["target"])
    if not path.is_absolute() or ".." in path.parts or len(value["fstype"]) > 64:
        raise ValueError("挂载路径或文件系统非法")
    options = value["options"].split(",")
    if options.count("ro") + options.count("rw") != 1:
        raise ValueError("挂载选项必须恰含一个ro或rw")
    return value


def _mount_candidate(row: dict[str, Any]) -> MountedStorageCandidate:
    """仅复用平台来源校验；不支持的来源保留为不可选事实。"""
    filesystem = row["fstype"]
    uuid = None
    nfs = None
    reason: Literal["unsupported_filesystem", "missing_uuid", "invalid_source"] | None = None
    if filesystem == "ext4":
        try:
            uuid = str(UUID(row["uuid"]))
        except (ValueError, TypeError):
            reason = "missing_uuid"
    elif filesystem in ("nfs", "nfs4"):
        try:
            StorageRootConfig(name="candidate", path=Path(row["target"]), nfs_export=row["source"])
            nfs = row["source"]
        except ValueError:
            reason = "invalid_source"
    else:
        reason = "unsupported_filesystem"
    return MountedStorageCandidate(
        Path(row["target"]), filesystem, uuid, nfs, "ro" in row["options"].split(","), reason
    )


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
    interfaces = _rows(_snapshot(interface_json))
    addresses: set[IPv4Address | IPv6Address] = set()
    count = 0
    for raw_interface in interfaces:
        if not isinstance(raw_interface, dict):
            raise ValueError("网卡必须为对象")
        interface = cast(dict[str, Any], raw_interface)
        if not isinstance(interface.get("ifname"), str):
            raise ValueError("网卡缺少接口名")
        name = interface["ifname"]
        if re.fullmatch(r"[A-Za-z0-9_.:-]{1,15}", name) is None:
            raise ValueError("接口名非法")
        entries = _rows(interface.get("addr_info"))
        count += len(entries)
        if count > 4096:
            raise ValueError("网卡地址至多4096项")
        for entry in entries:
            addresses.add(_interface_address(entry, name))
    if settings.host not in ("0.0.0.0", "::"):  # noqa: S104  # 理由：只映射监听配置，不绑定端口。
        return (_http_url(settings.host, settings.port),)
    version = 4 if settings.host == "0.0.0.0" else 6  # noqa: S104  # 理由：只映射地址族，不监听。
    loopback = ip_address("127.0.0.1" if version == 4 else "::1")
    selected = sorted(
        (
            a
            for a in addresses
            if a.version == version
            and a != loopback
            and not a.is_unspecified
            and not a.is_multicast
        ),
        key=lambda a: (int(a), str(a)),
    )
    return tuple(_http_url(str(a), settings.port) for a in (loopback, *selected))


def _interface_address(entry: Any, name: str) -> IPv4Address | IPv6Address:
    """验证IP族与来源形状，链路本地区域来自接口名而非用户载荷。"""
    if not isinstance(entry, dict):
        raise ValueError("网卡地址必须为对象")
    entry = cast(dict[str, Any], entry)
    if not all(isinstance(entry.get(k), str) for k in ("local", "family", "scope")):
        raise ValueError("网卡地址字段非法")
    try:
        if "%" in entry["local"]:
            raise ValueError("地址不应自带区域")
        address = ip_address(entry["local"])
    except ValueError as error:
        raise ValueError("网卡IP地址非法") from error
    if entry["family"] != ("inet" if address.version == 4 else "inet6"):
        raise ValueError("网卡地址与family不符")
    if address.version == 6 and address.is_link_local:
        address = ip_address(f"{address}%{name}")
    return address


def _http_url(host: str, port: int) -> str:
    """IPv6的区域标识只作URL编码，绝不解析DNS。"""
    if ":" in host:
        try:
            ip_address(host)
        except ValueError as error:
            raise ValueError("监听IPv6地址非法") from error
    elif re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9.])?", host) is None:
        raise ValueError("监听主机名非法")
    authority = f"[{quote(host, safe=':')}]" if ":" in host else host
    return f"http://{authority}:{port}/"


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
    parser = argparse.ArgumentParser(prog="rdp-setup-query")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("validate-config", "administrator", "mounts", "urls"):
        sub = commands.add_parser(name)
        if name in ("validate-config", "urls"):
            sub.add_argument("--config", type=Path, required=True)
        if name in ("mounts", "urls"):
            sub.add_argument("--input", type=Path, required=True)
        if name == "administrator":
            sub.add_argument("--database", type=Path, required=True)
    try:
        with redirect_stdout(stdout), redirect_stderr(stderr):
            args = parser.parse_args(argv)
    except SystemExit as error:
        return int(error.code or 0)
    try:
        result = _query_result(args, home)
    except (InputError, ConflictError, ExternalError, DefectError) as error:
        stderr.write(f"查询失败：{type(error).__name__}\n")
        for diagnostic in error.diagnostics:
            stderr.write(render_diagnostic(diagnostic) + "\n")
        return 1
    except (ValueError, OSError) as error:
        stderr.write(f"查询失败：{type(error).__name__}；{error}\n")
        return 1
    except Exception as error:
        stderr.write(f"查询失败：{type(error).__name__}\n")
        return 1
    stdout.write(json.dumps(result, ensure_ascii=False, default=str) + "\n")
    return 0


def _read_snapshot(path: Path) -> str:
    """用非阻塞描述符和fstat拒绝设备/FIFO；最多读取上限加一字节。"""
    descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    with os.fdopen(descriptor, "rb") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValueError("快照必须为普通文件")
        data = stream.read(SETUP_SNAPSHOT_MAX_BYTES + 1)
    if len(data) > SETUP_SNAPSHOT_MAX_BYTES:
        raise ValueError("快照超过2MiB")
    return data.decode("utf-8")


def _query_result(args: argparse.Namespace, home: Path) -> dict[str, Any]:
    """在完整查询成功后生成白名单对象，避免输出部分结果。"""
    if args.command == "administrator":
        return {"status": administrator_presence(args.database)}
    if args.command == "mounts":
        return {
            "items": [
                asdict(item) for item in mounted_storage_candidates(_read_snapshot(args.input))
            ]
        }
    loaded = validate_setup_configuration(args.config, home=home)
    if args.command == "urls":
        return {"urls": accessible_urls(loaded.config.web, _read_snapshot(args.input))}
    config = loaded.config
    return {
        "config_file": str(loaded.source),
        "state_dir": str(config.state_dir),
        "nav_root": str(config.nav_root),
        "web": config.web.model_dump(mode="json"),
        "gpus": config.jobs.gpus,
        "storage_roots": [root.model_dump(mode="json") for root in config.storage_roots],
    }


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
    return run_setup_query(
        sys.argv[1:] if argv is None else argv,
        home=Path.home(),
        stdout=sys.stdout,
        stderr=sys.stderr,
    )


if __name__ == "__main__":
    sys.exit(main())
