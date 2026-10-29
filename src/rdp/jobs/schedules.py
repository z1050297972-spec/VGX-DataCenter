"""每日计划与补跑规则（领域层）；标准库 datetime/zoneinfo 负责时区，不读系统时钟。

只计算提交资格；数据库唯一约束负责跨重启去重，JobService 负责原子提交与操作日志。
不使用 APScheduler，因为 ADR 0005 的事务/恢复约束需要与既有作业表共同提交。
"""

import struct
from copy import deepcopy
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import cast
from zoneinfo import ZoneInfo

from rdp.infra.actors import is_display_name
from rdp.infra.diagnostics import (
    DefectError,
    Diagnostic,
    DiagnosticCategory,
    DiagnosticLevel,
    DiagnosticObject,
    ExternalError,
)
from rdp.infra.timeutil import ensure_utc
from rdp.jobs import _storage
from rdp.jobs._parameters import validate as validate_parameters
from rdp.jobs.datasets.catalog import SIZING_NAME, SIZING_TYPE
from rdp.jobs.errors import JobInputError
from rdp.jobs.policy import SCHEDULE_CATCH_UP_AFTER_S, SCHEDULE_LIMIT, SCHEDULE_LOOKAHEAD_DAYS
from rdp.jobs.registry import (
    MAINTENANCE_JOB_TYPES,
    PURGE_AUDIT_LOGS_NAME,
    PURGE_AUDIT_LOGS_TYPE,
    PURGE_ERRORS_NAME,
    PURGE_ERRORS_TYPE,
    JobRegistry,
)
from rdp.jobs.scheduling_types import ScheduledJob, ScheduleSubmission
from rdp.jobs.types import RecoveryMode


class ScheduleRegistry:
    """显式不可变的每日计划登记对象；Web 和 worker 入口分别构造并注入。"""

    def __init__(self, definitions: tuple[ScheduledJob, ...], jobs: JobRegistry) -> None:
        """验证每日计划并复制参数，禁止隐式模块级注册。

        Args:
            definitions: 至多 SCHEDULE_LIMIT 条规则，名字唯一；参数须通过当前类型模型。
            jobs: 当前作业类型登记表，清除类型须为 restart 恢复方式。

        Returns:
            无；登记完成后不可追加，空元组可用于不运行定时作业的测试。

        Raises:
            DefectError: 重复/非法名字、超过容量、类型不存在、参数非法或时刻非整分钟本地时间。

        Side Effects:
            仅复制有界参数和规则，不提交作业，不访问数据库、文件或时钟。

        Time Semantics:
            启动前完成验证；local_time 无 tzinfo，时区来自入口显式注入的本机 ZoneInfo。
        """
        if (
            type(definitions) is not tuple
            or len(definitions) > SCHEDULE_LIMIT
            or not isinstance(cast(object, jobs), JobRegistry)
        ):
            raise DefectError()
        seen: set[str] = set()
        for definition in definitions:
            _validate_schedule(definition, jobs)
            if definition.name in seen:
                raise DefectError()
            seen.add(definition.name)
        self._definitions = deepcopy(tuple(sorted(definitions, key=lambda item: item.name)))

    def definitions(self) -> tuple[ScheduledJob, ...]:
        """枚举登记规则以供每轮判断和调度页展示。

        Args:
            无。

        Returns:
            按 name 升序的元组，参数副本与内部登记隔离；无规则返回空元组。

        Raises:
            无。

        Side Effects:
            无；不共享可变参数字典，也不按时间自动提交。

        Time Semantics:
            同步读取最多 SCHEDULE_LIMIT 项，不读墙钟或等待下一次触发。
        """
        return deepcopy(self._definitions)


def production_schedules(jobs: JobRegistry) -> ScheduleRegistry:
    """登记每天 03:00 的报错清除与两种日志联合清除。

    Args:
        jobs: 包含两个清除类型及dataset_sizing的生产类型登记表。

    Returns:
        三条规则：两个清除类型参数为空；统计数据集大小的dataset_id为None，表示全量。
        三类都按RESTART恢复；统计类型与手动入口共用永久键dataset_sizing。

    Raises:
        DefectError: 缺清除类型、参数模型/恢复声明不一致。

    Side Effects:
        仅构造新登记对象；不清除记录、不读取当前日志保留期。

    Time Semantics:
        默认本地 03:00；第一次启动从未提交时按 K2 补交，不在构造中读取时间。
    """
    return ScheduleRegistry(
        (
            ScheduledJob(PURGE_ERRORS_NAME, PURGE_ERRORS_TYPE, {}),
            ScheduledJob(PURGE_AUDIT_LOGS_NAME, PURGE_AUDIT_LOGS_TYPE, {}),
            ScheduledJob(SIZING_NAME, SIZING_TYPE, {"dataset_id": None}),
        ),
        jobs,
    )


