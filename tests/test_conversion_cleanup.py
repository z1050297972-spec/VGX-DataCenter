"""转换清理验收只使用临时目录和已结束的测试作业，不接触真实存储。"""

from datetime import timedelta
from pathlib import Path

from conversion_support import fake_converter, settings
from jobs_execution_support import execution_case
from jobs_storage_support import NOW, job_row

from rdp.infra.config import StorageRootConfig
from rdp.infra.db.connection import session_scope
from rdp.jobs.conversion.cleanup import ConversionCleanup
from rdp.jobs.conversion.job import ConversionDependencies
from rdp.jobs.execution import ExecutionContext, execute_job
from rdp.jobs.outcome import JobOutcome
from rdp.jobs.types import JobState


def test_cleanup_only_expired_unsuccessful_staging(tmp_path: Path) -> None:
    """验收5：七天前失败目录删除，六天前失败和七天前成功的目录保留。"""
    files = fake_converter(tmp_path / "tool")
    root = tmp_path / "storage"
    for number in (101, 102, 103):
        path = root / "暂存/转换" / str(number)
        path.mkdir(parents=True)
        (path / "partial").write_text("keep until expiry")

    def execute(context: ExecutionContext) -> None:
        ConversionCleanup(
            ConversionDependencies(
                deps.engine,
                settings(files),
                (
                    StorageRootConfig(
                        name="platform", path=root, nfs_export="server:/platform", writable=True
                    ),
                ),
            )
        ).execute(context)

    with execution_case(tmp_path / "state", {"steps": 1, "interval_ms": 0}, execute) as (
        work,
        deps,
        signals,
    ):
        with session_scope(deps.engine) as session:
            for number, days, outcome in (
                (101, 7, "failed"),
                (102, 6, "failed"),
                (103, 7, "succeeded"),
            ):
                row = job_row(JobState.COMPLETED, job_id=number)
                row.type_name = "convert_mcap2lerobot"
                row.submitted_at = row.started_at = row.ended_at = NOW - timedelta(days=days)
                row.outcome = outcome
                session.add(row)
        result = execute_job(work, deps, signals)
        assert result is not None and result.summary is not None
        assert result.summary.outcome is JobOutcome.SUCCEEDED
        assert not (root / "暂存/转换/101").exists()
        assert (root / "暂存/转换/102/partial").is_file()
        assert (root / "暂存/转换/103/partial").is_file()
        assert all(not thread.is_alive() for thread in signals.monitor.threads)
