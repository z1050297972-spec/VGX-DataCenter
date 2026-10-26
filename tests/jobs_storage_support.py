"""作业存取边界的已知行样本；只建临时数据库，预期计数不调用被测计算函数。"""

from collections.abc import Generator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import Engine

from rdp.infra.config import PlatformConfig
from rdp.infra.db.connection import create_database_engine
from rdp.infra.db.models import metadata
from rdp.infra.state import StatePaths, initialize_state, state_paths
from rdp.jobs.models import JobRow
from rdp.jobs.types import JobState

NOW = datetime(2026, 10, 26, 12, tzinfo=UTC)
PROGRESS: dict[str, object] = {
    "stage_index": 1,
    "stage_count": 2,
    "stage_name": "处理",
    "done": 2,
    "total": 4,
    "unit": "条",
    "warning_count": 3,
    "failed_items": 1,
    "total_items": 2,
}


def job_row(state: JobState = JobState.RUNNING, *, job_id: int = 71) -> JobRow:
    """提供固定且独立的合法状态快照，数据库测试据此验证状态转换而非绕过生产鉴权。"""
    terminal = state in {JobState.COMPLETED, JobState.CANCELLED, JobState.INTERRUPTED}
    progress = None if state is JobState.QUEUED else dict(PROGRESS)
    summary: dict[str, object] | None = None
    if terminal:
        summary = {
            "state": state.value,
            "outcome": "partially_succeeded" if state is JobState.COMPLETED else None,
            "progress": progress,
            "total_items": 2,
            "failed_items": 1,
            "warning_count": 3,
            "aborted": False,
            "elapsed_s": 2.5,
            "artifacts": ["产物/样例"],
            "tool_exit_code": 0,
        }
    return JobRow(
        job_id=job_id,
        type_name="example_count",
        display_name="示例：数数",
        parameters={"steps": 4, "interval_ms": 0},
        submitter_id=7,
        submitter_name="历史提交人",
        submitted_at=NOW,
        resubmitted_from=None,
        state=state.value,
        recovery_mode="interrupt",
        recovery_count=0,
        started_at=None if state is JobState.QUEUED else NOW,
        ended_at=NOW if terminal else None,
        outcome="partially_succeeded" if state is JobState.COMPLETED else None,
        total_items=0 if progress is None else 2,
        failed_items=0 if progress is None else 1,
        warning_count=0 if progress is None else 3,
        aborted=False,
        progress=progress,
        progress_at=None if progress is None else NOW,
        elapsed_s=0 if progress is None else 2.5,
        artifacts=[] if progress is None else ["产物/样例"],
        log_path=None
        if state is JobState.QUEUED
        else f"logs/示例：数数/2026-10-26_120000_000_{job_id}.log",
        diagnostics=[],
        summary=summary,
        tool_exit_code=None if progress is None else 0,
    )


@contextmanager
def job_database(root: Path) -> Generator[tuple[Engine, StatePaths]]:
    """创建具有标准状态布局的临时库，供领取时日志路径预留测试使用，最终关闭引擎。"""
    paths = state_paths(PlatformConfig(state_dir=root), ("示例：数数",))
    initialize_state(paths)
    engine = create_database_engine(paths.database)
    try:
        metadata.create_all(engine)
        yield engine, paths
    finally:
        engine.dispose()
