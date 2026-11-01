"""下载入库的临时样本；只用合成清单、假导航和已迁移测试数据库。"""

import json
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path

from creation_support import creation_case, stamp
from datasets_storage_support import enable_storage
from jobs_storage_support import job_row
from nav_manifest import FakeNavigation
from navwrite_pipeline_support import WHEN, Harness

from rdp.infra.db.connection import session_scope
from rdp.jobs.navwrite.jobs import PreviewBuild
from rdp.jobs.navwrite.models import NavPreview
from rdp.jobs.navwrite.previews import write_preview
from rdp.jobs.types import JobState

INFO = {
    "codebase_version": "v3.0",
    "robot_type": "so101",
    "fps": 30,
    "total_episodes": 2,
    "total_frames": 42,
    "features": {
        "observation.images.front": {"dtype": "video", "shape": [480, 640, 3]},
        "observation.state": {"dtype": "float32", "shape": [6]},
        "action": {"dtype": "float32", "shape": [7]},
    },
}
COMMIT = "a" * 40
DOWNLOAD_ID = 60
PREVIEW_ID = 70


@contextmanager
def ingest_case(root: Path, fake: FakeNavigation) -> Generator[tuple[Harness, Path]]:
    """提供成功下载记录和固定 commit 清单，下载内容为极小 LeRobot。"""
    with creation_case(root, fake) as h:
        roots = (
            h.case.scanning.roots[0].model_copy(update={"writable": True}),
            *h.case.scanning.roots[1:],
        )
        h.case.scanning = replace(h.case.scanning, roots=roots)
        enable_storage(h.case)
        h.dependencies = replace(h.dependencies, rescan=h.case.scanning)
        stage = roots[0].path / "暂存/下载/dataset/org/repo@aaaaaaaaaaaa"
        (stage / "meta").mkdir(parents=True)
        (stage / "meta/info.json").write_text(json.dumps(INFO))
        (stage / "data").mkdir()
        (stage / "data/sample.parquet").write_bytes(b"sample")
        request: dict[str, object] = {
            "repo_type": "dataset",
            "repo_id": "org/repo",
            "revision": "main",
            "storage_root": roots[0].name,
            "exclude_video": True,
        }
        receipt = {
            "version": 1,
            "commit": COMMIT,
            "parameters": request,
            "files": [
                {"path": "meta/info.json", "size_bytes": (stage / "meta/info.json").stat().st_size},
                {"path": "data/sample.parquet", "size_bytes": 6},
            ],
        }
        (h.case.paths.nav_previews / "download-receipt-60.json").write_text(json.dumps(receipt))
        with session_scope(h.case.engine) as session:
            row = job_row(JobState.COMPLETED, job_id=DOWNLOAD_ID)
            row.type_name = "download"
            row.parameters = request
            row.outcome = "succeeded"
            row.failed_items = row.warning_count = 0
            assert row.progress is not None and row.summary is not None
            row.progress = {**row.progress, "failed_items": 0, "warning_count": 0}
            row.summary = {
                **row.summary,
                "outcome": "succeeded",
                "failed_items": 0,
                "warning_count": 0,
                "progress": row.progress,
            }
            session.add(row)
        yield h, stage


def build(h: Harness):
    """从公共 worker 预览边界生成计划，不写导航和存储。"""
    from rdp.jobs.downloads.ingest import build_ingest_preview
    from rdp.jobs.downloads.ingest_models import IngestParameters

    return build_ingest_preview(
        h.dependencies,
        IngestParameters(download_job_id=DOWNLOAD_ID),
        stamp(),
        checkpoint=lambda: None,
    )


def save(h: Harness, result: PreviewBuild) -> None:
    """模拟框架已完成预览，再让实际写入流水线读取同一份持久计划。"""
    with session_scope(h.case.engine) as session:
        row = job_row(JobState.COMPLETED, job_id=PREVIEW_ID)
        row.type_name = "download_ingest_preview"
        row.parameters = {"download_job_id": DOWNLOAD_ID}
        row.outcome = "succeeded"
        row.failed_items = row.warning_count = 0
        assert row.progress is not None and row.summary is not None
        row.progress = {**row.progress, "failed_items": 0, "warning_count": 0}
        row.summary = {
            **row.summary,
            "outcome": "succeeded",
            "failed_items": 0,
            "warning_count": 0,
            "progress": row.progress,
        }
        session.add(row)
    write_preview(
        h.case.paths,
        NavPreview(
            preview_job_id=PREVIEW_ID,
            created_at=WHEN,
            parameters=result.parameters,
            plan=result.plan,
            report=result.report,
        ),
    )
