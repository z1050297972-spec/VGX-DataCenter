"""下载作业验收清单；骨架阶段不执行真实下载或外部进程。"""

import hashlib
import http.client
import shutil
import socket
import sys
import threading
import time
from collections.abc import Mapping
from contextlib import suppress
from dataclasses import replace
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Event, Thread
from typing import cast
from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from rdp.infra.config import JobsConfig
from rdp.infra.diagnostics import ExternalError, InputError
from rdp.jobs.downloads._context import bind
from rdp.jobs.downloads.adapters import Aria2Supervisor, HashFileVerifier
from rdp.jobs.downloads.job import (
    MAX_DOWNLOAD_LIMIT_BYTES_PER_S,
    Aria2Rpc,
    DownloadDependencies,
    DownloadParameters,
    TransferStatus,
    resolve_download_url,
    run_download,
)
from rdp.jobs.downloads.plan import Capacity, DownloadPlan, HttpResponse, HubFile
from rdp.jobs.execution import ExecutionContext
from rdp.jobs.types import JobClock


def _case(tmp_path: Path, *, filenames: tuple[str, ...] = ("small.bin",)) -> tuple[object, ...]:
    """构造全部 IO 可替换的下载执行环境，所有路径位于临时目录。"""
    from datetime import UTC, datetime
    from typing import cast
    from unittest.mock import Mock

    from rdp.infra.config import PlatformConfig, StorageRootConfig
    from rdp.infra.storage import StorageAccessChecker
    from rdp.jobs.downloads.job import (
        DownloadAdjustment,
        DownloadDependencies,
        DownloadStatus,
        TransferStatus,
    )
    from rdp.jobs.downloads.plan import (
        Capacity,
        DownloadPlan,
        DownloadRequest,
        HttpResponse,
        HubFile,
        PlanDependencies,
        RepositoryRevision,
    )
    from rdp.jobs.execution import ExecutionContext
    from rdp.jobs.logs import JobLog
    from rdp.jobs.progress import ProgressReporter
    from rdp.jobs.types import ExecutionMode, JobClock

    request = DownloadRequest("dataset", "org/repo", "main", "disk")
    files = tuple(HubFile(name, 3, "0" * 40, None) for name in filenames)
    total = 3 * len(files)
    plan = DownloadPlan(
        request,
        RepositoryRevision("a" * 40, False, False, False),
        files,
        None,
        tmp_path / "stage",
        Capacity(total, 0, total, 100, 0),
    )
    params = DownloadParameters(
        repo_type="dataset", repo_id="org/repo", revision="main", storage_root="disk"
    )
    reporter = Mock(spec=ProgressReporter)
    context = ExecutionContext(
        1,
        params,
        ExecutionMode.FRESH,
        None,
        reporter,
        cast(JobLog, Mock()),
        JobClock(lambda: datetime.now(UTC), lambda: 1.0),
        _navigation=None,
        gpu_index=None,
        maintenance=None,
        gpu_example_command=None,
        navigation_example_path=None,
    )
    mirror = Mock()
    mirror.request.return_value = HttpResponse(200, {}, b"x")
    plan_deps = PlanDependencies(
        PlatformConfig(
            state_dir=tmp_path / "state",
            storage_roots=(
                StorageRootConfig(
                    name="disk", path=tmp_path, nfs_export="host:/share", writable=True
                ),
            ),
        ),
        cast(StorageAccessChecker, Mock()),
        mirror,
        lambda _: None,
        lambda: None,
    )
    process, rpc, curl, verifier, channel = Mock(), Mock(), Mock(), Mock(), Mock()
    process.start.return_value = rpc
    rpc.add_file.return_value = "gid"
    rpc.status.return_value = TransferStatus("gid", "complete", 3, 0)
    verifier.verify.return_value = True
    channel.pending.return_value = None
    initial = DownloadAdjustment(
        max_concurrent_downloads=4, max_overall_download_limit_bytes_per_s=0
    )
    channel.read.return_value = DownloadStatus(0, 0, initial, initial, 0, len(files), 0, 0, 0)
    dependencies = DownloadDependencies(plan_deps, mirror, Mock(), process, curl, verifier, channel)
    return context, plan, dependencies, reporter, process, rpc, curl, verifier, mirror, channel


def test_isolated_fakes(tmp_path: Path) -> None:
    """验证 aria2 RPC 与文件校验使用替身，下载成功时不调用 curl。"""
    from typing import cast
    from unittest.mock import Mock

    from rdp.jobs.downloads.job import DownloadDependencies, run_download
    from rdp.jobs.downloads.plan import DownloadPlan
    from rdp.jobs.execution import ExecutionContext

    context, plan, dependencies, reporter, _, rpc, curl, verifier, _, _ = _case(tmp_path)
    run_download(
        cast(ExecutionContext, context),
        cast(DownloadPlan, plan),
        cast(DownloadDependencies, dependencies),
    )
    cast(Mock, rpc).add_file.assert_called_once()
    cast(Mock, verifier).verify.assert_called_once()
    cast(Mock, curl).download.assert_not_called()
    assert cast(Mock, reporter).report.call_args.args[0].total_items == 1


def test_mirror_308(tmp_path: Path) -> None:
    """验证镜像返回 308 到官方站时作业在启动 aria2 之前失败并给出处理建议。"""
    from dataclasses import replace
    from typing import cast
    from unittest.mock import Mock

    from rdp.infra.config import PlatformConfig, StorageRootConfig
    from rdp.infra.diagnostics import ExternalError
    from rdp.jobs.downloads.job import DownloadDependencies, DownloadExecutor
    from rdp.jobs.downloads.plan import HttpResponse
    from rdp.jobs.execution import ExecutionContext

    context, _, dependencies, _, process, _, _, _, mirror, _ = _case(tmp_path)
    deps = cast(DownloadDependencies, dependencies)
    root = StorageRootConfig(
        name="disk", path=tmp_path / "data", nfs_export="host:/share", writable=True
    )
    config = PlatformConfig(state_dir=tmp_path / "state", storage_roots=(root,))
    checker = deps.plan.checker
    cast(Mock, checker).mounts.roots = (root,)
    deps = replace(deps, plan=replace(deps.plan, config=config))
    cast(Mock, mirror).request.return_value = HttpResponse(
        308, {"Location": "https://huggingface.co"}, b""
    )
    with pytest.raises(ExternalError) as caught:
        DownloadExecutor(deps).execute(cast(ExecutionContext, context))
    assert "镜像不生效" in caught.value.diagnostics[0].actual
    assert caught.value.diagnostics[0].next_step
    cast(Mock, process).start.assert_not_called()


def test_aria_redirect(tmp_path: Path) -> None:
    """验证文件预解析遇官方站时不添加 aria2，记失败条目并报告镜像不生效。"""
    from typing import cast
    from unittest.mock import Mock

    from rdp.jobs.downloads.job import DownloadDependencies, run_download
    from rdp.jobs.downloads.plan import DownloadPlan, HttpResponse
    from rdp.jobs.execution import ExecutionContext

    context, plan, dependencies, reporter, _, rpc, curl, _, mirror, _ = _case(tmp_path)
    cast(Mock, mirror).request.return_value = HttpResponse(
        302, {"Location": "https://huggingface.co/file"}, b""
    )
    run_download(
        cast(ExecutionContext, context),
        cast(DownloadPlan, plan),
        cast(DownloadDependencies, dependencies),
    )
    cast(Mock, rpc).add_file.assert_not_called()
    cast(Mock, curl).download.assert_not_called()
    progress = cast(Mock, reporter).report.call_args.args[0]
    assert progress.failed_items == 1 and progress.total_items == 1
    diagnostic = cast(Mock, reporter).diagnostic.call_args.args[0]
    assert "镜像不生效" in diagnostic.actual


