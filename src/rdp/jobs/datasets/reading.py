"""导航读取与纯解析（领域层，M1-01、11 Q6/Q8），不写导航，不读取链接目标。

目录/文件使用 os.scandir、os.readlink、带 O_NOFOLLOW 的目录相对打开；JSON 用标准库 json。
项目特有的字段投影和路径推导由本模块维护，不能用严格新 schema 拒绝已有未知字段。
"""

from collections.abc import Callable
from pathlib import Path

from rdp.jobs.datasets.types import (
    EntryLocation,
    EntrySnapshot,
    JsonDocument,
    Link,
    NavigationCatalog,
)


def discover_entries(nav_root: Path) -> NavigationCatalog:
    """枚举登记视图的全部入口，并报告未知顶层项和格式目录。

    Args:
        nav_root: 注入的绝对导航目录，路径分量不得为软链接，必须已存在。

    Returns:
        路径升序的 NavigationCatalog；lerobot 多一层版本目录，空版本目录不产生入口。
        非数据集登记目录只识别名字，完全不进入；未知顶层文件或目录均产生需要处理发现。
        顶层、视图、格式、版本或入口层的软链接不跟随，记录 NAV_UNSAFE_DIRECTORY。

    Raises:
        InputError: 根非绝对路径、含 ..、项数超过 MAX_SCAN_ENTRIES 或目录结构不安全。
        ExternalError: 根/必需视图或已登记视图目录无法枚举，不能把读取失败当空导航。

    Side Effects:
        无（只读导航目录本身；不扫描存储根，不修改登记表或目录）。

    Time Semantics:
        同步一次枚举，不等待目录出现、不重试；worker 第一段持写锁调用，Web只读调用允许观察漂移。
    """
    raise NotImplementedError


def parse_document(location: EntryLocation, name: str, content: bytes) -> JsonDocument:
    """按已有宽松读取契约解析一份导航 JSON，保留未知字段和原始摘要。

    Args:
        location: 已按目录位置确定的入口。
        name: REQUIRED_DOCUMENTS 中一项，不接受来源.json。
        content: 原始 UTF-8 JSON 字节，长度不超过 MAX_DOCUMENT_BYTES，允许零字节但会报解析发现。

    Returns:
        可用对象或 payload=None 加需要处理诊断；缺 schema_version 当1，不把该键写回原对象。
        未知版本（包括bool）、非法 UTF-8/JSON、非有限JSON数值、非对象、缺依赖字段或类型错误使整份不可用。
        原始路径依赖 dataset_id/name/roots、links 的 name/source_path/source_type、
        sources 的 source_id/original_path/direct_path；信息依赖 dataset_id 和 fields 的
        number/name/value_markdown 结构；子任务只依赖 schema_version/dataset_id。
        未知字段原样保留；省略 version 与 null 的等价只作用于投影和比较，不改变 payload。

    Raises:
        InputError: name 不受支持、位置形状错误或字节数越界；坏 JSON 本身以发现返回。

    Side Effects:
        无；纯解析及 hashlib 原字节哈希，不查任何路径是否存在，不记录整份载荷。

    Time Semantics:
        不取时钟，相同字节及位置产生相同解析结果；不使用文件修改时刻推测内容。
    """
    raise NotImplementedError


def read_entry(
    nav_root: Path, location: EntryLocation, *, checkpoint: Callable[[], None]
) -> EntrySnapshot:
    """读取一个入口的三份 JSON 并投影有效字段，坏文件仍保留入口身份。

    Args:
        nav_root: 绝对导航根，所有路径分量必须是普通目录。
        location: discover_entries 返回的位置，不得逃逸 nav_root。
        checkpoint: 每文件/读块边界调用的控制检查点，不能省略。

    Returns:
        EntrySnapshot，三份文件缺失、打不开、非普通文件或 parse_document 拒绝时逐份记录发现。
        一份失败不丢弃其余文件；全部失败仍返回按目录名可展示的入口，dataset_id=None。
        links/source.entry_path 由位置推导，JSON 原值留给面板核对；来源.json 只看目录项有无。
        第4项取不出记录值时 recorded_size_bytes=None 并添加 RECORDED_SIZE_MISSING 提示。

    Raises:
        InputError: location 越界、目录项数量超过 MAX_ENTRY_MEMBERS 或调用参数非法。
        ExternalError: 入口目录本身无法枚举；调用扫描器保留目录占位并计失败入口。
        JobCancelledError: 检查点在非锁保护区收到取消。
        WorkerStoppingError: 检查点在非锁保护区收到停止。

    Side Effects:
        无（只读取导航层普通文件和链接自身，O_NOFOLLOW 防止 JSON 软链接指向存储根）。
        单文件超过 MAX_DOCUMENT_BYTES 按该文件不可用诊断返回，不无限分配内存。

    Time Semantics:
        worker 持导航锁调用；每文件单次尝试，文件在读取期间消失也按不可用返回，无重试。
    """
    raise NotImplementedError


def derive_source_entry_path(
    location: EntryLocation, direct_path: str, links: tuple[Link, ...]
) -> str:
    """由已声明链接推导数据块入口路径，保留链接够不着的数据块绝对路径。

    Args:
        location: 来源入口的已验证位置。
        direct_path: 非空绝对路径文本，不检查磁盘存在性。
        links: 同入口声明的链接元组，空集合合法，顺序为 JSON 顺序。

    Returns:
        覆盖 direct_path 的最长完整路径分量前缀对应的导航路径；相同长度按链接名排序选首个。
        无覆盖时原样返回 direct_path（alpha 的历史失效数据块）；相似字符串前缀不算覆盖。

    Raises:
        InputError: 位置或声明路径非绝对、包含 NUL，或 links 不属于此入口。

    Side Effects:
        无；只计算字符串分量，不调用 resolve/exists，不修正 original_path。

    Time Semantics:
        纯函数，无时间输入；输入来自同一次入口读取，不混用两个视图的链接集合。
    """
    raise NotImplementedError


def extract_recorded_size(information: JsonDocument) -> int | None:
    """从信息第4项提取10-12记录的字节数，不解析其他 Markdown 内容。

    Args:
        information: 数据集信息.json 的读取结果，payload=None 表示不可用。

    Returns:
        number=4 且 name=数据大小的唯一项中首个“（N B；”的非负十进制整数，单位字节；
        没有该项、重复该项、格式不匹配或大于 SQLite 有符号64位最大值时 None。
        不拿后面的单位换算值替代，不从另外13项猜测大小；None 的提示由 read_entry 生成。

    Raises:
        InputError: 传入其他种类的文档，调用职责错误。

    Side Effects:
        无；只读已解析对象，不修改 Markdown 或读取统计大小。

    Time Semantics:
        值属于2026-10-12记录，不是扫描时刻的测量；不取当前时间。
    """
    raise NotImplementedError
