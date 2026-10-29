"""扫描阶段交接值（领域层，M1-01），只传不可变观察集合，不传活动 Session 或锁。

第02张的磁盘检查值与导航值分离；未执行第二段不清空旧统计值，也不冒充所有根在线。
"""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from rdp.infra.config import StorageRootConfig
from rdp.infra.storage import StorageRootStatus
from rdp.jobs.datasets.fingerprint import DatasetFingerprint
from rdp.jobs.datasets.types import EntrySnapshot, FindingGroup


class StorageStage(StrEnum):
    """第二段是否真正执行，和作业结果、存储根在线状态分开。"""

    NOT_RUN = "not_run"
    COMPLETED = "completed"


class LinkStatus(StrEnum):
    """第二段的链接观察，离线与断链必须明确区分。"""

    AVAILABLE = "available"
    MISSING = "missing"
    BROKEN = "broken"
    OFFLINE = "offline"
    MISMATCH = "mismatch"
    UNREGISTERED = "unregistered"


class SourceStatus(StrEnum):
    """第二段的数据块路径观察，不对original_path作存在性判断。"""

    AVAILABLE = "available"
    MISSING = "missing"
    OFFLINE = "offline"
    UNREGISTERED = "unregistered"


@dataclass(frozen=True)
class IndexedDataset:
    """第一段开始时的索引身份，用于完整扫描中安全识别删除候选。

    Attributes:
        dataset_id: 原永久编号，非空；未知身份旧入口为None，不把位置键当永久编号。
        entry_paths: 索引中的全部入口相对路径，升序且无重复；dataset_id为None时恰好一项。
        fingerprint: 上次存下的状态，用于保留旧数据和核对索引代次，不访问文件。
    """

    dataset_id: str | None
    entry_paths: tuple[str, ...]
    fingerprint: DatasetFingerprint


@dataclass(frozen=True)
class DatasetObservation:
    """一个数据集或一个无法识别身份的入口的一次导航观察。

    Attributes:
        dataset_id: 原编号；三份文件均无法识别身份时None，此时entries恰好一项。
        entries: 路径升序的入口快照；基线中已消失的数据集可为空，不能直接据此删除。
        fingerprint: 同持锁段计算的L12状态，known_entry_paths包括基线入口。
        findings: 本数据集读取、记录值、①②组的聚合发现。
        failed_entry_paths: 无法建立完整读取投影的入口路径，去重排序；一个入口只算一次失败条目。
    """

    dataset_id: str | None
    entries: tuple[EntrySnapshot, ...]
    fingerprint: DatasetFingerprint
    findings: tuple[FindingGroup, ...]
    failed_entry_paths: tuple[str, ...]


@dataclass(frozen=True)
class NavigationScan:
    """第一段完整结果，发布前只在当前作业内存持有。

    Attributes:
        requested_dataset_id: None代表全量，否则为指定非空永久编号。
        registered_roots: 本次扫描启动时的已校验根配置，供NOT_RUN发布未检查状态，禁止访问根路径。
        baseline: 第一段读到的索引身份；全量包含全部，单数据集只包含指定编号。
        datasets: 按编号及入口路径排序的观察；含新入口、损坏入口和消失候选。
        global_findings: 顶层/格式登记发现，单数据集扫描不覆盖全局发现。
        started_at: UTC开始时刻，来自作业时钟。
        finished_at: UTC第一段结束时刻，可因墙钟回拨早于started_at。
        elapsed_s: 非负单调耗时，含等锁；回拨时按累计增量非负处理。
        lock_held_s: 第一段实际持锁秒数，非负，不把存储阶段算进来。
    """

    requested_dataset_id: str | None
    registered_roots: tuple[StorageRootConfig, ...]
    baseline: tuple[IndexedDataset, ...]
    datasets: tuple[DatasetObservation, ...]
    global_findings: tuple[FindingGroup, ...]
    started_at: datetime
    finished_at: datetime
    elapsed_s: float
    lock_held_s: float


