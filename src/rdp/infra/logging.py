"""基础层的运行日志与上下文契约，依赖 config 和 state 的权限快照，不依赖任何入口/Web 框架。

依据 M0 工单 03、09 号决策票和 ADR 0005；不写作业日志、操作日志或登录日志。
单进程写一个文件：v1 Web 只能有一个 uvicorn worker；Web/worker 各用自己的文件。
用标准库 logging、contextvars、TimedRotatingFileHandler，不自行实现通用日志框架。
标准 handler 的墙钟和本地时区不可按实例注入，且 backupCount 是文件数而非日历天；
因此仅用私有子类适配切分时刻及过期判断，复用标准库的 emit、锁和文件流管理。
"""

import json
import logging
import math
import re
import shutil
from collections.abc import Callable, Generator, Mapping
from contextlib import AbstractContextManager, contextmanager, suppress
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta, tzinfo
from datetime import time as datetime_time
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from typing import Literal, cast, override
from zoneinfo import ZoneInfo

from rdp.infra.config import LoadedConfig, LogConfig
from rdp.infra.ids import is_request_id
from rdp.infra.state import DirectoryPermissionWarning
from rdp.infra.timeutil import ensure_utc

logger = logging.getLogger(__name__)

# 运行日志字段键采用标识符形式；不符合时加引号，避免歧义而不丢整行。
_FIELD_KEY_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
# 只把标准日期后缀识别为候选归档，避免误删其他日志文件。
_ARCHIVE_DATE_SUFFIX_PATTERN = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
# 这些 ASCII 字符不会破坏 key=value 边界；其他字符串统一使用 JSON 引号和转义。
_SAFE_FIELD_STRING_PATTERN = re.compile(r"[A-Za-z0-9_./:@+-]+")

# 仅持有本模块安装的输出，重配时不关闭 pytest/宿主应用拥有的 handler。
_installed_handlers: tuple[logging.Handler, ...] = ()

# 09 号票要求自动关联当前作业/请求；None 表示未绑定，不输出该 key。
job_id_context: ContextVar[int | None] = ContextVar("rdp_job_id", default=None)
request_id_context: ContextVar[str | None] = ContextVar("rdp_request_id", default=None)


def _utc_now() -> datetime:
    """返回带 UTC 时区的当前墙钟，不用于测量耗时。"""
    return datetime.now(UTC)


def _local_timezone() -> tzinfo:
    """用 zoneinfo 只读 /etc/localtime 的规则时区；读取失败保留 OSError，不修改 TZ。"""
    # 切分检查和格式化使每条日志通常读取这个小文件两三次，清理时可能更多。
    # v1 日志量小，接受此代价，以保证系统时区修改在下一条记录生效。
    # P1 决定按本机时区写；第 11 张 systemd 单元不设 TZ，因此这里不读取 TZ 环境变量。
    path = Path("/etc/localtime")
    with path.open("rb") as stream:
        return ZoneInfo.from_file(stream, key=str(path.resolve()))


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


