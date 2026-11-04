"""调度只读 HTTP 模型（入口层，09）；编号转文本，时刻为 UTC，前端使用生成类型。"""

from pydantic import AwareDatetime, Field

from rdp.api.account_schemas import AccountId
from rdp.api.job_schemas import JobPayload
from rdp.infra.config import MAX_GPU_INDEX, MAX_JOB_CONCURRENCY
from rdp.infra.diagnostics import Diagnostic
from rdp.jobs.outcome import JobOutcome
from rdp.jobs.scheduling_types import GpuAvailability
from rdp.jobs.types import JobState


class TypeUsageResponse(JobPayload):
    """一类作业的生效上限与数据库运行数。

    Attributes:
        type_name: 稳定英文键。
        display_name: 中文显示名。
        concurrency: 生效上限，1 至 MAX_JOB_CONCURRENCY。
        requires_gpu: 是否需要一张 GPU。
        running_count: running/cancelling 数量，非负，恢复时可大于新配置上限。
    """

    type_name: str
    display_name: str
    concurrency: int = Field(ge=1, le=MAX_JOB_CONCURRENCY)
    requires_gpu: bool
    running_count: int = Field(ge=0)


class GpuUsageResponse(JobPayload):
    """一张配置卡的展示占用，空闲不是硬件健康承诺。

    Attributes:
        gpu_index: 非负物理编号，最大 MAX_GPU_INDEX。
        job_id: 当前作业编号文本，空闲/移出池 None；历史终态不计占用。
        availability: available/excluded/unknown；未有本实例核对记录不能当作可用。
        diagnostics: 移出池的有界统一诊断，通过或未知为空。
        checked_at: 启动核对的 UTC 时刻；未知为 None。
    """

    gpu_index: int = Field(ge=0, le=MAX_GPU_INDEX)
    job_id: AccountId | None
    availability: GpuAvailability
    diagnostics: tuple[Diagnostic, ...]
    checked_at: AwareDatetime | None


class ScheduleResponse(JobPayload):
    """每日计划及最近一次提交的结果。

    Attributes:
        name: 稳定登记名。
        description: 当前定时规则定义的非空用途说明，供页面原样展示。
        next_run_at: 按本机时区算出的下一次按点 UTC 时刻，浏览器仅负责本地显示。
        last_job_id: 最近提交的作业编号文本，从未提交 None。
        last_submitted_at: 最近提交的 UTC 时刻，从未提交 None。
        last_state: 最近作业六态之一，未提交 None。
        last_outcome: 仅最近作业 completed 时非空，不把取消/中断伪装失败结果。
    """

    name: str
    description: str = Field(min_length=1)
    next_run_at: AwareDatetime
    last_job_id: AccountId | None
    last_submitted_at: AwareDatetime | None
    last_state: JobState | None
    last_outcome: JobOutcome | None


class SchedulingResponse(JobPayload):
    """一个只读调度快照；无修改配置或分配资源的 HTTP 接口。

    Attributes:
        types: 按类型键升序的配置与数量。
        gpus: 按物理编号升序的占用。
        navigation_job_id: 持锁作业编号文本，无人持锁 None。
        schedules: 按登记名字升序的定时计划。
        checked_at: 服务端本请求 UTC 时刻。
        worker_online: 同一快照按心跳判断；False 时展示注明是最后已保存状态。
    """

    types: tuple[TypeUsageResponse, ...]
    gpus: tuple[GpuUsageResponse, ...]
    navigation_job_id: AccountId | None
    schedules: tuple[ScheduleResponse, ...]
    checked_at: AwareDatetime
    worker_online: bool
