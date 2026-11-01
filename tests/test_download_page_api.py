"""下载页面经真实应用提交作业的关键契约；仅使用临时状态目录。"""

from datetime import UTC, datetime
from pathlib import Path
from typing import cast
from unittest.mock import Mock, patch

from account_api_support import ApiCase, add_actor
from jobs_api_support import job_api_case
from pytest import LogCaptureFixture
from sqlalchemy import select

from rdp.audit.models import OperationLogRow
from rdp.infra.config import PlatformConfig, StorageConfig, StorageRootConfig
from rdp.infra.db.connection import session_scope
from rdp.infra.storage import MountInspector, StorageAccessChecker
from rdp.jobs.downloads.cleanup import DeleteParameters
from rdp.jobs.downloads.job import DownloadDependencies, DownloadParameters, request_from_parameters
from rdp.jobs.downloads.plan import (
    Capacity,
    DatasetPreview,
    DownloadPlan,
    HttpTransport,
    HubFile,
    PlanDependencies,
    RepositoryRevision,
)
from rdp.jobs.execution import ExecutionContext, ExecutionMode
from rdp.jobs.logs import JobLog
from rdp.jobs.processes import ToolCommand
from rdp.jobs.progress import ProgressReporter
from rdp.jobs.records import StateChange, transition_job
from rdp.jobs.registry import JobDefinition, production_registry
from rdp.jobs.types import JobClock, JobState


def test_submit_download(tmp_path: Path) -> None:
    """成员提交下载后排队，且不在 Web 进程访问存储根。"""
    with job_api_case(tmp_path) as case:
        case.login()
        response = case.client.post(
            "/api/jobs/download",
            json={
                "repo_type": "dataset",
                "repo_id": "lerobot/pusht",
                "revision": "main",
                "storage_root": "test",
            },
        )
        assert response.status_code == 201, response.text
        assert response.json()["type_name"] == "download"
        assert response.json()["state"] == "queued"


def test_download_adjustment(tmp_path: Path) -> None:
    """运行中的下载作业可提交并读取并发和限速调整。"""
    from rdp.infra.db.connection import session_scope
    from rdp.jobs.downloads.adjustments import SqlAdjustmentChannel
    from rdp.jobs.downloads.job import DownloadAdjustment
    from rdp.jobs.records import StateChange, transition_job
    from rdp.jobs.types import JobState

    with job_api_case(tmp_path) as case:
        case.login()
        response = case.client.post(
            "/api/jobs/download",
            json={
                "repo_type": "dataset",
                "repo_id": "lerobot/pusht",
                "revision": "main",
                "storage_root": "test",
            },
        )
        job_id = int(response.json()["job_id"])
        with session_scope(case.engine) as session:
            transition_job(
                session,
                job_id,
                StateChange(
                    JobState.QUEUED,
                    JobState.RUNNING,
                    case.clock.value,
                    log_path="logs/download/test.log",
                ),
            )
        channel = SqlAdjustmentChannel(case.engine)
        channel.initialize(
            job_id,
            DownloadAdjustment(
                max_concurrent_downloads=4, max_overall_download_limit_bytes_per_s=0
            ),
        )
        response = case.client.post(
            f"/api/jobs/{job_id}/download-adjustment",
            json={"max_concurrent_downloads": 6, "max_overall_download_limit_bytes_per_s": 1024},
        )
        assert response.status_code == 200, response.text
        assert response.json()["requested_version"] == 1
        assert response.json()["requested"]["max_concurrent_downloads"] == 6
        assert (
            case.client.get(f"/api/jobs/{job_id}/download-adjustment").json()["effective"][
                "max_concurrent_downloads"
            ]
            == 4
        )


