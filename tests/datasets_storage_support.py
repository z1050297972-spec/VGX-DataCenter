"""第二段测试依赖：真实访问检查器配临时存储根与合成挂载表，不读取系统挂载。"""

from collections.abc import Callable
from dataclasses import replace

from datasets_execution_support import DatasetCase
from jobs_storage_support import NOW

from rdp.infra.config import StorageConfig
from rdp.infra.storage import DeviceNumber, MountInspector, StorageAccessChecker, read_storage_root
from rdp.jobs.datasets.rescan import publish_scan, scan_navigation, scan_storage
from rdp.jobs.datasets.scan_types import StorageScan
from rdp.jobs.execution import ExecutionContext


def enable_storage(case: DatasetCase, *, table: str | None = None) -> None:
    """替换挂载表而非检查结果，使真实M0身份校验和超时路径参与测试。"""
    roots = case.scanning.roots
    devices = {root.uuid: DeviceNumber(8, index + 1) for index, root in enumerate(roots)}
    text = (
        table
        if table is not None
        else "\n".join(
            f"{index + 1} 0 8:{index + 1} / {root.path} rw - ext4 /dev/fake rw"
            for index, root in enumerate(roots)
        )
    )
    checker = StorageAccessChecker(
        MountInspector(roots, lambda: text, devices.get, lambda: NOW),
        StorageConfig(access_timeout_s=1),
        read_storage_root,
    )
    case.scanning = replace(case.scanning, storage=checker)


def scan(case: DatasetCase, checkpoint: Callable[[], None] = lambda: None) -> StorageScan:
    """经真实作业执行两段和发布；返回公开第二段结果供行为断言。"""
    results: list[StorageScan] = []

    def execute(context: ExecutionContext) -> None:
        navigation = scan_navigation(context, case.scanning)
        result = scan_storage(navigation, case.scanning, checkpoint=checkpoint)
        results.append(result)
        publish_scan(context, case.scanning, navigation, result)

    record = case.run(execute=execute)
    assert record.summary is not None and not record.summary.aborted
    return results[0]
