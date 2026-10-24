"""基础层报错记录读写与保留期契约（05/E2），不拥有会话、不调度定时任务、不记日志。

复用 SQLAlchemy 查询及 Pydantic 校验；编号规则是平台的请求/作业关联语义。
禁止附加请求体、SQL 参数、口令、令牌、cookie 或私钥；生产者负责安全摘要和报告来源。
"""

from datetime import datetime
from typing import Literal, Self

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator
from sqlalchemy.orm import Session

from rdp.infra.db.models import MAX_ERROR_SUMMARY_CHARS, MAX_EXCEPTION_REPORT_CHARS
from rdp.infra.diagnostics import DiagnosticCategory


class ErrorRecord(BaseModel):
    """脱离 Session 的不可变报错快照，同时作为查询接口响应模型。

    Attributes:
        error_id: 编号，无单位、必填不可空、无默认；request 为小写 uuid4 hex，job 为
            1-9223372036854775807 的规范十进制字符串；不是 ProblemResponse.error_id 的放宽。
        occurred_at: 发生时刻，aware datetime、精度微秒，必填不可空、无默认；模型规范化为 UTC，
            JSON 按 UTC ISO 8601 输出；列存储仍必须用六位微秒的 UTCDateTime。
        category: DiagnosticCategory 四种之一，无单位、不可空、无默认；请求缺陷固定 defect。
        summary: 安全摘要，1-512 个 Unicode 字符，至少含非空白字符，不含换行；必填不可空、无默认。
        report: 安全异常链及 traceback，1-262144 个 Unicode 字符；必填不可空、无默认；
            直接使用 format_exception_report 输出，保留其截断标记，不再添加诊断或上下文。
        source_kind: request/job，无单位、必填不可空、无默认；编号直接由 error_id 表示。
    """

    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)

    error_id: str = Field(strict=True, min_length=1, max_length=32)
    occurred_at: AwareDatetime
    category: DiagnosticCategory
    summary: str = Field(strict=True, min_length=1, max_length=MAX_ERROR_SUMMARY_CHARS)
    report: str = Field(strict=True, min_length=1, max_length=MAX_EXCEPTION_REPORT_CHARS)
    source_kind: Literal["request", "job"]

    @model_validator(mode="after")
    def _validate_record(self) -> Self:
        """按来源校验编号、摘要单行及 ensure_utc；ValueError 包装为不回显载荷的 ValidationError。"""
        raise NotImplementedError


def write_error(session: Session, record: ErrorRecord) -> None:
    """在当前写工作单元中插入并 flush 一条报错，不覆盖既有编号。

    Args:
        session: session_scope 提供的写会话，无单位，不可并发使用；不能是 read_only。
        record: 已校验的不可变快照；无单位，report 必须与运行日志采用同一格式化结果。

    Returns:
        无；插入一条完整记录并 flush，提交由外层工作单元负责；同编号不允许多条。

    Raises:
        ConflictError: 编号重复或约束冲突，保留第一条；锁竞争按 connection 的规则转换。
        InputError: 数据库损坏或 UTC 列拒绝值；含数据库/编号的安全诊断，不回显报告。
        ExternalError: 文件权限、磁盘满或 I/O 故障。
        DefectError: 只读会话写入或其他数据库编程错误；不把 SQL 参数放入诊断。

    Side Effects:
        当前事务增加一行；失败后调用者必须退出 session_scope 回滚整个工作单元，
        不在失败会话里继续查询，不留下半条记录；本函数不 commit、不另开会话、不记日志。

    Time Semantics:
        发生时间由 record 决定，不读时钟；写锁已在进入工作单元时取得，无额外重试。
    """
    raise NotImplementedError


def find_error(session: Session, error_id: str) -> ErrorRecord | None:
    """按规范编号查至多一条报错，返回不依赖会话的快照。

    Args:
        session: session_scope 提供的只读或写会话，无单位，不并发使用。
        error_id: 请求 uuid4 hex 或作业的规范正整数十进制文本，无单位，不能带前缀或前导零。

    Returns:
        找到时返回完整 ErrorRecord；找不到时 None（包括已清除记录），不伪造 traceback。

    Raises:
        InputError: 编号格式非法，或读到损坏 UTC/行数据/数据库；诊断不回显非法原值。
        ConflictError: SQLite 读操作遇到 BUSY/LOCKED。
        ExternalError: 读取权限或 I/O 故障。
        DefectError: 其他 SQL 或映射错误。

    Side Effects:
        无（只读报错表）；不按访问延长保留期，不写日志，最多物化一条有界报告。

    Time Semantics:
        返回事务内快照，时间是 UTC；不等记录将来出现，不轮询、不重试。
    """
    raise NotImplementedError


def clear_expired_errors(session: Session, *, now: datetime, retention_days: int) -> int:
    """按显式时钟删除严格早于保留边界的报错。

    Args:
        session: session_scope 的写会话，无单位；调度由第 09 张负责。
        now: 当前 aware datetime，微秒精度，内部 ensure_utc；测试传固定时刻，不读系统时钟。
        retention_days: UTC 的 24 小时时段数，严格整数 1-MAX_RETENTION_DAYS（3650），
            拒绝 bool；来自 PlatformConfig.errors.retention_days，默认 30。

    Returns:
        本事务删除的行数，整数且非负；无过期记录为 0。
        截止 now - timedelta(days=retention_days)，occurred_at 严格小于才删除；
        恰好等于截止、未来记录都保留，不使用本地日历天。

    Raises:
        InputError: now 无时区、换算/减法超出 datetime 范围，或保留天数类型/范围错误；
            执行 SQL 前拒绝，不删任何行；也用于数据库损坏。
        ConflictError: 锁或约束冲突。
        ExternalError: 文件权限、磁盘满或 I/O 故障。
        DefectError: 只读会话或其他 SQL/驱动编程错误。

    Side Effects:
        使用带 occurred_at 索引的单条 DELETE，不加载报告列表；不 VACUUM、不提交。
        失败时由 session_scope 回滚，不留下部分清除；没有定时器、日志或隐式重试。

    Time Semantics:
        UTC 的固定 24 小时，微秒严格比较，不受 -06:00 或夏令时影响；锁等待同 session_scope。
    """
    raise NotImplementedError
