"""基础层的 UTC 时间规范化，只转换显式时刻，不读取时钟或推测本地时区。

标准库 datetime.astimezone 会把无时区的值当成本地时间；此处增加拒绝无时区输入的
边界，转换仍交给标准库，避免平台内部悄悄混入本地时间。不处理采样对齐或时间同步。
依据：CODING_STANDARDS 5.1，ADR 0002，M0 工单 01「仓库骨架和检查链」。
"""

from datetime import UTC, datetime


def ensure_utc(value: datetime) -> datetime:
    """将带有效时区的时刻换算为 UTC，保持所表示的时刻不变。

    Args:
        value: 单个 datetime 时刻，必须带时区且 utcoffset() 不为 None；
            年份范围为 1 至 9999，精度为微秒。不推测无时区值所属的时区。

    Returns:
        tzinfo 为 datetime.UTC 的 datetime，表示与输入相同的时刻并保留微秒精度；
        已是 UTC 的输入保持值不变，不保证返回对象与输入具有相同身份。

    Raises:
        ValueError: 输入的 tzinfo 或 utcoffset() 为 None，属于调用方的程序缺陷。
        OverflowError: 换算后的 UTC 时刻超出 datetime 可表示的年份范围 1 至 9999。

    Side Effects:
        无。不修改输入，不读取系统时钟或本地时区。

    Time Semantics:
        输入时刻按其自带时区解释，输出使用 UTC；微秒不截断或舍入，无等待或重试。
    """
    # tzinfo 非空仍可能没有偏移；两种情况都不能交给 astimezone 猜测本地时区。
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("时刻必须带有效时区")
    return value.astimezone(UTC)
