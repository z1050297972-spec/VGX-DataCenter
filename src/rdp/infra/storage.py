"""存储根身份与只读访问契约（基础层，10、ADR 0006），不写数据、不决定作业结果。

Linux 系统读取、mountinfo 纯解析、挂载身份比较与 worker 访问预算分开；Web 仅持有
MountInspector，没有访问数据目录的回调。pathlib/stat/os 提供文件和设备号能力，
标准库及已批准依赖没有 mountinfo 解析器，只实现内核字段和四种转义的有限解析。
线程使用标准库 threading，设为 daemon；超时不无限 join，也无法强行结束卡死的 NFS 读取。
反复超时可能累积存活线程，待 NAS 挂载事实明确后另定进程隔离或挂载策略。
检查只反映当时状态，不能保证随后实际 I/O 仍在线，更不授予任何目录写权限。
"""

import logging
import os
import re
import stat
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from threading import Event, Thread
from types import MappingProxyType
from typing import cast

from rdp.infra.config import PlatformConfig, StorageConfig, StorageRootConfig
from rdp.infra.diagnostics import (
    DefectError,
    Diagnostic,
    DiagnosticCategory,
    DiagnosticLevel,
    DiagnosticObject,
    ExternalError,
)
from rdp.infra.timeutil import ensure_utc

logger = logging.getLogger(__name__)

# Linux 适配器的系统路径集中于此；业务判断只依赖回调，测试用临时文件替换。
DEFAULT_MOUNTINFO_PATH = Path("/proc/self/mountinfo")
DEFAULT_UUID_DIRECTORY = Path("/dev/disk/by-uuid")
# 每50毫秒重查调用方控制信号，使停止/取消不受最长60秒存储访问预算拖延。
STORAGE_CHECKPOINT_INTERVAL_S = 0.05
# mountinfo 只转义内核文档定义的四种字符；一次替换避免把字面的反斜杠再次解释。
_MOUNT_ESCAPES = {"040": " ", "011": "\t", "012": "\n", "134": "\\"}
_MOUNT_ESCAPE_PATTERN = re.compile(r"\\(040|011|012|134)")
# Linux mountinfo协议：前六列固定，独立分隔符之后恰有三列。
_MOUNT_FIXED_COLUMNS = 6
_MOUNT_TAIL_COLUMNS = 3


class OfflineReason(StrEnum):
    """存储根离线的三种业务原因；读取基础设施失败不伪装成其中任一种。"""

    NOT_MOUNTED = "not_mounted"
    SOURCE_MISMATCH = "source_mismatch"
    TIMEOUT = "timeout"


# 诊断与页面共用唯一中文映射；API通过生成的OpenAPI扩展元数据交给前端，不手抄第二份。
OFFLINE_REASON_LABELS: Mapping[OfflineReason, str] = MappingProxyType(
    {
        OfflineReason.NOT_MOUNTED: "没挂载",
        OfflineReason.SOURCE_MISMATCH: "挂错了盘",
        OfflineReason.TIMEOUT: "超时",
    }
)


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
        source: 分隔符后第二列的解码来源文本，允许空串，不按设备节点名字比较 ext4。
        filesystem_root: 第四列解码后的原样文本，可为子目录或nsfs命名空间标识；
            不作Path规范化，只有精确的/才代表整个文件系统。
    """

    mount_point: Path
    device: DeviceNumber
    filesystem: str
    source: str
    filesystem_root: str


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
        text: 一次完整挂载表文本，空文本合法；记录仅以 LF 分隔，字段以空格分隔，
            可有可选字段和结尾换行；CR、换页符及 Unicode 行分隔字符都是字段内容。
            挂载根、挂载点和来源只单次解码内核的 \040、\011、\012、\134，禁止递归解码。

    Returns:
        按最后出现行的顺序排列的不可变元组；同挂载点叠层只留最后一条，空表为空。
        正确跳过分隔符前可选字段，不把来源中的转义空格当作列分隔。
        第4列保存原样文本而非Path；来源列即使为空也保留，不猜测或替换成none。

    Raises:
        ValueError: 非空行字段数或分隔符不合协议，第3列设备号格式不合法，
            第5列挂载点不是合法绝对路径，或待解码字段含非法转义；消息指出字段位置。
            不因挂载根是特殊标识或来源为空而拒绝，不跳过结构损坏的记录。

    Side Effects:
        无；纯解析，不读取文件系统，不记录挂载表原文。

    Time Semantics:
        不取时钟，无等待；输入由调用者在一次读取中提供。
    """
    records: dict[Path, MountRecord] = {}
    # 内核只用LF结束记录；splitlines还会切开合法文件名中的CR等字符。
    for line in text.split("\n"):
        if not line:
            continue
        fields, separator = _split_mount_fields(line)
        device = _parse_device_number(fields[2])
        point = _decode_mount_field(fields[4], "第5列（挂载点）")
        source = _decode_mount_field(fields[separator + 2], f"第{separator + 3}列（挂载来源）")
        filesystem_root = _decode_mount_field(fields[3], "第4列（挂载根）")
        mount_point = Path(point)
        if not mount_point.is_absolute() or "\x00" in point:
            raise ValueError("第5列（挂载点）须为不含NUL的绝对路径")
        # 删除再插入，使叠层后的枚举顺序也对应最后一条记录的位置。
        records.pop(mount_point, None)
        records[mount_point] = MountRecord(
            mount_point,
            device,
            fields[separator + 1],
            source,
            filesystem_root,
        )
    return tuple(records.values())


