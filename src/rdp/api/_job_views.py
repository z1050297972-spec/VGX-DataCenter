"""HTTP作业记录映射的唯一实现，保持M0编号文本、历史操作者及字段筛选契约。"""

from dataclasses import asdict

from rdp.api.job_schemas import JobResponse
from rdp.jobs.types import JobRecord


def response(record: JobRecord) -> JobResponse:
    """在 HTTP 边界转换 64 位编号；系统账号编号保持 None，不输出字符串 None 或已删除标记。"""
    data = asdict(record)
    data["job_id"] = str(record.job_id)
    data["resubmitted_from"] = (
        None if record.resubmitted_from is None else str(record.resubmitted_from)
    )
    data["submitted_by"] = {
        "account_id": None
        if record.submitted_by.account_id is None
        else str(record.submitted_by.account_id),
        "name": record.submitted_by.name,
        "deleted": record.submitter_deleted,
    }
    for field in ("submitter_deleted", "artifacts", "tool_exit_code"):
        data.pop(field)
    return JobResponse.model_validate(data)
