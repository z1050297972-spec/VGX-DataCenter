"""创建预览的只读展示模型（领域层，M1-08），不包含可执行计划或文件全文。"""

from typing import Annotated, Literal, Self

from pydantic import AwareDatetime, Field, model_validator

from rdp.infra.ids import JOB_ID_PATTERN
from rdp.jobs.datasets.catalog import MAX_SCAN_ENTRIES
from rdp.jobs.navwrite.create_models import (
    CreationValue,
    DatasetPreviewParameters,
    LinkPreviewParameters,
)
from rdp.jobs.navwrite.models import PlanReport

CreationJobId = Annotated[str, Field(strict=True, pattern=f"^{JOB_ID_PATTERN}$")]


class CreationFormatOption(CreationValue):
    """格式登记表的一项，前端不复制目录映射。

    Attributes:
        format: 格式稳定键，来自 FORMAT_DIRECTORIES。
        directory: 原样磁盘目录名，archives 的显示名也由这里提供。
        has_versions: 是否要求输入单层版本目录。
        versions: 索引中已有版本候选，去重排序；允许用户输入新的安全单层版本名。
    """

    format: str
    directory: str
    has_versions: bool
    versions: tuple[str, ...]


class CreationOptions(CreationValue):
    """创建表单共享候选，不通过访问存储根推测格式。

    Attributes:
        formats: FORMAT_DIRECTORIES 的全部项，保持登记顺序。
        data_origins: DATA_ORIGINS 的全部中文值，保持登记顺序；未知也是可显式选择的值。
    """

    formats: tuple[CreationFormatOption, ...]
    data_origins: tuple[str, ...]


class QueuedNavigationJob(CreationValue):
    """提交前发现的同数据集排队写作业；不把预览作业算进写冲突提醒。

    Attributes:
        job_id: 规范十进制作业编号文本，禁止前端转 Number。
        dataset_ids: 与本次预览重叠的永久编号，去重升序。
    """

    job_id: CreationJobId
    dataset_ids: tuple[str, ...]


class CreationPreviewView(CreationValue):
    """成功预览的页面结果；仅投影已持久保存的同一份 NavPreview。

    Attributes:
        preview_job_id: 成功预览作业编号，文本，确认请求仅引用此编号。
        created_at: 预览保存的 UTC 时刻，不是 GET 请求时刻。
        operation: create_link 或 create_dataset；不允许拿撤回预览调用本票确认入口。
        dataset_id: 已有编号或预计分配的新编号；后者尚未占用。
        dataset_name: 规范入口名称。
        parameters: 原样回显已校验参数，不能在确认时覆盖。
        report: 第 07 张报告，creation 必须非空；差异、计数、检查范围与提示来自同一计划。
        queued_jobs: 当前数据库里同编号的排队写作业，升序，完整且有上界；仅作提醒。
    """

    preview_job_id: CreationJobId
    created_at: AwareDatetime
    operation: Literal["create_link", "create_dataset"]
    dataset_id: str
    dataset_name: str
    parameters: LinkPreviewParameters | DatasetPreviewParameters
    report: PlanReport
    queued_jobs: tuple[QueuedNavigationJob, ...] = Field(max_length=MAX_SCAN_ENTRIES)

    @model_validator(mode="after")
    def validate_creation_report(self) -> Self:
        """核对创建预览包含结构化差异且参数种类与操作一致。

        Args:
            无。

        Returns:
            当前展示对象；创建预览 report.creation 必须非空，参数类型与 operation 对应。

        Raises:
            ValueError: 缺创建差异、参数种类不符，或 noop 仍带写入差异/非零步骤计数。

        Side Effects:
            无；不读取计划文件或重新计算差异。

        Time Semantics:
            展示模型构造时校验，不刷新预览时刻或排队列表。
        """
        raise NotImplementedError
