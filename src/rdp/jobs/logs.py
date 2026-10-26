"""作业日志文件边界（领域层，08/09 Answer）；只访问显式状态目录的 logs 子树。

复用 pathlib、标准库文件 I/O 和 threading.Lock；业务格式、线程完整行和有限尾读在这里集中。
不使用运行日志的按天轮转 handler，因为一个作业跨天仍需追加同一文件。
"""

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

from rdp.infra.diagnostics import Diagnostic
from rdp.infra.state import StatePaths
from rdp.jobs.types import JobProgress, JobRecord, JobSummary, RecoveryMode


@dataclass(frozen=True)
class JobLogMetadata:
    """日志开头可选的复现信息，示例无配置或工具时明确省略相应项。

    Attributes:
        configuration: 无秘密的最终配置及配置哈希文本；没有为 None，最多 16 KiB。
        tool_version: 工具名和提交版本文本；没有工具为 None，最多 256 码点。
        protocol_version: 上报协议版本；没有上报通道为 None，本票示例固定 None。
    """

    configuration: str | None
    tool_version: str | None
    protocol_version: str | None


@dataclass(frozen=True)
class LogTail:
    """日志尾部结果，缺失与读取故障分开表达。

    Attributes:
        status: available、not_started、cleared；分别为已读取、未开始、日志已清除。
        lines: 最后至多 JOB_LOG_TAIL_LINES 行，时间顺序；非 available 为空。
        truncated: 超出 JOB_LOG_TAIL_MAX_BYTES 或行数时 True；不把首个半行冒充完整行。
    """

    status: Literal["available", "not_started", "cleared"]
    lines: tuple[str, ...]
    truncated: bool


class JobLog:
    """一个作业的串行追加文件；由 open_job_log 创建，执行器最终关闭，不跨进程共享句柄。"""

    def __init__(self, path: Path) -> None:
        """打开已验证的作业日志并建立线程间写锁。

        Args:
            path: open_job_log 校验过且在状态 logs 下的绝对普通文件路径。

        Returns:
            无；实例持有追加文件和不可继承的文件描述符。

        Raises:
            ExternalError: 打开文件权限、磁盘或 I/O 失败，诊断包含日志路径。
            DefectError: 路径不是普通文件、是软链接或调用次序错误。

        Side Effects:
            以 UTF-8 追加打开文件，不截断已有内容；失败关闭本次句柄，可能留下新建空文件。

        Time Semantics:
            同步本地 I/O，无重试；调用方保证状态目录不被恶意并发替换。
        """
        raise NotImplementedError

    def write_header(self, record: JobRecord, metadata: JobLogMetadata) -> None:
        """追加一次可复现的作业开头。

        Args:
            record: 已领取的记录，含编号、类型、提交人及无秘密参数。
            metadata: 可选配置/哈希、工具版本、协议版本，没有则不写对应项。

        Returns:
            无；开头明确标识 job_id、稳定键、显示名、提交人编号/快照、参数。

        Raises:
            ExternalError: 写入或刷新失败。
            DefectError: 无开始时刻、元数据超长、实例已关闭或无效参数快照。

        Side Effects:
            在同一锁内追加完整段落并 flush；不修改数据库，失败可能留下部分段落，不宣称已持久化。

        Time Semantics:
            在执行函数开始之前写；行内时刻采用 UTC 并注明 Z，与文件名、数据库对齐。
        """
        raise NotImplementedError

    def write_line(self, text: str, *, now: datetime) -> None:
        """在线程间互斥地追加平台过程消息。

        Args:
            text: 无秘密消息，含换行时逐行加时间前缀，最大 JOB_LOG_TAIL_MAX_BYTES 字节。
            now: 注入 aware 时刻，转换 UTC，拒绝 naive。

        Returns:
            无；每条物理行完整写入后刷新，线程间不混写半行。

        Raises:
            ExternalError: 写/flush I/O 失败，交执行器最外层报告。
            DefectError: 文本超上限、时刻非法、已关闭或并发使用违反生命周期。

        Side Effects:
            只追加日志；失败不截断先前内容，不在本层再写 ERROR。

        Time Semantics:
            写锁等待最多 OUTPUT_JOIN_TIMEOUT_S；超时为 ExternalError，不无限等线程。
        """
        raise NotImplementedError

    def write_diagnostic(self, diagnostic: Diagnostic, *, now: datetime) -> None:
        """将统一诊断完整写到作业日志，内存聚合不影响原始日志内容。

        Args:
            diagnostic: 已校验且不含秘密的统一诊断对象。
            now: aware 当前时刻，日志统一 UTC。

        Returns:
            无；使用 render_diagnostic 的五段格式，保留对象、实际、后果和下一步。

        Raises:
            ExternalError: 日志锁或磁盘写入失败。
            DefectError: 非法诊断、时钟或关闭后调用。

        Side Effects:
            追加并刷新诊断段，不修改计数，不重复向运行日志报告。

        Time Semantics:
            按进入写锁的次序记录，不按墙钟排序重写；锁预算 OUTPUT_JOIN_TIMEOUT_S。
        """
        raise NotImplementedError

    def write_interruption(
        self,
        progress: JobProgress | None,
        mode: RecoveryMode | Literal["cancel", "fail"],
        *,
        now: datetime,
        reason: str,
    ) -> None:
        """在恢复状态或重新执行之前追加中断段。

        Args:
            progress: 上一实例最后持久化进度；从未上报时 None，明确写“尚未上报”。
            mode: 本次处理方式；cancel表示正在取消收尾，fail表示类型/参数过时，其他为三种恢复枚举。
            now: 当前实例恢复的aware UTC时刻。
            reason: 固定安全原因说明，1至JOB_TEXT_MAX_CHARS码点；例如当前类型缺失、任一声明中断或恢复次数已达3次。

        Returns:
            无；段落含“中断”、阶段序号/名称、最后全部进度和计数、处理方式及reason，不仅写枚举而遗漏超过恢复上限的原因。

        Raises:
            ExternalError: 追加或刷新失败；不得再执行该作业，恢复边界仍可尝试将此条标记中断/已取消后继续别条。
            DefectError: 进度、恢复枚举或时刻非法。

        Side Effects:
            只追加原文件，不覆盖原开头；后续数据库失败可能在再次启动时再追加一个中断段。

        Time Semantics:
            正常恢复必须先flush本段，再计恢复次数、更新状态或清零/执行；日志故障隔离落终态为唯一例外，需ERROR说明缺日志。锁预算OUTPUT_JOIN_TIMEOUT_S。
        """
        raise NotImplementedError

    def write_summary(self, summary: JobSummary, *, now: datetime) -> None:
        """把已提交的冻结摘要逐项追加为日志结尾。

        Args:
            summary: 数据库终态事务返回的同一摘要，不重新推算结果、计数、耗时或产物。
            now: 摘要提交后的 aware UTC 日志时刻。

        Returns:
            无；最终状态、结果、全部进度/计数、aborted、elapsed_s、产物、工具退出码逐项与数据库一致。

        Raises:
            ExternalError: 日志追加失败；数据库终态仍保留，执行器 ERROR 说明摘要未写齐。
            DefectError: 非终态/摘要组合非法、已关闭或时钟错误。

        Side Effects:
            先提交数据库后追加文件，二者没有跨资源事务；故障可能只剩数据库摘要或半段结尾，
            不回滚已提交终态，不把未提交的候选摘要写成最终结论。

        Time Semantics:
            正常结束和取消/标记中断均调用；数据库终态失败时不调用。锁预算 OUTPUT_JOIN_TIMEOUT_S。
        """
        raise NotImplementedError

    def close(self) -> None:
        """在所有写线程已停止后刷新并释放文件。

        Args:
            无。

        Returns:
            无；重复关闭幂等。

        Raises:
            ExternalError: 最终刷新或关闭 I/O 失败；已有内容不删除。

        Side Effects:
            关闭句柄；调用方 finally 回收，已有主异常时附安全清理说明，不以关闭故障覆盖它。

        Time Semantics:
            先回收执行/输出线程再关闭，锁等待最多 OUTPUT_JOIN_TIMEOUT_S，不进行保留期清除。
        """
        raise NotImplementedError


