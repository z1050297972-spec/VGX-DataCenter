"""伪终端解析的领域边界（M4-02）；只传递进度和文本，不判断工具成败或访问存储。"""

from dataclasses import dataclass
from typing import Protocol

from rdp.jobs.types import JobProgress


@dataclass(frozen=True)
class TerminalUpdate:
    """一次流式解析产生的增量。

    Attributes:
        progress: 本次识别到的最新进度；没有完整进度记录时为 None。
        lines: 按输出顺序排列的新文本行，去除终端补位空格，不含进度条，可为空。
    """

    progress: JobProgress | None = None
    lines: tuple[str, ...] = ()


class TerminalParser(Protocol):
    """工具专用的有状态流式解析器；每次运行使用独立实例。"""

    def feed(self, chunk: bytes) -> TerminalUpdate:
        """消费任意边界的终端字节并返回完整记录。

        Args:
            chunk: 按读取顺序送入的 UTF-8 字节块，可为空或包含半个字符/CSI序列。

        Returns:
            最新进度与新文本行；不完整尾部留到下一次。

        Raises:
            无。

        Side Effects:
            更新实例内的有界解析状态，不写日志或文件。

        Time Semantics:
            同步解析，不读取时钟，不能并发调用同一实例。
        """
        ...

    def finish(self) -> TerminalUpdate:
        """在终端关闭后排出剩余文本并返回最后进度。

        Args:
            无。

        Returns:
            最后一次有效进度（未识别过为 None）与尾部新增文本。

        Raises:
            无。

        Side Effects:
            清空未完成记录；不将未闭合的控制序列当成文本。

        Time Semantics:
            在最后一次 feed 之后调用，不等待更多输出。
        """
        ...
