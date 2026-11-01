"""下载预览短作业；worker 只读存储根并把不含路径和凭据的摘要写入状态目录。

使用既有 build_plan 和标准库原子替换；不重复实现镜像、容量和筛选规则。
"""

import os
import tempfile
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from rdp.infra.db.validation import invalid_field
from rdp.infra.diagnostics import DefectError
from rdp.infra.state import StatePaths, state_paths
from rdp.jobs.downloads.job import DownloadDependencies, DownloadParameters, request_from_parameters
from rdp.jobs.downloads.plan import Capacity, DatasetPreview, build_plan
from rdp.jobs.execution import ExecutionContext
from rdp.jobs.types import JobProgress


class PreviewResult(BaseModel):
    """仅包含页面所需的只读摘要，不包含文件清单、绝对路径或凭据。"""

    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)
    created_at: datetime
    commit: str
    file_count: int
    dataset: DatasetPreview | None
    capacity: Capacity
    sufficient: bool


@dataclass(frozen=True)
class PreviewExecutor:
    """保存 worker 下载依赖；Web 登记时不提供执行能力。

    Attributes:
        dependencies: worker 下载边界；Web 登记时为 None。
    """

    dependencies: DownloadDependencies | None

    def execute(self, context: ExecutionContext) -> None:
        """生成只读下载预览并发布摘要。

        Args:
            context: 预览作业上下文及 DownloadParameters 参数。

        Returns:
            无。

        Raises:
            DefectError: 缺少 worker 依赖或参数类型错误。
            InputError: 下载请求或容量不满足计划契约。
            ExternalError: 镜像、存储检查或状态目录不可用。

        Side Effects:
            只读镜像及存储根；在状态目录发布预览摘要和作业进度。

        Time Semantics:
            复用计划的有界网络请求与取消检查；结果只反映生成时的容量快照。
        """
        if self.dependencies is None or not isinstance(context.parameters, DownloadParameters):
            raise DefectError()
        reporter = context.reporter
        reporter.check_cancelled()
        dependencies = replace(
            self.dependencies.plan,
            sleep=reporter.wait,
            checkpoint=reporter.check_cancelled,
        )
        plan = build_plan(request_from_parameters(context.parameters), dependencies)
        result = PreviewResult(
            created_at=context.clock.now(),
            commit=plan.revision.commit,
            file_count=len(plan.files),
            dataset=plan.preview,
            capacity=plan.capacity,
            sufficient=True,
        )
        _publish(state_paths(dependencies.config, ()), context.job_id, result)
        reporter.report(
            JobProgress(
                stage_index=1,
                stage_count=1,
                stage_name="下载预览",
                done=1,
                total=1,
                unit="预览",
                total_items=1,
                failed_items=0,
                warning_count=0,
            )
        )


def _path(paths: StatePaths, job_id: int) -> Path:
    """结果只按内部整数编号寻址，避免用户输入变成文件路径。"""
    if type(job_id) is not int or job_id < 1:
        problem = invalid_field("job_id", "正整数作业编号")
        raise problem
    return paths.nav_previews / f"download-{job_id}.json"


def _publish(paths: StatePaths, job_id: int, result: PreviewResult) -> None:
    """同目录临时文件替换保证读取方不看到半份 JSON；重跑可替换自己的旧结果。"""
    target = _path(paths, job_id)
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=target.parent, delete=False
    ) as stream:
        temporary = Path(stream.name)
        try:
            stream.write(result.model_dump_json())
            stream.flush()
            os.fsync(stream.fileno())
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)


def read_download_preview(paths: StatePaths, job_id: int) -> PreviewResult:
    """读取 worker 已发布的下载预览。

    Args:
        paths: 平台状态目录布局。
        job_id: 不小于 1 的预览作业编号。

    Returns:
        不含凭据和路径的预览摘要。

    Raises:
        InputError: 编号无效、结果尚未生成或内容损坏。
        OSError: 状态目录不可读取。

    Side Effects:
        只读状态目录，不访问存储根。

    Time Semantics:
        返回最近一次成功发布的快照。
    """
    try:
        return PreviewResult.model_validate_json(_path(paths, job_id).read_bytes())
    except (FileNotFoundError, ValueError) as error:
        problem = invalid_field("job_id", "已生成的下载预览")
        raise problem from error
