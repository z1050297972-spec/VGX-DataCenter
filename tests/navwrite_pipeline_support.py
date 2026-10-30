"""写入流水线测试的公共夹具：真实迁移的临时库、假导航层、真实领取与执行，所有路径属于 tmp_path。"""

from collections.abc import Callable, Generator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from datasets_execution_support import DatasetCase, dataset_case
from jobs_storage_support import job_row
from nav_manifest import FakeNavigation
from navwrite_support import dataset_id_of, noop, read_json, tree_state, write_step

from rdp.infra.db.connection import session_scope
from rdp.jobs.execution import ExecutionContext
from rdp.jobs.models import JobRow
from rdp.jobs.navwrite.jsonio import dump_navigation_json
from rdp.jobs.navwrite.models import (
    ApplyResult,
    NavOperation,
    NavPreview,
    NavWritePlan,
    PlanReport,
    SetLinkStep,
    Step,
)
from rdp.jobs.navwrite.pipeline import NavWriteDependencies, run_write_plan
from rdp.jobs.navwrite.preview_state import capture_preview_state
from rdp.jobs.navwrite.previews import write_preview
from rdp.jobs.registry import production_registry
from rdp.jobs.service import JobService
from rdp.jobs.types import JobRecord, JobState

WHEN = datetime(2026, 10, 29, 12, tzinfo=UTC)
PREVIEW_JOB = 70
EMPTY_REPORT = PlanReport(
    file_count=0,
    link_count=0,
    directory_count=0,
    field_counts=(),
    listed_changes=(),
    listed_total=0,
    checks=(),
    notices=(),
)


@dataclass
class Harness:
    """一个流水线用例：库、状态目录、假导航层和写入依赖。"""

    case: DatasetCase
    dependencies: NavWriteDependencies
    fake: FakeNavigation
    dataset: str
    original: dict[str, str]

    @property
    def nav(self) -> Path:
        """假导航层根。"""
        return self.fake.nav_root


@contextmanager
def harness(root: Path, fake: FakeNavigation) -> Generator[Harness]:
    """真实迁移的临时库 + 写入依赖；数据集取 EgoProDemo。"""
    with dataset_case(root / "state", fake) as case:
        service = JobService(case.engine, production_registry(case.scanning))
        deps = NavWriteDependencies(rescan=case.scanning, paths=case.paths, service=service)
        yield Harness(
            case, deps, fake, dataset_id_of(fake, "EgoProDemo"), tree_state(fake.nav_root)
        )


def modified_json(h: Harness, name: str) -> tuple[str, bytes, bytes]:
    """EgoProDemo 按任务入口里某份 JSON：返回 (相对路径, 旧字节, 加了一个键的新字节)。"""
    relative = f"按任务/EgoProDemo/{name}"
    old = (h.nav / relative).read_bytes()
    payload = read_json(h.nav, _task_location(h), name)
    payload["touched_by_test"] = True
    return relative, old, dump_navigation_json(payload)


def _task_location(h: Harness):
    """按任务入口位置。"""
    from navwrite_support import task_location

    return task_location(h.nav, "EgoProDemo")


def two_file_plan(h: Harness, *, with_link: bool = True) -> NavWritePlan:
    """改 数据集信息.json 与 子任务.json，再改一条链接的计划，预览状态取现状。"""
    steps: list[Step] = []
    for name in ("数据集信息.json", "子任务.json"):
        relative, old, new = modified_json(h, name)
        steps.append(write_step(relative, old, new))
    if with_link:
        link = h.nav / "按任务" / "EgoProDemo" / "原始数据"
        steps.append(
            SetLinkStep(
                path="按任务/EgoProDemo/原始数据",
                before_target=str(link.readlink()),
                after_target=str(h.nav.parent / "roots" / "dataset1"),
            )
        )
    state = capture_preview_state(h.nav, (h.dataset,), None, checkpoint=noop)
    return NavWritePlan(
        operation=NavOperation.REPOINT_DATASET,
        dataset_ids=(h.dataset,),
        steps=tuple(steps),
        state=state,
    )


def save_preview(
    h: Harness,
    plan: NavWritePlan,
    preview_id: int = PREVIEW_JOB,
    *,
    state: JobState = JobState.COMPLETED,
) -> NavPreview:
    """登记一个已成功结束的预览作业，并写出它的预览文件。"""
    with session_scope(h.case.engine) as session:
        row = job_row(state, job_id=preview_id)
        row.type_name = "dataset_rescan"
        session.add(row)
    preview = NavPreview(
        preview_job_id=preview_id, created_at=WHEN, parameters={}, plan=plan, report=EMPTY_REPORT
    )
    write_preview(h.case.paths, preview)
    return preview


@dataclass
class Outcome:
    """一次写入作业的结果：作业记录、返回值和异常。"""

    record: JobRecord
    result: ApplyResult | None
    error: Exception | None


def run_apply(
    h: Harness,
    preview_id: int = PREVIEW_JOB,
    *,
    around: Callable[[ExecutionContext], None] | None = None,
) -> Outcome:
    """作为一个真实的作业执行 run_write_plan；around 在其之前运行（用于放置取消信号等）。"""
    box: list[ApplyResult] = []
    errors: list[Exception] = []

    def execute(context: ExecutionContext) -> None:
        if around is not None:
            around(context)
        try:
            box.append(run_write_plan(context, h.dependencies, preview_id))
        except Exception as error:
            errors.append(error)
            raise

    record = h.case.run(execute=execute)
    # 写入作业会提交统计大小等后续作业，占用了后面的作业编号；让下一次 run 避开它们。
    h.case.number = max([h.case.number, *(row.job_id + 1 for row in job_rows(h))])
    return Outcome(record, box[0] if box else None, errors[0] if errors else None)


def job_rows(h: Harness) -> list[JobRow]:
    """库里全部作业行。"""
    from sqlalchemy import select

    with session_scope(h.case.engine, read_only=True) as session:
        return list(session.execute(select(JobRow).order_by(JobRow.job_id)).scalars())
