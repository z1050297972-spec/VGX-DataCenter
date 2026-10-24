"""基础层的运行日志与上下文契约，依赖 config，不依赖 state 或任何入口/Web 框架。

依据 M0 工单 03、09 号决策票和 ADR 0005；不写作业日志、操作日志或登录日志。
单进程写一个文件：v1 Web 只能有一个 uvicorn worker；Web/worker 各用自己的文件。
用标准库 logging、contextvars、TimedRotatingFileHandler，不自行实现通用日志框架。
标准 handler 的墙钟和本地时区不可按实例注入，且 backupCount 是文件数而非日历天；
因此仅用私有子类适配切分时刻及过期判断，复用标准库的 emit、锁和文件流管理。
"""

import logging
from collections.abc import Callable
from contextlib import AbstractContextManager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, tzinfo
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from typing import Literal, override

from rdp.infra.config import LoadedConfig, LogConfig

logger = logging.getLogger(__name__)

# 09 号票要求自动关联当前作业/请求；None 表示未绑定，不输出该 key。
job_id_context: ContextVar[int | None] = ContextVar("rdp_job_id", default=None)
request_id_context: ContextVar[str | None] = ContextVar("rdp_request_id", default=None)


def _utc_now() -> datetime:
    """返回带 UTC 时区的当前墙钟，不用于测量耗时。"""
    raise NotImplementedError


def _local_timezone() -> tzinfo:
    """用 zoneinfo 只读 /etc/localtime 的规则时区；读取失败保留 OSError，不修改 TZ。"""
    raise NotImplementedError


@dataclass(frozen=True)
class LogTime:
    """日志显示和日历切分共用的时间依赖，测试可注入固定或可推进的实现。

    Attributes:
        now: 无参数时钟，返回带有效时区的 datetime；默认 _utc_now，单位微秒。
            可返回任意有效时区，内部统一转 UTC；不返回 naive 时刻，不用于算耗时。
        timezone: 无参数时区提供器，返回有效 tzinfo（固定偏移或带规则的 ZoneInfo）；
            默认 _local_timezone，每条记录重新取值，系统时区修改在下条记录生效。
            测试传固定时区，禁止修改进程 TZ；默认规则文件读取失败传播 OSError。
    """

    now: Callable[[], datetime] = _utc_now
    timezone: Callable[[], tzinfo] = _local_timezone


# 冻结对象只保存函数引用，不在导入时读取时钟；供公开函数共享默认依赖。
_SYSTEM_LOG_TIME = LogTime()


@dataclass(frozen=True)
class LoggingSettings:
    """一次进程启动所需的不可变日志设置，不增加 TOML 配置项。

    Attributes:
        process: 进程名，无单位；只允许 web 或 worker，必填，无默认值。
        log_dir: 已存在且可写的日志目录绝对 Path，无单位；必填，无默认值。
        stderr: 是否同时写当前 sys.stderr，布尔值；默认 False，符合 systemd 约定。
        log: 已校验的 LogConfig，无单位；默认 LogConfig()，包含级别和保留天数。
    """

    process: Literal["web", "worker"]
    log_dir: Path
    stderr: bool = False
    log: LogConfig = LogConfig()