def _split_mount_fields(line: str) -> tuple[list[str], int]:
    """只按协议定位固定字段和尾部字段，不把第4列文本中的连字符当成分隔符。"""
    # 来源是文件系统专有文本，空串仍占一列；不能用split()或all(fields)消掉/拒绝它。
    fields = line.split(" ")
    if len(fields) < _MOUNT_FIXED_COLUMNS + 1 + _MOUNT_TAIL_COLUMNS:
        raise ValueError("字段数不足：需要前6列、分隔符及其后3列")
    try:
        separator = fields.index("-", _MOUNT_FIXED_COLUMNS)
    except ValueError as error:
        raise ValueError("第6列之后缺少独立的分隔符列") from error
    if len(fields) != separator + 1 + _MOUNT_TAIL_COLUMNS:
        raise ValueError(f"第{separator + 1}列分隔符之后须恰有3列，字段数不符")
    return fields, separator


def _parse_device_number(value: str) -> DeviceNumber:
    """设备号只接受内核十进制主次号格式，转换失败保留第3列身份。"""
    parts = value.split(":")
    if len(parts) != 2 or any(not part.isascii() or not part.isdecimal() for part in parts):
        raise ValueError("第3列（设备号）须为非负十进制major:minor")
    try:
        return DeviceNumber(int(parts[0]), int(parts[1]))
    except ValueError as error:
        raise ValueError("第3列（设备号）无法转换为整数") from error