def test_token_admin_only_and_never_echoed(tmp_path: Path, caplog: LogCaptureFixture) -> None:
    """只有管理员能设清 token；响应及操作日志不含 token 明文。"""
    from account_api_support import add_actor
    from sqlalchemy import select

    from rdp.audit.models import OperationLogRow
    from rdp.infra.db.connection import session_scope

    secret = "hf_ConfidentialSecretExample"  # noqa: S105  # 测试使用虚构凭据。
    with job_api_case(tmp_path) as case:
        member = add_actor(case)
        headers = {"Cookie": "rdp_session=" + member.token.get_secret_value()}
        assert (
            case.client.put(
                "/api/downloads/token", json={"token": secret}, headers=headers
            ).status_code
            == 403
        )
        case.login()
        response = case.client.put("/api/downloads/token", json={"token": secret})
        assert response.status_code == 200 and secret not in response.text
        token_path = tmp_path / "hf_token"
        assert token_path.read_text() == secret
        assert token_path.stat().st_mode & 0o777 == 0o600
        # 不可用于 HTTP 头的输入不得覆盖现有 token，也不能回显敏感原文。
        invalid = case.client.put("/api/downloads/token", json={"token": secret + "\n"})
        assert invalid.status_code == 422 and secret not in invalid.text
        assert token_path.read_text() == secret
        response = case.client.delete("/api/downloads/token")
        assert response.status_code == 200 and secret not in response.text
        assert not token_path.exists()
        with session_scope(case.engine, read_only=True) as session:
            rows = session.execute(
                select(
                    OperationLogRow.operation, OperationLogRow.object_name, OperationLogRow.details
                )
            ).all()
            assert secret not in repr(rows)
        assert secret not in caplog.text


def test_submit_and_read_preview(tmp_path: Path) -> None:
    """预览提交经过真实应用，worker 使用计划依赖生成结果后页面读取快照。"""
    with job_api_case(tmp_path) as case:
        case.login()
        payload = {
            "repo_type": "dataset",
            "repo_id": "lerobot/pusht",
            "revision": "main",
            "storage_root": "test",
        }
        response = case.client.post("/api/jobs/download-preview", json=payload)
        assert response.status_code == 201, response.text
        assert response.json()["type_name"] == "download_preview"
        job_id = int(response.json()["job_id"])
        parameters = DownloadParameters.model_validate(payload)
        dependencies = cast(DownloadDependencies, Mock(spec=DownloadDependencies))
        object.__setattr__(
            dependencies,
            "plan",
            PlanDependencies(
                PlatformConfig(state_dir=tmp_path),
                cast(StorageAccessChecker, Mock()),
                cast(HttpTransport, Mock()),
                lambda _: None,
                lambda: None,
            ),
        )
        context = ExecutionContext(
            job_id,
            parameters,
            ExecutionMode.FRESH,
            None,
            cast(ProgressReporter, Mock()),
            cast(JobLog, Mock()),
            JobClock(lambda: datetime(2026, 11, 1, tzinfo=UTC), lambda: 1.0),
            _navigation=None,
            gpu_index=None,
            maintenance=None,
            gpu_example_command=None,
            navigation_example_path=None,
        )
        plan = DownloadPlan(
            request_from_parameters(parameters),
            RepositoryRevision("a" * 40, False, False, False),
            (HubFile("meta/info.json", 100, "b" * 40, None),),
            DatasetPreview(1, 10, 30.0, "robot", "v2.1", ("front",)),
            tmp_path / "stage",
            Capacity(100, 10, 90, 5000, 1000),
        )
        definition = production_registry(download_dependencies=dependencies).lookup(
            "download_preview"
        )
        assert definition is not None
        with patch("rdp.jobs.downloads.preview.build_plan", return_value=plan) as build:
            definition.execute(context)
        assert build.call_count == 1
        # 只对成功终态开放结果，防止重跑期间或失败时读到旧快照。
        with session_scope(case.engine) as session:
            transition_job(
                session,
                job_id,
                StateChange(
                    JobState.QUEUED,
                    JobState.RUNNING,
                    case.clock.value,
                    log_path="logs/preview/test.log",
                ),
            )
            transition_job(
                session, job_id, StateChange(JobState.RUNNING, JobState.COMPLETED, case.clock.value)
            )
        result = case.client.get(f"/api/jobs/{job_id}/download-preview")
        assert result.status_code == 200, result.text
        data = result.json()
        assert data["commit"] == "a" * 40 and data["file_count"] == 1
        assert data["dataset"]["cameras"] == ["front"]
        assert data["capacity"]["complete_bytes"] == 10
        assert data["created_at"] == "2026-11-01T00:00:00Z"