@dataclass(frozen=True)
class _RecordSnapshot:
    """同一记录在多个输出流之间共用的不可变上下文。

    Attributes:
        moment: 本地 aware 时刻，微秒精度，无默认值。
        job_id: 正整数作业编号或 None，无默认值。
        request_id: uuid4.hex 请求编号或 None，无默认值。
    """

    moment: datetime
    job_id: int | None
    request_id: str | None


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
        super().__init__()
        self._time_source = time_source

    @override
    def format(self, record: logging.LogRecord) -> str:
        r"""把一条日志及缩进明细格式化，不写输出流。

        Args:
            record: 标准 LogRecord；消息由调用方提供中文，使用 getMessage() 合并参数。
                可通过 extra={"fields": {...}} 传上下文，键须匹配 [A-Za-z_][A-Za-z0-9_]*；
                值推荐为 str/int/有限 float/bool/None，不规范字段按 Returns 容错。
                禁止口令、令牌、cookie、私钥及整份载荷；job_id/request_id 为保留键。
                未设置 fields 等价于空映射。

        Returns:
            首行严格为“时间 级别 模块 中文消息 key=value…”，字段间一个 ASCII 空格；
            时间例如 2026-10-21 16:15:02.123+08:00，毫秒截断，不舍入；
            模块取 record.name，级别取 record.levelname，空字段时不留尾随空格。
            fields 按键字典序排列，然后依次追加非 None 的 job_id、request_id。
            字符串匹配 [A-Za-z0-9_./:@+-]+ 时原样输出；其他字符串含空串均用
            json.dumps(ensure_ascii=False) 的双引号与转义，空格、等号、换行不破坏字段边界；
            bool/None 输出 true/false/null，有限数字用 JSON 表示。
            其他值先 str() 再按字符串规则输出；str() 抛 Exception 时用 <无法字符串化>。
            非有限浮点用带 JSON 引号的 nan/inf/-inf 字符串；非法键字符串化后加 JSON 引号；
            用户字段中的 job_id/request_id 丢弃，不影响可信上下文。非映射 fields 作为
            fields=<字符串化的值> 输出；映射遍历失败时输出 fields="<无法读取字段>"。
            P2：以上字段问题均保留整行，不抛格式化异常。
            消息 CRLF/CR 统一成 LF，首行后每条明细（含空行）前加四个 ASCII 空格；
            key=value 只加首行。异常链及 stack_info 用标准库格式化并同样缩进；无末尾换行。

        Raises:
            ValueError: 注入时钟/时区不能提供有效 aware 时刻，属于配置错误；
                configure_logging 会预检，单独使用格式化器时仍保留此检查。
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
        snapshot = record.__dict__.get("_rdp_snapshot")
        if not isinstance(snapshot, _RecordSnapshot):
            snapshot = _RecordSnapshot(
                _local_time(self._time_source), job_id_context.get(), request_id_context.get()
            )
        timestamp = snapshot.moment.isoformat(sep=" ", timespec="milliseconds")
        suffix = _render_fields(record.__dict__.get("fields", {}))
        for key, value in (("job_id", snapshot.job_id), ("request_id", snapshot.request_id)):
            if value is not None:
                suffix += f" {key}={value}"
        message = record.getMessage()
        if record.exc_info:
            message += "\n" + self.formatException(record.exc_info)
        if record.stack_info:
            message += "\n" + self.formatStack(record.stack_info)
        lines = message.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        first = f"{timestamp} {record.levelname} {record.name} {lines[0]} {suffix.strip()}".rstrip()
        result = "\n".join((first, *("    " + line for line in lines[1:])))
        # 全部格式化成功后才发布快照，失败的记录修正后可重新格式化。
        record.__dict__["_rdp_snapshot"] = snapshot
        return result


class _DailyFileHandler(TimedRotatingFileHandler):
    """只适配可注入的日历切分，保留标准库单进程写文件的边界。"""

    def __init__(self, settings: LoggingSettings, time_source: LogTime) -> None:
        """按 settings 追加打开 UTF-8 文件；以注入时钟初始化日界，不用文件 mtime 猜当前时间。"""
        self._time_source = time_source
        moment = _local_time(time_source)
        self._interval_start = moment.date()
        self._zone_identity = str(moment.tzinfo)
        self.rolloverAt = _next_midnight(moment)
        self.backupCount = settings.log.retention_days
        self._startup_cleanup = True
        # TimedRotatingFileHandler.__init__ 硬读 time.time/mtime，无法实例级注入。
        # 直接初始化其文件基类，仍复用 BaseRotatingHandler.emit、Handler 锁与文件流。
        logging.FileHandler.__init__(
            self, settings.log_dir / f"{settings.process}.log", encoding="utf-8"
        )

    @override
    def shouldRollover(self, record: logging.LogRecord) -> bool:
        """按注入时钟判断是否越过当地零点；时钟回拨不重复切分，忽略 record.created。"""
        if self._startup_cleanup:
            self._delete_expired()
            self._startup_cleanup = False
        moment = _local_time(self._time_source)
        if str(moment.tzinfo) != self._zone_identity:
            # 单纯更换展示时区不补做旧时区的切分，从新时区的未来零点开始。
            self._zone_identity = str(moment.tzinfo)
            self.rolloverAt = _next_midnight(moment)
            return False
        return moment.timestamp() >= self.rolloverAt

    @override
    def doRollover(self) -> None:
        """按旧区间当地日期归档；同名归档追加合并而不覆盖，清过期文件后重开当前文件。"""
        moment = _local_time(self._time_source)
        if self.stream is not None:
            self.stream.close()
            self.stream = None
        destination = Path(f"{self.baseFilename}.{self._interval_start.isoformat()}")
        active = Path(self.baseFilename)
        # 上次可能已完成归档、却在清理时失败；活动文件缺失时继续清理和重开，不能反复读缺失源。
        if active.exists():
            if destination.exists():
                # 同日期可能已有重启前归档；追加合并而不是由 rename 覆盖旧证据。
                with active.open("rb") as source, destination.open("ab") as target:
                    shutil.copyfileobj(source, target)
                active.unlink()
            else:
                self.rotate(self.baseFilename, str(destination))
        self._delete_expired()
        self._interval_start = moment.date()
        self.rolloverAt = _next_midnight(moment)
        self.stream = self._open()

    def _delete_expired(self) -> None:
        """逐个尝试删除过期归档，单文件失败不阻断当前记录或其他归档的清理。"""
        try:
            expired = self.getFilesToDelete()
        except OSError:
            # 枚举和属性查询也是清理的一部分；失败只放弃本次清理，不阻断活动日志。
            # 正常返回让调用方清掉启动标记，或推进切分边界并重开文件，下次切分再试。
            return
        for filename in expired:
            # 清理失败不能让每条日志都走 handleError 丢弃；留下的归档下次切分或启动再试。
            # FileNotFoundError 也是 OSError：枚举后被其他清理者删除时同样继续。
            with suppress(OSError):
                Path(filename).unlink()

    @override
    def getFilesToDelete(self) -> list[str]:
        """按注入时区的当前日期返回过期的本进程日期归档，绝对路径排序；无过期时为空。"""
        current = _local_time(self._time_source).date()
        cutoff = date.fromordinal(max(1, current.toordinal() - self.backupCount))
        base = Path(self.baseFilename)
        prefix = base.name + "."
        expired: list[str] = []
        for candidate in base.parent.iterdir():
            suffix = candidate.name.removeprefix(prefix)
            if not candidate.name.startswith(prefix) or not _ARCHIVE_DATE_SUFFIX_PATTERN.fullmatch(
                suffix
            ):
                continue
            try:
                archive_date = date.fromisoformat(suffix)
            except ValueError:
                continue
            if archive_date < cutoff and not candidate.is_symlink() and candidate.is_file():
                expired.append(str(candidate))
        return sorted(expired)


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
        重复调用（包括换 process/目录）原子替换本模块输出，不重复写；按下述规则补归档。
        失败可能留下新建的空日志文件或已完成的启动归档；不改目录权限。
        运行中在越过当地零点后的第一条日志前归档为 <process>.log.YYYY-MM-DD；
        后缀为被关闭区间的起始当地日期。长期无日志时不生成空的逐日文件。
        切分时删除日期早于“当前当地日期减 retention_days”的本进程归档，边界日保留；
        当前文件、别的进程文件、非日期后缀、目录及软链接均不删除。无新日志不清理。
        删不掉的过期归档跳过并留下，下次切分或启动再试。
        打开活动文件前，按 time_source 的本地规则把 mtime 转为日期，与同次启动时钟的当地日期比较。
        修改日期早于今天先归档成 <process>.log.<修改日期>，再打开新活动文件；
        日期为今天或未来不补归档，文件缺失正常新建。空的旧活动文件也按此规则归档。
        同名归档存在时追加合并，不覆盖原归档；I/O 失败向调用方抛出，原 logging 配置保持不变，
        已完成的归档保留，合并失败可能留下归档中的部分追加和原活动文件，不声称磁盘故障下无重复。
        重启后首条日志仍做过期清理；补归档不改其他进程文件。
        切分/写入失败遵循标准 handler.handleError，不向业务抛 I/O 异常；
        设置 logging.raiseExceptions=False，systemd 下也不因日志自身故障写 stderr。
        这种运行期失败可能丢失当前记录或留下已完成的归档，不承诺磁盘故障下日志不丢。

    Time Semantics:
        只在启动或停止接收请求后串行配置，不与 emit 并发重配。
        每个当地自然日的下一次零点切分，夏令时日可为 23/25 小时，不按固定 86400 秒累加。
        时钟回拨不重复归档，追上原边界才切分；时区变化从下条记录重算未来边界，
        不把单纯换时区当作已越过旧边界。无休眠、重试、全局 TZ 修改或定时线程。
    """
    global _installed_handlers
    if settings.process not in {"web", "worker"} or not settings.log_dir.is_absolute():
        raise ValueError("日志进程必须是 web/worker，日志目录必须是绝对路径")
    _local_time(time_source)
    handlers = _prepare_handlers(settings, time_source)
    root = logging.getLogger()
    previous = _installed_handlers
    root.handlers = handlers
    _installed_handlers = tuple(handlers)
    for old in previous:
        # 新输出已经准备并发布；旧流关闭的 I/O 失败同样不写 stderr，也不能中断后续配置。
        with suppress(OSError):
            old.close()
    root.setLevel(settings.log.level)
    for name in ("uvicorn", "uvicorn.error"):
        target = logging.getLogger(name)
        target.handlers = []
        target.disabled = False
        target.propagate = True
        target.setLevel(settings.log.level)
    access = logging.getLogger("uvicorn.access")
    access.handlers = []
    access.disabled = True
    access.propagate = False
    # ADR 0005：systemd 下日志自身故障也不得写 stderr；代价是写失败时没有提示，可能丢记录。
    logging.raiseExceptions = False


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
    return _bound_context(job_id, request_id)


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
    if loaded.used_defaults:
        logger.info("使用默认配置", extra={"fields": {"config_file": str(loaded.source)}})


