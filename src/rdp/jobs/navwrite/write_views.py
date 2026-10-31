"""改指向与撤回的 HTTP 展示投影；不暴露可执行步骤或文件全文。"""

from datetime import datetime
from typing import Literal

from pydantic import Field, JsonValue

from rdp.jobs.navwrite.create_models import CreationValue
from rdp.jobs.navwrite.create_views import CreationJobId, QueuedNavigationJob
from rdp.jobs.navwrite.models import FieldChangeCount, ListedChange, PlanReport


class ReversalDetails(CreationValue):
    """原变更报告的反向投影，永久变更记录为唯一来源。

    Attributes:
        field_counts: 原作业按文件字段的替换数，反向操作保持相同数量。
        listed_changes: 原报告逐处替换的 before/after 对调；改指向取全量，历史报告取其样例。
        listed_total: 应展示总处数，改指向全量受 REPOINT_LISTED_CHANGE_LIMIT 约束。
    """

    field_counts: tuple[FieldChangeCount, ...]
    listed_changes: tuple[ListedChange, ...]
    listed_total: int = Field(ge=0)


class NavigationPreviewView(CreationValue):
    """保存预览的安全展示字段。

    Attributes:
        preview_job_id: 成功预览作业的十进制文本编号。
        created_at: 预览生成的 aware UTC 时刻。
        operation: 改指向或撤回，不接受其他预览类型。
        dataset_ids: 受影响的永久编号，原计划顺序。
        reverts_job_id: 撤回的目标作业文本编号；改指向为 None。
        parameters: 作业中校验通过的原始参数，不含执行计划。
        report: 保存的分字段计数、正文替换和检查范围。
        changes: 步骤路径及前后像摘要，JSON 仅给哈希，不给正文。
        queued_jobs: 当前排队的同数据集写作业，确认前须刷新。
        reversal: 撤回原变更报告的反向投影，无原报告时为 None。
    """

    preview_job_id: CreationJobId
    created_at: datetime
    operation: Literal["repoint_dataset", "revert_change"]
    dataset_ids: tuple[str, ...]
    reverts_job_id: CreationJobId | None
    parameters: dict[str, JsonValue]
    report: PlanReport
    changes: tuple[ListedChange, ...]
    queued_jobs: tuple[QueuedNavigationJob, ...] = Field(default=())
    reversal: ReversalDetails | None = None