def test_staging_list_worker_snapshot(tmp_path: Path) -> None:
    """真实应用提交只读暂存扫描，worker 写数据库后可读取含占用状态的快照。"""
    from sqlalchemy import select

    from rdp.infra.config import StorageConfig, StorageRootConfig
    from rdp.infra.storage import MountInspector
    from rdp.jobs.models import DownloadStagingSnapshotRow

    root_dir = tmp_path / "storage"
    stage = root_dir / "暂存" / "下载" / "dataset" / "org" / "repo@aaaaaaaaaaaa"
    stage.mkdir(parents=True)
    (stage / "data.bin").write_bytes(b"12345")
    with job_api_case(tmp_path / "state") as case:
        case.login()
        download = case.client.post(
            "/api/jobs/download",
            json={
                "repo_type": "dataset",
                "repo_id": "org/repo",
                "revision": "main",
                "storage_root": "disk",
            },
        )
        assert download.status_code == 201
        response = case.client.post("/api/jobs/download-staging-scan", json={})
        assert response.status_code == 201, response.text
        job_id = int(response.json()["job_id"])
        root = StorageRootConfig(
            name="disk", path=root_dir, nfs_export="host:/share", writable=True
        )
        config = PlatformConfig(state_dir=tmp_path / "state", storage_roots=(root,))
        inspector = MountInspector(
            (root,),
            lambda: f"20 1 0:1 / {root_dir} rw - nfs4 host:/share rw\n",
            lambda _: None,
            lambda: datetime.now(UTC),
        )
        checker = StorageAccessChecker(inspector, StorageConfig(), lambda _: None)
        dependencies = cast(DownloadDependencies, Mock(spec=DownloadDependencies))
        object.__setattr__(
            dependencies,
            "plan",
            PlanDependencies(
                config, checker, cast(HttpTransport, Mock()), lambda _: None, lambda: None
            ),
        )
        definition = production_registry(download_dependencies=dependencies).lookup(
            "download_staging_scan"
        )
        assert definition is not None
        context = ExecutionContext(
            job_id,
            definition.parameters_model(),
            ExecutionMode.FRESH,
            None,
            cast(ProgressReporter, Mock()),
            cast(JobLog, Mock()),
            JobClock(lambda: datetime(2026, 11, 1, tzinfo=UTC), lambda: 1.0),
            _navigation=None,
            gpu_index=None,
            maintenance=None,
            gpu_example_command=None,
            navigation_example_path=None,
        )
        definition.execute(context)
        with session_scope(case.engine) as session:
            assert (
                session.scalar(
                    select(DownloadStagingSnapshotRow).where(
                        DownloadStagingSnapshotRow.job_id == job_id
                    )
                )
                is not None
            )
            transition_job(
                session,
                job_id,
                StateChange(
                    JobState.QUEUED,
                    JobState.RUNNING,
                    case.clock.value,
                    log_path="logs/staging/test.log",
                ),
            )
            transition_job(
                session, job_id, StateChange(JobState.RUNNING, JobState.COMPLETED, case.clock.value)
            )
        result = case.client.get(f"/api/jobs/{job_id}/download-staging")
        assert result.status_code == 200, result.text
        data = result.json()
        assert data["created_at"] == "2026-11-01T00:00:00Z"
        assert data["items"][0]["repo_id"] == "org/repo"
        assert data["items"][0]["commit_prefix"] == "aaaaaaaaaaaa"
        assert data["items"][0]["size_bytes"] == 5
        assert data["items"][0]["in_use"] is True


def test_staging_delete_admission(tmp_path: Path) -> None:
    """删除类型经通用作业入口也须管理员；目标下载占用时 409，成员不能重提。"""
    from account_api_support import add_actor
    from sqlalchemy import select

    from rdp.audit.models import OperationLogRow
    from rdp.audit.types import OperationDetails

    registry = production_registry()
    target = {
        "storage_root": "disk",
        "repo_type": "dataset",
        "repo_id": "org/repo",
        "commit_prefix": "aaaaaaaaaaaa",
    }
    envelope = {"type_name": "download_staging_delete", "parameters": target}
    with job_api_case(tmp_path, registry=registry) as case:
        member = add_actor(case)
        member_header = {"Cookie": "rdp_session=" + member.token.get_secret_value()}
        assert (
            case.client.post("/api/jobs", json=envelope, headers=member_header).status_code == 403
        )
        case.login()
        download = case.client.post(
            "/api/jobs/download",
            json={
                "storage_root": "disk",
                "repo_type": "dataset",
                "repo_id": "org/repo",
                "revision": "main",
            },
        )
        assert download.status_code == 201
        assert case.client.post("/api/jobs", json=envelope).status_code == 409
        assert case.client.post("/api/jobs/download-staging-delete", json=target).status_code == 409
        assert case.client.post(f"/api/jobs/{download.json()['job_id']}/cancel").status_code == 200
        accepted = case.client.post("/api/jobs", json=envelope)
        assert accepted.status_code == 201, accepted.text
        job_id = accepted.json()["job_id"]
        assert case.client.post(f"/api/jobs/{job_id}/cancel").status_code == 200
        assert (
            case.client.post(f"/api/jobs/{job_id}/resubmit", headers=member_header).status_code
            == 403
        )
        with session_scope(case.engine, read_only=True) as session:
            event = session.scalar(
                select(OperationLogRow).where(
                    OperationLogRow.operation == "submit_job", OperationLogRow.object_id == job_id
                )
            )
            assert event is not None
            assert (
                OperationDetails.model_validate(event.details).after.job_type
                == "download_staging_delete"
            )


