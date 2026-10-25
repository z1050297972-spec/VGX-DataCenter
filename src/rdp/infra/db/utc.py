"""基础层 UTC 文本列类型（工单 05 F3），不读取本地时区或系统时钟。

复用 TypeDecorator 和 timeutil.ensure_utc；自定义部分仅为平台的固定文本格式和拒绝规则。
"""

import re
from datetime import UTC, datetime
from typing import cast, override

from sqlalchemy import Text
from sqlalchemy.engine import Dialect
from sqlalchemy.types import TypeDecorator

from rdp.infra.db.validation import invalid_field
from rdp.infra.timeutil import ensure_utc


class UTCDateTime(TypeDecorator[datetime]):
    """所有数据库时间列共用的有时区 datetime 与 UTC TEXT 映射。

    Attributes:
        impl: 底层 Text 类型，无单位、不可空配置值、默认 Text；列是否可空由模型声明。
        cache_ok: 编译缓存安全标志，固定 True，无单位、不可空；实例无可变格式配置。
    """

    impl = Text
    cache_ok = True

    @override
    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> str | None:
        """把带时区的时刻规范化成固定 27 字符的 UTC 文本。

        Args:
            value: aware datetime，年 1-9999、精度微秒；None 透传 SQL NULL，非空约束由列负责。
            dialect: SQLAlchemy 当前方言，无单位；只支持本票的 SQLite，不改变转换语义。

        Returns:
            None 或 YYYY-MM-DDTHH:MM:SS.ffffffZ；先 ensure_utc，再补齐四位年和六位微秒，
            例如 2026-10-23T02:00:00.123456Z；不截断、不舍入，按文本排序等于时刻排序。

        Raises:
            InputError: naive、utcoffset() 为 None、非 datetime，或 ensure_utc 的 UTC 换算溢出；
                诊断不回显输入。直接调用得到 InputError，SQLAlchemy 执行时包装为
                StatementError（orig 是 InputError），session_scope 解包并保留 cause。

        Side Effects:
            无；拒绝时未向驱动交付该值，不修改输入。

        Time Semantics:
            UTC、六位微秒；接受任意合法偏移，不推测本机 -06:00 或按日历折算。
        """
        if value is None:
            return None
        if not isinstance(cast(object, value), datetime):
            problem = invalid_field("datetime", "带有效时区的 datetime")
            raise problem
        try:
            return format_utc_text(value)
        except (ValueError, OverflowError) as error:
            problem = invalid_field("datetime", "带有效时区且可表示的 UTC 时刻")
            raise problem from error

    @override
    def process_result_value(self, value: str | None, dialect: Dialect) -> datetime | None:
        """将数据库里的严格 UTC 文本恢复为带 UTC 时区的时刻。

        Args:
            value: None 或固定 27 字符 UTC 文本；必须是 Z 结尾、六位微秒和有效日期。
            dialect: SQLAlchemy 当前方言，无单位，不读取数据库连接或环境。

        Returns:
            None 或 tzinfo=datetime.UTC 的 datetime，保留全部微秒；不接受宽松 ISO 变体。

        Raises:
            InputError: 非文本、错误长度/分隔符/偏移、非法日期或不足六位微秒，属于存量数据损坏；
                不静默补时区或返回 None。结果处理器的异常通常直接传播，非 bind 的
                StatementError 包装；经 session_scope 仍保留 InputError，不输出坏文本。

        Side Effects:
            无；只转换，不修复坏行，不写日志。

        Time Semantics:
            严格 UTC，不读取墙钟，无等待。
        """
        if value is None:
            return None
        # fromisoformat 接受空格和可变精度，必须先限定 F3 的唯一存储形式。
        if not isinstance(cast(object, value), str) or not re.fullmatch(
            r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{6}Z", value
        ):
            problem = invalid_field("datetime", "27 字符、六位微秒、Z 结尾的 UTC 文本")
            raise problem
        try:
            return datetime.fromisoformat(value).astimezone(UTC)
        except ValueError as error:
            problem = invalid_field("datetime", "有效的 UTC 日期和时间")
            raise problem from error


def format_utc_text(value: datetime) -> str:
    """把有时区的时刻格式化为统一的 UTC 微秒文本。

    Args:
        value: 带有效时区的 datetime，年份 1 至 9999，精度微秒；不接受 None。

    Returns:
        固定 27 字符的 YYYY-MM-DDTHH:MM:SS.ffffffZ，保留六位微秒，不舍入。

    Raises:
        ValueError: 时刻无时区或 utcoffset() 为 None；沿用 ensure_utc 的拒绝规则。
        OverflowError: 换算后的 UTC 时刻超出 datetime 的可表示范围。

    Side Effects:
        无；不改变输入、不读取环境或写文件。

    Time Semantics:
        输入按自带时区解释，输出为同一时刻的 UTC；不读时钟或等待。
    """
    return ensure_utc(value).isoformat(timespec="microseconds").replace("+00:00", "Z")