def _safe_string(value: object) -> str:
    """字段自身报错也保留主日志，不回显字符串化异常的潜在敏感载荷。"""
    try:
        return str(value)
    except Exception:
        return "<无法字符串化>"


def _field_value(value: object) -> str:
    """按 P2 容错转换字段，保证非标量与非有限数字不丢整行。"""
    if isinstance(value, float) and not math.isfinite(value):
        return json.dumps(str(value))
    if not isinstance(value, (str, int, float, bool, type(None))):
        value = _safe_string(value)
    if isinstance(value, str) and _SAFE_FIELD_STRING_PATTERN.fullmatch(value):
        return value
    return json.dumps(value, ensure_ascii=False)


def _render_fields(fields: object) -> str:
    """保留非规范字段的可读形式，保留键只由 contextvars 提供。"""
    if not isinstance(fields, Mapping):
        return "fields=" + _field_value(_safe_string(fields))
    try:
        entries = sorted(
            (_safe_string(key), _field_value(value))
            for key, value in cast(Mapping[object, object], fields).items()
        )
    except Exception:
        return 'fields="<无法读取字段>"'
    result: list[str] = []
    for key, value in entries:
        if key in {"job_id", "request_id"}:
            continue
        key_text = key if _FIELD_KEY_PATTERN.fullmatch(key) else json.dumps(key, ensure_ascii=False)
        result.append(f"{key_text}={value}")
    return " ".join(result)


