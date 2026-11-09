"""转换入库的可信事实读取：数据库身份在父进程，存储和报告在受限子进程。"""

import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import cast

from rdp.infra.config import StorageRootConfig
from rdp.infra.db.connection import session_scope
from rdp.infra.diagnostics import DefectError
from rdp.jobs.conversion._process import run_bounded
from rdp.jobs.datasets.models import DatasetRow
from rdp.jobs.datasets.types import JsonObject
from rdp.jobs.navwrite.errors import Advice, nav_external_error, nav_input_error
from rdp.jobs.navwrite.pipeline import NavWriteDependencies
from rdp.jobs.outcome import JobOutcome
from rdp.jobs.records import find_job
from rdp.jobs.types import JobRecord, JobState


@dataclass(frozen=True)
class Conversion:
    """固定的转换身份与唯一可写根，名称来自当前输入索引。

    Attributes:
        record: 原转换作业和实际起止时间。
        root: 首个登记可写根，与转换执行器选择一致。
        input_name: 输入数据集的当前名称。
        input_entry: 输入规范入口的导航相对路径。
    """

    record: JobRecord
    root: StorageRootConfig
    input_name: str
    input_entry: str


def conversion(deps: NavWriteDependencies, identifier: int) -> Conversion:
    """只定位已登记转换与输入，不读取产物或把客户端路径当授权。"""
    with session_scope(deps.rescan.engine, read_only=True) as session:
        record = find_job(session, identifier)
        if not record.type_name.startswith("convert_"):
            raise nav_input_error("CONVERSION_INGEST", "对象不是转换作业")
        dataset = session.get(DatasetRow, str(record.parameters["dataset_id"]))
        if dataset is None or dataset.canonical_entry_path is None:
            raise nav_input_error("CONVERSION_INGEST", "输入数据集没有唯一规范入口")
        name, entry = dataset.name, dataset.canonical_entry_path
    root = next((item for item in deps.rescan.roots if item.writable), None)
    if root is None:
        raise nav_external_error(
            "CONVERSION_INGEST",
            "没有已登记的可写存储根",
            advice=Advice(
                "未开始转换入库",
                "管理员在配置文件登记可写存储根（NAS 平台区）后重新提交",
            ),
        )
    if deps.rescan.storage is None:
        raise DefectError()
    return Conversion(record, root, name, entry)


def output_name(value: Conversion) -> str:
    """结果路径只能是本作业 out 或 cleaned；旧记录缺摘要时兼容 out。"""
    progress = value.record.progress
    result = progress.conversion if progress is not None else None
    stage = value.root.path / "暂存/转换" / str(value.record.job_id)
    if result is None:
        if value.record.parameters.get("cleaning_preview_job_id") is not None:
            raise nav_input_error("CONVERSION_INGEST", "转换缺少产物结果")
        return "out"
    path = Path(result.output_path)
    if path not in (stage / "out", stage / "cleaned"):
        raise nav_input_error("CONVERSION_INGEST", "产物路径越出本作业暂存目录")
    return path.name


def inspect(value: Conversion) -> JsonObject:
    """检查并写入报告；未成功或非零退出码的转换不继续读取 out。"""
    record = value.record
    valid = (
        record.state is JobState.COMPLETED
        and record.summary is not None
        and record.summary.outcome in (JobOutcome.SUCCEEDED, JobOutcome.SUCCEEDED_WITH_WARNINGS)
        and record.tool_exit_code == 0
    )
    command = (
        sys.executable,
        "-m",
        "rdp.jobs.conversion._ingest_child",
        str(value.root.path),
        str(record.job_id),
        str(record.parameters["output_format"]),
        "1" if valid else "0",
    )
    try:
        with TemporaryDirectory(prefix="rdp-conversion-check-") as scratch:
            stdout, stderr, code = run_bounded(
                (*command, scratch, output_name(value) if valid else "out")
            )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise nav_external_error("CONVERSION_CHECK", "检查或回收进程超时") from error
    if code:
        raise nav_external_error("CONVERSION_CHECK", stderr.decode(errors="replace")[-4096:])
    return cast(JsonObject, json.loads(stdout))
