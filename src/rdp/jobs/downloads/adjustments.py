"""下载运行时参数的事务通道；借用平台 SQLite 工作单元，不保留 Session。"""

from sqlalchemy import Engine
from sqlalchemy.orm import Session

from rdp.infra.db.connection import session_scope
from rdp.infra.db.validation import invalid_field
from rdp.infra.diagnostics import (
    ConflictError,
    DefectError,
    Diagnostic,
    DiagnosticCategory,
    DiagnosticLevel,
)
from rdp.jobs.downloads.job import DownloadAdjustment, DownloadStatus
from rdp.jobs.models import DownloadAdjustmentRow, JobRow


def _row(session: Session, job_id: int) -> DownloadAdjustmentRow:
    """查找已有下载通道；拒绝不存在、非下载作业或未初始化记录。"""
    job = session.get(JobRow, job_id)
    row = session.get(DownloadAdjustmentRow, job_id)
    if job is None or job.type_name != "download" or row is None:
        failure = invalid_field("job_id", "已初始化的下载作业")
        raise failure
    return row


def _conflict() -> ConflictError:
    """构造不携带外部参数的状态冲突诊断。"""
    return ConflictError(
        (
            Diagnostic(
                level=DiagnosticLevel.ERROR,
                category=DiagnosticCategory.CONFLICT,
                stage="下载调参",
                source="平台",
                objects=(),
                rule="download.adjustment_state",
                actual="下载作业不是运行状态",
                expected="运行中的下载作业",
                consequence="未提交调整",
                next_step="检查作业状态后重试",
            ),
        )
    )


