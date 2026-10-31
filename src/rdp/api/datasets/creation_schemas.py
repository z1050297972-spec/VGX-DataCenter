"""创建操作的 HTTP 确认字段（入口层，M1-08），复用领域输入和 M0 作业响应。"""

from pydantic import Field

from rdp.jobs.datasets.catalog import MAX_SCAN_ENTRIES
from rdp.jobs.navwrite.create_models import CreationValue
from rdp.jobs.navwrite.create_views import CreationJobId


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