def open_job_log(paths: StatePaths, record: JobRecord) -> tuple[JobLog, bool]:
    """只按领取事务已登记的路径创建或追加作业日志。

    Args:
        paths: initialize_state已建立的可信状态布局，只访问logs子树。
        record: 已有started_at和非空log_path的记录；领取时已原子确定唯一相对路径。

    Returns:
        日志实例和needs_header标记；新建或空文件为True，已有非空日志为False。
        文件不存在时在原登记路径排他新建，不重新选择时间名或编号后缀；
        调用者必须先write_header，再写中断段或执行。历史被清除与领取后尚未创建均明确说明“登记的日志文件不存在”。

    Raises:
        DefectError: 路径越出logs、软链接、非法显示名、缺开始时刻/登记路径或路径不匹配记录。
        ExternalError: 创建目录/文件、打开或权限失败，诊断含受限日志路径。

    Side Effects:
        只创建logs下目录/文件，不覆盖或截断。已有路径只追加，失败可能留下空文件，下一次needs_header仍为True。
        不计算新文件名、不更新数据库路径；同毫秒撞名在领取事务中已处理，文件只归该job_id。

    Time Semantics:
        先提交含日志路径的领取事务，再打开文件；恢复同一路径不随当前墙钟改名。
        创建冲突只核对本次路径是否已出现合法文件，不进行无界重新命名或重试。
    """
    raise NotImplementedError


def read_log_tail(paths: StatePaths, relative_path: str | None) -> LogTail:
    """有限读取日志尾部，区分未开始、已清除与真实故障。

    Args:
        paths: 显式状态布局，可信 root/logs，不从请求接收根目录。
        relative_path: 数据库保存的相对路径；None 表示作业尚未产生文件。

    Returns:
        None 路径为 not_started；文件不存在为 cleared，页面显示“作业日志已清除”；
        存在为 available，seek 尾部只读至多 JOB_LOG_TAIL_MAX_BYTES，再取最后 JOB_LOG_TAIL_LINES。
        UTF-8 首部半字符/半行舍弃并标 truncated，末尾尚未写完的行不作为完整行返回。

    Raises:
        DefectError: 绝对路径、..、解析后越出 logs、软链接指向越界或目标非普通文件。
        ExternalError: 非 FileNotFoundError 的权限/读取故障，不伪装已清除。

    Side Effects:
        无；只读有限尾部，不全量 read_text、不更改保留期或访问存储根。

    Time Semantics:
        单次同步本地尾读，允许看见执行中的最新完整行；不加 worker 写锁、不轮询等待下一行。
    """
    raise NotImplementedError