class RuntimeFormatter(logging.Formatter):
    """把标准 LogRecord 格式化为统一的中文运行日志，不承担敏感内容识别。"""

    def __init__(self, time_source: LogTime = _SYSTEM_LOG_TIME) -> None:
        """建立使用指定时间依赖的运行日志格式化器。

        Args:
            time_source: 时钟与时区依赖，无单位；默认使用 UTC 墙钟和系统本地时区。

        Returns:
            无。得到尚未读取时钟或修改全局 logging 的格式化器。

        Raises:
            无。

        Side Effects:
            无。

        Time Semantics:
            不在构造时冻结时钟或本地时区；格式化时取快照。
        """
        raise NotImplementedError

    @override
    def format(self, record: logging.LogRecord) -> str:
        r"""把一条日志及缩进明细格式化，不写输出流。

        Args:
            record: 标准 LogRecord；消息由调用方提供中文，使用 getMessage() 合并参数。
                可通过 extra={"fields": {...}} 传上下文，键须匹配 [A-Za-z_][A-Za-z0-9_]*；
                值仅为 str/int/有限 float/bool/None。禁止口令、令牌、cookie、私钥及整份载荷；
                job_id/request_id 为保留键，不得从 fields 注入。未设置 fields 等价于空映射。

        Returns:
            首行严格为“时间 级别 模块 中文消息 key=value…”，字段间一个 ASCII 空格；
            时间例如 2026-10-21 16:15:02.123+08:00，毫秒截断，不舍入；
            模块取 record.name，级别取 record.levelname，空字段时不留尾随空格。
            fields 按键字典序排列，然后依次追加非 None 的 job_id、request_id。
            字符串匹配 [A-Za-z0-9_./:@+-]+ 时原样输出；其他字符串含空串均用
            json.dumps(ensure_ascii=False) 的双引号与转义，空格、等号、换行不破坏字段边界；
            bool/None 输出 true/false/null，数字用 JSON 表示，拒绝 NaN/Infinity。
            消息 CRLF/CR 统一成 LF，首行后每条明细（含空行）前加四个 ASCII 空格；
            key=value 只加首行。异常链及 stack_info 用标准库格式化并同样缩进；无末尾换行。

        Raises:
            ValueError: fields 不是映射、键非法/使用保留键、值非允许标量或浮点非有限；
                或注入时钟/时区不能提供有效 aware 时刻。拒绝输出部分日志。
            TypeError: 消息的格式串与参数不匹配，保留 getMessage() 的错误，属调用方缺陷。
            OverflowError: 时间换算超出 datetime 的 1 至 9999 年范围。
            OSError: 默认时区提供器读取本地规则文件失败，保留路径及原因，不猜测时区。

        Side Effects:
            在 record 上缓存私有的时间/时区/上下文快照，文件和 stderr 复用同一快照；
            不修改消息、fields、异常缓存或 contextvars，不写磁盘、不输出 stderr。
            校验失败不缓存部分结果，不把 fields 的值写进异常消息。

        Time Semantics:
            首次格式化时从 time_source 读取时钟和时区一次；使用记录时的上下文快照。
            同一记录多次格式化时间与关联编号不变；同步处理，不使用队列或后台线程。
        """
        raise NotImplementedError


# 骨架阶段配置函数只有 raise；第二步 configure_logging 创建此类后删除本条豁免。
class _DailyFileHandler(TimedRotatingFileHandler):  # pyright: ignore[reportUnusedClass]
    """只适配可注入的日历切分，保留标准库单进程写文件的边界。"""

    def __init__(self, settings: LoggingSettings, time_source: LogTime) -> None:
        """按 settings 追加打开 UTF-8 文件；以注入时钟初始化日界，不用文件 mtime 猜当前时间。"""
        raise NotImplementedError

    @override
    def shouldRollover(self, record: logging.LogRecord) -> bool:
        """按注入时钟判断是否越过当地零点；时钟回拨不重复切分，忽略 record.created。"""
        raise NotImplementedError

    @override
    def doRollover(self) -> None:
        """按旧区间当地日期归档；同名归档追加合并而不覆盖，清过期文件后重开当前文件。"""
        raise NotImplementedError

    @override
    def getFilesToDelete(self) -> list[str]:
        """按注入时区的当前日期返回过期的本进程日期归档，绝对路径排序；无过期时为空。"""
        raise NotImplementedError


