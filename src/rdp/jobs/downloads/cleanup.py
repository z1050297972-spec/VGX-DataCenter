"""下载暂存清理的类型登记与 worker 执行边界；Web 不访问存储根。"""

import sys
from dataclasses import dataclass
from typing import Literal, override

from pydantic import BaseModel, ConfigDict, Field, field_validator

from rdp.infra.diagnostics import DefectError
from rdp.infra.ids import JOB_TYPE_KEY_PATTERN
from rdp.infra.state import state_paths
from rdp.jobs.downloads.coordination import download_guard
from rdp.jobs.downloads.job import DownloadDependencies, DownloadExecutor
from rdp.jobs.execution import ExecutionContext
from rdp.jobs.processes import ToolCommand
from rdp.jobs.registry import StorageUse
from rdp.jobs.storage import check_storage_before_job
from rdp.jobs.types import JobProgress

# 清理在独立进程执行以便取消、限时及留住 D 状态进程的锁；单位秒。
DELETE_TIMEOUT_SECONDS = 300.0


class DeleteParameters(BaseModel):
    """只允许平台的规范仓库身份，绝不接受绝对路径。"""

    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)
    storage_root: str = Field(pattern=f"^{JOB_TYPE_KEY_PATTERN}$")
    repo_type: Literal["dataset", "model"]
    repo_id: str = Field(pattern=r"^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$")
    commit_prefix: str = Field(pattern=r"^[0-9a-f]{12}$")

    @field_validator("repo_id")
    @classmethod
    def _valid_repo_id(cls, value: str) -> str:
        """拒绝特殊目录段，避免绕过安全仓库路径。"""
        if any(part in (".", "..") for part in value.split("/")):
            raise ValueError("非法仓库编号")
        return value


class ProtectedDownloadExecutor(DownloadExecutor):
    """在既有下载执行前取得与清理子进程共享的状态目录锁。"""

    @override
    def execute(self, context: ExecutionContext) -> None:
        """在暂存互斥保护下执行既有下载契约。

        Args:
            context: 原下载执行上下文。

        Returns:
            无；其余结果与原下载执行器一致。

        Raises:
            DefectError: worker 依赖缺失。
            ExternalError: 互斥锁超时或原下载外部依赖失败。
            InputError: 原下载输入无效。
            JobCancelledError: 等锁或下载时取消。
            WorkerStoppingError: 等锁或下载时 worker 停止。

        Side Effects:
            先锁定状态目录的本地锁文件，再执行原下载；不扩展存储写权限。

        Time Semantics:
            取得锁最多 30 秒；持锁覆盖整个下载及其子进程清理。
        """
        if self.dependencies is None:
            raise DefectError()
        with download_guard(self.dependencies.plan.config.state_dir, context):
            super().execute(context)


@dataclass(frozen=True)
class StagingDeleteExecutor:
    """绑定 worker 的可信根配置和有界检查器。

    Attributes:
        dependencies: worker 下载依赖；Web 登记时为 None。
    """

    dependencies: DownloadDependencies | None

    def execute(self, context: ExecutionContext) -> None:
        """校验可写根并启动有界删除子进程。

        Args:
            context: 已授权入队的删除作业上下文及 DeleteParameters。

        Returns:
            无；删除完成后报告一个已完成条目。

        Raises:
            DefectError: 依赖、参数或登记根不一致。
            ExternalError: 根不可写、离线、进程超时或目录删除失败。
            JobCancelledError: 等待或删除时收到取消。
            WorkerStoppingError: 等待或删除时 worker 停止。

        Side Effects:
            worker 在登记可写根中仅删除选定的暂存目录；报告进度，不修改已入库目录。

        Time Semantics:
            先检查可写许可与挂载，再启动有界子进程；子进程持锁并再次核对占用。
        """
        if self.dependencies is None or not isinstance(context.parameters, DeleteParameters):
            raise DefectError()
        plan = self.dependencies.plan
        parameters = context.parameters
        if plan.checker.mounts.roots != plan.config.storage_roots:
            raise DefectError()
        roots = [root for root in plan.config.storage_roots if root.name == parameters.storage_root]
        if len(roots) != 1:
            raise DefectError()
        check_storage_before_job(
            (StorageUse(parameters.storage_root, write=True),),
            checker=plan.checker,
            checkpoint=context.reporter.check_cancelled,
        )
        paths = state_paths(plan.config, ())
        context.run_process(
            ToolCommand(
                "删除下载暂存",
                (
                    sys.executable,
                    "-m",
                    "rdp.jobs.downloads._delete_child",
                    str(paths.root),
                    str(roots[0].path),
                    str(context.job_id),
                    parameters.storage_root,
                    parameters.repo_type,
                    parameters.repo_id,
                    parameters.commit_prefix,
                ),
                paths.root,
                DELETE_TIMEOUT_SECONDS,
            )
        )
        context.reporter.report(
            JobProgress(
                stage_index=1,
                stage_count=1,
                stage_name="清理下载暂存",
                done=1,
                total=1,
                unit="目录",
                total_items=1,
                failed_items=0,
                warning_count=0,
            )
        )
