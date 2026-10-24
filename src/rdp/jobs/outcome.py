"""作业领域层的唯一作业结果计算规则（09 Answer、规范 6.8、M0 工单 04）。

使用标准库枚举；四种结果的优先级是项目业务规则，需要在本模块集中表达。
只按显式计数计算，不从诊断级别推断失败条目，不处理取消/中断等作业状态，
不 import 数据库、进程、rdp.api 或 rdp.ops；调用方不得自行赋值作业结果。
"""

from enum import StrEnum


class JobOutcome(StrEnum):
    """已完成作业的四种结果；无单位，无默认成员，不是作业状态。

    Attributes:
        SUCCEEDED: Succeeded，JSON 值 succeeded，中文“成功”。
        SUCCEEDED_WITH_WARNINGS: Succeeded with Warnings，JSON 值 succeeded_with_warnings，
            中文“带警告成功”。
        PARTIALLY_SUCCEEDED: Partially Succeeded，JSON 值 partially_succeeded，中文“部分成功”。
        FAILED: Failed，JSON 值 failed，中文“失败”。
    """

    SUCCEEDED = "succeeded"
    SUCCEEDED_WITH_WARNINGS = "succeeded_with_warnings"
    PARTIALLY_SUCCEEDED = "partially_succeeded"
    FAILED = "failed"


def calculate_outcome(
    *, total_items: int, failed_items: int, warning_count: int, aborted: bool
) -> JobOutcome:
    """用完整条目计数、警告数及整体中止标志计算唯一的作业结果。

    Args:
        total_items: 本作业条目总数，单位条目，非负整数，拒绝 bool、浮点和字符串。
        failed_items: 失败条目数，单位条目，整数且 0 ≤ failed_items ≤ total_items，拒绝 bool。
        warning_count: 警告总数，单位条，非负整数，拒绝 bool；不由聚合样例长度代替。
        aborted: 是否因失败整体中止，必须为 bool；不是用户取消或进程中断状态。

    Returns:
        先校验全部输入，再依次判定：aborted=True 一律 FAILED，包括总数或失败数为零；
        total_items>0 且全部失败为 FAILED；0<failed_items<total_items 为 PARTIALLY_SUCCEEDED，
        即使同时有警告也不改变；失败为零时 warning_count>0 为 SUCCEEDED_WITH_WARNINGS，
        否则 SUCCEEDED。总数为零且未中止是合法空作业，按警告数返回后两者，不能误判全失败。

    Raises:
        ValueError: 任一计数不是严格整数或为负，失败数大于总数，或 aborted 不是 bool；
            整体中止也不能绕过校验；异常不回显输入对象。

    Side Effects:
        无；不修改计数、不打日志、不访问文件、数据库或外部进程。

    Time Semantics:
        同步纯函数，不读时钟；调用方在作业已完成、计数冻结后调用，取消/中断不调用。
    """
    if type(aborted) is not bool:
        raise ValueError("整体中止标志必须为 bool")
    if any(type(value) is not int for value in (total_items, failed_items, warning_count)):
        raise ValueError("作业计数必须为整数且不能为 bool")
    if any(value < 0 for value in (total_items, failed_items, warning_count)):
        raise ValueError("作业计数必须为非负整数")
    if failed_items > total_items:
        raise ValueError("失败条目数不能大于总条目数")
    if aborted:
        return JobOutcome.FAILED
    if total_items > 0 and failed_items == total_items:
        return JobOutcome.FAILED
    if failed_items > 0:
        return JobOutcome.PARTIALLY_SUCCEEDED
    if warning_count > 0:
        return JobOutcome.SUCCEEDED_WITH_WARNINGS
    return JobOutcome.SUCCEEDED
