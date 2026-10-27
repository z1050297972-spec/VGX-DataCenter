"""作业 HTTP 字段（08）；复用领域状态/进度，编号用十进制文本，不泄漏 ORM 或秘密。"""

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, JsonValue

from rdp.api.account_schemas import AccountId
from rdp.api.audit_schemas import HistoricalActorResponse
from rdp.infra.diagnostics import DiagnosticGroup
from rdp.jobs.logs import LogTail
from rdp.jobs.policy import (
    JOB_CURSOR_MAX_CHARS,
    JOB_DISPLAY_NAME_MAX_CHARS,
    JOB_PAGE_LIMIT,
    JOB_RECOVERY_LIMIT,
    JOB_TYPE_MAX_CHARS,
)
from rdp.jobs.types import JobProgress, JobState, JobSummary, RecoveryMode


class JobPayload(BaseModel):
    """作业请求/响应共同配置，拒绝未知字段，不将输入值放进校验异常。"""

    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)


class SubmitJobPayload(JobPayload):
    """提交载荷；类型模型的进一步校验由领域服务执行。

    Attributes:
        type_name: 稳定英文键，1-64 字符。
        parameters: JSON 对象，最多 JOB_PARAMETERS_MAX_BYTES 字节，不得包含秘密。
    """

    type_name: str = Field(strict=True, min_length=1, max_length=JOB_TYPE_MAX_CHARS)
    parameters: dict[str, JsonValue]


class JobFilters(JobPayload):
    """作业列表的状态筛选和游标字段。

    Attributes:
        state: 六态之一；默认 None 查全部。
        cursor: 绑定筛选的 opaque 文本；默认 None 首页，最多 512 字符。
        limit: 1-100 整数，默认 JOB_PAGE_LIMIT。
    """

    state: JobState | None = None
    cursor: str | None = Field(default=None, min_length=1, max_length=JOB_CURSOR_MAX_CHARS)
    limit: int = Field(default=JOB_PAGE_LIMIT, ge=1, le=JOB_PAGE_LIMIT)


class JobResponse(JobPayload):
    """详情及列表中的永久记录，字段单位与 JobRecord 相同；时刻统一 UTC 微秒。

    Attributes:
        job_id: 1 至 2^63-1 规范十进制文本。
        type_name: 稳定类型键，1-64 字符。
        display_name: 提交时显示名快照，1-40 码点。
        parameters: 无秘密参数 JSON；历史原值，不按新版本静默改写。
        submitted_by: 历史身份和 deleted 标记；前端显示“名字（已删除）”。
        submitted_at: UTC 提交时刻。
        resubmitted_from: 原作业编号文本或 None。
        state: 六种状态之一。
        started_at: 首次开始 UTC 时刻或 None。
        ended_at: 终态结束 UTC 时刻或 None。
        progress: 最后进度或 None，未知 total 返回 null。
        progress_at: 最后进度 UTC 时刻或 None。
        elapsed_s: 有限非负秒数，存储的已运行时长；页面可据本地单调样本增量显示。
        log_path: 状态目录相对路径或 None，浏览器不据此直接访问文件。
        summary: 终态冻结摘要或 None，只有 completed 内 outcome 非空。
        diagnostics: 有界诊断组，真实总数与前 N 样例分别展示。
        recovery_mode: 提交时恢复方式快照，只作记录及interrupt保护。
        recovery_count: 自动恢复资格累计次数，0至JOB_RECOVERY_LIMIT；不随重跑清零。
    """

    job_id: AccountId
    type_name: str
    display_name: str = Field(min_length=1, max_length=JOB_DISPLAY_NAME_MAX_CHARS)
    parameters: dict[str, JsonValue]
    submitted_by: HistoricalActorResponse
    submitted_at: AwareDatetime
    resubmitted_from: AccountId | None
    state: JobState
    started_at: AwareDatetime | None
    ended_at: AwareDatetime | None
    progress: JobProgress | None
    progress_at: AwareDatetime | None
    elapsed_s: float = Field(ge=0, allow_inf_nan=False)
    log_path: str | None
    summary: JobSummary | None
    diagnostics: tuple[DiagnosticGroup, ...]
    recovery_mode: RecoveryMode
    recovery_count: int = Field(strict=True, ge=0, le=JOB_RECOVERY_LIMIT)


class JobListResponse(JobPayload):
    """按自增作业编号倒序的一页，最多 100 项；next_cursor 为 None 表示末页。"""

    items: tuple[JobResponse, ...]
    next_cursor: str | None


class WorkerStatusResponse(JobPayload):
    """在线状态和最近心跳，所有已登录账号可查看；空心跳不伪造 PID。

    Attributes:
        online: 按 15 秒 UTC 差判定，未来心跳按经过零秒。
        instance_id: 最近实例 uuid4 hex；无心跳为 None。
        pid: 最近实例正进程号；无心跳为 None。
        started_at: 实例 UTC 启动时刻；无心跳 None。
        last_seen_at: 最近 UTC 心跳；无心跳 None。
        checked_at: 本请求 UTC 时刻，便于解释判定边界。
    """

    online: bool
    instance_id: str | None
    pid: int | None
    started_at: AwareDatetime | None
    last_seen_at: AwareDatetime | None
    checked_at: AwareDatetime


class JobLogResponse(JobPayload):
    """日志尾部状态；cleared 明确提示已清除，未开始不是服务端错误。"""

    tail: LogTail
