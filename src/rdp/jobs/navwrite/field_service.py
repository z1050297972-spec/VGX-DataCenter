"""编辑确认的 Web 领域边界（M1.5-02）：读取同一预览，快速检查冲突，再提交通用写入作业。

只读导航和预览文件；确认检查不代替 worker 持锁复核，不在此执行写入。
"""

from datetime import timedelta
from pathlib import Path

from rdp.infra.state import StatePaths
from rdp.jobs import _storage
from rdp.jobs.navwrite.errors import nav_input_error
from rdp.jobs.navwrite.field_models import FIELD_PREVIEW_TYPE
from rdp.jobs.navwrite.models import NavOperation
from rdp.jobs.navwrite.policy import NAV_APPLY_TYPE, PREVIEW_RETENTION_DAYS
from rdp.jobs.navwrite.preview_state import verify_preview_state
from rdp.jobs.navwrite.previews import read_preview
from rdp.jobs.outcome import JobOutcome
from rdp.jobs.service import JobRequest, JobService
from rdp.jobs.types import JobRecord, JobState


def submit_field_write(
    jobs: JobService, paths: StatePaths, nav_root: Path, request: JobRequest, preview_job_id: int
) -> JobRecord:
    """确认成功且未过期的字段预览并提交统一写作业。

    Args:
        jobs: 当前应用已登记类型的作业服务。
        paths: 同一应用状态目录，只读预览文件。
        nav_root: 服务器配置的绝对导航根。
        request: 确认者的真实身份、UTC 时刻与审计来源。
        preview_job_id: 1 至 2^63-1 的预览作业编号。

    Returns:
        queued 的 nav_write_apply，参数只引用同一预览编号。

    Raises:
        JobInputError: 编号或提交参数不合格。
        JobNotFoundError: 预览作业不存在。
        InputError: 预览未成功、类型或关联不符、损坏或超过七天。
        ConflictError: 导航指纹有变化，或者提交事务竞争。
        AuthenticationError: 当前会话在读取或提交事务失效。
        PasswordChangeRequiredError: 当前账号必须改密。
        ExternalError: 预览、导航或数据库读取/提交失败。

    Side Effects:
        只读状态和导航；通过检查才新增作业和提交日志。冲突不提交，导航不写。

    Time Semantics:
        回拨按零经过时长处理；确认无锁，worker 随后仍须持锁复核 L12，不重算计划。
    """
    identifier = _storage.identifier(preview_job_id)
    job = jobs.get(request, identifier)
    if (
        job.type_name != FIELD_PREVIEW_TYPE
        or job.state is not JobState.COMPLETED
        or job.summary is None
        or job.summary.outcome not in (JobOutcome.SUCCEEDED, JobOutcome.SUCCEEDED_WITH_WARNINGS)
    ):
        problem = nav_input_error("NAV_FIELDS", "字段编辑预览尚未成功完成")
        raise problem
    preview = read_preview(paths, identifier)
    if (
        preview.plan.operation is not NavOperation.EDIT_DATASET_FIELDS
        or preview.parameters != job.parameters
        or preview.preview_job_id != identifier
        or max(timedelta(), request.now - preview.created_at)
        > timedelta(days=PREVIEW_RETENTION_DAYS)
    ):
        problem = nav_input_error("NAV_FIELDS", "预览关联不符或已过七天，请重新预览")
        raise problem
    verify_preview_state(nav_root, preview.plan.state, checkpoint=_checkpoint)
    return jobs.submit(request, NAV_APPLY_TYPE, {"preview_job_id": identifier})


def _checkpoint() -> None:
    """HTTP 只进行有界导航观察，无 worker 取消信号。"""