def _local_time(source: LogTime) -> datetime:
    """验证注入依赖后换算本地时刻，不把 naive 值交给 astimezone 猜时区。"""
    moment = ensure_utc(source.now())
    zone = cast(object, source.timezone())
    if not isinstance(zone, tzinfo):
        raise ValueError("日志时钟和时区必须提供有效 aware 时刻")
    return moment.astimezone(zone)


@contextmanager
def _bound_context(job_id: int | None, request_id: str | None) -> Generator[None, None, None]:
    """绑定和恢复在同一个上下文内成对发生，异常和取消也经过 finally。"""
    # 两项均校验后才 set，避免一个合法、另一个非法时留下部分绑定。
    if job_id is not None and (type(job_id) is not int or job_id <= 0):
        raise ValueError("作业编号必须是正整数且不是 bool")
    if request_id is not None and not is_request_id(request_id):
        raise ValueError("请求编号必须是小写 uuid4.hex")
    job_token = job_id_context.set(job_id) if job_id is not None else None
    request_token = request_id_context.set(request_id) if request_id is not None else None
    try:
        yield
    finally:
        if request_token is not None:
            request_id_context.reset(request_token)
        if job_token is not None:
            job_id_context.reset(job_token)


def _prepare_handlers(settings: LoggingSettings, time_source: LogTime) -> list[logging.Handler]:
    """所有输出先准备好再发布；失败关闭新资源，旧日志配置仍可用。"""
    handlers: list[logging.Handler] = []
    try:
        file_handler = _DailyFileHandler(settings, time_source)
        handlers.append(file_handler)
        formatter = RuntimeFormatter(time_source)
        file_handler.setFormatter(formatter)
        if settings.stderr:
            stderr_handler = logging.StreamHandler()
            handlers.append(stderr_handler)
            stderr_handler.setFormatter(formatter)
    except BaseException:
        for handler in handlers:
            handler.close()
        raise
    return handlers


