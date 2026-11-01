"""读取内核计数器并计算采样间的变化；标准库足以解析 proc 文本。"""

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ProcSample:
    """一个时刻的内核累计计数和内存容量。

    Attributes:
        timestamp: 采样的单调时间，秒。
        network: 各网卡接收和发送累计字节。
        cpu: 内核 CPU 累计计数。
        memory_bytes: 内存总量、可用量、交换区总量和空闲量，单位字节。
    """

    timestamp: float
    network: dict[str, tuple[int, int]]
    cpu: tuple[int, ...]
    memory_bytes: tuple[int, int, int, int]


@dataclass(frozen=True)
class ProcRates:
    """采样区间内的平均速率。

    Attributes:
        network: 各网卡接收和发送字节每秒。
        cpu_percent: CPU 忙碌百分比。
    """

    network: dict[str, tuple[float, float]]
    cpu_percent: float


def read_sample(net: Path, stat: Path, mem: Path, timestamp: float) -> ProcSample:
    """读取一次内核采样。

    Args:
        net: 网卡累计计数文件路径。
        stat: CPU 累计计数文件路径。
        mem: 内存容量文件路径。
        timestamp: 采样时的单调时间，单位秒。

    Returns:
        三种计数及采样时间。

    Raises:
        OSError: 文件不可读时。
        ValueError: 计数不是整数时。
        KeyError: 缺少所需内存字段时。

    Side Effects:
        读取指定文件，不修改文件。

    Time Semantics:
        时间由调用者提供，累计计数随内核更新。
    """
    network: dict[str, tuple[int, int]] = {}
    for line in net.read_text().splitlines():
        if ":" in line:
            name, values = line.split(":", 1)
            fields = values.split()
            network[name.strip()] = (int(fields[0]), int(fields[8]))
    cpu = tuple(int(value) for value in stat.read_text().splitlines()[0].split()[1:])
    memory: dict[str, int] = {}
    for line in mem.read_text().splitlines():
        key, value = line.split(":", 1)
        memory[key] = int(value.split()[0]) * 1024
    return ProcSample(
        timestamp,
        network,
        cpu,
        (memory["MemTotal"], memory["MemAvailable"], memory["SwapTotal"], memory["SwapFree"]),
    )


def sample_rates(before: ProcSample, after: ProcSample) -> ProcRates:
    """计算两次采样之间的平均速率。

    Args:
        before: 较早的内核计数。
        after: 较晚的内核计数，时间必须大于前者。

    Returns:
        每个共同网卡的收发字节每秒和 CPU 忙碌百分比。

    Raises:
        ValueError: 采样时间没有前进时。

    Side Effects:
        无。

    Time Semantics:
        速率是两次单调时间之间的平均值，不是瞬时值。
    """
    elapsed = after.timestamp - before.timestamp
    if elapsed <= 0:
        raise ValueError("采样时间必须前进")
    network = {
        name: ((rx - before.network[name][0]) / elapsed, (tx - before.network[name][1]) / elapsed)
        for name, (rx, tx) in after.network.items()
        if name in before.network
    }
    # guest 已计入 user/nice，不能在总时长中重复计数。
    total = sum(after.cpu[:8]) - sum(before.cpu[:8])
    idle = sum(after.cpu[3:5]) - sum(before.cpu[3:5])
    return ProcRates(network, (total - idle) * 100 / total if total else 0.0)
