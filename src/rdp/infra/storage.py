"""存储根身份与只读访问契约（基础层，10、ADR 0006），不写数据、不决定作业结果。

Linux 系统读取、mountinfo 纯解析、挂载身份比较与 worker 访问预算分开；Web 仅持有
MountInspector，没有访问数据目录的回调。pathlib/stat/os 提供文件和设备号能力，
标准库及已批准依赖没有 mountinfo 解析器，只实现内核字段和四种转义的有限解析。
线程使用标准库 threading，设为 daemon；超时不无限 join，也无法强行结束卡死的 NFS 读取。
反复超时可能累积存活线程，待 NAS 挂载事实明确后另定进程隔离或挂载策略。
检查只反映当时状态，不能保证随后实际 I/O 仍在线，更不授予任何目录写权限。
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path

from rdp.infra.config import StorageConfig, StorageRootConfig

# Linux 适配器的系统路径集中于此；业务判断只依赖回调，测试用临时文件替换。
DEFAULT_MOUNTINFO_PATH = Path("/proc/self/mountinfo")
DEFAULT_UUID_DIRECTORY = Path("/dev/disk/by-uuid")


class OfflineReason(StrEnum):
    """存储根离线的三种业务原因；读取基础设施失败不伪装成其中任一种。"""

    NOT_MOUNTED = "not_mounted"
    SOURCE_MISMATCH = "source_mismatch"
    TIMEOUT = "timeout"


@dataclass(frozen=True)
class DeviceNumber:
    """Linux 块设备身份，不依赖设备节点名字或别名。

    Attributes:
        major: 非负整数主设备号，无单位。
        minor: 非负整数次设备号，无单位。
    """

    major: int
    minor: int


@dataclass(frozen=True)
class MountRecord:
    """挂载表里一条记录的最小身份信息，不包含原文或敏感挂载选项。

    Attributes:
        mount_point: 解码后的绝对挂载点；不 resolve，不访问该路径。
        device: mountinfo 第三列的主次设备号。
        filesystem: 分隔符后第一列文件系统类型，区分 ext4/nfs/nfs4。
        source: 分隔符后第二列的解码来源文本，不按设备节点名字比较 ext4。
    """

    mount_point: Path
    device: DeviceNumber
    filesystem: str
    source: str


@dataclass(frozen=True)
class StorageRootStatus:
    """一个登记根的一次观察，不持久化为数据集事实。

    Attributes:
        name: 已校验配置名。
        path: 登记的绝对路径，无文件访问。
        writable: 平台登记的写许可。
        online: True 表示本次检查通过，False 表示离线。
        reason: 在线必须为 None，离线必须为 OfflineReason；TIMEOUT 仅由 worker 返回。
        checked_at: 检查结束时注入时钟的 aware UTC 时刻，不是读取开始时刻。
    """

    name: str
    path: Path
    writable: bool
    online: bool
    reason: OfflineReason | None
    checked_at: datetime


def parse_mountinfo(text: str) -> tuple[MountRecord, ...]:
    r"""把 Linux mountinfo 文本解析成每个挂载点最后一条有效记录。

    Args:
        text: 一次完整挂载表文本，空文本合法；字段以空格分隔，可有可选字段和结尾换行。
            挂载点和来源只单次解码内核的 \040、\011、\012、\134，禁止递归解码。

    Returns:
        按最后出现行的顺序排列的不可变元组；同挂载点叠层只留最后一条，空表为空。
        正确跳过分隔符前可选字段，不把来源中的转义空格当作列分隔。

    Raises:
        ValueError: 非空行缺必需列或独立的 - 分隔符，设备号不是非负整数，
            挂载点非绝对、字段含非法转义或记录形状损坏；不跳过坏行继续猜在线。

    Side Effects:
        无；纯解析，不读取文件系统，不记录挂载表原文。

    Time Semantics:
        不取时钟，无等待；输入由调用者在一次读取中提供。
    """
    raise NotImplementedError


@dataclass(frozen=True)
class LinuxMountSource:
    """Linux 只读系统适配器，不在构造时探测系统状态。

    Attributes:
        mountinfo_path: 绝对系统表路径，默认 DEFAULT_MOUNTINFO_PATH；测试显式传临时文件。
        uuid_directory: 绝对 UUID 链接目录，默认 DEFAULT_UUID_DIRECTORY；不遍历该目录。
    """

    mountinfo_path: Path = DEFAULT_MOUNTINFO_PATH
    uuid_directory: Path = DEFAULT_UUID_DIRECTORY

    def read_mountinfo(self) -> str:
        """读取本进程挂载命名空间的完整挂载表。

        Args:
            无。

        Returns:
            文件原文；使用 UTF-8 与 surrogateescape 保留 Linux 路径原始字节。

        Raises:
            OSError: 文件不存在、不可读或读取失败，保留原异常交检查层转换为 ExternalError。
            DefectError: 适配器路径不是无 NUL/.. 的绝对 Path。

        Side Effects:
            无（只读 mountinfo_path）；不 stat 挂载点或枚举目录。

        Time Semantics:
            单次本地系统表读取，不重试；worker 的外层预算覆盖此调用。
        """
        raise NotImplementedError

    def resolve_uuid_device(self, uuid: str) -> DeviceNumber | None:
        """查询 UUID 对应块设备的主次设备号。

        Args:
            uuid: 已校验的小写标准连字符 UUID，只能形成一个文件名，不能含路径分隔符。

        Returns:
            对链接目标 stat 后由 st_rdev 得到的设备号；链接缺失、断链或目标不是块设备返回 None。
            不比较 /dev/sdX 与 /dev/mapper 的名字，不读取设备内容。

        Raises:
            OSError: 除缺失/断链外的权限或设备元数据读取失败；检查层转换为 ExternalError。
            DefectError: uuid 或 uuid_directory 违反调用契约。

        Side Effects:
            无（只读 uuid_directory 下该链接及设备节点元数据）；不访问存储根。

        Time Semantics:
            每次重新 stat，不缓存设备号；worker 的整个检查预算覆盖此调用。
        """
        raise NotImplementedError


@dataclass(frozen=True)
class MountInspector:
    """可供 Web 使用的挂载检查依赖，不持有存储根文件访问能力。

    Attributes:
        roots: 按配置顺序的已校验根元组，允许空，无重复名字或嵌套路径。
        read_mountinfo: 无参数回调，每次返回完整挂载表；仅生产适配器读系统表。
        resolve_uuid_device: UUID 到设备号的回调，缺失返回 None；NFS 不调用。
        clock: 返回 aware datetime 的时钟，接受任何有效偏移并经 timeutil 转 UTC；非法值为缺陷。
    """

    roots: tuple[StorageRootConfig, ...]
    read_mountinfo: Callable[[], str]
    resolve_uuid_device: Callable[[str], DeviceNumber | None]
    clock: Callable[[], datetime]

    def inspect(self) -> tuple[StorageRootStatus, ...]:
        """现场核对全部登记根的挂载身份，不读取数据目录。

        Args:
            无。

        Returns:
            按 roots 顺序每根一条；空配置返回空且不读挂载表、UUID 或时钟。
            一次读取挂载表，每根检查结束单独取 UTC 时刻；从不返回 TIMEOUT。
            没有精确挂载点为 NOT_MOUNTED；ext4 类型/设备号不符、UUID 缺失或
            NFS 类型/来源不符为 SOURCE_MISMATCH；其余为在线。路径按分量词法比较，不 resolve。

        Raises:
            ExternalError: 挂载表读取/解析或 UUID 元数据读取失败，诊断含根名字、
                规则 storage.mount_table 或 storage.uuid_device、实际失败原因和重新检查建议；
                整次请求失败，不捏造部分状态，不泄露挂载表原文。
            DefectError: 依赖、回调返回类型、设备号或注入时钟非法，或回调抛出非 I/O 异常。

        Side Effects:
            无（只读系统表和 UUID 设备元数据）；不碰根目录，不写缓存、标记文件或操作日志。

        Time Semantics:
            每次调用现场读取本地系统状态，不轮询不重试；Web 不执行可能阻塞的 NFS 访问。
        """
        raise NotImplementedError


def read_storage_root(path: Path) -> None:
    """对已核对挂载身份的存储根做一次只读目录访问。

    Args:
        path: 已登记且挂载身份核对通过的绝对 Path，只访问根本身，不枚举其子项。

    Returns:
        无；stat 成功且为目录才视为访问成功。

    Raises:
        OSError: stat 失败，包括检查后被卸载、权限不足和其他 I/O 故障。
        NotADirectoryError: stat 成功但对象不再是目录。
        DefectError: 传入相对路径、NUL 或 ..，禁止猜测工作目录。

    Side Effects:
        无（仅 stat 存储根）；禁止创建标记文件或读取数据内容。

    Time Semantics:
        只能由 StorageAccessChecker 的 daemon 线程调用，预算由外层管理；本函数不能中止内核 I/O。
    """
    raise NotImplementedError


@dataclass(frozen=True)
class StorageAccessChecker:
    """worker 专用访问检查依赖，与 Web 的挂载表查询隔开。

    Attributes:
        mounts: 已冻结根列表和系统读取回调；作业只检查声明的根。
        options: 已校验访问超时，单位秒。
        access: 对根本身只读访问的回调，生产为 read_storage_root；测试注入可释放的阻塞函数。
    """

    mounts: MountInspector
    options: StorageConfig
    access: Callable[[Path], None]

    def check(self, name: str) -> StorageRootStatus:
        """在一个总预算内核对指定根的挂载身份并尝试只读访问。

        Args:
            name: mounts.roots 中已登记的名字，必须精确匹配；不接受路径代替名字。

        Returns:
            一条检查结果；没挂载或来源不符时跳过 access；在线时才对根调用一次 access。
            读表、UUID 查询或根访问任一步耗尽总预算均返回离线 TIMEOUT；
            超时结果的 checked_at 在调用线程返回前读取，迟到线程不得覆盖状态或追加警告。

        Raises:
            ExternalError: 预算内挂载表/UUID/根访问发生 I/O 或解析错误，保留异常链，
                诊断含 storage_root 名字、规则、实际失败、阻止访问的后果和下一步。
            DefectError: 根未登记、依赖非法、回调或时钟损坏，不当作离线。

        Side Effects:
            只启动一个 daemon 线程，只读系统元数据和根本身，不写存储。
            超时仅调用线程记一条 WARNING：storage_root=<名字> timeout_s=<预算>，
            文案说明按离线处理；不再等待线程、不无限 join、不在迟到线程写日志或调用 access。

        Time Semantics:
            整体等待至多 options.access_timeout_s 秒，使用单调时钟，不按步骤重置预算。
            返回时刻用 mounts.clock 转 UTC；线程中的系统调用可能在返回后仍卡住。
        """
        raise NotImplementedError