def configure_logging(
    settings: LoggingSettings, *, time_source: LogTime = _SYSTEM_LOG_TIME
) -> None:
    """为单个进程安装文件输出及可选 stderr，并统一接管 uvicorn 日志。

    Args:
        settings: 进程、绝对日志目录、stderr 开关、级别及保留天数的不可变设置；
            目录须预先由 initialize_state 创建。process 只能是 web/worker。
        time_source: 日志格式化及切分共用的时钟和时区，默认 LogTime()；测试显式注入。

    Returns:
        无。root logger 按 settings.log.level 接收日志；web 只写 web.log，
        worker 只写 worker.log，UTF-8 追加，使用 RuntimeFormatter 和 _DailyFileHandler。
        stderr=True 时同时写 sys.stderr，False 时本配置不向 stderr 输出。
        uvicorn、uvicorn.error 清空自有 handler、启用传播且使用统一阈值；
        uvicorn.access 禁用、清空 handler 且不传播，包括 /api/health 均不输出访问日志。
        第 11 张启动 uvicorn 时必须传 log_config=None、access_log=False，避免再次覆盖配置；
        本函数只按 logger 名字操作，不 import uvicorn、fastapi 或 starlette。

    Raises:
        ValueError: process 不合法、log_dir 非绝对路径，或时钟/时区返回无效 aware 时刻。
        FileNotFoundError: 日志目录不存在；不隐式建目录。
        NotADirectoryError: 日志目录不是目录。
        OverflowError: 注入时刻换算或计算下一次零点超出 datetime 的 1 至 9999 年范围。
        OSError: 打开/追加日志文件、读取本地时区规则或切分所需状态失败，例如权限不足、磁盘满。
            所有初始化失败均关闭本次新建的 handler，原 logging 配置保持不变。

    Side Effects:
        创建或追加打开本进程日志文件，修改 root 及上述三个 logger 的 handler、级别和传播设置。
        成功后替换旧 root handler，关闭本模块之前创建的 handler；外部 handler 只解除挂载不关闭。
        其他命名 logger 不改；调用方须确保应用 logger 不自行挂 handler，并向 root 传播。
        重复调用（包括换 process/目录）原子替换本模块输出，不重复写；旧文件内容不改。
        失败可能留下新建的空日志文件，不删除已有文件；不改目录权限。
        运行中在越过当地零点后的第一条日志前归档为 <process>.log.YYYY-MM-DD；
        后缀为被关闭区间的起始当地日期。长期无日志时不生成空的逐日文件。
        切分时删除日期早于“当前当地日期减 retention_days”的本进程归档，边界日保留；
        当前文件、别的进程文件、非日期后缀、目录及软链接均不删除。无新日志不清理。
        重启后首条日志也做过期清理，已有活动文件从本次启动建立新区间，不按 mtime 回溯切分。
        切分/写入失败遵循标准 handler.handleError，不向业务抛 I/O 异常；
        设置 logging.raiseExceptions=False，systemd 下也不因日志自身故障写 stderr。
        这种运行期失败可能丢失当前记录或留下已完成的归档，不承诺磁盘故障下日志不丢。

    Time Semantics:
        只在启动或停止接收请求后串行配置，不与 emit 并发重配。
        每个当地自然日的下一次零点切分，夏令时日可为 23/25 小时，不按固定 86400 秒累加。
        时钟回拨不重复归档，追上原边界才切分；时区变化从下条记录重算未来边界，
        不把单纯换时区当作已越过旧边界。无休眠、重试、全局 TZ 修改或定时线程。
    """
    raise NotImplementedError


def log_context(
    *, job_id: int | None = None, request_id: str | None = None
) -> AbstractContextManager[None]:
    """临时绑定作业与请求编号，并在离开作用域时恢复原值。

    Args:
        job_id: 正整数作业编号，无单位；拒绝 bool；None 表示保留当前绑定，不强制清空。
        request_id: 无单位的 32 位小写十六进制 uuid4.hex；None 表示保留当前绑定。
            非 None 时须具有 UUID v4 的版本及 variant 位，与 Web 生成规则一致。

    Returns:
        同步上下文管理器，进入时返回 None；可在 async 函数内用 with。
        无参数时保持两个绑定不变；支持嵌套，退出（包括异常、任务取消）用 token 恢复原值。

    Raises:
        ValueError: 进入上下文时编号非法；两个参数全部校验后才设置，不留下部分绑定。
        BaseException: with 体内异常原样传播，不吞掉 CancelledError 或业务异常。

    Side Effects:
        只修改当前 contextvars 上下文；不改其他并发任务或线程的绑定，不打日志。
        新 asyncio 任务按标准 contextvars 规则继承创建时上下文，之后修改互不影响；
        不负责把上下文传播到任意手工创建的线程。

    Time Semantics:
        绑定在进入 with 时生效，离开时立即恢复，不读取时钟或等待。
    """
    raise NotImplementedError


def log_config_source(loaded: LoadedConfig) -> None:
    """在启动边界记录缺省配置来源，不重复读取文件。

    Args:
        loaded: load_config 的结果，无单位；日志和目录已由第 11 张入口配置完成。

    Returns:
        无。used_defaults=True 时按 INFO 发出一条“使用默认配置”，fields 仅含 config_file 路径；
        False 时不发日志。遵循配置阈值，WARNING/ERROR 阈值下此 INFO 不落盘。

    Raises:
        无。

    Side Effects:
        无（仅运行日志）。不修改 loaded、不建文件以外的资源，不缓存全局“已记录”标记；
        每次调用独立发出至多一条，启动入口负责每次成功启动只调用一次。

    Time Semantics:
        先 load_config，再 initialize_state，再 configure_logging，最后调用本函数；
        日志时间取日志配置的注入时钟，配置错误由启动入口报告，不在读取层重复记录。
    """
    raise NotImplementedError
