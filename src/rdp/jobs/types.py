"""作业领域的值对象（08、ADR 0005）；状态、恢复和进度的唯一类型定义。

使用标准库 dataclass/enum 和已批准 Pydantic，不暴露 ORM、HTTP 或入口层类型。
作业结果只由 outcome.calculate_outcome 计算；本模块的 outcome 字段仅传递该结果。
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from rdp.infra.actors import ActorRef
from rdp.infra.diagnostics import DiagnosticGroup
from rdp.jobs.conversion.check_models import IngestCheckResult
from rdp.jobs.outcome import JobOutcome
from rdp.jobs.policy import JOB_PAGE_LIMIT, JOB_TEXT_MAX_CHARS


class JobState(StrEnum):
    """工单规定的六种状态；已完成之外的状态没有作业结果。"""

    QUEUED = "queued"
    RUNNING = "running"
    CANCELLING = "cancelling"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"


class WaitReason(StrEnum):
    """资源等待不增加作业状态；无等待用 None，终态必须清空。"""

    GPU = "gpu"
    NAVIGATION_LOCK = "navigation_lock"


class RecoveryMode(StrEnum):
    """类型登记的三种中断处理；续跑和重跑不新增状态边。"""

    RESUME = "resume"
    RESTART = "restart"
    INTERRUPT = "interrupt"


class ExecutionMode(StrEnum):
    """本次调用原因；恢复时开始时间保持原值，previous_progress 保存上次快照。"""

    FRESH = "fresh"
    RESUME = "resume"
    RESTART = "restart"


class ProgressPart(BaseModel):
    """工具一个特征的独立完成计数（M4-02），不参与作业条目成败计算。

    Attributes:
        model_config: 不可变且禁止额外字段，不回显非法值。
        name: 分项名，1-40 码点且非空白。
        done: 已完成数，严格非负整数，单位见 unit。
        total: 总数，不小于 done；未知为 None。
        unit: 非空白计数单位。
    """

    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)
    name: str = Field(strict=True, min_length=1, max_length=40)
    done: int = Field(strict=True, ge=0)
    total: int | None = Field(strict=True, ge=0)
    unit: str = Field(strict=True, min_length=1)

    @model_validator(mode="after")
    def _validate_relations(self) -> Self:
        """分项沿用总进度的计数关系，拒绝无显示意义的空白文本。"""
        if not self.name.strip() or not self.unit.strip():
            raise ValueError("分项名称和单位不能只有空白")
        if self.total is not None and self.done > self.total:
            raise ValueError("分项已完成数不能超过总数")
        return self


class ConversionResult(BaseModel):
    """转换收尾的产物事实；由meta/info.json取得，不从终端进度推算。

    Attributes:
        total_episodes: 产物episode数，非负整数。
        total_frames: 产物帧数，非负整数。
        codebase_version: 产物格式版本，非空。
        output_path: 本作业暂存产物绝对位置。
    """

    model_config = ConfigDict(frozen=True, extra="forbid")
    total_episodes: int = Field(strict=True, ge=0)
    total_frames: int = Field(strict=True, ge=0)
    codebase_version: str = Field(min_length=1)
    output_path: str = Field(min_length=1)


class JobProgress(BaseModel):
    """执行线程最近一次完整上报，所有计数为严格非负整数，不从诊断样例反推。

    Attributes:
        model_config: 不可变且禁止额外字段；不回显非法输入。
        stage_index: 当前阶段序号，1 起，不超过 stage_count。
        stage_count: 总阶段数，正整数。
        stage_name: 非空阶段名称，至多 JOB_TEXT_MAX_CHARS 码点。
        done: 当前阶段实际完成数，单位见 unit，非负；阶段切换允许归零。
        total: 当前阶段总数，不小于 done；未知为 None，不编造百分比。
        unit: 非空计数单位，至多 JOB_TEXT_MAX_CHARS 码点。
        warning_count: 作业累计警告条数，非负；和失败条目数独立。
        failed_items: 作业累计失败条目数，非负且不大于 total_items。
        total_items: 作业累计已处理条目数，非负；示例每步为一个条目。
        parts: 按工具显示顺序排列的分项，最多16项；旧记录或无分项时为空元组。
        conversion: 转换收尾结果；其他作业或尚未收尾为None。
        ingest_check: 入库四层检查快照，其他类型省略。
    """

    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)
    stage_index: int = Field(strict=True, ge=1)
    stage_count: int = Field(strict=True, ge=1)
    stage_name: str = Field(strict=True, min_length=1, max_length=JOB_TEXT_MAX_CHARS)
    done: int = Field(strict=True, ge=0)
    total: int | None = Field(strict=True, ge=0)
    unit: str = Field(strict=True, min_length=1, max_length=JOB_TEXT_MAX_CHARS)
    warning_count: int = Field(strict=True, ge=0)
    failed_items: int = Field(strict=True, ge=0)
    total_items: int = Field(strict=True, ge=0)
    parts: tuple[ProgressPart, ...] = Field(default=(), max_length=16)
    # 非转换作业保持既有JSON形状；仅收尾成功后序列化新增结果。
    conversion: ConversionResult | None = Field(
        default=None, exclude_if=lambda value: value is None
    )

    ingest_check: IngestCheckResult | None = Field(
        default=None, exclude_if=lambda value: value is None
    )

    @model_validator(mode="after")
    def _validate_relations(self) -> Self:
        """校验阶段序号、done/total 和失败/总条目关系，拒绝纯空白名称或单位。"""
        if self.stage_index > self.stage_count:
            raise ValueError("阶段序号不能超过阶段总数")
        if self.total is not None and self.done > self.total:
            raise ValueError("已完成数不能超过已知总数")
        if self.failed_items > self.total_items:
            raise ValueError("失败条目数不能超过总条目数")
        if not self.stage_name.strip() or not self.unit.strip():
            raise ValueError("阶段名称和单位不能只有空白")
        return self


@dataclass(frozen=True)
class JobClock:
    """可注入的两种时钟，不混用跨进程时刻和进程内时长。

    Attributes:
        now: 无参数回调，返回 aware datetime，由 ensure_utc 规范化；非法值为 DefectError。
        monotonic: 无参数回调，返回有限且不递减的秒读数，起点任意；只用于本进程预算，非法为 DefectError。
    """

    now: Callable[[], datetime]
    monotonic: Callable[[], float]


@dataclass(frozen=True)
class ExecutionSnapshot:
    """执行器用于最终事务的冻结快照；内存有界，计数不从样例推算。

    Attributes:
        progress: 最新完整进度；尚未上报为 None。
        diagnostics: 按来源/规则聚合，组数上限 100 加一个溢出组，每组最多 DIAGNOSTIC_SAMPLE_LIMIT 样例。
        artifacts: 至多 100 个产物位置，每项至多 4096 字符，不在取消时删除。
        tool_exit_code: 最近一次工具退出码/负信号，无工具 None。
        elapsed_s: 已存片段加本次单调运行时长，有限非负秒数，不含 worker 停机时间。
    """

    progress: JobProgress | None
    diagnostics: tuple[DiagnosticGroup, ...]
    artifacts: tuple[str, ...]
    tool_exit_code: int | None
    elapsed_s: float


@dataclass(frozen=True)
class JobSummary:
    """数据库和日志结尾共用的冻结摘要，不各自再算结论。

    Attributes:
        state: completed/cancelled/interrupted 之一。
        outcome: 仅 completed 为 calculate_outcome 的结果；其他必须 None。
        progress: 最后进度；排队即取消为 None，未知总数保持 None。
        total_items: 完整已处理条目数，非负，和 progress 一致；无进度时为零。
        failed_items: 失败条目数，0 至 total_items，不由样例数量推算。
        warning_count: 独立累计警告数，非负，不与失败数合并。
        aborted: 整体异常中止为 True；取消、中断为 False，不混淆用户取消。
        elapsed_s: 有限非负秒数；本实例单调时长加已保存片段，不将离线等待计为运行耗时。
        artifacts: 产物位置文本元组，最多 100 项、每项至多 4096 字符；取消不清理产物。
        tool_exit_code: 外部进程最后退出码；负数表示信号，未调用为 None。
    """

    state: JobState
    outcome: JobOutcome | None
    progress: JobProgress | None
    total_items: int
    failed_items: int
    warning_count: int
    aborted: bool
    elapsed_s: float
    artifacts: tuple[str, ...]
    tool_exit_code: int | None


@dataclass(frozen=True)
class JobRecord:
    """脱离会话的永久作业记录；不建立到账号的外键，也没有删除操作。

    Attributes:
        job_id: AUTOINCREMENT 正整数，1 至 2^63-1，永久不复用。
        type_name: 登记时稳定英文键，1-64 字符；升级后可能已不在登记表。
        display_name: 提交时显示名快照，1-40 码点；日志目录恢复不随类型改名改变。
        parameters: 校验后的 JSON 对象，UTF-8 最多 JOB_PARAMETERS_MAX_BYTES；不得含秘密。
        submitted_by: 账号或 SYSTEM_ACTOR；空编号只允许名字为“系统”，有编号的同名账号按编号识别，运维身份不可提交。
        submitter_deleted: 查询时该编号不存在为 True，按编号查，不按同名猜测。
        submitted_at: aware UTC 微秒时刻，允许因墙钟回拨晚于开始时间。
        resubmitted_from: 原作业正编号；普通提交为 None。
        state: 六种 JobState 之一，所有改变经过 transition_job。
        started_at: 首次领取的 aware UTC 时刻；未领取为 None，恢复不重写。
        ended_at: 终态的 aware UTC 时刻；进行中为 None，不以先后校验拒绝时钟回拨。
        progress: 最后持久化完整进度；尚未报告为 None。
        progress_at: 最近一次进度的 aware UTC 时刻；没有进度为 None。
        elapsed_s: 已保存的单调执行片段总秒数，有限非负；进行中每次进度持久化更新。
        artifacts: 已保存产物位置元组，不因取消/中断清理。
        tool_exit_code: 最近保存的工具退出码，负值为信号，无工具 None。
        log_path: 领取事务内登记的唯一相对logs路径；queued未领取为None，running即使文件未建也非空。
        summary: 终态冻结摘要；进行中为 None。
        diagnostics: 总数及前 N 样例的元组；规则组最多 100，溢出另组保留完整总数。
        recovery_mode: 提交时类型方式快照；仅作记录及interrupt保护，执行方式取当前登记。
        recovery_count: 已提交的续跑/重跑资格次数，0至JOB_RECOVERY_LIMIT=3；达到3后再次恢复标中断。
        gpu_index: 非负物理卡号；未领过为 None，正常终态保留；启动统一清 running/cancelling 的旧卡，恢复重新领取后更新。
        wait_reason: None、GPU、NAVIGATION_LOCK，不改变 state；主循环唯一写 queued 的 GPU 等待，
            每轮重判，领到卡、类型上限阻挡或取消后清旧原因；终态强制清空，启动统一清全部非终态。
        holds_navigation_lock: 展示副本，默认 False；终态和恢复处理时清空，不是真正的互斥锁。
        platform_version: 最近一次实际领取的平台版本，1-128 个码点；默认 None，表示历史未知或尚未领取。
            恢复领取更新为当前 worker 快照；终态不再变化，重新提交的新作业不继承此字段。
    """

    job_id: int
    type_name: str
    display_name: str
    parameters: dict[str, object]
    submitted_by: ActorRef
    submitter_deleted: bool
    submitted_at: datetime
    resubmitted_from: int | None
    state: JobState
    started_at: datetime | None
    ended_at: datetime | None
    progress: JobProgress | None
    progress_at: datetime | None
    elapsed_s: float
    artifacts: tuple[str, ...]
    tool_exit_code: int | None
    log_path: str | None
    summary: JobSummary | None
    diagnostics: tuple[DiagnosticGroup, ...]
    recovery_mode: RecoveryMode
    recovery_count: int
    gpu_index: int | None = None
    wait_reason: WaitReason | None = None
    holds_navigation_lock: bool = False
    platform_version: str | None = None


@dataclass(frozen=True)
class JobQuery:
    """列表状态筛选和稳定游标，不使用 offset。

    Attributes:
        state: 指定状态或 None 表示全部。
        cursor: 与状态、limit、首页最大编号绑定的 v1 base64url 游标；None 为首页。
        limit: 严格整数 1 至 JOB_PAGE_LIMIT，默认该上限。
    """

    state: JobState | None = None
    cursor: str | None = None
    limit: int = JOB_PAGE_LIMIT


@dataclass(frozen=True)
class JobPage:
    """有界的列表快照；变更筛选须丢弃旧游标。

    Attributes:
        items: 按job_id倒序的元组，至多 limit 项，允许空。
        next_cursor: 下一页游标；没有更多记录为 None，最多 JOB_CURSOR_MAX_CHARS 字符。
    """

    items: tuple[JobRecord, ...]
    next_cursor: str | None


@dataclass(frozen=True)
class WorkerHeartbeat:
    """单行心跳的跨进程快照。

    Attributes:
        instance_id: 当前实例 uuid4 hex，32 位；每次启动重新生成。
        pid: 正整数进程号，只用于诊断，不凭 pid 判断在线。
        started_at: 本实例启动的 aware UTC 微秒时刻。
        last_seen_at: 最近成功心跳的 aware UTC 微秒时刻；不存 monotonic。
    """

    instance_id: str
    pid: int
    started_at: datetime
    last_seen_at: datetime
