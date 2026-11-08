"""M4-04 的 worker/API 装配，所有产物和登记根仅位于 tmp。"""

import json
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path

from account_api_support import ApiCase
from conversion_ingest_support import product
from creation_support import creation_api_case
from datasets_execution_support import DatasetCase
from datasets_storage_support import enable_storage
from jobs_storage_support import job_row
from nav_manifest import FakeNavigation
from navwrite_support import dataset_id_of

from rdp.infra.db.connection import session_scope
from rdp.jobs.navwrite.pipeline import NavWriteDependencies
from rdp.jobs.types import JobState

CONVERSION_ID = 60


@contextmanager
def conversion_case(
    root: Path, fake: FakeNavigation, *, warning: bool = False, input_name: str = "EgoProDemo"
) -> Generator[tuple[ApiCase, NavWriteDependencies, Path]]:
    """成功转换记录配真实格式元信息及 tmp 生成的 parquet/视频。"""
    info_path = fake.nav_root / "按任务" / input_name / "数据集信息.json"
    input_info = json.loads(info_path.read_text())
    input_info["data_origin"] = "真机采集"
    info_path.write_text(json.dumps(input_info, ensure_ascii=False))
    with creation_api_case(root, fake) as (api, deps):
        roots = (deps.rescan.roots[0].model_copy(update={"writable": True}), *deps.rescan.roots[1:])
        case = DatasetCase(api.engine, deps.paths, replace(deps.rescan, roots=roots))
        enable_storage(case)
        deps = replace(deps, rescan=case.scanning)
        stage = product(roots[0].path / "暂存/转换/60/out")
        if warning:
            info = json.loads((stage / "meta/info.json").read_text())
            info["vendor_extension"] = "future"
            (stage / "meta/info.json").write_text(json.dumps(info))
        parameters: dict[str, object] = {
            "dataset_id": dataset_id_of(fake, input_name),
            "source_ids": ["source-1"],
            "robot_model": "r1lite",
            "output_format": "v3.0",
        }
        receipt = {
            "job_id": CONVERSION_ID,
            "tool": {
                "name": "mcap2lerobot",
                "version": "0.1.0",
                "source_commit": "abc",
                "binary_sha256": "f" * 64,
            },
            "configuration": {
                "filename": "configs/r1lite.toml",
                "content": "[robot]\nname = 'r1lite'\n",
                "sha256": "c" * 64,
            },
            "inputs": [
                {
                    "dataset_id": parameters["dataset_id"],
                    "source_id": "source-1",
                    "path": str(root / "input.mcap"),
                }
            ],
            "exit_code": 0,
        }
        (stage.parent / "转换回执.json").write_text(json.dumps(receipt))
        with session_scope(api.engine) as session:
            row = job_row(JobState.COMPLETED, job_id=CONVERSION_ID)
            row.type_name = "convert_mcap2lerobot"
            row.parameters = parameters
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
        yield api, deps, stage
