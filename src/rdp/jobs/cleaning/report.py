"""依次读取输入文件并生成清洗报告，每个文件的致命问题单独隔离。"""

from collections.abc import Callable, Sequence
from pathlib import Path

from rdp.jobs.cleaning._config import load_configs
from rdp.jobs.cleaning._io import collect_inputs
from rdp.jobs.cleaning._report import ReportBuilder
from rdp.jobs.cleaning.models import CleaningReport


# 可选文件通知保留第 01 张的五参数调用契约，避免已有调用方被迫更换回调结构。
def build_cleaning_report(  # noqa: PLR0913
    inputs: Sequence[tuple[str, Path]],
    tool_config_path: Path,
    rules_path: Path,
    *,
    checkpoint: Callable[[], None],
    progress: Callable[[int], None],
    file_progress: Callable[[int, int, int | None], None] | None = None,
) -> CleaningReport:
    """按工具规则预览 MCAP 的对齐切段和段内质量问题。

    Args:
        inputs: 按用户顺序的非空数据块编号和文件或目录路径，允许空序列；单位项。
        tool_config_path: 已登记工具配置的可读 TOML 路径。
        rules_path: schema_version 为 1 的清洗规则 TOML 路径。
        checkpoint: 无参数取消检查函数；抛出异常时原样终止，不生成部分报告。
        progress: 接收累计实际读取的 MCAP 字节数，非负且单调；每秒至多通知一次。
        file_progress: 可选文件开始通知，接收从 1 起的文件序号、总文件数和总字节数；
            任一文件无法 stat 时总字节为 None，省略表示不通知。

    Returns:
        冻结的版本一报告；文件按展开顺序，episode 按文件、保留段顺序排列。
        文件读不了或数据不合格记文件致命诊断，其他文件继续；不存全局 episode 编号。

    Raises:
        InputError: 配置或规则不合法、目录无法展开或没有 MCAP、输入规模超过安全上限。
        Exception: checkpoint、progress 或 file_progress 抛出的异常原样传播。

    Side Effects:
        只读输入和配置，不写任何数据。文件请求 O_NOATIME；EPERM 时退回只读并记警告。
        目录内的目录软链接跳过并警告；Rust 会跟随它，平台为避免越界不跟随。

    Time Semantics:
        同步线性读取每个文件一次，不按 MCAP 索引或 log_time 重排。
        使用 header.stamp 纳秒，零值排除，稳定排序；最近邻可取未来值，同距取较早值。
        episode 时长为帧数/fps，检查时间使用原 stamp，相对文件起点取首个有效基准 stamp。
        每条记录及运算批次调用检查点；取消等待不超过一次有界块读取或解码。
    """
    config, rules, tool_sha256, rules_sha256 = load_configs(tool_config_path, rules_path)
    files, warnings = collect_inputs(inputs, checkpoint)
    builder = ReportBuilder(config, rules, checkpoint, progress, file_progress)
    return builder.build(files, warnings, (tool_sha256, rules_sha256))
