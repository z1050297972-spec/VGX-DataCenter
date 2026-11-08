"""转换暂存每日维护（领域层，M4-03）；按作业结束时间筛选，仅删除失败/取消/中断产物。"""

import sys
from dataclasses import dataclass
from datetime import timedelta

from pydantic import BaseModel, ConfigDict
from sqlalchemy import or_, select

from rdp.infra.db.connection import session_scope
from rdp.infra.diagnostics import DefectError
from rdp.jobs.conversion.job import ConversionDependencies
from rdp.jobs.execution import ExecutionContext
from rdp.jobs.models import JobRow
from rdp.jobs.processes import ToolCommand
from rdp.jobs.types import JobProgress

# ADR0008、M4-03：失败产物保留7天；成功产物等待入库，不按年龄删除。
CONVERSION_RETENTION = timedelta(days=7)
CLEANUP_TYPE = "purge_conversion_staging"
CLEANUP_NAME = "清除过期转换暂存"
# 每批100个目录限制SQL结果和命令行长度；删除进程最多5分钟，超时保留剩余目录。
CLEANUP_BATCH_SIZE = 100
CLEANUP_TIMEOUT_S = 300.0


class CleanupParameters(BaseModel):
    """维护类型无用户路径或保留期参数，防止扩大删除边界。"""

    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)


@dataclass(frozen=True)
class ConversionCleanup:
    """每日清理执行能力，仅worker持有。

    Attributes:
        dependencies: 数据库和登记存储根；Web为None。
    """

    dependencies: ConversionDependencies | None

    def execute(self, context: ExecutionContext) -> None:
        """分批清理结束满七天的失败、取消和中断转换暂存目录。

        Args:
            context: 当前维护作业的时钟、取消与受管子进程能力。

        Returns:
            无；上报已经完成清理检查的作业数。

        Raises:
            DefectError: worker依赖缺失。
            ExternalError: 数据库查询、子进程删除失败或超过预算。
            JobCancelledError: 清理取消，保留尚未处理的目录。
            WorkerStoppingError: worker停止，已删除目录不恢复。

        Side Effects:
            只在登记可写根的暂存/转换下删除符合条件的数字作业目录；不改作业记录。
            子进程拒绝目录链上的软链接，成功产物永不选中。

        Time Semantics:
            使用作业UTC时钟减七天；每批子进程最多300秒，批次间响应取消。
            每日调度由框架负责，重跑只会重查剩余目录。
        """
        if self.dependencies is None:
            raise DefectError()
        deps = self.dependencies
        cutoff = context.clock.now() - CONVERSION_RETENTION
        last_id = 0
        completed = 0
        while True:
            context.reporter.check_cancelled()
            with session_scope(deps.engine, read_only=True) as session:
                identifiers = tuple(
                    session.scalars(
                        select(JobRow.job_id)
                        .where(
                            JobRow.job_id > last_id,
                            JobRow.type_name.startswith("convert_", autoescape=True),
                            JobRow.ended_at <= cutoff,
                            or_(
                                JobRow.state.in_(("cancelled", "interrupted")),
                                (JobRow.state == "completed") & (JobRow.outcome == "failed"),
                            ),
                        )
                        .order_by(JobRow.job_id)
                        .limit(CLEANUP_BATCH_SIZE)
                    )
                )
            if not identifiers:
                return
            for root in deps.roots:
                if root.writable:
                    context.run_process(
                        ToolCommand(
                            CLEANUP_NAME,
                            (
                                sys.executable,
                                "-m",
                                "rdp.jobs.conversion._cleanup_child",
                                str(root.path),
                                *(str(identifier) for identifier in identifiers),
                            ),
                            deps.tools.registry_dir,
                            CLEANUP_TIMEOUT_S,
                        )
                    )
            completed += len(identifiers)
            last_id = identifiers[-1]
            context.reporter.report(
                JobProgress(
                    stage_index=1,
                    stage_count=1,
                    stage_name=CLEANUP_NAME,
                    done=completed,
                    total=None,
                    unit="作业",
                    warning_count=0,
                    failed_items=0,
                    total_items=completed,
                )
            )