def _decode_mount_field(value: str, column: str) -> str:
    """先验证原始转义再做单次替换，避免合法字面反斜杠被二次拒绝。"""
    if "\\" in _MOUNT_ESCAPE_PATTERN.sub("", value):
        raise ValueError(f"{column}含非法转义")
    return _MOUNT_ESCAPE_PATTERN.sub(lambda match: _MOUNT_ESCAPES[match[1]], value)


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
            文件原文；使用 UTF-8 与 surrogateescape 保留 Linux 路径原始字节，不转换CR或CRLF。

        Raises:
            OSError: 文件不存在、不可读或读取失败，保留原异常交检查层转换为 ExternalError。
            DefectError: 适配器路径不是无 NUL/.. 的绝对 Path。

        Side Effects:
            无（只读 mountinfo_path）；不 stat 挂载点或枚举目录。

        Time Semantics:
            单次本地系统表读取，不重试；worker 的外层预算覆盖此调用。
        """
        _absolute_path(self.mountinfo_path)
        return self.mountinfo_path.read_bytes().decode("utf-8", errors="surrogateescape")

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
        _absolute_path(self.uuid_directory)
        try:
            StorageRootConfig(name="device", path=self.uuid_directory, uuid=uuid)
        except ValueError as error:
            raise DefectError() from error
        try:
            info = (self.uuid_directory / uuid).stat()
        except FileNotFoundError:
            return None
        if not stat.S_ISBLK(info.st_mode):
            return None
        return DeviceNumber(os.major(info.st_rdev), os.minor(info.st_rdev))


def _absolute_path(path: Path) -> None:
    """系统适配器不接受需要猜测或展开的目录位置。"""
    if not isinstance(cast(object, path), Path):
        raise DefectError()
    try:
        PlatformConfig.validate_state_dir(path)
    except ValueError as error:
        raise DefectError() from error


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
            NFS 类型/来源不符或挂载根不是/为 SOURCE_MISMATCH；其余为在线。
            登记指整个文件系统，不接受其子目录bind；路径按分量词法比较，不 resolve。

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
        validate_mount_inspector(self)
        if not self.roots:
            return ()
        records = _mount_records(self, ",".join(root.name for root in self.roots))
        return tuple(_check_mount(root, records, self) for root in self.roots)


def _check_mount(
    root: StorageRootConfig, records: tuple[MountRecord, ...], inspector: MountInspector
) -> StorageRootStatus:
    """只按挂载身份形成状态，不访问登记根目录。"""
    record = next((item for item in records if item.mount_point == root.path), None)
    reason = None
    if record is None:
        reason = OfflineReason.NOT_MOUNTED
    elif record.filesystem_root != "/" or (
        root.uuid is not None
        and (record.filesystem != "ext4" or _uuid_device(root, inspector) != record.device)
        or root.nfs_export is not None
        and (record.filesystem not in {"nfs", "nfs4"} or record.source != root.nfs_export)
    ):
        reason = OfflineReason.SOURCE_MISMATCH
    return StorageRootStatus(
        root.name, root.path, root.writable, reason is None, reason, _now(inspector)
    )


def _now(inspector: MountInspector) -> datetime:
    """注入时钟错误只归平台缺陷，不污染在线状态。"""
    try:
        value = inspector.clock()
        if not isinstance(cast(object, value), datetime):
            raise DefectError()
        return ensure_utc(value)
    except Exception as error:
        raise DefectError() from error


def _uuid_device(root: StorageRootConfig, inspector: MountInspector) -> DeviceNumber | None:
    """设备元数据的I/O失败保留身份与原始异常链。"""
    if root.uuid is None:
        raise DefectError()
    try:
        device = inspector.resolve_uuid_device(root.uuid)
    except OSError as error:
        raise _external_failure(root.name, "storage.uuid_device", error) from error
    except Exception as error:
        raise DefectError() from error
    if device is not None and (
        not isinstance(cast(object, device), DeviceNumber)
        or type(device.major) is not int
        or type(device.minor) is not int
        or device.major < 0
        or device.minor < 0
    ):
        raise DefectError()
    return device


def validate_mount_inspector(inspector: MountInspector) -> None:
    """校验挂载检查器依赖，不执行任何检查回调。

    Args:
        inspector: Web或worker显式装配的MountInspector；根元组已按配置契约登记，回调均可调用。

    Returns:
        无；根登记与回调形状合法，可交给挂载检查或绑定应用。

    Raises:
        DefectError: 检查器类型、根集合、单根配置或任一回调形状非法。

    Side Effects:
        无；仅核对内存配置，不读系统表、设备节点或数据目录，不调用时钟。

    Time Semantics:
        启动装配或每次检查之前同步执行，无等待与重试。
    """
    if (
        not isinstance(cast(object, inspector), MountInspector)
        or type(inspector.roots) is not tuple
    ):
        raise DefectError()
    if not all(
        callable(item)
        for item in (inspector.read_mountinfo, inspector.resolve_uuid_device, inspector.clock)
    ):
        raise DefectError()
    try:
        for root in inspector.roots:
            if not isinstance(cast(object, root), StorageRootConfig):
                raise DefectError()
            StorageRootConfig.model_validate(root.model_dump())
        PlatformConfig.validate_storage_roots(inspector.roots)
    except ValueError as error:
        raise DefectError() from error


def _mount_records(inspector: MountInspector, names: str) -> tuple[MountRecord, ...]:
    """为读取失败补登记身份，不把挂载表原文带入对外诊断。"""
    try:
        text = inspector.read_mountinfo()
    except OSError as error:
        raise _external_failure(names, "storage.mount_table", error) from error
    except Exception as error:
        raise DefectError() from error
    if not isinstance(cast(object, text), str):
        raise DefectError()
    try:
        return parse_mountinfo(text)
    except ValueError as error:
        raise _external_failure(names, "storage.mount_table", error) from error


def _external_failure(name: str, rule: str, error: Exception) -> ExternalError:
    """只公开异常类别与errno；完整异常链保留给最外层报告。"""
    actual = type(error).__name__
    if isinstance(error, OSError):
        actual += f" errno={error.errno}"
    return ExternalError(
        (
            Diagnostic(
                level=DiagnosticLevel.ERROR,
                category=DiagnosticCategory.EXTERNAL,
                stage="存储检查",
                source="平台",
                objects=(DiagnosticObject(key="storage_root", value=name),),
                rule=rule,
                actual=actual,
                expected="挂载身份可核对且存储可访问",
                consequence="检查失败，阻止本次存储访问",
                next_step="核对挂载配置与读取权限，恢复后重新检查",
            ),
        )
    )


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
    _absolute_path(path)
    if not stat.S_ISDIR(path.stat().st_mode):
        raise NotADirectoryError(str(path))


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

    def check(self, name: str, *, checkpoint: Callable[[], None]) -> StorageRootStatus:
        """在一个总预算内核对指定根的挂载身份并尝试只读访问。

        Args:
            name: mounts.roots 中已登记的名字，必须精确匹配；不接受路径代替名字。
            checkpoint: 必填关键字，调用方提供的同步、有界控制检查；正常返回None，
                取消或停止时抛控制异常。只在调用线程运行，不交给可能卡住的读取线程。

        Returns:
            一条检查结果；没挂载或来源不符时跳过 access；在线时才对根调用一次 access。
            读表、UUID 查询或根访问任一步耗尽总预算均返回离线 TIMEOUT；
            超时结果的 checked_at 在调用线程返回前读取，迟到线程不得覆盖状态或追加警告。

        Raises:
            ExternalError: 预算内挂载表/UUID/根访问发生 I/O 或解析错误，保留异常链，
                诊断含 storage_root 名字、规则、实际失败、阻止访问的后果和下一步。
            DefectError: 根未登记、依赖非法、回调或时钟损坏，不当作离线。
            Exception: checkpoint 抛出的取消、停止或上报异常原样向调用方传播。

        Side Effects:
            只启动一个 daemon 线程，只读系统元数据和根本身，不写存储。
            超时仅调用线程记一条 WARNING：storage_root=<名字> timeout_s=<预算>，
            文案说明按离线处理；不再等待线程、不无限 join、不在迟到线程写日志或调用 access。
            checkpoint 中止时标记读取已放弃，不记超时警告；已开始的内核读取仍可能存活。

        Time Semantics:
            整体等待至多 options.access_timeout_s 秒，使用单调时钟，不按步骤重置预算。
            返回时刻用 mounts.clock 转 UTC；线程中的系统调用可能在返回后仍卡住。
            启动读取前及等待中调用checkpoint；等待片段至多STORAGE_CHECKPOINT_INTERVAL_S秒，
            控制响应另加checkpoint自身有界耗时，不因检查控制信号重置总预算。
        """
        validate_mount_inspector(self.mounts)
        if not isinstance(cast(object, self.options), StorageConfig) or not callable(self.access):
            raise DefectError()
        root = next((item for item in self.mounts.roots if item.name == name), None)
        if root is None:
            raise DefectError()
        if not callable(checkpoint):
            raise DefectError()
        checkpoint()
        completed = Event()
        expired = Event()
        outcome: list[StorageRootStatus | Exception] = []
        deadline = time.monotonic() + self.options.access_timeout_s

        def run() -> None:
            try:
                result = _probe_storage(self, root, deadline, expired)
                if result is not None:
                    outcome.append(result)
            except Exception as error:
                outcome.append(error)
            finally:
                completed.set()

        Thread(target=run, daemon=True, name=f"storage-{name}").start()
        try:
            finished = _wait_for_probe(completed, deadline, checkpoint)
        finally:
            # 成功、超时、控制异常都关闭后续步骤，迟到结果只留在线程私有结果槽。
            expired.set()
        if not finished:
            logger.warning(
                "存储访问超时，按离线处理 storage_root=%s timeout_s=%s",
                name,
                self.options.access_timeout_s,
            )
            return StorageRootStatus(
                name, root.path, root.writable, False, OfflineReason.TIMEOUT, _now(self.mounts)
            )
        if not outcome:
            raise DefectError()
        result = outcome[0]
        if isinstance(result, Exception):
            raise result
        return StorageRootStatus(
            name, root.path, root.writable, result.online, result.reason, _now(self.mounts)
        )


def _wait_for_probe(completed: Event, deadline: float, checkpoint: Callable[[], None]) -> bool:
    """等待和控制检查共享单调截止，控制信号优先于刚到达的结果或超时。"""
    while True:
        checkpoint()
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        if completed.wait(min(remaining, STORAGE_CHECKPOINT_INTERVAL_S)):
            checkpoint()
            return time.monotonic() < deadline


def _probe_storage(
    checker: StorageAccessChecker, root: StorageRootConfig, deadline: float, expired: Event
) -> StorageRootStatus | None:
    """在线程内执行有共同截止的只读步骤，迟到后不继续访问下一层。"""
    records = _mount_records(checker.mounts, root.name)
    if expired.is_set() or time.monotonic() >= deadline:
        return None
    result = _check_mount(root, records, checker.mounts)
    # 身份检查迟到时禁止继续触碰数据盘；已经开始的内核调用无法强行中止。
    if expired.is_set() or time.monotonic() >= deadline:
        return None
    if result.online:
        try:
            value = checker.access(root.path)
        except OSError as error:
            raise _external_failure(root.name, "storage.access", error) from error
        except Exception as error:
            raise DefectError() from error
        if value is not None:
            raise DefectError()
    return result
