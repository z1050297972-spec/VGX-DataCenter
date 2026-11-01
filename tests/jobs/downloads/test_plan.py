"""下载计划的契约清单；HTTP 测试使用注入替身，不访问网络。"""

import secrets
import sys
import time
from collections.abc import Mapping
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import NamedTuple, cast

import pytest

from rdp.infra.config import PlatformConfig, StorageConfig, StorageRootConfig
from rdp.infra.diagnostics import ExternalError, InputError
from rdp.infra.storage import MountInspector, StorageAccessChecker
from rdp.jobs.downloads import plan
from rdp.jobs.downloads.plan import (
    CREDENTIAL_FILENAME,
    DatasetPreview,
    DownloadRequest,
    HttpResponse,
    HubFile,
    PlanDependencies,
    RepositoryRevision,
    UrllibTransport,
    build_plan,
    filter_files,
    list_files,
    model_weights_path,
    probe_mirror,
    read_dataset_preview,
    read_token,
    resolve_revision,
    staging_path,
)


class Usage(NamedTuple):
    """测试用磁盘容量观测值，单位字节。"""

    total: int
    used: int
    free: int


def _mock_free(monkeypatch: pytest.MonkeyPatch, free: int) -> None:
    """把容量观察替换为固定的可用字节数。"""

    def disk_usage(path: object) -> Usage:
        return Usage(free, 0, free)

    monkeypatch.setattr("shutil.disk_usage", disk_usage)


class FakeTransport:
    """返回预设响应，记录请求；不访问网络。"""

    def __init__(self, responses: list[HttpResponse | OSError]) -> None:
        """保存按请求顺序返回的响应。"""
        self.responses = responses
        self.requests: list[tuple[str, str, Mapping[str, str]]] = []

    def request(
        self, method: str, url: str, *, headers: Mapping[str, str], timeout_s: float
    ) -> HttpResponse:
        """记录请求并返回下一份预设响应。"""
        self.requests.append((method, url, headers))
        value = self.responses.pop(0)
        if isinstance(value, OSError):
            raise value
        return value


def _plan_inputs(
    tmp_path: Path, *, writable: bool = True, online: bool = True
) -> tuple[DownloadRequest, PlanDependencies, FakeTransport]:
    """用临时根和伪挂载表构造真实存储检查器，不读取真实存储。"""
    root = StorageRootConfig(
        name="disk", path=tmp_path, nfs_export="host:/share", writable=writable
    )
    config = PlatformConfig(state_dir=tmp_path / "state", storage_roots=(root,))
    mountinfo = f"20 1 0:1 / {tmp_path} rw - nfs4 host:/share rw\n" if online else ""
    inspector = MountInspector(
        (root,), lambda: mountinfo, lambda _: None, lambda: datetime.now(UTC)
    )
    checker = StorageAccessChecker(inspector, StorageConfig(), lambda _: None)
    revision = b'{"sha":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","gated":false,"private":false,"disabled":false}'
    tree = b'[{"type":"file","path":"model.bin","size":10,"oid":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"}]'
    transport = FakeTransport(
        [
            HttpResponse(200, {}, b""),
            HttpResponse(200, {}, b""),
            HttpResponse(200, {}, revision),
            HttpResponse(200, {}, tree),
        ]
    )
    request = DownloadRequest(
        repo_type="model", repo_id="org/repo", revision="main", storage_root="disk"
    )
    dependencies = PlanDependencies(
        config=config,
        checker=checker,
        transport=transport,
        sleep=lambda _: None,
        checkpoint=lambda: None,
    )
    return request, dependencies, transport


def test_mirror_head_redirect_to_official() -> None:
    """首页 308 指向官方站时拒绝，不跟随跳转。"""
    transport = FakeTransport([HttpResponse(308, {"Location": "https://huggingface.co/"}, b"")])
    with pytest.raises(ExternalError) as error:
        probe_mirror(transport, sleep=lambda _: None)
    assert "镜像" in error.value.diagnostics[0].actual
    assert "VPN" in error.value.diagnostics[0].next_step
    assert "直连" in error.value.diagnostics[0].next_step
    assert transport.requests == [("HEAD", "https://hf-mirror.com/", {})]


def test_mirror_api_redirect_to_official() -> None:
    """API 的 3xx 指向官方站时拒绝，即使首页通过。"""
    transport = FakeTransport(
        [
            HttpResponse(200, {}, b""),
            HttpResponse(308, {"Location": "https://huggingface.co/api"}, b""),
        ]
    )
    with pytest.raises(ExternalError):
        probe_mirror(transport, sleep=lambda _: None)
    assert [call[0] for call in transport.requests] == ["HEAD", "GET"]
    assert all(call[1].startswith("https://hf-mirror.com/") for call in transport.requests)


def test_no_proxy_or_redirect_in_default_transport(monkeypatch: pytest.MonkeyPatch) -> None:
    """默认传输显式禁用代理和自动重定向，并设置超时。"""
    _mock_http_child(monkeypatch, "normal")
    result = UrllibTransport().request("GET", "https://hf-mirror.com/", headers={}, timeout_s=2.0)
    assert result.status == 200 and result.body == b"ok"


