"""转换暂存的数据库投影；Web 只读作业及本机提交记录，worker 删除前再次核对。

复用已有作业与 M1 永久提交记录，不另建容易与导航事务失步的入库状态表。
"""

from typing import Literal

from pydantic import BaseModel
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from rdp.infra.db.connection import session_scope
from rdp.infra.state import StatePaths
from rdp.jobs.conversion.check_models import CheckReport
from rdp.jobs.conversion.ingest_models import APPLY_TYPE, CHECK_TYPE, DELETE_TYPE
from rdp.jobs.datasets.models import DatasetRow
from rdp.jobs.downloads._ingest_access import committed
from rdp.jobs.models import JobRow
from rdp.jobs.types import JobProgress

# 每页50项只读取本页关联作业；编号游标避免新转换插入时翻页重复。
STAGING_PAGE_SIZE = 50


class StagingItem(BaseModel):
    """转换及其最新检查、入库状态；大小是最近一次worker检查时的字节数。"""

    job_id: str
    input_dataset: str
    tool: str
    output_format: str
    size_bytes: int | None
    check: CheckReport | None
    status: Literal["待检查", "待确认", "已入库", "不通过", "失败"]
    in_use: bool
    deleted: bool


class StagingPage(BaseModel):
    """按转换编号倒序的暂存页，next_before为空表示已到底。"""

    items: tuple[StagingItem, ...]
    next_before: str | None


def related(session: Session, identifier: int) -> tuple[JobRow, ...]:
    """读取转换的检查、删除及由检查产生的入库作业，用于展示和执行前核对。

    Args:
        session: 调用方管理的只读数据库事务。
        identifier: 正整数转换编号。

    Returns:
        编号升序的关联作业行，仅在当前事务使用。

    Raises:
        ExternalError: 数据库不可用，由会话边界转换。

    Side Effects:
        只读作业表，无存储访问。

    Time Semantics:
        当前事务快照，不等待关联作业完成。
    """
    previews = select(JobRow.job_id).where(
        JobRow.type_name == CHECK_TYPE,
        JobRow.parameters["conversion_job_id"].as_integer() == identifier,
    )
    return tuple(
        session.scalars(
            select(JobRow)
            .where(
                (
                    JobRow.type_name.in_((CHECK_TYPE, DELETE_TYPE))
                    & (JobRow.parameters["conversion_job_id"].as_integer() == identifier)
                )
                | (
                    (JobRow.type_name == APPLY_TYPE)
                    & JobRow.parameters["preview_job_id"].as_integer().in_(previews)
                )
            )
            .order_by(JobRow.job_id)
        )
    )


def item(session: Session, paths: StatePaths, row: JobRow) -> StagingItem:
    """将转换与后继作业合成展示状态，永久导航提交事实优先于作业收尾状态。

    Args:
        session: 当前只读事务。
        paths: 本机状态目录，不包含任意存储根访问能力。
        row: 当前转换作业行。

    Returns:
        展示行；in_use防止在活跃转换、检查或入库期间删除。

    Raises:
        ExternalError: 数据库或永久提交记录读取失败。

    Side Effects:
        只读数据库和本机M1变更记录。

    Time Semantics:
        返回当前快照；删除执行时必须在暂存锁内重新读取。
    """
    jobs = related(session, row.job_id)
    checks = [job for job in jobs if job.type_name == CHECK_TYPE and job.progress is not None]
    progress = JobProgress.model_validate(checks[-1].progress) if checks else None
    result = progress.ingest_check if progress else None
    applied = any(job.type_name == APPLY_TYPE and committed(paths, job.job_id) for job in jobs)
    deleted = any(job.type_name == DELETE_TYPE and job.outcome == "succeeded" for job in jobs)
    active = {"queued", "running", "cancelling"}
    busy = row.state in active or any(
        job.state in active for job in jobs if job.type_name != DELETE_TYPE
    )
    dataset = session.get(DatasetRow, str(row.parameters["dataset_id"]))
    status = _status(row, result.report if result else None, applied)
    return StagingItem(
        job_id=str(row.job_id),
        input_dataset=dataset.name if dataset else str(row.parameters["dataset_id"]),
        tool=row.type_name.removeprefix("convert_"),
        output_format=str(row.parameters.get("output_format", "")),
        size_bytes=result.size_bytes if result else None,
        check=result.report if result else None,
        status=status,
        in_use=busy,
        deleted=deleted,
    )


def _status(
    row: JobRow, report: CheckReport | None, applied: bool
) -> Literal["待检查", "待确认", "已入库", "不通过", "失败"]:
    """已提交优先；警告和通过但未入库都保留人工入口。"""
    if applied:
        return "已入库"
    if row.state in ("cancelled", "interrupted") or row.outcome == "failed":
        return "失败"
    if report is None:
        return "待检查"
    return "不通过" if report.result == "不通过" else "待确认"


def read_staging(engine: Engine, paths: StatePaths, before: int | None) -> StagingPage:
    """按游标读取转换暂存列表，删除成功的条目不再显示。

    Args:
        engine: 受管数据库引擎。
        paths: 本机平台状态目录。
        before: 可选正整数上界，首次读取为None。

    Returns:
        至多50条转换及下一页游标；已入库记录保留但不可删除。

    Raises:
        ExternalError: 数据库或提交记录不可读。

    Side Effects:
        无写入；不枚举存储根，不创建扫描作业。

    Time Semantics:
        当前请求快照；大小和报告沿用最近worker检查，不宣称实时文件统计。
    """
    with session_scope(engine, read_only=True) as session:
        query = select(JobRow).where(JobRow.type_name.startswith("convert_", autoescape=True))
        if before is not None:
            query = query.where(JobRow.job_id < before)
        rows = tuple(session.scalars(query.order_by(JobRow.job_id.desc()).limit(STAGING_PAGE_SIZE)))
        items = tuple(item(session, paths, row) for row in rows)
        return StagingPage(
            items=tuple(value for value in items if not value.deleted),
            next_before=str(rows[-1].job_id) if len(rows) == STAGING_PAGE_SIZE else None,
        )