class SqlAdjustmentChannel:
    """以受管 SQLite 事务存放独立的请求和生效版本。"""

    def __init__(self, engine: Engine) -> None:
        """绑定数据库引擎，不持有数据库会话。

        Args:
            engine: 平台受管数据库引擎。

        Returns:
            无。

        Raises:
            DefectError: 引擎不是平台受管引擎。

        Side Effects:
            无；不连接数据库。

        Time Semantics:
            同步构造，不读取时钟。
        """
        if not engine.get_execution_options().get("rdp_managed"):
            raise DefectError()
        self._engine = engine

    def initialize(self, job_id: int, initial: DownloadAdjustment) -> None:
        """为下载作业建立初始调参行，重复调用保留现有请求。

        Args:
            job_id: 已登记下载作业的正整数编号。
            initial: 完整初始并发和速率，速率为 bytes/s。

        Returns:
            无；已有记录不改变。

        Raises:
            InputError: 作业不存在、类型错误或初始值不完整。
            ExternalError: 数据库事务失败。

        Side Effects:
            不存在记录时插入版本 0 的请求和实际值。

        Time Semantics:
            持写锁完成检查和插入；恢复不覆盖现有版本。
        """
        if (
            initial.max_concurrent_downloads is None
            or initial.max_overall_download_limit_bytes_per_s is None
        ):
            failure = invalid_field("initial", "完整初始并发与限速")
            raise failure
        with session_scope(self._engine) as session:
            job = session.get(JobRow, job_id)
            if job is None or job.type_name != "download":
                failure = invalid_field("job_id", "已登记的下载作业")
                raise failure
            if session.get(DownloadAdjustmentRow, job_id) is None:
                session.add(
                    DownloadAdjustmentRow(
                        job_id=job_id,
                        requested_version=0,
                        applied_version=0,
                        requested_concurrency=initial.max_concurrent_downloads,
                        requested_limit_bytes_per_s=initial.max_overall_download_limit_bytes_per_s,
                        effective_concurrency=initial.max_concurrent_downloads,
                        effective_limit_bytes_per_s=initial.max_overall_download_limit_bytes_per_s,
                    )
                )

    def submit(self, job_id: int, adjustment: DownloadAdjustment) -> int:
        """提交一份非空调整并返回其单调版本。

        Args:
            job_id: 正整数下载作业编号。
            adjustment: 至少包含并发或速率之一，速率单位 bytes/s。

        Returns:
            已提交的正整数版本号。

        Raises:
            InputError: 作业不存在、类型错误或调整为空。
            ConflictError: 作业未运行或数据库竞争。
            ExternalError: 数据库 I/O 故障。

        Side Effects:
            写事务内合并目标、递增版本，不访问 aria2。

        Time Semantics:
            事务提交为可见时刻；写锁保护并发字段合并。
        """
        if (
            adjustment.max_concurrent_downloads is None
            and adjustment.max_overall_download_limit_bytes_per_s is None
        ):
            failure = invalid_field("adjustment", "至少指定一个调整项")
            raise failure
        with session_scope(self._engine) as session:
            row = _row(session, job_id)
            job = session.get(JobRow, job_id)
            if job is None or job.state != "running":
                failure = _conflict()
                raise failure
            if adjustment.max_concurrent_downloads is not None:
                row.requested_concurrency = adjustment.max_concurrent_downloads
            if adjustment.max_overall_download_limit_bytes_per_s is not None:
                row.requested_limit_bytes_per_s = adjustment.max_overall_download_limit_bytes_per_s
            row.requested_version += 1
            return row.requested_version

    def read(self, job_id: int) -> DownloadStatus:
        """读取调参目标、生效值与文件计数。

        Args:
            job_id: 正整数下载作业编号。

        Returns:
            来自同一数据库快照的详情。

        Raises:
            InputError: 作业不存在、类型错误或通道尚未初始化。
            ExternalError: 数据库读取失败。

        Side Effects:
            只读数据库。

        Time Semantics:
            快照反映最近一次事务提交，不代表实时速度。
        """
        with session_scope(self._engine, read_only=True) as session:
            row = _row(session, job_id)
            return DownloadStatus(
                requested_version=row.requested_version,
                applied_version=row.applied_version,
                requested=DownloadAdjustment(
                    max_concurrent_downloads=row.requested_concurrency,
                    max_overall_download_limit_bytes_per_s=row.requested_limit_bytes_per_s,
                ),
                effective=DownloadAdjustment(
                    max_concurrent_downloads=row.effective_concurrency,
                    max_overall_download_limit_bytes_per_s=row.effective_limit_bytes_per_s,
                ),
                speed_bytes_per_s=row.speed_bytes_per_s,
                total_files=row.total_files,
                completed_files=row.completed_files,
                failed_files=row.failed_files,
                skipped_files=row.skipped_files,
            )

    def pending(self, job_id: int) -> tuple[int, DownloadAdjustment] | None:
        """读取当前尚未生效的完整目标。

        Args:
            job_id: 正整数下载作业编号。

        Returns:
            未生效版本及其完整目标；否则 None。

        Raises:
            InputError: 下载通道不存在。
            ExternalError: 数据库读取失败。

        Side Effects:
            只读数据库。

        Time Semantics:
            只表示读取时的快照，后续提交可能更新版本。
        """
        snapshot = self.read(job_id)
        if snapshot.applied_version >= snapshot.requested_version:
            return None
        return snapshot.requested_version, snapshot.requested

    def acknowledge(self, job_id: int, version: int, effective: DownloadAdjustment) -> None:
        """确认已成功调用 RPC 的版本，不改变新请求。

        Args:
            job_id: 正整数下载作业编号。
            version: 已应用的正整数版本。
            effective: 两项都非空的实际值，速率单位 bytes/s。

        Returns:
            无。

        Raises:
            InputError: 下载通道不存在或版本非法。
            ExternalError: 数据库写入失败。

        Side Effects:
            原子更新应用版本和生效值，保留请求字段。

        Time Semantics:
            仅在 RPC 成功之后调用；过期确认不回退生效版本。
        """
        if (
            version <= 0
            or effective.max_concurrent_downloads is None
            or effective.max_overall_download_limit_bytes_per_s is None
        ):
            failure = invalid_field("adjustment", "完整生效值和正版本")
            raise failure
        with session_scope(self._engine) as session:
            row = _row(session, job_id)
            if version > row.requested_version:
                failure = invalid_field("version", "不超过请求版本")
                raise failure
            if version > row.applied_version:
                row.applied_version = version
                row.effective_concurrency = effective.max_concurrent_downloads
                row.effective_limit_bytes_per_s = effective.max_overall_download_limit_bytes_per_s

    def report(self, job_id: int, status: DownloadStatus) -> None:
        """只写传输速度和文件计数，不覆盖调参字段。

        Args:
            job_id: 正整数下载作业编号。
            status: 速度为 bytes/s、计数为非负整数的快照。

        Returns:
            无。

        Raises:
            InputError: 下载通道不存在。
            DefectError: 计数或速度非法。
            ExternalError: 数据库写入失败。

        Side Effects:
            同事务更新速度和文件计数。

        Time Semantics:
            调用方负责每秒至多一次；最终可强制保存。
        """
        values = (
            status.speed_bytes_per_s,
            status.total_files,
            status.completed_files,
            status.failed_files,
            status.skipped_files,
        )
        if (
            any(type(value) is not int or value < 0 for value in values)
            or sum(values[2:]) > status.total_files
        ):
            raise DefectError()
        with session_scope(self._engine) as session:
            row = _row(session, job_id)
            row.speed_bytes_per_s = status.speed_bytes_per_s
            row.total_files = status.total_files
            row.completed_files = status.completed_files
            row.failed_files = status.failed_files
            row.skipped_files = status.skipped_files