def test_three_page_tree_uses_pinned_commit() -> None:
    """三页 Link next 按顺序获取，所有文件属于同一固定 commit。"""
    base = (
        "https://hf-mirror.com/api/datasets/org/repo/tree/"
        + "a" * 40
        + "?recursive=true&expand=false"
    )

    def body(name: str) -> bytes:
        return (
            '[{"type":"file","path":"' + name + '","size":1,"oid":"' + "b" * 40 + '"}]'
        ).encode()

    transport = FakeTransport(
        [
            HttpResponse(200, {"Link": f'<{base}&cursor=2>; rel="next"'}, body("one")),
            HttpResponse(200, {"Link": f'<{base}&cursor=3>; rel="next"'}, body("two")),
            HttpResponse(200, {}, body("three")),
        ]
    )
    request = DownloadRequest(
        repo_type="dataset", repo_id="org/repo", revision="main", storage_root="disk"
    )
    revision = RepositoryRevision(commit="a" * 40, gated=False, private=False, disabled=False)
    sample_credential = secrets.token_hex(12)
    files = list_files(request, revision, transport, token=sample_credential, sleep=lambda _: None)
    assert [item.path for item in files] == ["one", "two", "three"]
    assert [call[1] for call in transport.requests] == [
        base,
        base + "&cursor=2",
        base + "&cursor=3",
    ]
    assert all(
        call[2] == {"Authorization": f"Bearer {sample_credential}"} for call in transport.requests
    )


def test_429_then_success() -> None:
    """429 后按退避重试，成功响应被正常处理。"""
    transport = FakeTransport(
        [HttpResponse(429, {}, b""), HttpResponse(200, {}, b""), HttpResponse(200, {}, b"")]
    )
    waits: list[float] = []
    probe_mirror(transport, sleep=waits.append)
    assert len(transport.requests) == 3
    assert waits == [1.0]


def test_retries_exhausted() -> None:
    """连接、TLS、429 和 5xx 超过预算后返回外部失败诊断。"""
    for failure in (
        OSError("connection"),
        OSError("TLS"),
        HttpResponse(429, {}, b""),
        HttpResponse(503, {}, b""),
    ):
        transport = FakeTransport([failure, failure, failure])
        waits: list[float] = []
        with pytest.raises(ExternalError):
            probe_mirror(transport, sleep=waits.append)
        assert len(transport.requests) == 3
        assert waits == [1.0, 2.0]


def test_gated_without_token() -> None:
    """受 gated 限制的仓库无 token 时要求用户处理，不列清单。"""
    response = b'{"sha":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","gated":"manual","private":false,"disabled":false}'
    transport = FakeTransport([HttpResponse(200, {}, response)])
    request = DownloadRequest(
        repo_type="dataset", repo_id="org/repo", revision="main", storage_root="disk"
    )
    with pytest.raises(ExternalError) as error:
        resolve_revision(request, transport, token=None, sleep=lambda _: None)
    assert "token" in error.value.diagnostics[0].actual
    assert len(transport.requests) == 1


def test_disabled_repository() -> None:
    """已 disabled 的仓库拒绝生成计划并返回诊断。"""
    response = b'{"sha":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","gated":false,"private":false,"disabled":true}'
    transport = FakeTransport([HttpResponse(200, {}, response)])
    request = DownloadRequest(
        repo_type="model", repo_id="org/repo", revision="main", storage_root="disk"
    )
    with pytest.raises(ExternalError) as error:
        resolve_revision(request, transport, token=None, sleep=lambda _: None)
    assert "禁用" in error.value.diagnostics[0].actual
    assert "/api/models/org/repo/revision/main" in transport.requests[0][1]


def test_lfs_and_git_files() -> None:
    """清单分别保留普通文件 blob SHA-1 和 LFS 文件的两种校验值。"""
    data = (
        '[{"type":"file","path":"plain","size":2,"oid":"' + "a" * 40 + '"},'
        '{"type":"file","path":"large","size":3,"oid":"'
        + "b" * 40
        + '","lfs":{"oid":"'
        + "c" * 64
        + '"}}]'
    ).encode()
    request = DownloadRequest(
        repo_type="model", repo_id="org/repo", revision="main", storage_root="disk"
    )
    revision = RepositoryRevision(commit="d" * 40, gated=False, private=False, disabled=False)
    files = list_files(
        request,
        revision,
        FakeTransport([HttpResponse(200, {}, data)]),
        token=None,
        sleep=lambda _: None,
    )
    assert files == (HubFile("plain", 2, "a" * 40, None), HubFile("large", 3, "b" * 40, "c" * 64))


