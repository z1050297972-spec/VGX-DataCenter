"""分类删除的只读范围发现（领域层，M1.5-16）；Web 与 worker 共用，不访问数据链接目标。

复用导航受限读取及已有分类投影，以规范副本为准，不依赖可能过期的索引计数。
"""

from collections.abc import Callable
from pathlib import Path

from rdp.jobs.datasets.reading import discover_entries, read_entry
from rdp.jobs.datasets.types import View
from rdp.jobs.errors import JobInputError
from rdp.jobs.navwrite.classification_parameters import ClassificationRemoveParameters
from rdp.jobs.navwrite.errors import nav_input_error


def classification_dataset_ids(
    nav_root: Path,
    parameters: ClassificationRemoveParameters,
    *,
    checkpoint: Callable[[], None],
) -> tuple[str, ...]:
    """找出规范副本中实际使用待删除值的数据集编号。

    Args:
        nav_root: 导航层根目录绝对路径；不跟随数据链接。
        parameters: 已验证字段名及非空分类值。
        checkpoint: 每份文件及读块的取消检查，HTTP 调用可传空操作。

    Returns:
        非空、升序且去重的永久数据集编号。

    Raises:
        JobInputError: 没有任何规范副本使用该值。
        InputError: 规范入口身份或信息文件不可读，不能证明删除范围完整。
        ExternalError: 导航层无法枚举。
        JobCancelledError: worker 检查点检测到取消。
        WorkerStoppingError: worker 检查点检测到停止。

    Side Effects:
        无（只读导航层的规范入口，不写索引、不访问存储根）。

    Time Semantics:
        不取时钟；范围只代表读取时状态，worker 重新发现并在计划里记录指纹。
    """
    ids: set[str] = set()
    for location in discover_entries(nav_root).entries:
        if location.view is not View.TASK:
            continue
        current = read_entry(nav_root, location, checkpoint=checkpoint)
        if current.dataset_id is None or current.documents[1].payload is None:
            problem = nav_input_error("NAV_CLASSIFICATION_REMOVE", "规范入口身份或信息文件不可用")
            raise problem
        values = current.scene if parameters.kind == "scene" else current.tasks
        if parameters.value in values:
            ids.add(current.dataset_id)
    if not ids:
        raise JobInputError(
            nav_input_error("NAV_CLASSIFICATION_REMOVE", "没有数据集使用这个分类值").diagnostics
        )
    return tuple(sorted(ids))
