"""转换暂存删除worker：复用M4清理子进程，只删除未入库且不再使用的数字作业目录。"""

import sys
from functools import partial

from pydantic import Field

from rdp.accounts.types import Role
from rdp.infra.db.connection import session_scope
from rdp.infra.diagnostics import DefectError
from rdp.jobs.conversion import _ingest_read
from rdp.jobs.conversion.cleanup import CLEANUP_TIMEOUT_S
from rdp.jobs.conversion.ingest_models import DELETE_TYPE
from rdp.jobs.conversion.staging import item
from rdp.jobs.downloads._ingest_access import check_root
from rdp.jobs.downloads.coordination import download_guard
from rdp.jobs.execution import ExecutionContext
from rdp.jobs.models import JobRow
from rdp.jobs.navwrite.create_models import CreationValue
from rdp.jobs.navwrite.errors import nav_input_error
from rdp.jobs.navwrite.pipeline import NavWriteDependencies
from rdp.jobs.processes import ToolCommand
from rdp.jobs.registry import JobDefinition
from rdp.jobs.types import JobProgress, RecoveryMode


class DeleteParameters(CreationValue):
    """只接收转换编号，不接受任何客户端目录或存储根。"""

    conversion_job_id: int = Field(strict=True, ge=1)


def _delete(deps: NavWriteDependencies | None, context: ExecutionContext) -> None:
    """暂存互斥覆盖状态复核与删除进程，入库在同一把锁下执行。"""
    if (
        deps is None
        or not isinstance(context.parameters, DeleteParameters)
        or deps.rescan.storage is None
    ):
        raise DefectError()
    identifier = context.parameters.conversion_job_id
    with download_guard(deps.paths.root, context):
        value = _ingest_read.conversion(deps, identifier)
        with session_scope(deps.rescan.engine, read_only=True) as session:
            row = session.get(JobRow, identifier)
            if row is None:
                raise DefectError()
            state = item(session, deps.paths, row)
        if state.status == "已入库" or state.in_use:
            raise nav_input_error("CONVERSION_DELETE", "仅可删除未入库且未被作业使用的转换暂存")
        check_root(value.root, deps.rescan.storage, context.reporter.check_cancelled)
        context.run_process(
            ToolCommand(
                "删除转换暂存",
                (
                    sys.executable,
                    "-m",
                    "rdp.jobs.conversion._cleanup_child",
                    str(value.root.path),
                    str(identifier),
                ),
                deps.paths.root,
                CLEANUP_TIMEOUT_S,
            )
        )
        context.reporter.report(
            JobProgress(
                stage_index=1,
                stage_count=1,
                stage_name="删除转换暂存",
                done=1,
                total=1,
                unit="作业",
                warning_count=0,
                failed_items=0,
                total_items=1,
            )
        )


def build_delete_definition(dependencies: NavWriteDependencies | None) -> JobDefinition:
    """登记只对管理员开放的转换暂存删除作业。

    Args:
        dependencies: worker 的存储及状态能力；Web登记时为None。

    Returns:
        INTERRUPT恢复类型，删除超时或中断不自动重复执行。

    Raises:
        无。

    Side Effects:
        只创建定义，不读取暂存。

    Time Semantics:
        启动登记；实际删除最多300秒，等暂存锁最多30秒。
    """
    return JobDefinition(
        DELETE_TYPE,
        "删除转换暂存",
        DeleteParameters,
        RecoveryMode.INTERRUPT,
        partial(_delete, dependencies),
        submission_role=Role.ADMINISTRATOR,
    )
