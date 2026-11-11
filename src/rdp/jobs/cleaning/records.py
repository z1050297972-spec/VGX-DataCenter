"""清洗报告持久化（领域层，M4.5-02）；复用 SQLAlchemy 与第 01 张报告 JSON 模型。

报告随永久作业保留，dataset_id 不外键连接可重建索引，避免重扫删掉历史报告。
"""

from datetime import datetime

from pydantic import AwareDatetime, BaseModel, ConfigDict, ValidationError
from sqlalchemy import JSON, ForeignKey, Text
from sqlalchemy.orm import Mapped, Session, mapped_column

from rdp.infra.db.models import Base
from rdp.infra.db.utc import UTCDateTime
from rdp.infra.db.validation import invalid_field
from rdp.infra.diagnostics import DefectError
from rdp.jobs.cleaning.models import CleaningReport
from rdp.jobs.errors import JobNotFoundError


class CleaningPreviewRow(Base):
    """一次成功预览的事实快照；时间为 UTC，三个指纹均为完整 SHA-256。"""

    __tablename__ = "cleaning_previews"

    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.job_id"), primary_key=True)
    dataset_id: Mapped[str] = mapped_column(Text)
    tool_name: Mapped[str] = mapped_column(Text)
    robot_model: Mapped[str] = mapped_column(Text)
    binary_sha256: Mapped[str] = mapped_column(Text)
    config_sha256: Mapped[str] = mapped_column(Text)
    rules_sha256: Mapped[str] = mapped_column(Text)
    report: Mapped[dict[str, object]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime())


class CleaningPreview(BaseModel):
    """成功预览及其可复现身份；报告版本由 CleaningReport 严格校验。"""

    model_config = ConfigDict(frozen=True, extra="forbid", from_attributes=True)
    job_id: int
    dataset_id: str
    tool_name: str
    robot_model: str
    binary_sha256: str
    config_sha256: str
    rules_sha256: str
    created_at: AwareDatetime
    report: CleaningReport


def save_preview(session: Session, preview: CleaningPreview) -> None:
    """在作业成功终态的同一事务内新增完整报告。

    Args:
        session: 执行器持有的终态写事务，不得自行提交。
        preview: 已完成的版本一报告，job_id 为当前正整数编号，时刻为 UTC。

    Returns:
        无。

    Raises:
        ExternalError: 数据库写入失败，由受管会话转换。
        ConflictError: 同一作业已有报告，主键约束拒绝覆盖。

    Side Effects:
        新增 cleaning_previews 一行；事务失败连同作业终态回滚，不写存储根。

    Time Semantics:
        仅在执行器确认成功且未取消后调用；created_at 取生成报告时刻。
    """
    session.add(
        CleaningPreviewRow(
            **preview.model_dump(mode="python", exclude={"report"}),
            report=preview.report.model_dump(mode="json"),
        )
    )


def read_preview(session: Session, job_id: int) -> CleaningPreview:
    """读取成功预览并用原报告模型核验存量 JSON。

    Args:
        session: 调用方管理的只读数据库事务。
        job_id: 正整数作业编号。

    Returns:
        含完整报告、三个指纹及 UTC 生成时刻的冻结快照。

    Raises:
        JobNotFoundError: 不存在报告，包括未完成、失败或非预览作业。
        DefectError: 存量报告版本未知或字段不符合模型。
        ExternalError: 数据库读取失败，经受管会话边界转换。

    Side Effects:
        无（只读报告表，不打开任何文件）。

    Time Semantics:
        当前事务快照；不等待作业完成，不重新计算历史报告。
    """
    row = session.get(CleaningPreviewRow, job_id)
    if row is None:
        raise JobNotFoundError(invalid_field("job_id", "已有成功清洗预览的作业").diagnostics)
    try:
        return CleaningPreview.model_validate(row)
    except ValidationError as error:
        raise DefectError() from error