def test_curl_redirect(tmp_path: Path) -> None:
    """验证 curl 实际响应若跳往官方站，拒绝跟随并恢复已有部分文件。"""
    from unittest.mock import Mock

    from rdp.infra.diagnostics import InputError
    from rdp.jobs.downloads.adapters import CurlDownloader
    from rdp.jobs.downloads.plan import HttpResponse

    mirror = Mock()
    mirror.request.return_value = HttpResponse(200, {}, b"x")
    calls: list[tuple[str, ...]] = []
    target = tmp_path / "partial"
    target.write_bytes(b"abc")

    def run(argv: tuple[str, ...], config: bytes) -> HttpResponse:
        calls.append(argv)
        with target.open("ab") as stream:
            stream.write(b"redirect body")
        return HttpResponse(302, {"Location": "https://huggingface.co/secret"}, b"")

    adapter = CurlDownloader(Path("/usr/bin/curl"), mirror, Mock(), run=run)
    parameters = DownloadParameters(
        repo_type="dataset", repo_id="a/b", revision="main", storage_root="disk"
    )
    with pytest.raises(InputError):
        adapter.download("https://hf-mirror.com/resolve/a", target, None, parameters)
    assert target.read_bytes() == b"abc" and len(calls) == 1
    assert all("huggingface.co" not in arg for arg in calls[0])


def _aria_command(
    tmp_path: Path, params: DownloadParameters, monkeypatch: pytest.MonkeyPatch
) -> tuple[str, ...]:
    """替换进程和 RPC 边界，观察真实 supervisor 生成的 argv。"""
    from unittest.mock import MagicMock

    import rdp.jobs.downloads.adapters as adapters
    from rdp.infra.config import JobsConfig
    from rdp.jobs.downloads._context import bind
    from rdp.jobs.execution import ExecutionContext
    from rdp.jobs.processes import ToolCommand

    raw_context, *_ = _case(tmp_path)
    context = cast(ExecutionContext, raw_context)
    commands: list[tuple[str, ...]] = []
    process = Mock()
    process.running.return_value = True

    def launch(command: ToolCommand, *_args: object, **_kwargs: object) -> Mock:
        commands.append(command.argv)
        return process

    probe = MagicMock()
    probe.__enter__.return_value = probe
    probe.getsockname.return_value = ("127.0.0.1", 32123)
    monkeypatch.setattr(adapters, "ManagedExternalProcess", launch)

    def fake_rpc(*_args: object) -> Mock:
        return Mock(return_value="ok")

    def fake_socket(*_args: object, **_kwargs: object) -> MagicMock:
        return probe

    monkeypatch.setattr(adapters, "_LocalRpc", fake_rpc)
    monkeypatch.setattr(adapters.socket, "socket", fake_socket)
    supervisor = adapters.Aria2Supervisor(JobsConfig(aria2c_path=sys.executable), tmp_path)
    try:
        with bind(context):
            supervisor.start(params)
    finally:
        supervisor.terminate()
    return commands[0]