def test_token_never_leaks(
    caplog: pytest.LogCaptureFixture, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """凭据不出现在计划、诊断、异常文本或日志中。"""
    secret = secrets.token_hex(12)
    request, dependencies, transport = _plan_inputs(tmp_path)
    dependencies.config.state_dir.mkdir()
    token_file = dependencies.config.state_dir / CREDENTIAL_FILENAME
    token_file.write_text(secret, encoding="ascii")
    token_file.chmod(0o600)
    _mock_free(monkeypatch, 10**12)
    result = build_plan(request, dependencies)
    assert secret not in repr(result)
    assert any(
        headers.get("Authorization") == f"Bearer {secret}" for _, _, headers in transport.requests
    )
    failing = FakeTransport([OSError(secret), OSError(secret), OSError(secret)])
    with pytest.raises(ExternalError) as error:
        resolve_revision(request, failing, token=secret, sleep=lambda _: None)
    assert secret not in str(error.value)
    assert secret not in repr(error.value.diagnostics)
    assert secret not in caplog.text


def test_include_exclude_fnmatchcase() -> None:
    """包含和排除区分大小写，星号跨斜杠，尾部斜杠补星号且排除优先。"""
    files = tuple(
        HubFile(path=path, size_bytes=1, blob_sha1="a" * 40, lfs_sha256=None)
        for path in (
            "data/a.parquet",
            "data/nested/b.parquet",
            "data/private/c.parquet",
            "Data/upper.parquet",
            "other.txt",
        )
    )
    request = DownloadRequest(
        repo_type="dataset",
        repo_id="org/repo",
        revision="main",
        storage_root="disk",
        include=("data/*.parquet",),
        exclude=("data/private/",),
    )
    assert tuple(file.path for file in filter_files(files, request, None)) == (
        "data/a.parquet",
        "data/nested/b.parquet",
    )


def test_video_and_camera_filters() -> None:
    """不选视频和排除指定相机分别只过滤对应视频路径。"""
    files = tuple(
        HubFile(path=path, size_bytes=1, blob_sha1="a" * 40, lfs_sha256=None)
        for path in ("meta/info.json", "videos/front/a.mp4", "videos/rear/a.mp4", "data/a.parquet")
    )
    request = DownloadRequest(
        repo_type="dataset", repo_id="org/repo", revision="main", storage_root="disk"
    )
    preview = DatasetPreview(
        episodes=1,
        frames=3,
        fps=30.0,
        robot_type=None,
        codebase_version="v3.0",
        cameras=("front", "rear"),
    )
    assert tuple(
        f.path for f in filter_files(files, replace(request, exclude_video=True), preview)
    ) == ("meta/info.json", "data/a.parquet")
    assert tuple(
        f.path for f in filter_files(files, replace(request, exclude_cameras=("front",)), preview)
    ) == ("meta/info.json", "videos/rear/a.mp4", "data/a.parquet")
    for invalid_preview, camera in ((None, "front"), (preview, "missing")):
        with pytest.raises(InputError):
            filter_files(files, replace(request, exclude_cameras=(camera,)), invalid_preview)


def test_dataset_preview_from_pinned_info() -> None:
    """从固定 commit 的元数据读取 episode、帧、FPS、版本、类型和相机。"""
    info = b'{"total_episodes":7,"total_frames":83,"fps":30,"robot_type":"arm","codebase_version":"v3.0","features":{"observation.images.front":{"dtype":"video"},"observation.state":{"dtype":"float32"}}}'
    transport = FakeTransport([HttpResponse(200, {}, info)])
    request = DownloadRequest(
        repo_type="dataset", repo_id="org/repo", revision="main", storage_root="disk"
    )
    revision = RepositoryRevision(commit="a" * 40, gated=False, private=False, disabled=False)
    preview = read_dataset_preview(request, revision, transport, token=None, sleep=lambda _: None)
    assert preview == DatasetPreview(7, 83, 30.0, "arm", "v3.0", ("observation.images.front",))
    assert "/resolve/" + "a" * 40 + "/meta/info.json" in transport.requests[0][1]


def test_model_has_no_dataset_preview(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """模型计划不读取数据集元数据且预览为空。"""
    request, dependencies, transport = _plan_inputs(tmp_path)
    _mock_free(monkeypatch, 10**12)
    result = build_plan(request, dependencies)
    assert result.preview is None
    assert not any("meta/info.json" in url for _, url, _ in transport.requests)
    assert result.capacity.remaining_bytes == 10


def test_bad_repo_id_rejected(tmp_path: Path) -> None:
    """含点段、绝对路径或空段的 repo_id 不得构造暂存路径。"""
    root = StorageRootConfig(name="disk", path=tmp_path, nfs_export="host:/share", writable=True)
    revision = RepositoryRevision(commit="a" * 40, gated=False, private=False, disabled=False)
    request = DownloadRequest(
        repo_type="model", repo_id="org/repo", revision="main", storage_root="disk"
    )
    for repo in ("org/..", "/org/repo", "org//repo", "org/./repo", "org/", "org\\repo", "org/x\0y"):
        with pytest.raises(InputError):
            staging_path(root, replace(request, repo_id=repo), revision)


def test_staging_path_reuses_commit(tmp_path: Path) -> None:
    """相同类型、仓库与提交复用暂存路径，不同类型隔离。"""
    root = StorageRootConfig(name="disk", path=tmp_path, nfs_export="host:/share", writable=True)
    revision = RepositoryRevision(commit="a" * 40, gated=False, private=False, disabled=False)
    request = DownloadRequest(
        repo_type="model", repo_id="org/repo", revision="main", storage_root="disk"
    )
    model = staging_path(root, request, revision)
    assert model == tmp_path / "暂存" / "下载" / "model" / "org" / "repo@aaaaaaaaaaaa"
    assert staging_path(root, request, revision) == model
    assert staging_path(root, replace(request, repo_type="dataset"), revision) != model


def test_insufficient_capacity_diagnostic(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """空间不足诊断包含待下载字节数、可用字节数和目标根。"""
    request, dependencies, _ = _plan_inputs(tmp_path)
    _mock_free(monkeypatch, 7)
    with pytest.raises(ExternalError) as error:
        build_plan(request, dependencies)
    diag = error.value.diagnostics[0]
    assert "10" in diag.actual and "7" in diag.actual
    assert any(item.key == "storage_root" and item.value == "disk" for item in diag.objects)


def test_complete_files_reduce_remaining_by_size_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """仅以大小判断暂存文件完整并扣除，预检不计算哈希。"""
    request, dependencies, _ = _plan_inputs(tmp_path)
    stage = tmp_path / "暂存" / "下载" / "model" / "org" / "repo@aaaaaaaaaaaa"
    stage.mkdir(parents=True)
    (stage / "model.bin").write_bytes(b"xxxxxxxxxx")
    _mock_free(monkeypatch, 10**12)
    result = build_plan(request, dependencies)
    assert result.capacity.selected_bytes == 10
    assert result.capacity.complete_bytes == 10
    assert result.capacity.remaining_bytes == 0


def test_readonly_or_offline_root_rejected(tmp_path: Path) -> None:
    """目标根未登记为可写或不在线时不能生成可执行计划。"""
    for writable, online in ((False, True), (True, False)):
        request, dependencies, _ = _plan_inputs(tmp_path, writable=writable, online=online)
        with pytest.raises(ExternalError):
            build_plan(request, dependencies)


def test_token_file_missing_and_permission(tmp_path: Path) -> None:
    """凭据文件不存在视为未设置，存在但权限不是 0600 时拒绝。"""
    config = PlatformConfig(state_dir=tmp_path)
    assert read_token(config) is None
    file = tmp_path / CREDENTIAL_FILENAME
    file.write_text("secret-value\n", encoding="utf-8")
    file.chmod(0o644)
    with pytest.raises(ExternalError):
        read_token(config)
    file.chmod(0o600)
    assert read_token(config) == "secret-value"
    file.write_text("\n", encoding="utf-8")
    with pytest.raises(InputError):
        read_token(config)
    file.write_text("secret\nheader", encoding="utf-8")
    with pytest.raises(InputError):
        read_token(config)


def test_untrusted_pagination_target() -> None:
    """分页地址不能将请求或凭据发送至镜像以外的主机。"""
    request = DownloadRequest(
        repo_type="model", repo_id="org/repo", revision="main", storage_root="disk"
    )
    revision = RepositoryRevision(commit="a" * 40, gated=False, private=False, disabled=False)
    transport = FakeTransport(
        [HttpResponse(200, {"Link": '<https://evil.example/steal>; rel="next"'}, b"[]")]
    )
    with pytest.raises(ExternalError):
        list_files(request, revision, transport, token=secrets.token_hex(12), sleep=lambda _: None)
    assert len(transport.requests) == 1


def test_model_weights_path(tmp_path: Path) -> None:
    """模型权重路径使用用户指定的安全相对目录，未指定时默认根下仓库和提交目录。"""
    root = StorageRootConfig(
        name="weights", path=tmp_path, nfs_export="host:/weights", writable=True
    )
    revision = RepositoryRevision(commit="a" * 40, gated=False, private=False, disabled=False)
    request = DownloadRequest(
        repo_type="model", repo_id="org/model", revision="main", storage_root="weights"
    )
    assert model_weights_path(root, request, revision) == tmp_path / "org" / "model@aaaaaaaaaaaa"
    for invalid in ("../outside", "/absolute", "a//b", "a\\b", "a/./b", "x\0y", ""):
        with pytest.raises(InputError):
            model_weights_path(root, replace(request, target_subdir=invalid), revision)
    selected = replace(request, target_subdir="team/run-1")
    assert model_weights_path(root, selected, revision) == tmp_path / "team" / "run-1"
    with pytest.raises(InputError):
        model_weights_path(
            root,
            DownloadRequest(
                repo_type="dataset", repo_id="org/model", revision="main", storage_root="weights"
            ),
            revision,
        )


def test_untrusted_file_paths_and_symlinks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """恶意或重复清单路径被拒绝，暂存容量检查不跟随软链接逃出根。"""
    root_path = tmp_path / "root"
    root_path.mkdir()
    request, dependencies, _ = _plan_inputs(root_path)
    revision = RepositoryRevision(commit="a" * 40, gated=False, private=False, disabled=False)
    for data in (
        b'[{"type":"file","path":"../bad","size":1,"oid":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"}]',
        b'[{"type":"file","path":"x","size":1,"oid":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"},{"type":"file","path":"x","size":1,"oid":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"}]',
    ):
        with pytest.raises(ExternalError):
            list_files(
                request,
                revision,
                FakeTransport([HttpResponse(200, {}, data)]),
                token=None,
                sleep=lambda _: None,
            )
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "model.bin").write_bytes(b"xxxxxxxxxx")
    stage_parent = root_path / "暂存" / "下载" / "model" / "org"
    stage_parent.mkdir(parents=True)
    (stage_parent / "repo@aaaaaaaaaaaa").symlink_to(outside, target_is_directory=True)
    _mock_free(monkeypatch, 10**12)
    result = build_plan(request, dependencies)
    assert result.capacity.complete_bytes == 0
    assert result.capacity.remaining_bytes == 10


def test_slow_response_exceeds_total_deadline(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """慢速分块响应超过请求总时长时失败并计入重试。"""
    assert plan.HTTP_TOTAL_DEADLINE_S == 30.0
    marker = tmp_path / "slow-read"
    _mock_http_child(monkeypatch, "slow", marker=marker)
    monkeypatch.setattr(plan, "HTTP_TOTAL_DEADLINE_S", 1.0)
    with pytest.raises(ExternalError) as error:
        UrllibTransport().request("GET", "https://hf-mirror.com/", headers={}, timeout_s=2.0)
    assert error.value.diagnostics[0].rule == "download.http_deadline"
    assert marker.read_text(encoding="ascii") == "read"
    waits: list[float] = []
    start = time.monotonic()
    with pytest.raises(ExternalError) as failure:
        probe_mirror(UrllibTransport(), sleep=waits.append)
    assert "总时长" in failure.value.diagnostics[0].actual
    assert time.monotonic() - start < 8.0
    assert waits == [1.0, 2.0]


def test_response_exceeds_body_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    """响应体超过上限时失败并计入重试。"""
    assert plan.HTTP_MAX_BODY_BYTES == 16 * 1024 * 1024
    _mock_http_child(monkeypatch, "oversize")
    monkeypatch.setattr(plan, "HTTP_MAX_BODY_BYTES", 5)
    with pytest.raises(ExternalError) as error:
        UrllibTransport().request("GET", "https://hf-mirror.com/", headers={}, timeout_s=2.0)
    assert error.value.diagnostics[0].rule == "download.http_body_limit"
    waits: list[float] = []
    with pytest.raises(ExternalError) as failure:
        probe_mirror(UrllibTransport(), sleep=waits.append)
    assert "上限" in failure.value.diagnostics[0].actual
    assert waits == [1.0, 2.0]


def test_model_target_chinese_and_spaces(tmp_path: Path) -> None:
    """模型目标子目录允许中文和段内空格。"""
    root = StorageRootConfig(
        name="weights", path=tmp_path, nfs_export="host:/weights", writable=True
    )
    request = DownloadRequest(
        repo_type="model",
        repo_id="org/repo",
        revision="main",
        storage_root="weights",
        target_subdir="机器人 权重/模型一",
    )
    revision = RepositoryRevision(commit="a" * 40, gated=False, private=False, disabled=False)
    assert model_weights_path(root, request, revision) == tmp_path / "机器人 权重" / "模型一"


def test_model_target_rejects_controls(tmp_path: Path) -> None:
    """模型目标子目录拒绝 C0、C1 控制字符及每段首尾空白。"""
    root = StorageRootConfig(
        name="weights", path=tmp_path, nfs_export="host:/weights", writable=True
    )
    request = DownloadRequest(
        repo_type="model", repo_id="org/repo", revision="main", storage_root="weights"
    )
    revision = RepositoryRevision(commit="a" * 40, gated=False, private=False, disabled=False)
    for target in ("模型/坏\n名", "模型/坏\x85名", "模型/ 空格", "模型/空格 "):
        with pytest.raises(InputError):
            model_weights_path(root, replace(request, target_subdir=target), revision)


def _mock_http_child(
    monkeypatch: pytest.MonkeyPatch, scenario: str, *, marker: Path | None = None
) -> None:
    """以无网络的子进程适配器替代真实 HTTP，保留总截止时间边界。"""
    source = f"""
import io, time, urllib.request
from http.client import HTTPMessage
from pathlib import Path
import rdp.jobs.downloads._http_child as p
scenario = {scenario!r}
marker = {str(marker) if marker is not None else None!r}
class Response(io.BytesIO):
    status = 200
    headers = {{}}
    def read(self, size=-1):
        if scenario == 'slow':
            if marker:
                Path(marker).write_text('read', encoding='ascii')
            time.sleep(0.3)
            return super().read(min(size, 1))
        return super().read(size)
class Opener:
    def open(self, request, timeout):
        assert request.full_url.startswith('https://hf-mirror.com/')
        if scenario == 'redirect':
            raise urllib.error.HTTPError(request.full_url, 308, 'redirect', {{'Location': 'https://huggingface.co/'}}, io.BytesIO(b''))
        if scenario == 'normal':
            assert timeout == 2.0
        response = Response(b'123456' if scenario == 'oversize' else b'abcdefgh' if scenario == 'slow' else b'ok')
        if scenario == 'multi':
            response.headers = HTTPMessage()
            response.headers.add_header('Link', '<https://hf-mirror.com/next>; rel="next"')
            response.headers.add_header('Link', '<https://hf-mirror.com/prev>; rel="prev"')
        return response
def opener(*handlers):
    proxy = next(h for h in handlers if isinstance(h, urllib.request.ProxyHandler))
    assert vars(proxy)['proxies'] == {{}}
    redirect = next(h for h in handlers if isinstance(h, urllib.request.HTTPRedirectHandler))
    assert redirect.redirect_request(None, None, 308, '', {{}}, 'https://huggingface.co/') is None
    return Opener()
urllib.request.build_opener = opener
p._main()
"""

    def command() -> list[str]:
        return [sys.executable, "-c", source]

    monkeypatch.setattr(plan, "_child_command", command, raising=False)


def test_transport_avoids_unsafe_fork(monkeypatch: pytest.MonkeyPatch) -> None:
    """默认传输从多线程进程执行时不调用 os.fork。"""

    def forbidden_fork() -> int:
        raise AssertionError("多线程 worker 不得直接 fork")

    monkeypatch.setattr(plan.os, "fork", forbidden_fork)
    _mock_http_child(monkeypatch, "normal")
    response = UrllibTransport().request("GET", "https://hf-mirror.com/", headers={}, timeout_s=2.0)
    assert response.body == b"ok"


def test_malformed_pagination_url_is_external_error() -> None:
    """格式损坏的分页 URL 不得泄漏 ValueError，也不得发出第二次请求。"""
    request = DownloadRequest(
        repo_type="model", repo_id="org/repo", revision="main", storage_root="disk"
    )
    revision = RepositoryRevision(commit="a" * 40, gated=False, private=False, disabled=False)
    transport = FakeTransport([HttpResponse(200, {"Link": '<https://[bad>; rel="next"'}, b"[]")])
    with pytest.raises(ExternalError):
        list_files(request, revision, transport, token=None, sleep=lambda _: None)
    assert len(transport.requests) == 1


def test_gated_integer_is_invalid_response() -> None:
    """仓库 gated 状态必须是布尔值或 Hub 的 auto/manual 字符串，整数不冒充布尔。"""
    data = b'{"sha":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","gated":1,"private":false,"disabled":false}'
    request = DownloadRequest(
        repo_type="dataset", repo_id="org/repo", revision="main", storage_root="disk"
    )
    transport = FakeTransport([HttpResponse(200, {}, data)])
    with pytest.raises(ExternalError) as error:
        resolve_revision(request, transport, token=secrets.token_hex(8), sleep=lambda _: None)
    assert error.value.diagnostics[0].rule == "download.invalid_revision"


def test_dataset_target_subdir_rejected_before_network(tmp_path: Path) -> None:
    """数据集填写模型落点时按输入错误拒绝，且不发请求。"""
    request, dependencies, transport = _plan_inputs(tmp_path)
    with pytest.raises(InputError):
        build_plan(replace(request, repo_type="dataset", target_subdir="权重目录"), dependencies)
    assert transport.requests == []


def test_token_fifo_does_not_block(tmp_path: Path) -> None:
    """状态目录里的 FIFO 不得让凭据读取无限等待。"""
    import errno
    import os
    from threading import Thread

    file = tmp_path / CREDENTIAL_FILENAME
    os.mkfifo(file, 0o600)

    def unblock_old_reader() -> None:
        time.sleep(0.7)
        try:
            fd = os.open(file, os.O_WRONLY | os.O_NONBLOCK)
        except OSError as error:
            if error.errno != errno.ENXIO:
                raise
        else:
            os.close(fd)

    writer = Thread(target=unblock_old_reader)
    writer.start()
    started = time.monotonic()
    try:
        with pytest.raises(ExternalError):
            read_token(PlatformConfig(state_dir=tmp_path))
        assert time.monotonic() - started < 0.5
    finally:
        writer.join(timeout=2.0)
    assert not writer.is_alive()


def test_dataset_preview_rejects_huge_fps() -> None:
    """元数据中的超大 FPS 归为外部数据错误，不泄漏数值转换异常。"""
    data = (
        '{"total_episodes":1,"total_frames":1,"fps":1'
        + "0" * 400
        + ',"robot_type":null,"codebase_version":"v3.0","features":{}}'
    ).encode()
    request = DownloadRequest(
        repo_type="dataset", repo_id="org/repo", revision="main", storage_root="disk"
    )
    revision = RepositoryRevision(commit="a" * 40, gated=False, private=False, disabled=False)
    with pytest.raises(ExternalError):
        read_dataset_preview(
            request,
            revision,
            FakeTransport([HttpResponse(200, {}, data)]),
            token=None,
            sleep=lambda _: None,
        )


def test_manifest_preserves_safe_whitespace_path() -> None:
    """清单中安全文件名的段内及首尾空格不按目标目录规则删改。"""
    data = b'[{"type":"file","path":"folder/ file name .bin","size":1,"oid":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"}]'
    request = DownloadRequest(
        repo_type="model", repo_id="org/repo", revision="main", storage_root="disk"
    )
    revision = RepositoryRevision(commit="a" * 40, gated=False, private=False, disabled=False)
    files = list_files(
        request,
        revision,
        FakeTransport([HttpResponse(200, {}, data)]),
        token=None,
        sleep=lambda _: None,
    )
    assert files[0].path == "folder/ file name .bin"


def test_staging_symlink_file_is_not_complete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """暂存文件本身是软链接时，即使目标大小相同也不能算作完整。"""
    root = tmp_path / "root"
    root.mkdir()
    request, dependencies, _ = _plan_inputs(root)
    stage = root / "暂存" / "下载" / "model" / "org" / "repo@aaaaaaaaaaaa"
    stage.mkdir(parents=True)
    outside = tmp_path / "outside.bin"
    outside.write_bytes(b"xxxxxxxxxx")
    (stage / "model.bin").symlink_to(outside)
    _mock_free(monkeypatch, 10**12)
    assert build_plan(request, dependencies).capacity.complete_bytes == 0


def test_incomplete_staging_file_not_deducted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """暂存文件大小不符时保持全部待下载字节数。"""
    request, dependencies, _ = _plan_inputs(tmp_path)
    stage = tmp_path / "暂存" / "下载" / "model" / "org" / "repo@aaaaaaaaaaaa"
    stage.mkdir(parents=True)
    (stage / "model.bin").write_bytes(b"x" * 9)
    _mock_free(monkeypatch, 10**12)
    capacity = build_plan(request, dependencies).capacity
    assert capacity.complete_bytes == 0
    assert capacity.remaining_bytes == 10


def test_dataset_plan_contains_preview_and_filtered_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """数据集计划在固定提交读取预览并按不选视频筛选及计算容量。"""
    request, dependencies, transport = _plan_inputs(tmp_path)
    request = replace(request, repo_type="dataset", exclude_video=True)
    oid = "b" * 40
    transport.responses[-1] = HttpResponse(
        200,
        {},
        (
            '[{"type":"file","path":"meta/info.json","size":2,"oid":"'
            + oid
            + '"},{"type":"file","path":"videos/front/clip.mp4","size":3,"oid":"'
            + oid
            + '"}]'
        ).encode(),
    )
    transport.responses.append(
        HttpResponse(
            200,
            {},
            b'{"total_episodes":2,"total_frames":11,"fps":30,"robot_type":"arm","codebase_version":"v3.0","features":{"front":{"dtype":"video"}}}',
        )
    )
    _mock_free(monkeypatch, 10**12)
    result = build_plan(request, dependencies)
    assert result.preview == DatasetPreview(2, 11, 30.0, "arm", "v3.0", ("front",))
    assert [item.path for item in result.files] == ["meta/info.json"]
    assert result.capacity.remaining_bytes == 2
    assert "/resolve/" + "a" * 40 + "/meta/info.json" in transport.requests[-1][1]


def test_default_transport_returns_redirect_without_following(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """默认传输把 308 和 Location 原样返回而不跟随官方站。"""
    _mock_http_child(monkeypatch, "redirect")
    response = UrllibTransport().request("GET", "https://hf-mirror.com/", headers={}, timeout_s=2.0)
    assert response.status == 308
    assert response.headers["Location"] == "https://huggingface.co/"


def test_transport_rejects_nonread_method(monkeypatch: pytest.MonkeyPatch) -> None:
    """只读传输拒绝非 GET/HEAD 方法。"""
    _mock_http_child(monkeypatch, "normal")
    with pytest.raises(ExternalError):
        UrllibTransport().request("POST", "https://hf-mirror.com/", headers={}, timeout_s=2.0)


def test_capacity_probe_is_bounded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """剩余空间读取被卡住时，预检按存储访问预算失败且可释放测试线程。"""
    from threading import Event, Thread

    request, dependencies, _ = _plan_inputs(tmp_path)
    dependencies = replace(
        dependencies,
        checker=replace(dependencies.checker, options=StorageConfig(access_timeout_s=0.1)),
    )
    release = Event()
    finished = Event()

    def blocked_disk_usage(path: object) -> Usage:
        release.wait(timeout=2.0)
        finished.set()
        return Usage(10**12, 0, 10**12)

    def delayed_release() -> None:
        release.wait(timeout=0.8)
        release.set()

    monkeypatch.setattr("shutil.disk_usage", blocked_disk_usage)
    releaser = Thread(target=delayed_release)
    releaser.start()
    started = time.monotonic()
    try:
        with pytest.raises(ExternalError):
            build_plan(request, dependencies)
        assert time.monotonic() - started < 0.6
    finally:
        release.set()
        releaser.join(timeout=2.0)
        assert finished.wait(timeout=2.0)
    assert not releaser.is_alive()


def test_capacity_probe_propagates_checkpoint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """容量检查等待中，checkpoint 的取消异常向调用方传播。"""
    from threading import Event

    class StopProbeError(Exception):
        """表示调用方要求取消。"""

    request, dependencies, _ = _plan_inputs(tmp_path)
    started, release, done = Event(), Event(), Event()

    def blocked_disk_usage(path: object) -> Usage:
        started.set()
        release.wait(timeout=2.0)
        done.set()
        return Usage(10**12, 0, 10**12)

    def checkpoint() -> None:
        if started.is_set():
            raise StopProbeError

    dependencies = replace(dependencies, checkpoint=checkpoint)
    monkeypatch.setattr("shutil.disk_usage", blocked_disk_usage)
    try:
        with pytest.raises(StopProbeError):
            build_plan(request, dependencies)
    finally:
        release.set()
        assert done.wait(timeout=2.0)


def test_non_string_path_inputs_are_input_errors(tmp_path: Path) -> None:
    """不可信仓库编号或目标目录类型错误时按输入问题拒绝。"""
    root = StorageRootConfig(
        name="weights", path=tmp_path, nfs_export="host:/weights", writable=True
    )
    revision = RepositoryRevision(commit="a" * 40, gated=False, private=False, disabled=False)
    request = DownloadRequest(
        repo_type="model", repo_id="org/repo", revision="main", storage_root="weights"
    )
    with pytest.raises(InputError):
        model_weights_path(root, replace(request, repo_id=cast(str, None)), revision)
    with pytest.raises(InputError):
        model_weights_path(root, replace(request, target_subdir=cast(str, 42)), revision)


def test_default_transport_preserves_multiple_link_headers(monkeypatch: pytest.MonkeyPatch) -> None:
    """重复的 Link 响应头合并保留，避免下一页链接被后一个头覆盖。"""
    _mock_http_child(monkeypatch, "multi")
    response = UrllibTransport().request("GET", "https://hf-mirror.com/", headers={}, timeout_s=2.0)
    assert 'rel="next"' in response.headers["Link"]
    assert 'rel="prev"' in response.headers["Link"]


def test_transport_rejects_failed_child_even_with_output(monkeypatch: pytest.MonkeyPatch) -> None:
    """子进程异常退出时，不把其部分输出当成有效 HTTP 响应。"""

    def command() -> list[str]:
        return [
            sys.executable,
            "-c",
            'import sys; print(\'{"status":200,"headers":{},"body":"b2s="}\'); sys.exit(1)',
        ]

    monkeypatch.setattr(plan, "_child_command", command)
    with pytest.raises(OSError):
        UrllibTransport().request("GET", "https://hf-mirror.com/", headers={}, timeout_s=2.0)


def test_include_pattern_with_trailing_slash_matches_directory() -> None:
    """包含模式末尾的斜杠补星号，只保留该目录下的文件。"""
    files = tuple(
        HubFile(path=path, size_bytes=1, blob_sha1="a" * 40, lfs_sha256=None)
        for path in ("meta/info.json", "meta/nested/stats.json", "metadata/info.json", "data/a")
    )
    request = DownloadRequest(
        repo_type="dataset",
        repo_id="org/repo",
        revision="main",
        storage_root="disk",
        include=("meta/",),
    )
    assert tuple(item.path for item in filter_files(files, request, None)) == (
        "meta/info.json",
        "meta/nested/stats.json",
    )


def test_exclude_pattern_with_trailing_slash_matches_directory() -> None:
    """排除模式末尾的斜杠补星号，只排除该目录下的文件。"""
    files = tuple(
        HubFile(path=path, size_bytes=1, blob_sha1="a" * 40, lfs_sha256=None)
        for path in ("meta/info.json", "meta/nested/stats.json", "metadata/info.json", "data/a")
    )
    request = DownloadRequest(
        repo_type="dataset",
        repo_id="org/repo",
        revision="main",
        storage_root="disk",
        exclude=("meta/",),
    )
    assert tuple(item.path for item in filter_files(files, request, None)) == (
        "metadata/info.json",
        "data/a",
    )


def test_capacity_reserve_and_equality_boundary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """可用空间不足待下载量加余量时拒绝并报告余量，恰好相等时通过。"""
    # 假清单的待下载量为 10 字节；夹在两个阈值之间才能区分是否计入预留量。
    remaining = 10
    reserve = plan.SPACE_RESERVE_BYTES
    between = remaining + reserve // 2
    request, dependencies, _ = _plan_inputs(tmp_path)
    _mock_free(monkeypatch, between)
    with pytest.raises(ExternalError) as error:
        build_plan(request, dependencies)
    diagnostic = error.value.diagnostics[0]
    assert str(reserve) in diagnostic.actual
    assert str(remaining) in diagnostic.actual and str(between) in diagnostic.actual
    assert any(item.key == "storage_root" and item.value == "disk" for item in diagnostic.objects)

    request, dependencies, _ = _plan_inputs(tmp_path)
    _mock_free(monkeypatch, remaining + reserve)
    capacity = build_plan(request, dependencies).capacity
    assert capacity.remaining_bytes == remaining
    assert capacity.reserve_bytes == reserve
    assert capacity.available_bytes == remaining + reserve