def local_timezone(localtime_path: Path) -> ZoneInfo:
    """读取操作系统实际使用的时区文件，保留完整夏令时规则。

    Args:
        localtime_path: 入口明确指定的绝对 tzfile 路径，生产为 /etc/localtime，测试为临时文件。

    Returns:
        从 tzfile 解析的 ZoneInfo；不使用可能过时的 /etc/timezone，也不用当前固定 UTC 偏移代替时区。

    Raises:
        ExternalError: 文件不存在、不可读或不是可解析 tzfile，诊断给出路径及修正系统时区建议。
        DefectError: 路径非绝对或依赖类型错误。

    Side Effects:
        无（只读指定本地时区文件）；不修改 TZ、不调用 tzset、不联网寻找时区包。

    Time Semantics:
        启动时读一次；修改机器时区后重启入口，遵循 brief/0013 的 /etc/localtime 事实。
    """
    if not isinstance(cast(object, localtime_path), Path) or not localtime_path.is_absolute():
        raise DefectError()
    try:
        with localtime_path.open("rb") as stream:
            return ZoneInfo.from_file(stream)
    except (OSError, ValueError, EOFError, struct.error) as error:
        raise ExternalError(
            (
                Diagnostic(
                    level=DiagnosticLevel.ERROR,
                    category=DiagnosticCategory.EXTERNAL,
                    stage="读取本机时区",
                    source="平台",
                    objects=(DiagnosticObject(key="path", value=str(localtime_path)),),
                    rule="本机时区必须是有效tzfile",
                    actual="时区文件不可读取或解析",
                    expected="可读的完整时区规则文件",
                    consequence="入口无法确定定时作业的本地日期和时刻",
                    next_step="修正系统时区文件后重启入口",
                ),
            )
        ) from error


