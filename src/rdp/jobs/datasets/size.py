"""数据块表观大小的只读入口（领域层，M4-07），不更新索引、不计算容量策略。

复用M1的低IO优先级遍历、O_NOATIME和停滞超时，不另写文件遍历或等待算法。
"""

from pathlib import Path

from rdp.infra.storage import StorageAccessChecker
from rdp.jobs.datasets import _size_access
from rdp.jobs.execution import ExecutionContext


def measure_size(path: Path, checker: StorageAccessChecker, context: ExecutionContext) -> int:
    """只读统计一个数据块的表观字节数，不发布索引统计值。

    Args:
        path: 已选数据块的绝对路径，必须位于checker登记的在线存储根内。
        checker: worker的存储检查器，访问等待预算单位为秒。
        context: 当前作业上下文，用于取消检查和遍历线程回收。

    Returns:
        非负整数，单位字节；普通文件按表观大小累计，块内硬链接去重，
        内部软链接仅计链接自身长度，不跟随；不计目录大小。

    Raises:
        OSError: 路径越出登记根、根离线、元数据读取失败或遍历深度超过M1上限。
        TimeoutError: 元数据访问停滞达到checker.options.access_timeout_s秒。
        ExternalError: 存储检查或设置低IO优先级失败。
        JobCancelledError: 等待时观察到作业取消。
        WorkerStoppingError: 等待时观察到worker停止。

    Side Effects:
        只读文件元数据，不打开数据文件；目录使用O_NOATIME，权限不足时沿用M1回退。
        启动受作业跟踪的低IO优先级线程和ionice进程，不写存储根或索引。

    Time Semantics:
        仅反映本次遍历的观察；每次元数据访问停滞受checker的秒级预算约束，
        全树遍历不设总时限；等待期间检查取消，超时或取消后不返回迟到结果。
    """
    value = _size_access.measure(path, checker, context, ())
    if value is None:
        raise TimeoutError(f"存储访问停滞：{path}")
    return value.size_bytes
