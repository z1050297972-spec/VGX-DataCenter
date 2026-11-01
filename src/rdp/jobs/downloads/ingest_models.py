"""下载入库的值契约（领域层，M2-05）；不访问导航层或存储根。"""

from pydantic import Field

from rdp.jobs.navwrite.create_models import CreationValue, EntryName, FormatEntrySelection
from rdp.jobs.navwrite.create_views import CreationJobId

INGEST_PREVIEW_TYPE = "download_ingest_preview"
INGEST_APPLY_TYPE = "download_ingest_apply"


class IngestOptions(CreationValue):
    """手动入库的预览输入，路径和名字的默认值由固定下载回执推导。

    Attributes:
        dataset_name: M1 安全单层数据集名；None 使用仓库名。
        target_subdir: 同一个可写根内的相对路径；None 使用 下载/命名空间/仓库@短提交。
        format_entries: 勾选的 M1 格式入口；None 默认 lerobot/数据版本，空元组表示不建格式入口。
    """

    dataset_name: EntryName | None = None
    target_subdir: str | None = Field(default=None, min_length=1)
    format_entries: tuple[FormatEntrySelection, ...] | None = None


class IngestParameters(IngestOptions):
    """worker 保存的入库请求，来源编号由 HTTP 路径解析。

    Attributes:
        download_job_id: 成功的数据集下载编号，严格正整数。
    """

    download_job_id: int = Field(strict=True, ge=1)


class IngestConfirmation(CreationValue):
    """只确认保存的预览，不接受客户端计划。

    Attributes:
        preview_job_id: 正整数编号的十进制文本，范围沿用 M1。
    """

    preview_job_id: CreationJobId


class IngestPreviewView(CreationValue):
    """从保存的计划提取页面摘要，不返回可执行计划正文。

    Attributes:
        preview_job_id: 十进制预览编号文本，避免浏览器整数精度损失。
        parameters: 已解析默认值的输入；修改后必须重新预览。
        fields: 14 项名称和正文，保持导航层规定的顺序。
        checks: 预览已经完成的检查说明。
        notices: 部分下载等提示。
        format_entry_options: 沿用 M1 格式登记表与已知版本的完整勾选候选。
    """

    preview_job_id: str
    parameters: IngestParameters
    fields: dict[str, str]
    checks: tuple[str, ...]
    notices: tuple[str, ...]
    format_entry_options: tuple[FormatEntrySelection, ...] = ()