def test_secret_redaction(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """验证 token 不出现在 aria2/curl 命令行、作业参数、日志或诊断。"""
    from collections.abc import Sequence
    from unittest.mock import Mock

    from rdp.infra.diagnostics import ExternalError
    from rdp.jobs.downloads.adapters import Aria2JsonRpc, CurlDownloader
    from rdp.jobs.downloads.plan import HttpResponse, HubFile

    secret = "private-" + "token-test"
    params = DownloadParameters(
        repo_type="dataset", repo_id="a/b", revision="main", storage_root="disk"
    )
    assert secret not in params.model_dump_json()
    with pytest.raises(ValidationError) as validation:
        DownloadParameters.model_validate({**params.model_dump(), "token": secret})
    assert secret not in str(validation.value)
    mirror = Mock()
    mirror.request.return_value = HttpResponse(200, {}, b"x")
    commands: list[tuple[str, ...]] = []

    def run(argv: tuple[str, ...], data: bytes) -> HttpResponse:
        commands.append(argv)
        assert secret.encode() in data
        return HttpResponse(206, {}, b"")

    CurlDownloader(Path("/usr/bin/curl"), mirror, Mock(), run=run).download(
        "https://hf-mirror.com/resolve/a", tmp_path / "file", secret, params
    )
    assert all(secret not in arg for command in commands for arg in command)
    assert all(secret not in arg for arg in _aria_command(tmp_path, params, monkeypatch))

    def reject(_method: str, _args: Sequence[object]) -> object:
        return None

    with pytest.raises(ExternalError) as error:
        Aria2JsonRpc(reject).add_file(
            "https://huggingface.co/file", tmp_path / "x", HubFile("x", 1, "0" * 40, None), secret
        )
    assert secret not in str(error.value) and secret not in repr(error.value.diagnostics)
    assert secret not in caplog.text


@pytest.mark.parametrize("interruption", ["cancel", "crash"])
def test_cancel_resume(tmp_path: Path, interruption: str) -> None:
    """验证取消或 worker 中断后保留暂存，重新执行跳过已完成文件。"""
    from dataclasses import replace
    from typing import cast
    from unittest.mock import Mock

    from rdp.infra.diagnostics import Diagnostic, DiagnosticCategory, DiagnosticLevel
    from rdp.jobs.downloads.job import DownloadDependencies, run_download
    from rdp.jobs.downloads.plan import DownloadPlan
    from rdp.jobs.errors import JobCancelledError, WorkerStoppingError
    from rdp.jobs.execution import ExecutionContext
    from rdp.jobs.types import ExecutionMode

    raw_context, raw_plan, raw_deps, raw_reporter, raw_process, raw_rpc, _, _, _, _ = _case(
        tmp_path, filenames=("first", "second")
    )
    context, plan, deps = (
        cast(ExecutionContext, raw_context),
        cast(DownloadPlan, raw_plan),
        cast(DownloadDependencies, raw_deps),
    )
    reporter, process, rpc = cast(Mock, raw_reporter), cast(Mock, raw_process), cast(Mock, raw_rpc)
    diagnostic = Diagnostic(
        level=DiagnosticLevel.ERROR,
        category=DiagnosticCategory.CONFLICT,
        stage="下载",
        source="平台",
        objects=(),
        rule="download.stopped",
        actual="停止",
        expected="继续",
        consequence="保留暂存",
        next_step="重新执行",
    )
    signal = (
        JobCancelledError((diagnostic,))
        if interruption == "cancel"
        else WorkerStoppingError((diagnostic,))
    )

    def add_file(_url: str, target: Path, _file: object, _token: str | None) -> str:
        if target.name == "first":
            target.write_bytes(b"abc")
        return target.name

    rpc.add_file.side_effect = add_file

    def complete(gid: str) -> TransferStatus:
        return TransferStatus(gid, "complete", 3, 0)

    rpc.status.side_effect = complete
    reporter.report.side_effect = signal
    with pytest.raises(type(signal)):
        run_download(context, plan, deps)
    assert (plan.staging_dir / "first").read_bytes() == b"abc"
    process.terminate.assert_called_once()
    previous = reporter.report.call_args.args[0]
    reporter.report.side_effect = None
    rpc.add_file.reset_mock()
    context = (
        replace(context, mode=ExecutionMode.RESUME, previous_progress=previous)
        if interruption == "crash"
        else replace(context, job_id=2)
    )
    run_download(context, plan, deps)
    assert rpc.add_file.call_count == 1
    assert rpc.add_file.call_args.args[1].name == "second"
    progress = reporter.report.call_args.args[0]
    assert progress.total_items == 2 and progress.failed_items == 0


def test_live_options(tmp_path: Path) -> None:
    """验证下载轮询时把待生效并发和限速传到 RPC，成功后确认版本。"""
    from typing import cast
    from unittest.mock import Mock

    from rdp.jobs.downloads.job import (
        DownloadAdjustment,
        DownloadDependencies,
        TransferStatus,
        run_download,
    )
    from rdp.jobs.downloads.plan import DownloadPlan
    from rdp.jobs.execution import ExecutionContext

    context, plan, dependencies, _, _, rpc, _, _, _, channel = _case(tmp_path)
    adjustment = DownloadAdjustment(
        max_concurrent_downloads=2, max_overall_download_limit_bytes_per_s=2048
    )
    cast(Mock, channel).pending.side_effect = [(1, adjustment), None, None]
    cast(Mock, rpc).status.side_effect = [
        TransferStatus("gid", "active", 1, 12),
        TransferStatus("gid", "complete", 3, 0),
    ]
    run_download(
        cast(ExecutionContext, context),
        cast(DownloadPlan, plan),
        cast(DownloadDependencies, dependencies),
    )
    cast(Mock, rpc).change_global_options.assert_called_once_with(adjustment)
    cast(Mock, channel).acknowledge.assert_called_once_with(1, 1, adjustment)


def test_outcome_success(tmp_path: Path) -> None:
    """验证全部文件成功时累计成功条目，不把每个文件误当独立作业。"""
    from typing import cast
    from unittest.mock import Mock

    from rdp.jobs.downloads.job import DownloadDependencies, run_download
    from rdp.jobs.downloads.plan import DownloadPlan
    from rdp.jobs.execution import ExecutionContext
    from rdp.jobs.outcome import JobOutcome, calculate_outcome

    context, plan, dependencies, reporter, _, _, _, _, _, _ = _case(tmp_path, filenames=("a", "b"))
    run_download(
        cast(ExecutionContext, context),
        cast(DownloadPlan, plan),
        cast(DownloadDependencies, dependencies),
    )
    progress = cast(Mock, reporter).report.call_args.args[0]
    assert (progress.done, progress.total, progress.total_items, progress.failed_items) == (
        6,
        6,
        2,
        0,
    )
    assert (
        calculate_outcome(
            total_items=progress.total_items,
            failed_items=progress.failed_items,
            warning_count=progress.warning_count,
            aborted=False,
        )
        is JobOutcome.SUCCEEDED
    )


def test_outcome_skipped(tmp_path: Path) -> None:
    """验证已完成文件校验通过后跳过，同时被计入成功的条目总数。"""
    from typing import cast
    from unittest.mock import Mock

    from rdp.jobs.downloads.job import DownloadDependencies, run_download
    from rdp.jobs.downloads.plan import DownloadPlan
    from rdp.jobs.execution import ExecutionContext

    context, raw_plan, dependencies, reporter, _, rpc, _, _, _, _ = _case(
        tmp_path, filenames=("a", "b")
    )
    plan = cast(DownloadPlan, raw_plan)
    plan.staging_dir.mkdir()
    (plan.staging_dir / "a").write_bytes(b"abc")
    run_download(cast(ExecutionContext, context), plan, cast(DownloadDependencies, dependencies))
    cast(Mock, rpc).add_file.assert_called_once()
    progress = cast(Mock, reporter).report.call_args.args[0]
    assert progress.done == 6 and progress.total_items == 2 and progress.failed_items == 0


def test_outcome_partial(tmp_path: Path) -> None:
    """验证一个文件下载失败、另一个成功时计算部分成功。"""
    from typing import cast
    from unittest.mock import Mock

    from rdp.infra.diagnostics import Diagnostic, DiagnosticCategory, DiagnosticLevel, ExternalError
    from rdp.jobs.downloads.job import DownloadDependencies, TransferStatus, run_download
    from rdp.jobs.downloads.plan import DownloadPlan
    from rdp.jobs.execution import ExecutionContext
    from rdp.jobs.outcome import JobOutcome, calculate_outcome

    context, plan, dependencies, reporter, _, rpc, curl, _, _, _ = _case(
        tmp_path, filenames=("a", "b")
    )
    cast(Mock, rpc).status.side_effect = [
        TransferStatus("gid", "complete", 3, 0),
        TransferStatus("gid", "error", 0, 0),
    ]
    cast(Mock, curl).download.side_effect = ExternalError(
        (
            Diagnostic(
                level=DiagnosticLevel.ERROR,
                category=DiagnosticCategory.EXTERNAL,
                stage="下载",
                source="平台",
                objects=(),
                rule="download.test",
                actual="失败",
                expected="成功",
                consequence="失败",
                next_step="重试",
            ),
        )
    )
    run_download(
        cast(ExecutionContext, context),
        cast(DownloadPlan, plan),
        cast(DownloadDependencies, dependencies),
    )
    progress = cast(Mock, reporter).report.call_args.args[0]
    assert (progress.total_items, progress.failed_items) == (2, 1)
    assert (
        calculate_outcome(total_items=2, failed_items=1, warning_count=0, aborted=False)
        is JobOutcome.PARTIALLY_SUCCEEDED
    )


def test_outcome_failure(tmp_path: Path) -> None:
    """验证所有文件失败时 M0 计算失败结果。"""
    from typing import cast
    from unittest.mock import Mock

    from rdp.infra.diagnostics import Diagnostic, DiagnosticCategory, DiagnosticLevel, ExternalError
    from rdp.jobs.downloads.job import DownloadDependencies, TransferStatus, run_download
    from rdp.jobs.downloads.plan import DownloadPlan
    from rdp.jobs.execution import ExecutionContext
    from rdp.jobs.outcome import JobOutcome, calculate_outcome

    context, plan, dependencies, reporter, _, rpc, curl, _, _, _ = _case(
        tmp_path, filenames=("a", "b")
    )
    cast(Mock, rpc).status.return_value = TransferStatus("gid", "error", 0, 0)
    cast(Mock, curl).download.side_effect = ExternalError(
        (
            Diagnostic(
                level=DiagnosticLevel.ERROR,
                category=DiagnosticCategory.EXTERNAL,
                stage="下载",
                source="平台",
                objects=(),
                rule="download.test",
                actual="失败",
                expected="成功",
                consequence="失败",
                next_step="重试",
            ),
        )
    )
    run_download(
        cast(ExecutionContext, context),
        cast(DownloadPlan, plan),
        cast(DownloadDependencies, dependencies),
    )
    progress = cast(Mock, reporter).report.call_args.args[0]
    assert (progress.total_items, progress.failed_items) == (2, 2)
    assert (
        calculate_outcome(total_items=2, failed_items=2, warning_count=0, aborted=False)
        is JobOutcome.FAILED
    )


def test_parameter_bounds() -> None:
    """验证所有 aria2 参数的默认值和范围校验。"""
    required = {
        "repo_type": "dataset",
        "repo_id": "a/b",
        "revision": "main",
        "storage_root": "root",
    }
    params = DownloadParameters.model_validate(required)
    assert (params.max_concurrent_downloads, params.max_connection_per_server, params.split) == (
        4,
        4,
        4,
    )
    assert (
        params.min_split_size_bytes,
        params.max_overall_download_limit_bytes_per_s,
        params.max_tries,
        params.retry_wait_s,
    ) == (20 * 1024**2, 0, 5, 10)
    limits = {
        "max_concurrent_downloads": (1, 16),
        "max_connection_per_server": (1, 16),
        "split": (1, 16),
        "min_split_size_bytes": (1024**2, 1024**3),
        "max_tries": (1, 20),
        "retry_wait_s": (0, 600),
        "max_overall_download_limit_bytes_per_s": (1024, MAX_DOWNLOAD_LIMIT_BYTES_PER_S),
    }
    for field, (lower, upper) in limits.items():
        for value in (lower, upper):
            assert (
                getattr(DownloadParameters.model_validate({**required, field: value}), field)
                == value
            )
        for value in (upper + 1, False):
            with pytest.raises(ValidationError):
                DownloadParameters.model_validate({**required, field: value})
        if lower > 1:
            with pytest.raises(ValidationError):
                DownloadParameters.model_validate({**required, field: lower - 1})


def test_no_token() -> None:
    """验证作业参数拒绝 token 和未知字段。"""
    required = {
        "repo_type": "dataset",
        "repo_id": "a/b",
        "revision": "main",
        "storage_root": "root",
    }
    for forbidden in ("token", "unknown"):
        with pytest.raises(ValidationError) as error:
            DownloadParameters.model_validate({**required, forbidden: "secret-example"})
        assert "secret-example" not in str(error.value)


def test_lfs_verify(tmp_path: Path) -> None:
    """验证 LFS 文件必须同时匹配实际大小和 SHA-256。"""
    from rdp.jobs.downloads.adapters import HashFileVerifier
    from rdp.jobs.downloads.plan import HubFile

    target = tmp_path / "part.bin"
    target.write_bytes(b"abc")
    file = HubFile(
        "part.bin", 3, "0" * 40, "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    )
    assert HashFileVerifier().verify(target, file)
    target.write_bytes(b"xyz")
    assert not HashFileVerifier().verify(target, file)
    target.write_bytes(b"abcd")
    assert not HashFileVerifier().verify(target, file)


def test_blob_verify(tmp_path: Path) -> None:
    """验证非 LFS 文件校验大小和包含 blob 头的 git SHA-1。"""
    from rdp.jobs.downloads.adapters import HashFileVerifier
    from rdp.jobs.downloads.plan import HubFile

    target = tmp_path / "small.txt"
    target.write_bytes(b"hello\n")
    file = HubFile("small.txt", 6, "ce013625030ba8dba906f756967f9e9ca394464a", None)
    assert HashFileVerifier().verify(target, file)
    target.write_bytes(b"hello!")
    assert not HashFileVerifier().verify(target, file)


def test_cache_invalidation(tmp_path: Path) -> None:
    """验证缓存仅在大小、哈希与文件身份全匹配时有效，文件变化后失效。"""
    import json

    from rdp.jobs.downloads.job import cached_file_is_valid
    from rdp.jobs.downloads.plan import HubFile

    target = tmp_path / "weights.bin"
    target.write_bytes(b"abc")
    file = HubFile("weights.bin", 3, "0123456789abcdef0123456789abcdef01234567", None)
    stat = target.stat()
    manifest = tmp_path / ".rdp-verified-v1.json"
    manifest.write_text(
        json.dumps(
            {
                "version": 1,
                "entries": {
                    "weights.bin": {
                        "algorithm": "git-blob-sha1",
                        "digest": file.blob_sha1,
                        "size": 3,
                        "dev": stat.st_dev,
                        "ino": stat.st_ino,
                        "mtime_ns": stat.st_mtime_ns,
                        "ctime_ns": stat.st_ctime_ns,
                    }
                },
            }
        )
    )
    assert cached_file_is_valid(target, file, manifest)
    target.write_bytes(b"xyz")
    assert not cached_file_is_valid(target, file, manifest)


def test_progress(tmp_path: Path) -> None:
    """验证活动字节、速度与总文件数经现有进度及下载快照上报。"""
    from dataclasses import replace
    from datetime import UTC, datetime
    from typing import cast
    from unittest.mock import Mock

    from rdp.jobs.downloads.job import DownloadDependencies, TransferStatus, run_download
    from rdp.jobs.downloads.plan import DownloadPlan
    from rdp.jobs.execution import ExecutionContext
    from rdp.jobs.types import JobClock

    raw_context, plan, dependencies, reporter, _, rpc, _, _, _, channel = _case(tmp_path)
    context = cast(ExecutionContext, raw_context)
    elapsed = iter(float(value) for value in range(100))
    context = replace(context, clock=JobClock(lambda: datetime.now(UTC), lambda: next(elapsed)))
    cast(Mock, rpc).status.side_effect = [
        TransferStatus("gid", "active", 1, 12),
        TransferStatus("gid", "complete", 3, 0),
    ]
    run_download(context, cast(DownloadPlan, plan), cast(DownloadDependencies, dependencies))
    snapshots = [call.args[1] for call in cast(Mock, channel).report.call_args_list]
    assert any(
        snapshot.speed_bytes_per_s == 12 and snapshot.total_files == 1 for snapshot in snapshots
    )
    assert any(
        call.args[0].done == 1 and call.args[0].total == 3
        for call in cast(Mock, reporter).report.call_args_list
    )
    assert snapshots[-1].completed_files == 1 and snapshots[-1].failed_files == 0


def test_model_rename(tmp_path: Path) -> None:
    """验证模型下载后改名到目标目录，目标已存在时不覆盖且保留暂存。"""
    from dataclasses import replace
    from typing import cast

    from rdp.infra.config import PlatformConfig, StorageRootConfig
    from rdp.infra.diagnostics import InputError
    from rdp.jobs.downloads.job import DownloadDependencies, run_download
    from rdp.jobs.downloads.plan import DownloadPlan
    from rdp.jobs.execution import ExecutionContext

    context, raw_plan, raw_deps, _, _, _, _, _, _, _ = _case(tmp_path)
    plan = cast(DownloadPlan, raw_plan)
    deps = cast(DownloadDependencies, raw_deps)
    root = StorageRootConfig(name="disk", path=tmp_path, nfs_export="host:/share", writable=True)
    deps = replace(
        deps,
        plan=replace(
            deps.plan, config=PlatformConfig(state_dir=tmp_path / "state", storage_roots=(root,))
        ),
    )
    request = replace(plan.request, repo_type="model", target_subdir="weights/model")
    plan = replace(plan, request=request)
    context = replace(
        cast(ExecutionContext, context),
        parameters=DownloadParameters(
            repo_type="model",
            repo_id="org/repo",
            revision="main",
            storage_root="disk",
            target_subdir="weights/model",
        ),
    )
    run_download(context, plan, deps)
    target = tmp_path / "weights/model"
    assert target.is_dir() and not plan.staging_dir.exists()
    (target / "keep").write_text("original")
    with pytest.raises(InputError):
        run_download(context, plan, deps)
    assert (target / "keep").read_text() == "original"


def test_adjustment_race(tmp_path: Path) -> None:
    """验证确认旧版本不会覆盖并发提交的请求，生效值仍反映已应用版本。"""
    from jobs_storage_support import job_database, job_row

    from rdp.infra.db.connection import session_scope
    from rdp.jobs.downloads.adjustments import SqlAdjustmentChannel
    from rdp.jobs.downloads.job import DownloadAdjustment
    from rdp.jobs.models import DownloadAdjustmentRow

    with job_database(tmp_path) as (engine, _):
        with session_scope(engine) as session:
            job = job_row()
            job.type_name = "download"
            session.add(job)
            session.flush()
            session.add(
                DownloadAdjustmentRow(
                    job_id=71,
                    requested_version=0,
                    applied_version=0,
                    requested_concurrency=4,
                    requested_limit_bytes_per_s=0,
                    effective_concurrency=4,
                    effective_limit_bytes_per_s=0,
                )
            )
        channel = SqlAdjustmentChannel(engine)
        first = channel.submit(71, DownloadAdjustment(max_concurrent_downloads=2))
        second = channel.submit(71, DownloadAdjustment(max_overall_download_limit_bytes_per_s=2048))
        channel.acknowledge(
            71,
            first,
            DownloadAdjustment(
                max_concurrent_downloads=2, max_overall_download_limit_bytes_per_s=0
            ),
        )
        assert channel.pending(71) == (
            second,
            DownloadAdjustment(
                max_concurrent_downloads=2, max_overall_download_limit_bytes_per_s=2048
            ),
        )
        snapshot = channel.read(71)
        assert (
            snapshot.applied_version == first and snapshot.effective.max_concurrent_downloads == 2
        )
        assert snapshot.requested.max_overall_download_limit_bytes_per_s == 2048


def test_curl_rate(tmp_path: Path) -> None:
    """验证 curl 使用生效总限速、续传和重试，凭据只经标准输入。"""
    from unittest.mock import Mock

    from rdp.jobs.downloads.adapters import CurlDownloader
    from rdp.jobs.downloads.plan import HttpResponse

    mirror = Mock()
    mirror.request.return_value = HttpResponse(200, {}, b"x")
    redirects = Mock()
    calls: list[tuple[tuple[str, ...], bytes]] = []

    def run(argv: tuple[str, ...], config: bytes) -> HttpResponse:
        calls.append((argv, config))
        return HttpResponse(206, {}, b"")

    adapter = CurlDownloader(Path("/usr/bin/curl"), mirror, redirects, run=run)
    parameters = DownloadParameters(
        repo_type="dataset",
        repo_id="a/b",
        revision="main",
        storage_root="disk",
        max_overall_download_limit_bytes_per_s=2048,
        max_tries=5,
    )
    adapter.download(
        "https://hf-mirror.com/resolve/a", tmp_path / "file", "secret-token", parameters
    )
    argv, config = calls[0]
    assert "--limit-rate" in argv and argv[argv.index("--limit-rate") + 1] == "2048"
    assert "--retry" in argv and argv[argv.index("--retry") + 1] == "5"
    assert argv[argv.index("-C") : argv.index("-C") + 2] == ("-C", "-")
    assert "-L" not in argv and "--location" not in argv
    assert all("secret-token" not in arg for arg in argv)
    assert b"secret-token" in config and argv[argv.index("-K") : argv.index("-K") + 2] == (
        "-K",
        "-",
    )


def test_redirect_token() -> None:
    """验证镜像首跳使用 token，跨域后续跳转只携带 Range。"""
    from rdp.jobs.downloads.job import resolve_download_url
    from rdp.jobs.downloads.plan import HttpResponse

    class Mirror:
        def request(
            self, method: str, url: str, *, headers: Mapping[str, str], timeout_s: float
        ) -> HttpResponse:
            assert method == "GET"
            assert headers == {"Range": "bytes=0-0", "Authorization": "Bearer private-value"}
            return HttpResponse(302, {"Location": "https://cdn.example/part"}, b"")

    class Redirect:
        def request(self, url: str, *, timeout_s: float) -> HttpResponse:
            assert url == "https://cdn.example/part"
            return HttpResponse(206, {}, b"x")

    assert (
        resolve_download_url(
            "https://hf-mirror.com/org/repo/resolve/abc/a", "private-value", Mirror(), Redirect()
        )
        == "https://cdn.example/part"
    )


def test_retry_bound() -> None:
    """验证重定向链最多五跳后失败，不访问第六跳。"""
    from rdp.infra.diagnostics import ExternalError
    from rdp.jobs.downloads.job import resolve_download_url
    from rdp.jobs.downloads.plan import HttpResponse

    class Mirror:
        def request(
            self, method: str, url: str, *, headers: Mapping[str, str], timeout_s: float
        ) -> HttpResponse:
            return HttpResponse(302, {"Location": "https://cdn.example/0"}, b"")

    class Redirect:
        count = 0

        def request(self, url: str, *, timeout_s: float) -> HttpResponse:
            self.count += 1
            return HttpResponse(302, {"Location": f"https://cdn.example/{self.count}"}, b"")

    redirects = Redirect()
    with pytest.raises(ExternalError):
        resolve_download_url("https://hf-mirror.com/resolve/file", None, Mirror(), redirects)
    assert redirects.count == 5


def _local_test_server() -> tuple[
    ThreadingHTTPServer, Thread, bytes, list[tuple[str, str | None]], Event, Event, Event
]:
    """启动只绑定回环地址的 HTTP 服务器并返回可观察状态。"""
    payload = b"abcdefgh01234567" * 16384
    requests: list[tuple[str, str | None]] = []
    interrupted = threading.Event()
    slow_started = threading.Event()
    release_slow = threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:
            return

        def do_GET(self) -> None:
            value = self.headers.get("Range")
            requests.append((self.path, value))
            if self.path == "/redirect":
                self.send_response(302)
                self.send_header("Location", "https://huggingface.co/private")
                self.end_headers()
                return
            start = (
                int(value.split("=", 1)[1].split("-", 1)[0])
                if value and value.startswith("bytes=")
                else 0
            )
            body = payload[start:]
            self.send_response(206 if start else 200)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Accept-Ranges", "bytes")
            if start:
                self.send_header(
                    "Content-Range", f"bytes {start}-{len(payload) - 1}/{len(payload)}"
                )
            self.end_headers()
            if self.path == "/slow":
                self.wfile.write(body[:65536])
                self.wfile.flush()
                slow_started.set()
                release_slow.wait(5)
                return
            if self.path == "/good" and not interrupted.is_set():
                interrupted.set()
                self.wfile.write(body[:65536])
                self.wfile.flush()
                self.connection.shutdown(socket.SHUT_RDWR)
                self.connection.close()
                return
            with suppress(BrokenPipeError, ConnectionResetError):
                self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, payload, requests, interrupted, slow_started, release_slow


def _wait_aria(rpc: Aria2Rpc, gid: str) -> TransferStatus:
    """在有界时间内等待单文件进入终态。"""
    deadline = time.monotonic() + 25
    while True:
        status = rpc.status(gid)
        if status.state in ("complete", "error") or time.monotonic() >= deadline:
            return status
        time.sleep(0.05)


def _exercise_local_aria(
    tmp_path: Path,
    executable: str,
    root: str,
    payload: bytes,
    signals: tuple[list[tuple[str, str | None]], Event, Event, Event],
) -> tuple[ExecutionContext, DownloadPlan, DownloadDependencies, Mock, HubFile]:
    """用本机 aria2 完成断线续传、错误哈希和停止操作。"""
    requests, interrupted, slow_started, release_slow = signals
    raw_context, raw_plan, raw_deps, reporter, _, _, _, _, _, _ = _case(
        tmp_path, filenames=("good",)
    )
    context = replace(
        cast(ExecutionContext, raw_context),
        clock=JobClock(lambda: datetime.now(UTC), time.monotonic),
    )
    plan = cast(DownloadPlan, raw_plan)
    plan.staging_dir.mkdir()
    parameters = cast(DownloadParameters, context.parameters).model_copy(
        update={
            "max_tries": 5,
            "retry_wait_s": 0,
            "max_connection_per_server": 1,
            "split": 1,
            "min_split_size_bytes": 1024**2,
        }
    )
    context = replace(context, parameters=parameters)
    digest = hashlib.sha256(payload).hexdigest()
    supervisor = Aria2Supervisor(JobsConfig(aria2c_path=executable), tmp_path)
    rpc: Aria2Rpc | None = None
    stopped = False
    try:
        with bind(context):
            rpc = supervisor.start(parameters)
            good = HubFile("good", len(payload), "0" * 40, digest)
            gid = rpc.add_file(root + "/good", plan.staging_dir / "good", good, None)
            assert _wait_aria(rpc, gid).state == "complete"
            assert interrupted.is_set() and any(
                path == "/good" and value and not value.startswith("bytes=0-")
                for path, value in requests
            )
            assert (plan.staging_dir / "good").read_bytes() == payload
            wrong = HubFile("bad", len(payload), "0" * 40, "f" * 64)
            bad_gid = rpc.add_file(root + "/bad", plan.staging_dir / "bad", wrong, None)
            assert _wait_aria(rpc, bad_gid).state == "error"
            slow = HubFile("slow", len(payload), "0" * 40, digest)
            slow_gid = rpc.add_file(root + "/slow", plan.staging_dir / "slow", slow, None)
            assert slow_started.wait(5)
            rpc.stop((slow_gid,))
            stopped = True
            release_slow.set()
            assert (plan.staging_dir / "good").exists()
    finally:
        release_slow.set()
        if rpc is not None and not stopped:
            with suppress(ExternalError):
                rpc.stop(())
        supervisor.terminate()
    return context, plan, cast(DownloadDependencies, raw_deps), cast(Mock, reporter), good


def test_local_aria2_http_server_resume_integrity_and_cancel(tmp_path: Path) -> None:
    """验证本机 aria2 的中断续传、错误哈希、取消后跳过及官方站跳转拒绝。"""
    executable = shutil.which("aria2c")
    if executable is None:
        pytest.skip("本机未安装 aria2c")
    server, thread, payload, requests, interrupted, slow_started, release_slow = (
        _local_test_server()
    )
    try:
        context, plan, dependencies, reporter, good = _exercise_local_aria(
            tmp_path,
            executable,
            f"http://127.0.0.1:{server.server_port}",
            payload,
            (requests, interrupted, slow_started, release_slow),
        )
        before = len(requests)
        plan = replace(
            plan, files=(good,), capacity=Capacity(len(payload), len(payload), 0, len(payload), 0)
        )
        dependencies = replace(
            dependencies,
            process=Aria2Supervisor(JobsConfig(aria2c_path=executable), tmp_path),
            verifier=HashFileVerifier(),
        )
        run_download(context, plan, dependencies)
        assert reporter.report.call_args.args[0].total_items == 1
        assert len(requests) == before

        class LocalMirror:
            def request(
                self, method: str, url: str, *, headers: Mapping[str, str], timeout_s: float
            ) -> HttpResponse:
                connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=2)
                try:
                    connection.request("GET", "/redirect", headers=dict(headers))
                    response = connection.getresponse()
                    return HttpResponse(
                        response.status, dict(response.getheaders()), response.read()
                    )
                finally:
                    connection.close()

        with pytest.raises(InputError):
            resolve_download_url(
                "https://hf-mirror.com/resolve/x", None, LocalMirror(), dependencies.redirects
            )
    finally:
        release_slow.set()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        assert not thread.is_alive()


def test_type_concurrency_override_cannot_exceed_one() -> None:
    """验证配置覆盖不能使下载作业类型同时运行超过一个。"""
    from rdp.infra.config import JobsConfig
    from rdp.infra.diagnostics import InputError
    from rdp.jobs.registry import production_registry
    from rdp.jobs.scheduling import resolve_scheduling

    with pytest.raises(InputError):
        resolve_scheduling(JobsConfig(concurrency={"download": 2}), production_registry())
    resolve_scheduling(JobsConfig(concurrency={"download": 1}), production_registry())


def test_aria2_executable_comes_from_config(tmp_path: Path) -> None:
    """验证 aria2 适配器绑定的是配置指定的可执行文件，而非作业参数。"""
    from rdp.infra.config import JobsConfig
    from rdp.jobs.downloads.adapters import Aria2Supervisor

    executable = tmp_path / "aria2c"
    supervisor = Aria2Supervisor(JobsConfig(aria2c_path=str(executable)), tmp_path)
    assert supervisor.executable == executable


def test_validate_download_redirect_rejects_official_and_unsafe() -> None:
    """验证重定向只允许安全 HTTPS 并拒绝官方站及其子域。"""
    from rdp.infra.diagnostics import InputError
    from rdp.jobs.downloads.job import validate_download_redirect

    current = "https://hf-mirror.com/resolve/file"
    assert (
        validate_download_redirect(current, "https://cdn.example/file")
        == "https://cdn.example/file"
    )
    assert validate_download_redirect(current, "/next") == "https://hf-mirror.com/next"
    for location in (
        "https://huggingface.co/a",
        "https://sub.huggingface.co/a",
        "https://HUGGINGFACE.CO./a",
        "http://cdn.example/a",
        "https://name@cdn.example/a",
        "https://cdn.example:bad/a",
    ):
        with pytest.raises(InputError):
            validate_download_redirect(current, location)


def test_request_from_parameters_preserves_download_selection() -> None:
    """验证下载参数转计划请求时保留筛选与目标，不携带下载器参数。"""
    from rdp.jobs.downloads.job import request_from_parameters
    from rdp.jobs.downloads.plan import DownloadRequest

    parameters = DownloadParameters.model_validate(
        {
            "repo_type": "model",
            "repo_id": "org/name",
            "revision": "dev",
            "storage_root": "disk",
            "include": ["*.bin"],
            "exclude": ["old*"],
            "exclude_video": True,
            "exclude_cameras": ["right"],
            "target_subdir": "weights/a",
        }
    )
    assert request_from_parameters(parameters) == DownloadRequest(
        "model", "org/name", "dev", "disk", ("*.bin",), ("old*",), True, ("right",), "weights/a"
    )


def test_followup_transport_rejects_non_https_and_userinfo() -> None:
    """验证后续单跳传输在连接前拒绝非 HTTPS 和带用户信息的 URL。"""
    from rdp.infra.diagnostics import ExternalError
    from rdp.jobs.downloads.adapters import RedirectHttpTransport

    transport = RedirectHttpTransport()
    for url in ("http://example.invalid/file", "https://user@example.invalid/file"):
        with pytest.raises(ExternalError):
            transport.request(url, timeout_s=1.0)


def test_adjustment_channel_initializes_once_without_overwriting(tmp_path: Path) -> None:
    """验证初始化使用提交参数，恢复时不覆盖尚待生效的调整。"""
    from jobs_storage_support import job_database, job_row

    from rdp.infra.db.connection import session_scope
    from rdp.jobs.downloads.adjustments import SqlAdjustmentChannel
    from rdp.jobs.downloads.job import DownloadAdjustment

    with job_database(tmp_path) as (engine, _):
        with session_scope(engine) as session:
            job = job_row()
            job.type_name = "download"
            session.add(job)
        channel = SqlAdjustmentChannel(engine)
        channel.initialize(
            71,
            DownloadAdjustment(
                max_concurrent_downloads=4, max_overall_download_limit_bytes_per_s=0
            ),
        )
        channel.submit(71, DownloadAdjustment(max_concurrent_downloads=2))
        channel.initialize(
            71,
            DownloadAdjustment(
                max_concurrent_downloads=4, max_overall_download_limit_bytes_per_s=0
            ),
        )
        assert channel.pending(71) == (
            1,
            DownloadAdjustment(
                max_concurrent_downloads=2, max_overall_download_limit_bytes_per_s=0
            ),
        )


def test_mirror_range_transport_uses_single_byte_without_cdn_token() -> None:
    """验证镜像单跳传输使用 Range、单字节读取及镜像限定，并拒绝跨域发送令牌。"""
    from collections.abc import Mapping

    from rdp.infra.diagnostics import ExternalError
    from rdp.jobs.downloads.adapters import MirrorRangeHttpTransport
    from rdp.jobs.downloads.plan import HttpResponse

    calls: list[tuple[str, str, Mapping[str, str], bool]] = []

    def send(
        method: str,
        url: str,
        headers: Mapping[str, str],
        timeout_s: float,
        *,
        first_byte_only: bool = False,
    ) -> HttpResponse:
        calls.append((method, url, headers, first_byte_only))
        return HttpResponse(200, {}, b"x")

    transport = MirrorRangeHttpTransport(send=send)
    response = transport.request(
        "GET",
        "https://hf-mirror.com/a",
        headers={"Range": "bytes=0-0", "Authorization": "Bearer test-secret"},
        timeout_s=1.0,
    )
    assert response.status == 200 and response.body == b"x"
    assert calls == [
        (
            "GET",
            "https://hf-mirror.com/a",
            {"Range": "bytes=0-0", "Authorization": "Bearer test-secret"},
            True,
        )
    ]
    with pytest.raises(ExternalError):
        transport.request(
            "GET",
            "https://cdn.example/a",
            headers={"Authorization": "Bearer test-secret"},
            timeout_s=1.0,
        )
    assert len(calls) == 1


def test_managed_process_reclaims_process_group_on_stop(tmp_path: Path) -> None:
    """验证 M0 受管长进程停止后回收子进程，不遗留文件描述符。"""
    import sys
    import time
    from datetime import UTC, datetime
    from typing import cast
    from unittest.mock import Mock

    from rdp.jobs.logs import JobLog
    from rdp.jobs.processes import ManagedExternalProcess, ToolCommand
    from rdp.jobs.progress import ProgressReporter
    from rdp.jobs.types import JobClock

    reporter = Mock(spec=ProgressReporter)
    command = ToolCommand(
        "test-child", (sys.executable, "-c", "import time; time.sleep(60)"), tmp_path, 90
    )
    child = ManagedExternalProcess(
        command, reporter, cast(JobLog, Mock()), JobClock(lambda: datetime.now(UTC), time.monotonic)
    )
    try:
        child.start()
        assert child.running()
    finally:
        child.stop()
    assert not child.running()


def test_aria2_rpc_add_file_uses_checksum_and_sensitive_header(tmp_path: Path) -> None:
    """验证 aria2 RPC 在正文中携带鉴权头及 LFS 校验，命令行无文件凭据。"""
    from collections.abc import Mapping, Sequence

    from rdp.jobs.downloads.adapters import Aria2JsonRpc
    from rdp.jobs.downloads.plan import HubFile

    calls: list[tuple[str, Sequence[object]]] = []

    def send(method: str, args: Sequence[object]) -> object:
        calls.append((method, args))
        return "gid-1"

    rpc = Aria2JsonRpc(send)
    target = tmp_path / "file.bin"
    file = HubFile("file.bin", 3, "0" * 40, "a" * 64)
    assert rpc.add_file("https://hf-mirror.com/part", target, file, "private-token") == "gid-1"
    method, args = calls[0]
    assert method == "aria2.addUri"
    assert args[0] == ["https://hf-mirror.com/part"]
    options = args[1]
    assert isinstance(options, Mapping)
    assert options["checksum"] == "sha-256=" + "a" * 64
    assert options["header"] == ["Authorization: Bearer private-token"]
    assert options["dir"] == str(tmp_path) and options["out"] == "file.bin"


def test_aria2_rpc_status_decodes_progress_and_expiry() -> None:
    """验证 aria2 状态转换字节、速度与资源不可用错误码。"""
    from rdp.jobs.downloads.adapters import Aria2JsonRpc
    from rdp.jobs.downloads.job import TransferStatus

    rpc = Aria2JsonRpc(
        lambda _method, _args: {
            "gid": "abc",
            "status": "error",
            "completedLength": "12",
            "downloadSpeed": "34",
            "errorCode": "3",
        }
    )
    assert rpc.status("abc") == TransferStatus("abc", "error", 12, 34, None, 3)


def test_aria2_rpc_change_global_options() -> None:
    """验证并发和速率以 aria2 全局选项名和字节字符串下发。"""
    from collections.abc import Sequence

    from rdp.jobs.downloads.adapters import Aria2JsonRpc
    from rdp.jobs.downloads.job import DownloadAdjustment

    calls: list[tuple[str, Sequence[object]]] = []
    rpc = Aria2JsonRpc(lambda method, args: calls.append((method, args)))
    rpc.change_global_options(
        DownloadAdjustment(max_concurrent_downloads=3, max_overall_download_limit_bytes_per_s=2048)
    )
    assert calls == [
        (
            "aria2.changeGlobalOption",
            [{"max-concurrent-downloads": "3", "max-overall-download-limit": "2048"}],
        )
    ]


def test_aria2_rpc_removes_all_then_shuts_down_even_on_failure() -> None:
    """验证取消逐个 forceRemove，失败仍尝试其余条目和 shutdown。"""
    from collections.abc import Sequence

    from rdp.infra.diagnostics import Diagnostic, DiagnosticCategory, DiagnosticLevel, ExternalError
    from rdp.jobs.downloads.adapters import Aria2JsonRpc

    calls: list[tuple[str, Sequence[object]]] = []
    problem = ExternalError(
        (
            Diagnostic(
                level=DiagnosticLevel.ERROR,
                category=DiagnosticCategory.EXTERNAL,
                stage="下载",
                source="平台",
                objects=(),
                rule="download.test",
                actual="失败",
                expected="成功",
                consequence="失败",
                next_step="重试",
            ),
        )
    )

    def send(method: str, args: Sequence[object]) -> object:
        calls.append((method, args))
        if method == "aria2.forceRemove" and args == ["a"]:
            raise problem
        return "OK"

    with pytest.raises(ExternalError):
        Aria2JsonRpc(send).stop(("a", "b"))
    assert calls == [
        ("aria2.forceRemove", ["a"]),
        ("aria2.forceRemove", ["b"]),
        ("aria2.shutdown", []),
    ]


def test_mirror_recheck_stops_transfer_before_process_group(tmp_path: Path) -> None:
    """验证下载运行 60 秒后复探镜像，失效时先 RPC 停止再终止进程并保留暂存。"""
    from dataclasses import replace
    from datetime import UTC, datetime
    from typing import cast
    from unittest.mock import Mock

    from rdp.infra.diagnostics import ExternalError
    from rdp.jobs.downloads.job import DownloadDependencies, TransferStatus, run_download
    from rdp.jobs.downloads.plan import DownloadPlan, HttpResponse
    from rdp.jobs.execution import ExecutionContext
    from rdp.jobs.types import JobClock

    raw_context, plan, dependencies, _, process, rpc, _, _, mirror, _ = _case(tmp_path)
    context = cast(ExecutionContext, raw_context)
    ticks = iter((0.0, 61.0, 62.0, 63.0, 64.0))
    context = replace(context, clock=JobClock(lambda: datetime.now(UTC), lambda: next(ticks, 64.0)))
    cast(Mock, rpc).status.side_effect = [
        TransferStatus("gid", "active", 1, 2),
        TransferStatus("gid", "complete", 3, 0),
    ]
    cast(Mock, mirror).request.side_effect = [
        HttpResponse(200, {}, b"x"),
        HttpResponse(308, {"Location": "https://huggingface.co"}, b""),
    ]
    ordering: list[str] = []

    def stopped(_gids: tuple[str, ...]) -> None:
        ordering.append("rpc")

    cast(Mock, rpc).stop.side_effect = stopped
    cast(Mock, process).terminate.side_effect = lambda: ordering.append("process")
    with pytest.raises(ExternalError):
        run_download(context, cast(DownloadPlan, plan), cast(DownloadDependencies, dependencies))
    assert ordering == ["rpc", "process"]
    assert cast(DownloadPlan, plan).staging_dir.is_dir()


@pytest.mark.parametrize("first_cdn", [False, True], ids=["首轮镜像", "首轮CDN"])
@pytest.mark.parametrize("retry_cdn", [False, True], ids=["重解析镜像", "重解析CDN"])
def test_rpc_token_only_for_mirror_on_initial_and_refresh(
    tmp_path: Path, first_cdn: bool, retry_cdn: bool
) -> None:
    """验证首轮和签名过期重解析后，RPC 仅对镜像地址携带 token。"""
    raw_context, raw_plan, raw_deps, _, _, raw_rpc, _, _, raw_mirror, _ = _case(tmp_path)
    context = cast(ExecutionContext, raw_context)
    plan = cast(DownloadPlan, raw_plan)
    deps = cast(DownloadDependencies, raw_deps)
    rpc, mirror = cast(Mock, raw_rpc), cast(Mock, raw_mirror)
    secret = "test-" + "credential"
    state_dir = deps.plan.config.state_dir
    state_dir.mkdir()
    credential = state_dir / "hf_token"
    credential.write_text(secret)
    credential.chmod(0o600)
    # 两次响应分别控制首轮与签名过期重解析的最终主机，覆盖跨域和回到镜像两种顺序。
    mirror.request.side_effect = [
        HttpResponse(302, {"Location": "https://cdn.example/first"}, b"")
        if first_cdn
        else HttpResponse(200, {}, b"x"),
        HttpResponse(302, {"Location": "https://cdn.example/retry"}, b"")
        if retry_cdn
        else HttpResponse(200, {}, b"x"),
    ]
    cast(Mock, deps.redirects).request.return_value = HttpResponse(206, {}, b"x")
    rpc.add_file.side_effect = ["first-gid", "retry-gid"]
    rpc.status.side_effect = [
        TransferStatus("first-gid", "error", 0, 0, 403),
        TransferStatus("retry-gid", "complete", 3, 0),
    ]

    run_download(context, plan, deps)

    assert rpc.add_file.call_count == 2
    first, retry = rpc.add_file.call_args_list
    assert first.args[3] == (None if first_cdn else secret)
    assert retry.args[3] == (None if retry_cdn else secret)
    assert first.args[0].startswith(
        "https://cdn.example/" if first_cdn else "https://hf-mirror.com/"
    )
    assert retry.args[0].startswith(
        "https://cdn.example/" if retry_cdn else "https://hf-mirror.com/"
    )


def test_model_target_created_empty_during_download_is_not_overwritten(tmp_path: Path) -> None:
    """验证下载后、原子改名前出现空目标目录时不覆盖并保留暂存。"""
    from rdp.infra.config import PlatformConfig, StorageRootConfig

    raw_context, raw_plan, raw_deps, _, _, _, _, raw_verifier, _, _ = _case(tmp_path)
    context = cast(ExecutionContext, raw_context)
    plan = cast(DownloadPlan, raw_plan)
    deps = cast(DownloadDependencies, raw_deps)
    root = StorageRootConfig(name="disk", path=tmp_path, nfs_export="host:/share", writable=True)
    deps = replace(
        deps,
        plan=replace(
            deps.plan,
            config=PlatformConfig(state_dir=tmp_path / "state", storage_roots=(root,)),
        ),
    )
    request = replace(plan.request, repo_type="model", target_subdir="weights/model")
    plan = replace(plan, request=request)
    context = replace(
        context,
        parameters=DownloadParameters(
            repo_type="model",
            repo_id="org/repo",
            revision="main",
            storage_root="disk",
            target_subdir="weights/model",
        ),
    )
    target = tmp_path / "weights/model"
    original_inode: list[int] = []

    def create_competing_target(_path: Path, _file: HubFile) -> bool:
        # 在启动检查之后、最终 rename 之前制造竞争；空目录能区分普通 rename 和 NOREPLACE。
        target.mkdir(parents=True)
        original_inode.append(target.stat().st_ino)
        return True

    cast(Mock, raw_verifier).verify.side_effect = create_competing_target
    with pytest.raises(InputError):
        run_download(context, plan, deps)
    assert target.is_dir() and not list(target.iterdir())
    assert target.stat().st_ino == original_inode[0]
    assert plan.staging_dir.is_dir()


@pytest.mark.parametrize("last_status", [200, 302], ids=["第五跳成功", "第六次跳转超限"])
def test_redirect_limit_accepts_five_and_rejects_six(last_status: int) -> None:
    """验证五次合法跳转可到达终点，第六次跳转被拒绝且不再发请求。"""
    mirror, redirects = Mock(), Mock()
    mirror.request.return_value = HttpResponse(302, {"Location": "https://cdn.example/0"}, b"")
    responses = [
        HttpResponse(302, {"Location": f"https://cdn.example/{index}"}, b"")
        for index in range(1, 5)
    ]
    responses.append(HttpResponse(last_status, {"Location": "https://cdn.example/6"}, b"x"))
    redirects.request.side_effect = responses

    if last_status == 200:
        result = resolve_download_url("https://hf-mirror.com/resolve/file", None, mirror, redirects)
        assert result == "https://cdn.example/4"
    else:
        with pytest.raises(ExternalError):
            resolve_download_url("https://hf-mirror.com/resolve/file", None, mirror, redirects)
    assert redirects.request.call_count == 5