def daily_deadline(local_date: date, local_time: time, zone: ZoneInfo) -> datetime | None:
    """解析指定本地日期的第一次不早于登记时刻的有效分钟。

    Args:
        local_date: 本地日历日期，精确类型 date，不接受 datetime。
        local_time: 无时区的整分钟时刻，00:00 至 23:59。
        zone: 入口注入的本机时区规则，测试使用固定 ZoneInfo，不依赖机器当前设置。

    Returns:
        对应 aware UTC 时刻；重复小时取较早的 UTC 出现（fold=0），当天只触发一次。
        跳过的分钟顺延到同日本地第一个有效分钟；若当天余下时间全不存在则 None，不伪造时刻。

    Raises:
        DefectError: 日期/分钟/时区非法或 UTC 换算溢出。

    Side Effects:
        无；只通过 zoneinfo 换算和 UTC 往返验证，不读系统时间或数据库。

    Time Semantics:
        最多枚举当天余下 1440 个分钟；不是固定 UTC 的每日 24 小时间隔。
        春季 02:30 不存在而 03:00 有效时取 03:00；秋季 01:30 重复时取第一次 01:30。
    """
    if (
        type(local_date) is not date
        or type(local_time) is not time
        or local_time.tzinfo is not None
        or local_time.second
        or local_time.microsecond
        or not isinstance(cast(object, zone), ZoneInfo)
    ):
        raise DefectError()
    try:
        # 同一天最多1440个整分钟，UTC往返不相等表示本地时刻在跳时空洞里。
        for minute in range(local_time.hour * 60 + local_time.minute, 24 * 60):
            wall = datetime.combine(local_date, time(minute // 60, minute % 60))
            candidate = ensure_utc(wall.replace(tzinfo=zone, fold=0))
            if candidate.astimezone(zone).replace(tzinfo=None) == wall:
                return candidate
    except (ValueError, OverflowError) as error:
        raise DefectError() from error
    return None


def schedule_due(
    definition: ScheduledJob,
    previous: ScheduleSubmission | None,
    *,
    now: datetime,
    zone: ZoneInfo,
    startup: bool,
) -> date | None:
    """决定本轮是否提交今天的一次定时作业。

    Args:
        definition: 已验证的每日规则。
        previous: 此名字最近提交记录；从未提交为 None，不能使用最近执行完成时刻代替。
        now: 注入的 aware 时刻，规范化 UTC 后换算本地日期；非法时钟属于程序缺陷。
        zone: 与登记规则共同注入的本机时区。
        startup: 是否仍在本实例首次补跑检查；每条成功检查后不再把普通轮询当启动。

    Returns:
        有资格返回 now 在 zone 下的日期，否则 None。
        当日本地日期已有提交不再提交；startup 且从未提交或 max(0, now-previous.submitted_at)
        严格超过 SCHEDULE_CATCH_UP_AFTER_S 时马上补交一次；恰好 24 小时不满足补跑。
        其他情况 now 不早于今天 daily_deadline 才提交；补交占用今天的唯一资格。
        回拨时旧的更晚日期不代表今天已提交，最终以数据库 (name,date) 唯一约束判重。

    Raises:
        DefectError: 注入时刻、规则、记录身份或时区不合法，不能归为用户输入错误。

    Side Effects:
        无；不修改 previous、不提交、不读取时钟；返回日期不保证数据库还没有该日期的行。

    Time Semantics:
        跨重启补跑使用 UTC 墙钟的固定 86400 秒；负经过时长按零，日常触发使用本地日期。
        DST 重复小时不重复，跳过小时顺延；停机多日不逐日补历史记录。
    """
    current, today = _local_day(definition, now, zone)
    deadline = daily_deadline(today, definition.local_time, zone)
    if type(startup) is not bool:
        raise DefectError()
    if previous is not None:
        if (
            not isinstance(cast(object, previous), ScheduleSubmission)
            or previous.schedule_name != definition.name
            or type(previous.local_date) is not date
        ):
            raise DefectError()
        _storage.identifier(previous.job_id, internal=True)
        submitted = _storage.moment(previous.submitted_at)
        if previous.local_date == today:
            return None
        elapsed = max(0.0, (current - submitted).total_seconds())
    else:
        elapsed = 0.0
    if startup and (previous is None or elapsed > SCHEDULE_CATCH_UP_AFTER_S):
        return today
    return today if deadline is not None and current >= deadline else None


def next_run_at(
    definition: ScheduledJob, submitted_dates: frozenset[date], *, now: datetime, zone: ZoneInfo
) -> datetime:
    """计算页面上下一次按点提交的时刻。

    Args:
        definition: 已验证规则，不预测未来重启的补跑。
        submitted_dates: 从数据库读取的候选日期去重集合；最多未来 SCHEDULE_LOOKAHEAD_DAYS 天。
        now: 本次请求 aware UTC 时刻，由入口注入。
        zone: 本机当地时区，不能用浏览器时区决定触发日期。

    Returns:
        第一个尚未提交的按点 UTC 时刻；今天已到点但未提交时返回该到期时刻，页面显示已到点等待 worker。

    Raises:
        DefectError: 时钟/输入非法、日期溢出，或 SCHEDULE_LOOKAHEAD_DAYS 内没有可用日期。

    Side Effects:
        无；只计算，不提交或补写数据库。

    Time Semantics:
        最多向后检查 SCHEDULE_LOOKAHEAD_DAYS=370 个本地日期；重复/跳过分钟与 daily_deadline 相同。
        墙钟回拨后仍查询日期去重集合，不从单条 latest 推测历史日期未提交。
    """
    _current, today = _local_day(definition, now, zone)
    if (
        type(submitted_dates) is not frozenset
        or len(submitted_dates) > SCHEDULE_LOOKAHEAD_DAYS
        or any(type(day) is not date for day in submitted_dates)
    ):
        raise DefectError()
    try:
        for offset in range(SCHEDULE_LOOKAHEAD_DAYS):
            day = today + timedelta(days=offset)
            deadline = daily_deadline(day, definition.local_time, zone)
            if day not in submitted_dates and deadline is not None:
                return deadline
    except (ValueError, OverflowError) as error:
        raise DefectError() from error
    raise DefectError()


def _validate_schedule(definition: ScheduledJob, jobs: JobRegistry) -> None:
    """登记是代码配置，参数拒绝统一归程序缺陷；复用提交的模型/容量校验，不回显秘密。"""
    if not isinstance(cast(object, definition), ScheduledJob) or not is_display_name(
        definition.name
    ):
        raise DefectError()
    moment = definition.local_time
    if type(moment) is not time or moment.tzinfo is not None or moment.second or moment.microsecond:
        raise DefectError()
    try:
        job, _ = validate_parameters(jobs, definition.type_name, definition.parameters)
    except JobInputError as error:
        raise DefectError() from error
    if (
        definition.type_name in MAINTENANCE_JOB_TYPES
        and job.recovery_mode is not RecoveryMode.RESTART
    ):
        raise DefectError()


def _local_day(definition: ScheduledJob, now: datetime, zone: ZoneInfo) -> tuple[datetime, date]:
    """只转换显式时刻，日历溢出及错误依赖都属于平台缺陷。"""
    if (
        not isinstance(cast(object, definition), ScheduledJob)
        or not is_display_name(definition.name)
        or not isinstance(cast(object, zone), ZoneInfo)
    ):
        raise DefectError()
    current = _storage.moment(now)
    try:
        return current, current.astimezone(zone).date()
    except (ValueError, OverflowError) as error:
        raise DefectError() from error
