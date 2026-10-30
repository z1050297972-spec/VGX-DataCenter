"""M1-08 测试装配：临时导航、合成挂载、真实数据库和写入底座。"""

from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path

from account_api_support import ApiCase
from datasets_storage_support import enable_storage
from nav_manifest import FakeNavigation
from navwrite_pipeline_support import Harness, harness

from rdp.jobs.navwrite.create_models import FirstLink, LinkPreviewParameters
from rdp.jobs.navwrite.pipeline import NavWriteDependencies
from rdp.jobs.types import JobRecord


@contextmanager
def creation_case(root: Path, fake: FakeNavigation) -> Generator[Harness]:
    """提供真实底座，所有目标和挂载观察仅来自本测试的临时目录。"""
    with harness(root, fake) as value:
        enable_storage(value.case)
        value.dependencies = replace(value.dependencies, rescan=value.case.scanning)
        yield value


def target_path(value: Harness) -> Path:
    """创建尚未登记的新目标，只写临时存储根。"""
    path = value.case.scanning.roots[0].path / "creation-target"
    path.mkdir(exist_ok=True)
    return path


def link_parameters(value: Harness, **changes: object) -> LinkPreviewParameters:
    """给 EgoProDemo 增加目标不被已有数据块覆盖的 mcap 链接。"""
    body: dict[str, object] = {
        "dataset_id": value.dataset,
        "link": FirstLink(
            name="新增链接", target_path=str(target_path(value)), fallback_format="mcap"
        ),
    }
    body.update(changes)
    return LinkPreviewParameters.model_validate(body)


def new_parameters(value: Harness, **changes: object):
    """新的 mcap 数据集参数；所有路径仍为临时目录。"""
    from rdp.jobs.navwrite.create_models import DatasetPreviewParameters

    body: dict[str, object] = {
        "dataset_name": "新数据集",
        "data_origin": "开源下载",
        "link": link_parameters(value).link,
    }
    body.update(changes)
    return DatasetPreviewParameters.model_validate(body)


def stamp():
    """固定 UTC 人工印记，不依赖本机时区。"""
    from rdp.jobs.navwrite.provenance import ActorStamp

    return ActorStamp(kind="人工标注", account_id=1, account_name="甲", at="2026-10-30T07:00:00Z")


@contextmanager
def creation_api_case(
    root: Path, fake: FakeNavigation
) -> Generator[tuple[ApiCase, NavWriteDependencies]]:
    """真实 HTTP 与 worker 共用临时库，存储根身份只读合成挂载表。"""
    from dataset_api_support import browser_case
    from datasets_execution_support import DatasetCase

    from rdp.jobs.datasets.rescan import RescanDependencies
    from rdp.jobs.navwrite.pipeline import NavWriteDependencies

    with browser_case(root, fake) as api:
        paths = api.app.state.job_paths
        value = DatasetCase(
            api.engine,
            paths,
            RescanDependencies(api.engine, fake.nav_root, fake.storage_roots, None),
        )
        enable_storage(value)
        yield api, NavWriteDependencies(value.scanning, paths, api.app.state.job_service)


def run_queued(api: ApiCase, dependencies: NavWriteDependencies, identifier: str) -> JobRecord:
    """通过真实领取和执行器运行指定作业，不替换任何业务执行函数。"""
    import time
    from threading import Event, Lock

    from jobs_scheduling_support import claim_fixture, resources_fixture

    from rdp.infra.db.connection import session_scope
    from rdp.jobs.execution import ExecutionWork, ExecutorDependencies, execute_job
    from rdp.jobs.progress import ExecutionMonitor, ExecutionSignals
    from rdp.jobs.records import claim_job
    from rdp.jobs.registry import production_registry
    from rdp.jobs.types import ExecutionMode, JobClock

    registry = production_registry(dependencies.rescan, dependencies)
    with session_scope(api.engine) as session:
        record = claim_job(
            session, int(identifier), now=api.clock(), paths=dependencies.paths, gpu_index=None
        )
    execution = ExecutorDependencies(
        api.engine,
        registry,
        dependencies.paths,
        JobClock(api.clock, time.monotonic),
        resources=resources_fixture(registry),
        storage=None,
    )
    work = ExecutionWork(record, ExecutionMode.FRESH, None, claim=claim_fixture(record, execution))
    result = execute_job(
        work, execution, ExecutionSignals(Event(), Event(), ExecutionMonitor([], None, Lock()))
    )
    assert result is not None
    return result


def preview_job(
    api: ApiCase,
    dependencies: NavWriteDependencies,
    fake: FakeNavigation,
    *,
    operation: str = "link",
    execute: bool = True,
    **changes: object,
) -> str:
    """通过真实接口提交并可选执行创建预览，返回文本编号。"""
    from navwrite_support import dataset_id_of

    target = dependencies.rescan.roots[0].path / "api-target"
    target.mkdir(exist_ok=True)
    body: dict[str, object] = {
        "link": {"name": "新增链接", "target_path": str(target), "fallback_format": "mcap"}
    }
    if operation == "link":
        body["dataset_id"] = dataset_id_of(fake, "EgoProDemo")
        path = "/api/datasets/link-previews"
    else:
        body.update(dataset_name="接口新数据集", data_origin="开源下载")
        path = "/api/datasets/creation-previews"
    body.update(changes)
    response = api.client.post(path, json=body)
    assert response.status_code == 201, response.text
    identifier = str(response.json()["job_id"])
    if execute:
        result = run_queued(api, dependencies, identifier)
        assert result.summary is not None and not result.summary.aborted
    return identifier
