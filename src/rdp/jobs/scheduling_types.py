"""调度值对象（领域层，09）；只传递配置与数据库快照，不创建线程、锁或定时器。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
from enum import StrEnum
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from rdp.infra.diagnostics import Diagnostic
from rdp.jobs.outcome import JobOutcome
from rdp.jobs.types import JobState
from rdp.jobs.types import WaitReason as WaitReason

if TYPE_CHECKING:
    from rdp.jobs.schedules import ScheduleRegistry


@dataclass(frozen=True)
class TypeCapacity:
    """一类作业的最终生效资源要求。

    Attributes:
        type_name: 已登记的稳定英文键。
        display_name: 类型中文名，1-40 码点。
        concurrency: 同时执行上限，1 至 MAX_JOB_CONCURRENCY。
        requires_gpu: 是否必须领一张卡；严格布尔值。
    """

    type_name: str
    display_name: str
    concurrency: int
    requires_gpu: bool


@dataclass(frozen=True)
class SchedulingSettings:
    """Web 与 worker 入口分别注入的不可变配置快照。

    Attributes:
        gpus: 升序、无重复的非负卡号元组，最多 MAX_CONFIGURED_GPUS 项；空表示禁用 GPU。
        types: 按 type_name 升序的最终生效要求，类型键唯一，可为空。
    """

    gpus: tuple[int, ...]
    types: tuple[TypeCapacity, ...]


@dataclass(frozen=True)
class ResourceClaim:
    """本实例一次执行的资源凭据；不从展示用数据库标记重建。

    Attributes:
        job_id: 永久正编号，同一时刻只允许一个凭据。
        type_name: 类型容量的稳定键。
        gpu_index: 非负物理卡号；无需 GPU 或本实例没有可用卡时 None，需卡作业由执行器按外部失败结束。
    """

    job_id: int
    type_name: str
    gpu_index: int | None


@dataclass(frozen=True)
class Admission:
    """一次内存资源申请结果。

    Attributes:
        claim: 成功的凭据；类型已满或 GPU 全忙时 None。
        wait_reason: 仅 GPU 全忙为 GPU，类型满或成功为 None；写锁在执行阶段取得。
    """

    claim: ResourceClaim | None
    wait_reason: WaitReason | None


@dataclass(frozen=True)
class ResourceDisplay:
    """写给页面的瞬时资源状态；不能作为真正的互斥锁。

    Attributes:
        wait_reason: None、GPU 或 NAVIGATION_LOCK；终态始终 None。
        holds_navigation_lock: 当前是否持有导航层写锁，终态 False。
    """

    wait_reason: WaitReason | None
    holds_navigation_lock: bool


@dataclass(frozen=True)
class ScheduledJob:
    """代码显式登记的每天一次提交规则。

    Attributes:
        name: 唯一稳定名字，1-64 码点，无首尾空白及控制字符；用于跨重启去重，不随显示名改变。
        type_name: 当前登记表中的稳定类型键。
        parameters: 无秘密 JSON 对象，按类型模型校验；登记后复制，不让调用者后续修改。
        local_time: 无 tzinfo 的本地时刻，精确到分钟，默认 03:00；秒和微秒必须零。
    """

    name: str
    type_name: str
    parameters: dict[str, object]
    local_time: time = time(3, 0)


@dataclass(frozen=True)
class ScheduleSubmission:
    """已原子提交的定时去重记录，不是作业执行结果。

    Attributes:
        schedule_name: 登记的稳定名字，1-64 码点。
        local_date: 提交时在登记时区下的本地日历日期，不将此日期当 UTC 时刻。
        job_id: 本次提交的永久正编号。
        submitted_at: 带时区的 UTC 提交时刻，供跨重启的 24 小时判断。
    """

    schedule_name: str
    local_date: date
    job_id: int
    submitted_at: datetime


@dataclass(frozen=True)
class TypeUsage:
    """调度页的一类并发用量。

    Attributes:
        capacity: 启动时合并配置后的容量。
        running_count: 数据库 running/cancelling 行数，非负；恢复前可超过当前降低的上限。
    """

    capacity: TypeCapacity
    running_count: int


@dataclass(frozen=True)
class GpuUsage:
    """调度页的一张卡及其当前作业。

    Attributes:
        gpu_index: 配置中的非负物理编号。
        job_id: running/cancelling 且领此卡的正编号；空闲/移出池为 None，历史终态不计占用。
        availability: 数据库中当前实例的启动核对状态；未保存核对结果时 UNKNOWN，不伪造可用。
        diagnostics: 移出池的诊断，其他状态为空；来源为 worker 保存的副本。
        checked_at: 核对时的 UTC 时刻；尚未核对为 None。
    """

    gpu_index: int
    job_id: int | None
    availability: GpuAvailability
    diagnostics: tuple[Diagnostic, ...]
    checked_at: datetime | None


@dataclass(frozen=True)
class ScheduleView:
    """某定时作业下一次计划和最近一次提交结果。

    Attributes:
        name: 稳定登记名。
        next_run_at: 下一次按点提交的 UTC 时刻；不预测下一次启动补跑。
        last_submission: 最近提交记录；从未提交为 None。
        last_state: 对应作业六态之一；从未提交为 None。
        last_outcome: 仅上次作业已完成时非空，由既有结果计算函数产生。
    """

    name: str
    next_run_at: datetime
    last_submission: ScheduleSubmission | None
    last_state: JobState | None
    last_outcome: JobOutcome | None


@dataclass(frozen=True)
class SchedulingSnapshot:
    """一个数据库读快照的调度展示，不访问 worker 进程内存。

    Attributes:
        types: 按类型键升序的容量和计数。
        gpus: 按物理编号升序的卡与作业。
        navigation_job_id: 数据库持锁标记对应的作业；无人持有时 None。
        schedules: 按稳定名字升序的计划与最近结果。
        checked_at: 本请求注入的 UTC 时刻。
        worker_online: 根据同一读快照的心跳判定；离线时占用仅表示最后已保存观察。
    """

    types: tuple[TypeUsage, ...]
    gpus: tuple[GpuUsage, ...]
    navigation_job_id: int | None
    schedules: tuple[ScheduleView, ...]
    checked_at: datetime
    worker_online: bool


@dataclass(frozen=True)
class SchedulingCatalog:
    """两个入口共享形状的只读配置；没有 worker 内存资源。

    Attributes:
        settings: resolve_scheduling 生成的有效配置，不读取默认配置文件。
        schedules: 入口私有定时登记对象，允许空表。
        timezone: 从本机实际 tzfile 读取的完整时区，测试可注入其他 ZoneInfo。
    """

    settings: SchedulingSettings
    schedules: ScheduleRegistry
    timezone: ZoneInfo


class GpuAvailability(StrEnum):
    """当前 worker 实例启动核对的展示状态，不通过 Web 再探测硬件。"""

    UNKNOWN = "unknown"
    AVAILABLE = "available"
    EXCLUDED = "excluded"


@dataclass(frozen=True)
class GpuCheck:
    """一张配置卡启动核对结果，用于构造池及保存数据库展示副本。

    Attributes:
        gpu_index: 配置中的非负物理编号。
        available: 核对通过为 True；失败 False，本实例永不重新启用。
        diagnostics: 失败时非空统一诊断元组；通过为空，样例数量沿用既有有界诊断规则。
        checked_at: 注入时钟给出的 aware UTC 核对时刻，不保存 monotonic。
    """

    gpu_index: int
    available: bool
    diagnostics: tuple[Diagnostic, ...]
    checked_at: datetime