def _next_midnight(moment: datetime) -> int:
    """按当地日历取下一日零点，不能累加 86400 秒，否则夏令时日会错位。"""
    next_date = moment.date() + timedelta(days=1)
    return int(datetime.combine(next_date, datetime_time.min, tzinfo=moment.tzinfo).timestamp())


def log_state_warnings(warnings: tuple[DirectoryPermissionWarning, ...]) -> None:
    """在日志就绪后的启动边界报告既有状态目录的宽权限。

    Args:
        warnings: initialize_state 返回的不可变权限快照元组；可为空，顺序保持不变。
            路径为绝对路径，mode 为 0 至 0o7777 的 POSIX 权限位，且 mode & 0o077 非零。

    Returns:
        无。每项记录一条 WARNING，fields 含 path 和至少四位的八进制 mode；
        消息说明数据库以后有口令哈希，其他用户可能读到。空清单不记录。
        P4 的启动权限警告不受配置级别阈值抑制，ERROR 阈值下仍写入已配置的进程日志。

    Raises:
        无。

    Side Effects:
        无（仅运行日志）。不重新读取或修改目录、不改权限、不修改清单；
        不改 logger 阈值，每次调用独立记录，由启动入口每次初始化后调用一次。

    Time Semantics:
        调用方先 initialize_state，再 configure_logging，最后传入快照；
        时间由日志配置决定，权限值代表初始化时的检查结果，不是写日志时重新查询。
    """
    for warning in warnings:
        # P4 是启动安全提示，必须落盘；直接 handle 单条 WARNING，不临时降低全局阈值。
        record = logger.makeRecord(
            logger.name,
            logging.WARNING,
            __file__,
            0,
            "状态目录权限宽于 0700；数据库以后有口令哈希，其他用户可能读到，请检查权限",
            (),
            None,
            extra={"fields": {"path": str(warning.path), "mode": f"{warning.mode:04o}"}},
        )
        logger.handle(record)
