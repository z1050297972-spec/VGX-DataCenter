"""下载入库的受限存储访问与改名恢复；不改 M1 日志协议。

复用已登记挂载检查器、下载互斥锁与标准库 subprocess 的超时回收；移动意图先原子落盘，
导航变更记录决定重启后保留正式目录还是改回暂存，避免把已提交的数据错误退回。
"""

import json
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Literal, cast

from rdp.infra.config import StorageRootConfig
from rdp.infra.state import StatePaths
from rdp.infra.storage import StorageAccessChecker
from rdp.jobs._inherited_fds import INHERITED_FDS
from rdp.jobs.datasets.types import JsonObject
from rdp.jobs.downloads._ingest_receipt import receipt_path
from rdp.jobs.navwrite.changes import ChangeOutcome, read_change_record
from rdp.jobs.navwrite.errors import nav_external_error, nav_input_error
from rdp.jobs.registry import StorageUse
from rdp.jobs.storage import check_storage_before_job

# 每次文件系统访问上限 30 秒；子进程退出时回收，无遗留工作线程。
INGEST_IO_TIMEOUT_S = 30.0


def access(
    action: Literal["check", "move", "restore"],
    root: StorageRootConfig,
    stage: str,
    target: str,
    receipt: Path,
) -> JsonObject:
    """隔离 NAS 读写；无 shell，异常保留具体文件身份而不包含凭据。"""
    command = (
        sys.executable,
        "-m",
        "rdp.jobs.downloads._ingest_child",
        action,
        str(root.path),
        stage,
        target,
        str(receipt),
    )
    try:
        result = subprocess.run(  # noqa: S603  # 理由：固定解释器和模块，路径来自登记根与已校验的相对路径，无 shell。
            command,
            capture_output=True,
            timeout=INGEST_IO_TIMEOUT_S,
            check=False,
            start_new_session=True,
            pass_fds=INHERITED_FDS.get(),
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise nav_external_error(
            "DOWNLOAD_INGEST_IO",
            "入库文件系统访问失败或超时",
            objects=(("storage_root", root.name),),
        ) from error
    if result.returncode != 0:
        detail = result.stdout.decode("utf-8", errors="replace")[-4096:]
        if action == "check" and result.returncode == 1:
            raise nav_input_error(
                "DOWNLOAD_INGEST_CHECK",
                detail,
                objects=(
                    ("storage_root", root.name),
                    ("staging_path", stage),
                    ("target_subdir", target),
                ),
            )
        raise nav_external_error(
            "DOWNLOAD_INGEST_IO",
            "入库改名失败",
            objects=(
                ("storage_root", root.name),
                ("returncode", str(result.returncode)),
                ("detail", detail),
                ("stderr", result.stderr.decode("utf-8", errors="replace")[-4096:]),
            ),
        )
    return cast(JsonObject, json.loads(result.stdout))


def check_root(
    root: StorageRootConfig, checker: StorageAccessChecker, checkpoint: Callable[[], None]
) -> None:
    """先确认可写许可和实际挂载身份，不能把未挂载的空目录当成存储根。"""
    check_storage_before_job(
        (StorageUse(root.name, write=True),), checker=checker, checkpoint=checkpoint
    )


def committed(paths: StatePaths, job_id: int) -> bool:
    """只以 M1 的永久提交记录为准，不因之后的索引/统计失败而移动已入库数据。"""
    if not (paths.nav_changes / f"{job_id}.json.gz").exists():
        return False
    return read_change_record(paths, job_id).outcome is ChangeOutcome.COMMITTED


def check_files(
    paths: StatePaths, job_id: int, root: StorageRootConfig, stage: str, target: str
) -> JsonObject:
    """读取固定下载回执，逐个检查文件而不重新计算哈希。"""
    return access("check", root, stage, target, receipt_path(paths, job_id))
