"""写导航层测试的公共夹具函数：只在 pytest 临时目录里读写假导航层，从不碰真实路径。"""

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from nav_manifest import FakeNavigation

from rdp.audit.models import OperationLogRow
from rdp.infra.state import StatePaths
from rdp.jobs.datasets.reading import discover_entries, read_entry
from rdp.jobs.datasets.types import EntryLocation, EntrySnapshot, JsonObject, View
from rdp.jobs.navwrite.atomic import apply_plan, capture_before_images
from rdp.jobs.navwrite.changes import ArchiveRequest, ChangeOutcome, archive_journal
from rdp.jobs.navwrite.journal import Journal, discard_journal, journal_directory, write_journal
from rdp.jobs.navwrite.models import (
    FileImage,
    MakeDirStep,
    NavOperation,
    NavWritePlan,
    PreviewState,
    SetLinkStep,
    Step,
    WriteFileStep,
)


def noop() -> None:
    """不抛异常的检查点。"""


def locations(nav_root: Path, name: str) -> tuple[EntryLocation, ...]:
    """导航层里目录名为 name 的全部入口位置，按相对路径升序。"""
    return tuple(
        entry for entry in discover_entries(nav_root).entries if entry.dataset_name == name
    )


def task_location(nav_root: Path, name: str) -> EntryLocation:
    """按任务入口位置。"""
    (found,) = (item for item in locations(nav_root, name) if item.view is View.TASK)
    return found


def format_location(nav_root: Path, name: str) -> EntryLocation:
    """唯一的按格式入口位置（样本里每个数据集至多一个）。"""
    (found,) = (item for item in locations(nav_root, name) if item.view is View.FORMAT)
    return found


def snapshot(nav_root: Path, location: EntryLocation) -> EntrySnapshot:
    """读取入口快照。"""
    return read_entry(nav_root, location, checkpoint=noop)


def read_json(nav_root: Path, location: EntryLocation, name: str) -> JsonObject:
    """读入口里一份 JSON 对象。"""
    return json.loads((nav_root / location.path / name).read_text(encoding="utf-8"))


def sha(content: bytes) -> str:
    """原字节的 sha256 十六进制。"""
    return hashlib.sha256(content).hexdigest()


def dataset_id_of(fake_nav: FakeNavigation, name: str) -> str:
    """假导航层里某数据集的永久编号。"""
    (found,) = {
        entry.dataset_id for entry in fake_nav.manifest.entries if Path(entry.path).name == name
    }
    return found


def tree_state(root: Path) -> dict[str, str]:
    """目录树的完整状态（文件哈希、链接目标、目录），用来断言一行都没写。"""
    state: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        relative = str(path.relative_to(root))
        if path.is_symlink():
            state[relative] = "link:" + str(path.readlink())
        elif path.is_dir():
            state[relative] = "dir"
        else:
            state[relative] = "file:" + sha(path.read_bytes())
    return state


def file_image(content: bytes | None) -> FileImage:
    """文件的前像或后像；None 表示文件不存在。"""
    if content is None:
        return FileImage(exists=False)
    return FileImage(exists=True, sha256=sha(content), size_bytes=len(content))


def write_step(path: str, before: bytes | None, after: bytes) -> WriteFileStep:
    """一个 write_file 步骤；before 为 None 表示新建。"""
    return WriteFileStep(
        path=path,
        before=file_image(before),
        after=file_image(after),
        after_content=after.decode("utf-8"),
    )


def plan_for(
    nav_root: Path, steps: tuple[Step, ...], *, ids: tuple[str, ...] = ("dataset-1",)
) -> NavWritePlan:
    """只含给定步骤的计划；预览状态为空（单元测试不经过指纹）。"""
    return NavWritePlan(
        operation=NavOperation.REPOINT_DATASET,
        dataset_ids=ids,
        steps=steps,
        state=PreviewState(nav_root=str(nav_root), datasets=(), new_dataset=None),
    )


def simple_nav(root: Path) -> tuple[Path, tuple[Step, ...]]:
    """造最小导航树（两个 JSON、一条链接、一个将新建的目录）和对应的五步计划。"""
    nav = root / "nav"
    nav.mkdir()
    (nav / "a.json").write_bytes(b'{"v": 1}\n')
    (nav / "b.json").write_bytes(b'{"v": 2}\n')
    (nav / "L").symlink_to("/old-target")
    steps: tuple[Step, ...] = (
        MakeDirStep(path="newdir"),
        write_step("a.json", b'{"v": 1}\n', b'{"v": 11}\n'),
        write_step("b.json", b'{"v": 2}\n', b'{"v": 22}\n'),
        write_step("newdir/c.json", None, b'{"v": 3}\n'),
        SetLinkStep(path="L", before_target="/old-target", after_target="/new-target"),
    )
    return nav, steps


def _request(plan: NavWritePlan | None, outcome: ChangeOutcome) -> ArchiveRequest:
    """归档请求，时间固定。"""
    moment = datetime(2026, 10, 29, 12, tzinfo=UTC)
    return ArchiveRequest(outcome, 1, "管理员", None, moment, moment, plan, None, ())


def commit_keep_journal(
    paths: StatePaths,
    nav: Path,
    plan: NavWritePlan,
    job_id: int,
    outcome: ChangeOutcome = ChangeOutcome.COMMITTED,
) -> tuple[Journal, Path]:
    """核对前像 → 落日志 → 写入 → 归档，保留写入日志（供重复归档的测试使用）。"""
    moment = datetime(2026, 10, 29, 12, tzinfo=UTC)
    journal = write_journal(paths, plan, capture_before_images(nav, plan), job_id, moment)
    directory = journal_directory(paths, job_id)
    apply_plan(nav, plan, job_id, checkpoint=noop)
    committed = outcome is ChangeOutcome.COMMITTED
    archive_journal(paths, directory, journal, _request(plan if committed else None, outcome))
    return journal, directory


def archive_again(paths: StatePaths, journal: Journal, directory: Path, plan: NavWritePlan) -> None:
    """对同一份写入日志再归档一次。"""
    archive_journal(paths, directory, journal, _request(plan, ChangeOutcome.COMMITTED))


def run_committed(
    paths: StatePaths,
    nav: Path,
    plan: NavWritePlan,
    job_id: int,
    *,
    outcome: ChangeOutcome = ChangeOutcome.COMMITTED,
) -> None:
    """按流水线的顺序写一个作业：核对前像 → 落日志 → 写入 → 归档 → 删日志。"""
    _journal, directory = commit_keep_journal(paths, nav, plan, job_id, outcome)
    discard_journal(directory)


def archive_request_without_plan(
    paths: StatePaths, nav: Path, plan: NavWritePlan, job_id: int
) -> None:
    """落日志后以 COMMITTED 归档却不给 plan，应当被拒绝。"""
    moment = datetime(2026, 10, 29, 12, tzinfo=UTC)
    journal = write_journal(paths, plan, capture_before_images(nav, plan), job_id, moment)
    archive_journal(
        paths, journal_directory(paths, job_id), journal, _request(None, ChangeOutcome.COMMITTED)
    )


def audit_details(row: OperationLogRow) -> dict[str, dict[str, Any]]:
    """操作日志行的 details（v1 JSON）当成嵌套字典读。"""
    return cast(dict[str, dict[str, Any]], row.details)