@dataclass(frozen=True)
class LinkCheck:
    """第二段对一条声明链接的观察，不要求存储根可写。

    Attributes:
        entry_path: 导航相对入口路径。
        ordinal: 声明链接非负数组序号。
        storage_root_name: 已登记根名；未登记为None。
        status: available/missing/broken/offline/mismatch/unregistered之一，不能用离线表示断链。
        checked_at: UTC检查结束时刻。
    """

    entry_path: str
    ordinal: int
    storage_root_name: str | None
    status: LinkStatus
    checked_at: datetime


@dataclass(frozen=True)
class SourceCheck:
    """第二段对数据块路径与LeRobot元信息的观察。

    Attributes:
        entry_path: 导航相对入口路径。
        ordinal: 数据块非负数组序号。
        storage_root_name: 根配置名，未登记为None。
        status: available/missing/offline/unregistered之一。
        checked_at: UTC路径检查结束时刻。
        robot_type: 非空型号标签；unknown/null/读不到/非LeRobot为None。
        fps: 有限正帧率，帧/秒；未知为None。
        codebase_version: 原meta版本文本；未知为None。
        meta_checked_at: UTC元信息检查时刻；离线/未执行为None。
    """

    entry_path: str
    ordinal: int
    storage_root_name: str | None
    status: SourceStatus
    checked_at: datetime
    robot_type: str | None
    fps: float | None
    codebase_version: str | None
    meta_checked_at: datetime | None


@dataclass(frozen=True)
class StorageScan:
    """第二段输出，NOT_RUN明确表示没有执行存储检查。

    Attributes:
        stage: NOT_RUN或COMPLETED；NOT_RUN时其他集合必须为空、warning_count为0。
        roots: 配置根顺序的StorageRootStatus；只包含实际检查，不能构造假在线值。
        links: 按入口路径/序号排列的链接观察。
        sources: 按入口路径/序号排列的数据块观察。
        findings: (归属键,聚合发现)元组，归属键为dataset:编号、entry:路径或global。
        warning_count: 存储根离线/超时导致跳过检查的非负次数，不是面板发现条数。
    """

    stage: StorageStage
    roots: tuple[StorageRootStatus, ...]
    links: tuple[LinkCheck, ...]
    sources: tuple[SourceCheck, ...]
    findings: tuple[tuple[str, FindingGroup], ...]
    warning_count: int


@dataclass(frozen=True)
class IndexReplacement:
    """在提交写锁下已经核对的索引替换计划，只由发布函数消费一次。

    Attributes:
        navigation: 原第一段完整快照。
        storage: 第二段结果，NOT_RUN不清旧磁盘统计。
        accepted: 可以替换的观察，顺序同navigation.datasets；完整身份和指纹已核对。
        deleted_dataset_ids: 两次都确认全部入口消失的基线编号，升序；不能删除中途新增的编号。
        deleted_entry_paths: 两次均确认消失且无法识别编号的旧入口，升序；不删除未经过基线观察的路径。
        skipped: 发生变化或不能核对的观察，旧行保留，返回提示不覆盖其内容。
        notices: 本次跳过提示，保留完整计数和有界样例。
        committed_at: 注入UTC提交观察时刻，不是数据库自动时间。
    """

    navigation: NavigationScan
    storage: StorageScan
    accepted: tuple[DatasetObservation, ...]
    deleted_dataset_ids: tuple[str, ...]
    deleted_entry_paths: tuple[str, ...]
    skipped: tuple[DatasetObservation, ...]
    notices: tuple[FindingGroup, ...]
    committed_at: datetime


@dataclass(frozen=True)
class ScanPublication:
    """数据库事务成功提交后才返回的统计摘要。

    Attributes:
        scan_id: 新发布正代次编号。
        dataset_count: 本次实际发布的数据集数量，非负，不把被跳过的算成功。
        entry_count: 本次处理入口数，非负，作为作业total_items口径。
        failed_entry_count: 无法完整建立投影的入口数，0至entry_count。
        skipped_dataset_count: 指纹变化或不可验证而跳过的数据集数，非负。
        finding_count: 面板完整发现条数，非负，不用它替代warning_count。
        warning_count: 跳过数据集加存储检查跳过次数，非负。
    """

    scan_id: int
    dataset_count: int
    entry_count: int
    failed_entry_count: int
    skipped_dataset_count: int
    finding_count: int
    warning_count: int
