"""基础层的有界异常报告；Web与worker共用标准库traceback格式，不记录日志或访问业务数据。

第8张约定jobs与api共用此格式化入口，基础层不依赖Web入口。
"""

import sys
import traceback
from itertools import chain
from typing import cast

from rdp.infra.db.models import MAX_EXCEPTION_REPORT_CHARS, REPORT_TRUNCATION_MARKER


def format_exception_report(error: BaseException) -> str:
    """生成保留异常消息和源码行、不打印局部变量的有界异常报告。

    Args:
        error: 当前异常及 cause/context 链，也支持 BaseExceptionGroup；不接受 None。

    Returns:
        按标准库 traceback 的格式保留每层异常的类型和消息、栈帧文件/函数/行号及源码行，
        __notes__ 沿用标准库行为，不打印局部变量。遵循显式 cause 和 suppress_context，
        在字符上限内保留所选链的根因；异常组不截断宽度或深度，循环引用标明已出现。
        无 traceback 时仍输出异常类型和消息；异常消息和源码行按标准库格式保留。
        增量收集标准库 format(chain=True)
        的前缀，最多 models.MAX_EXCEPTION_REPORT_CHARS 个 Unicode 字符；超过时预留
        REPORT_TRUNCATION_MARKER 的长度，尾部加该标记，总长度仍不超过上限。
        未超限逐字保留；显式标记有损，不另拼诊断或请求数据。日志与数据库共用同一个结果。

    Raises:
        无。

    Side Effects:
        无（只读栈帧对应源文件以取得源码行）；不改变异常、traceback 或 logging 状态，不写日志。

    Time Semantics:
        同步转换，不读取时钟，不请求数据库或外部系统。
    """
    report = traceback.TracebackException.from_exception(
        error, capture_locals=False, max_group_width=sys.maxsize, max_group_depth=sys.maxsize
    )
    suffix = (
        ("循环引用：已出现的异常不重复展开。\n",)
        if _has_exception_cycle(error, frozenset())
        else ()
    )
    pieces: list[str] = []
    remaining = MAX_EXCEPTION_REPORT_CHARS
    for piece in chain(report.format(chain=True), suffix):
        pieces.append(piece[:remaining])
        if len(piece) > remaining:
            return (
                "".join(pieces)[: MAX_EXCEPTION_REPORT_CHARS - len(REPORT_TRUNCATION_MARKER)]
                + REPORT_TRUNCATION_MARKER
            )
        remaining -= len(piece)
    return "".join(pieces)


def _has_exception_cycle(error: BaseException, ancestors: frozenset[int]) -> bool:
    """标准库避免无限展开；补一个明确标记，不自行重建 traceback 文本。"""
    if id(error) in ancestors:
        return True
    path = ancestors | {id(error)}
    cause = error.__cause__ or (None if error.__suppress_context__ else error.__context__)
    children = (
        cast(BaseExceptionGroup[BaseException], error).exceptions
        if isinstance(error, BaseExceptionGroup)
        else ()
    )
    return (cause is not None and _has_exception_cycle(cause, path)) or any(
        _has_exception_cycle(child, path) for child in children
    )
