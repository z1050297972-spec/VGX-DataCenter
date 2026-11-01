"""下载固定清单的本地回执；使用已有 Pydantic 和标准库原子文件，不改变下载公开参数。"""

import os
import tempfile
from pathlib import Path
from typing import Literal

from pydantic import Field

from rdp.infra.state import StatePaths
from rdp.jobs.downloads.job import DownloadParameters
from rdp.jobs.downloads.plan import DownloadPlan
from rdp.jobs.navwrite.create_models import CreationValue
from rdp.jobs.navwrite.errors import nav_input_error

# 清单沿用下载计划的百万文件上界；字节预算防止损坏回执耗尽内存。
MAX_RECEIPT_BYTES = 256 * 1024 * 1024


class ReceiptFile(CreationValue):
    """下载计划已筛选的一个文件。

    Attributes:
        path: 仓库相对文件路径，访问前仍逐段核对。
        size_bytes: 预期大小，非负字节数。
    """

    path: str
    size_bytes: int = Field(ge=0)


class Receipt(CreationValue):
    """只读回执，记录下载实际使用的 commit 和文件清单。

    Attributes:
        version: 本地回执版本，固定 1，不属于来源.json 格式。
        commit: 固定的 40 位小写提交散列。
        parameters: 下载时的原始参数，不包含凭据。
        files: 筛选后完整清单，不重算文件哈希。
    """

    version: Literal[1] = 1
    commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    parameters: DownloadParameters
    files: tuple[ReceiptFile, ...]


def receipt_path(paths: StatePaths, job_id: int) -> Path:
    """只使用内部整数作业编号定位状态文件。"""
    return paths.nav_previews / f"download-receipt-{job_id}.json"


def atomic_bytes(path: Path, content: bytes) -> None:
    """同目录原子替换并 fsync，失败清理本次临时文件。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="wb", dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        try:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
            temporary.replace(path)
            directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            temporary.unlink(missing_ok=True)


def atomic_json(path: Path, content: str) -> None:
    """UTF-8 JSON 使用同一份原子落盘能力。"""
    atomic_bytes(path, content.encode("utf-8"))


def save_receipt(
    paths: StatePaths, job_id: int, plan: DownloadPlan, parameters: DownloadParameters
) -> None:
    """在下载前保存实际计划，入库只接受成功终态对应的这份清单。"""
    receipt = Receipt(
        commit=plan.revision.commit,
        parameters=parameters,
        files=tuple(ReceiptFile(path=file.path, size_bytes=file.size_bytes) for file in plan.files),
    )
    atomic_json(receipt_path(paths, job_id), receipt.model_dump_json())


def read_receipt(paths: StatePaths, job_id: int) -> Receipt:
    """有界读取本地回执；旧下载无回执时明确要求重新下载，不访问网络猜版本。"""
    try:
        with receipt_path(paths, job_id).open("rb") as stream:
            raw = stream.read(MAX_RECEIPT_BYTES + 1)
        if len(raw) > MAX_RECEIPT_BYTES:
            raise ValueError("回执超过预算")
        return Receipt.model_validate_json(raw)
    except (OSError, ValueError) as error:
        raise nav_input_error(
            "DOWNLOAD_INGEST",
            "下载回执缺失或损坏，请重新下载",
            objects=(("download_job_id", str(job_id)),),
        ) from error