def test_delete_staging_worker(tmp_path: Path) -> None:
    """管理员经真实接口入队后由 worker 删除暂存；只操作临时可写根并记录提交。"""
    root = tmp_path / "storage"
    stage = root / "暂存" / "下载" / "dataset" / "org" / "repo@aaaaaaaaaaaa"
    stage.mkdir(parents=True)
    (stage / "file.bin").write_bytes(b"test")
    target = {
        "storage_root": "disk",
        "repo_type": "dataset",
        "repo_id": "org/repo",
        "commit_prefix": "aaaaaaaaaaaa",
    }
    with job_api_case(tmp_path / "state") as case:
        member = add_actor(case)
        member_headers = {"Cookie": "rdp_session=" + member.token.get_secret_value()}
        assert (
            case.client.post(
                "/api/jobs/download-staging-delete", json=target, headers=member_headers
            ).status_code
            == 403
        )
        case.login()
        response = case.client.post("/api/jobs/download-staging-delete", json=target)
        assert response.status_code == 201, response.text
        job_id = int(response.json()["job_id"])
        root_config = StorageRootConfig(
            name="disk", path=root, nfs_export="host:/share", writable=True
        )
        config = PlatformConfig(state_dir=tmp_path / "state", storage_roots=(root_config,))
        inspector = MountInspector(
            (root_config,),
            lambda: f"20 1 0:1 / {root} rw - nfs4 host:/share rw\n",
            lambda _: None,
            lambda: datetime.now(UTC),
        )
        checker = StorageAccessChecker(inspector, StorageConfig(), lambda _: None)
        dependencies = cast(DownloadDependencies, Mock(spec=DownloadDependencies))
        object.__setattr__(
            dependencies,
            "plan",
            PlanDependencies(
                config, checker, cast(HttpTransport, Mock()), lambda _: None, lambda: None
            ),
        )
        definition = production_registry(download_dependencies=dependencies).lookup(
            "download_staging_delete"
        )
        assert definition is not None
        context = Mock(spec=ExecutionContext)
        context.job_id = job_id
        context.parameters = DeleteParameters.model_validate(target)
        context.reporter = Mock(spec=ProgressReporter)

        codes: list[int] = []

        from functools import partial

        context.run_process.side_effect = partial(_run_cleanup_tool, codes=codes)
        # worker 尚未领取作业时，子进程必须拒绝删除。
        definition.execute(cast(ExecutionContext, context))
        assert codes == [1] and stage.exists()
        with session_scope(case.engine) as session:
            transition_job(
                session,
                job_id,
                StateChange(
                    JobState.QUEUED,
                    JobState.RUNNING,
                    case.clock.value,
                    log_path="logs/cleanup/test.log",
                ),
            )
        job_id = _exercise_cleanup_race(case, definition, context, codes, stage)
        definition.execute(cast(ExecutionContext, context))
        assert codes == [1, 1, 0] and not stage.exists()
        _check_download_child_inherits_lock(tmp_path / "state")
        with session_scope(case.engine, read_only=True) as session:
            assert (
                session.scalar(
                    select(OperationLogRow).where(
                        OperationLogRow.operation == "submit_job",
                        OperationLogRow.object_id == str(job_id),
                    )
                )
                is not None
            )


