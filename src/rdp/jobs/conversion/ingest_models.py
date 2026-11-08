"""转换入库的请求与预览值契约；沿用 M1 的名称、入口选择和确认编号。"""

from pydantic import Field

from rdp.jobs.conversion.check_models import CheckReport
from rdp.jobs.downloads.ingest_models import IngestOptions
from rdp.jobs.navwrite.create_models import CreationValue, FormatEntrySelection

CHECK_TYPE = "conversion_ingest_preview"
APPLY_TYPE = "conversion_ingest_apply"
DELETE_TYPE = "conversion_staging_delete"


class ConversionIngestParameters(IngestOptions):
    """检查与预览参数；automatic 仅由 worker 的成功收尾触发器填写。"""

    conversion_job_id: int = Field(strict=True, ge=1)
    automatic: bool = False


class ConversionIngestPreviewView(CreationValue):
    """保存预览的可展示部分；修改选项后必须重新检查并预览。"""

    preview_job_id: str
    parameters: ConversionIngestParameters
    fields: dict[str, str]
    check: CheckReport
    checks: tuple[str, ...]
    notices: tuple[str, ...]
    format_entry_options: tuple[FormatEntrySelection, ...]
