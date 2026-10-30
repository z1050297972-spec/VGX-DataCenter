"""创建操作的 HTTP 确认字段（入口层，M1-08），复用领域输入和 M0 作业响应。"""

from typing import Self

from pydantic import Field, model_validator

from rdp.api.job_schemas import JobResponse
from rdp.jobs.datasets.catalog import MAX_SCAN_ENTRIES
from rdp.jobs.navwrite.create_models import CreationValue
from rdp.jobs.navwrite.create_views import CreationJobId, QueuedNavigationJob


class ConfirmCreationRequest(CreationValue):
    """用户确认保存的预览，不能夹带替换参数或计划。

    Attributes:
        preview_job_id: 成功的创建预览编号，规范十进制文本，数值不超过 MAX_SQLITE_INTEGER。
        acknowledged_queue_job_ids: 已在页面看到并确认的排队作业编号，去重；默认空。
            新出现未确认的排队编号会再次返回提醒，不能以通配布尔值绕过。
    """

    preview_job_id: CreationJobId
    acknowledged_queue_job_ids: tuple[CreationJobId, ...] = Field(
        default=(), max_length=MAX_SCAN_ENTRIES
    )


class CreationSubmitResponse(CreationValue):
    """确认提交结果；HTTP 200 的提醒分支没有创建资源。

    Attributes:
        confirmation_required: True 时 job 必须为 None 且 queued_jobs 非空，需要用户再次确认。
        job: False 分支为新 nav_write_apply 的 M0 queued 记录；不改变既有 JobResponse。
        queued_jobs: 本次检查观察到的排队写作业，升序，不包含本次新作业；可以为空。
    """

    confirmation_required: bool
    job: JobResponse | None
    queued_jobs: tuple[QueuedNavigationJob, ...] = Field(max_length=MAX_SCAN_ENTRIES)

    @model_validator(mode="after")
    def validate_submission(self) -> Self:
        """核对排队提醒和已提交作业两个分支不能混淆。

        Args:
            无。

        Returns:
            当前响应；提醒分支 job=None 且 queued_jobs 非空，提交分支 job 非空。

        Raises:
            ValueError: confirmation_required 与 job/queued_jobs 关系不满足上述分支约束。

        Side Effects:
            无；不提交作业，不修改队列或已有响应对象。

        Time Semantics:
            HTTP 序列化边界同步校验，不再读取队列快照。
        """
        raise NotImplementedError
