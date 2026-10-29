"""预览结果文件 `nav-previews/<预览作业编号>.json.gz` 的读写（领域层，M1-07）。

预览是只读的 worker 作业（M1-07 工单）：它访问存储根，所以不能在 Web 里算；
结果是一整份计划，大到不适合放进作业记录，所以存成状态目录里的文件，作业记录里只有编号。
页面用预览作业编号来取；写入作业的参数里也只带这个编号，执行时从这里读出同一份计划，不重新计算。
写入走 worker，读取 Web 和 worker 两侧都可以。
"""

from pathlib import Path

from rdp.infra.state import StatePaths
from rdp.jobs.navwrite.models import NavPreview


def preview_path(paths: StatePaths, preview_job_id: int) -> Path:
    """计算预览文件的路径，只计算、不创建。

    Args:
        paths: 已初始化的状态布局。
        preview_job_id: 预览作业编号，≥ 1。

    Returns:
        `<状态目录>/nav-previews/<preview_job_id>.json.gz` 的绝对路径。

    Raises:
        InputError: preview_job_id 不是 ≥ 1 的整数。

    Side Effects:
        无。

    Time Semantics:
        无；纯路径计算。
    """
    raise NotImplementedError


def write_preview(paths: StatePaths, preview: NavPreview) -> Path:
    """把预览结果原子地写成压缩文件。

    Args:
        paths: 已初始化的状态布局。
        preview: 要保存的预览，plan.state 必须可验证。

    Returns:
        写好的文件路径。

    Raises:
        ConflictError: 该编号的预览已存在（预览作业重跑时由 RESTART 路径先删旧文件，不覆盖别人的）。
        ExternalError: 写入、fsync 或 rename 失败；不留半截文件。

    Side Effects:
        写同目录临时文件 → fsync → os.replace → fsync 目录。只写 nav-previews。

    Time Semantics:
        同步；预览作业收尾时调用一次。预览文件目前不自动清理（体积小、可手工删除），清理策略另行决定。
    """
    raise NotImplementedError


def read_preview(paths: StatePaths, preview_job_id: int) -> NavPreview:
    """读取一份预览结果。

    Args:
        paths: 已初始化的状态布局。
        preview_job_id: 预览作业编号，≥ 1。

    Returns:
        NavPreview。

    Raises:
        InputError: 文件不存在（预览作业未成功或编号不对）、解压或解析失败、format_version 不认识。
        ExternalError: 读取时 I/O 失败。

    Side Effects:
        无（只读状态目录）。

    Time Semantics:
        同步；写入作业在拿写锁之前读取，页面轮询到预览作业结束后读取。文件不记过期时间。
    """
    raise NotImplementedError
