"""改指向的 HTTP 展示投影；不暴露可执行步骤或文件全文。"""

from datetime import datetime
from typing import Literal

from pydantic import Field, JsonValue

from rdp.jobs.navwrite.create_models import CreationValue
from rdp.jobs.navwrite.create_views import CreationJobId, QueuedNavigationJob
from rdp.jobs.navwrite.models import ListedChange, PlanReport


class NavigationPreviewView(CreationValue):
    """保存预览的安全展示字段。

    Attributes:
        preview_job_id: 成功预览作业的十进制文本编号。
        created_at: 预览生成的 aware UTC 时刻。
        operation: 改指向，不接受其他预览类型。
        dataset_ids: 受影响的永久编号，原计划顺序。
        parameters: 作业中校验通过的原始参数，不含执行计划。
        report: 保存的分字段计数、正文替换和检查范围。
        changes: 步骤路径及前后像摘要，JSON 仅给哈希，不给正文。
        queued_jobs: 当前排队的同数据集写作业，确认前须刷新。
    """

    preview_job_id: CreationJobId
    created_at: datetime
    operation: Literal["repoint_dataset"]
    dataset_ids: tuple[str, ...]
    parameters: dict[str, JsonValue]
    report: PlanReport
    changes: tuple[ListedChange, ...]
    queued_jobs: tuple[QueuedNavigationJob, ...] = Field(default=())
