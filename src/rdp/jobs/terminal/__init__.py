"""工具伪终端解析器登记入口（领域层，M4-02）；不依赖工具库模块或启动工具。"""

from rdp.infra.diagnostics import DefectError
from rdp.jobs.terminal._mcap2lerobot import Mcap2LerobotParser
from rdp.jobs.terminal.types import TerminalParser, TerminalUpdate

__all__ = ["TerminalParser", "TerminalUpdate", "create_terminal_parser"]


def create_terminal_parser(name: str, *, stage_count: int, first_stage: int) -> TerminalParser:
    """按工具清单的 runtime.progress 名称创建独立解析器。

    Args:
        name: 已登记的解析器名，当前为 mcap2lerobot-pty。
        stage_count: 作业总阶段数，严格整数，须容纳扫描和转换两个阶段。
        first_stage: 扫描阶段序号，严格整数且至少1，first_stage + 1不得超过stage_count；
            转换阶段紧随其后，由调用方为工具运行前的核对阶段预留序号。

    Returns:
        空状态的解析器，供单次工具执行独占。

    Raises:
        DefectError: 名称未登记、阶段参数不是严格整数、first_stage小于1，或两个阶段超出总数。

    Side Effects:
        无；不读取清单或工具目录。

    Time Semantics:
        同步构造；调用方按到达顺序送入字节。
    """
    if (
        name != "mcap2lerobot-pty"
        or type(stage_count) is not int
        or type(first_stage) is not int
        or first_stage < 1
        or first_stage + 1 > stage_count
    ):
        raise DefectError()
    return Mcap2LerobotParser(stage_count, first_stage)