def _exercise_cleanup_race(
    case: ApiCase,
    definition: JobDefinition,
    context: Mock,
    codes: list[int],
    stage: Path,
) -> int:
    """清理排队后有新下载时，执行侧不得按旧快照删除；重新申请才能执行。"""
    old_id = context.job_id
    download = case.client.post(
        "/api/jobs/download",
        json={
            "storage_root": "disk",
            "repo_type": "dataset",
            "repo_id": "org/repo",
            "revision": "main",
        },
    )
    assert download.status_code == 201
    definition.execute(cast(ExecutionContext, context))
    assert codes == [1, 1] and stage.exists()
    assert case.client.post(f"/api/jobs/{download.json()['job_id']}/cancel").status_code == 200
    assert case.client.post(f"/api/jobs/{old_id}/cancel").status_code == 200
    with session_scope(case.engine) as session:
        transition_job(
            session, old_id, StateChange(JobState.CANCELLING, JobState.CANCELLED, case.clock.value)
        )
    target = cast(DeleteParameters, context.parameters).model_dump(mode="json")
    accepted = case.client.post("/api/jobs/download-staging-delete", json=target)
    assert accepted.status_code == 201, accepted.text
    job_id = int(accepted.json()["job_id"])
    context.job_id = job_id
    with session_scope(case.engine) as session:
        transition_job(
            session,
            job_id,
            StateChange(
                JobState.QUEUED,
                JobState.RUNNING,
                case.clock.value,
                log_path="logs/cleanup/retry.log",
            ),
        )
    return job_id


def _run_cleanup_tool(command: ToolCommand, *, codes: list[int]) -> int:
    """运行真实本机删除子进程，测试只使用临时目录。"""
    import subprocess

    result = subprocess.run(command.argv, cwd=command.cwd, timeout=10, check=False)  # noqa: S603  # 登记命令与临时目录均由测试构造。
    codes.append(result.returncode)
    return result.returncode


def _check_download_child_inherits_lock(state: Path) -> None:
    """真实下载工具存活时，父执行段结束也不能让清理取得锁。"""
    import fcntl
    import os
    import sys
    import time

    import pytest

    from rdp.jobs.downloads.coordination import download_guard, open_lock
    from rdp.jobs.processes import ManagedExternalProcess

    reporter = cast(ProgressReporter, Mock(spec=ProgressReporter))
    context = cast(ExecutionContext, Mock(spec=ExecutionContext))
    object.__setattr__(context, "reporter", reporter)
    command = ToolCommand(
        "锁测试", (sys.executable, "-c", "import time; time.sleep(30)"), state, 10
    )
    process = ManagedExternalProcess(
        command, reporter, cast(JobLog, Mock()), JobClock(lambda: datetime.now(UTC), time.monotonic)
    )
    try:
        with download_guard(state, context):
            process.start()
        # 父描述符已关闭，只有真实子进程继承了协调锁。
        fd = open_lock(state)
        try:
            with pytest.raises(BlockingIOError):
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        finally:
            os.close(fd)
    finally:
        process.stop()


def test_token_changes_are_audited_without_secret(tmp_path: Path) -> None:
    """设置和清除各有一条审计，只记录动作、操作人与时间，绝无 token 原文。"""
    from sqlalchemy import select

    from rdp.audit.models import OperationLogRow

    value = "hf_AuditExampleTokenOnly"  # 测试用虚构凭据。
    with job_api_case(tmp_path) as case:
        login = case.login()
        actor_id = int(login.json()["account_id"])
        assert case.client.put("/api/downloads/token", json={"token": value}).status_code == 200
        assert case.client.delete("/api/downloads/token").status_code == 200
        with session_scope(case.engine, read_only=True) as session:
            events = session.scalars(
                select(OperationLogRow)
                .where(
                    OperationLogRow.operation.in_(("set_download_token", "clear_download_token"))
                )
                .order_by(OperationLogRow.log_id)
            ).all()
            assert [item.operation for item in events] == [
                "set_download_token",
                "clear_download_token",
            ]
            assert all(
                item.actor_id == actor_id and item.occurred_at == case.clock.value
                for item in events
            )
            assert all(item.source_ip is None and item.request_id is None for item in events)
            assert all(item.details == {"version": 1, "before": {}, "after": {}} for item in events)
            all_columns = session.execute(select(OperationLogRow.__table__)).all()
            assert value not in repr(all_columns)
        # 既有审计查询仍能解码并按新增类型筛选，不泄露凭据。
        audit = case.client.get("/api/audit/operations", params={"operation": "set_download_token"})
        assert audit.status_code == 200 and value not in audit.text
        assert [item["operation"] for item in audit.json()["items"]] == ["set_download_token"]
