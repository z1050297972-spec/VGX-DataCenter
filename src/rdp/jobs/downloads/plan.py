"""只读生成下载计划；HTTP、重试等待及存储检查由调用方注入。"""

import base64
import errno
import json
import math
import os
import re
import shutil
import stat
import subprocess
import sys
import time
import unicodedata
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from fnmatch import fnmatchcase
from pathlib import Path
from threading import Event
from typing import Literal, NoReturn, Protocol, cast
from urllib.parse import quote, urljoin, urlsplit

from rdp.infra.config import PlatformConfig, StorageRootConfig
from rdp.infra.diagnostics import (
    DefectError,
    Diagnostic,
    DiagnosticCategory,
    DiagnosticLevel,
    DiagnosticObject,
    ExternalError,
    InputError,
)
from rdp.infra.storage import StorageAccessChecker
from rdp.jobs.registry import StorageUse
from rdp.jobs.storage import check_storage_before_job

# 调研 §5.2：所有请求使用镜像，不能透明退回官方站。
MIRROR_ENDPOINT = "https://hf-mirror.com"
_MIRROR_NETLOC = urlsplit(MIRROR_ENDPOINT).netloc
# 请求等待和重试均有上限；这些数值是本计划的保守预算，单位分别为秒、次、秒。
HTTP_TIMEOUT_S = 10.0
# 负责人批准：限制慢速响应和异常大载荷，避免请求无限占用资源。
HTTP_TOTAL_DEADLINE_S = 30.0
HTTP_MAX_BODY_BYTES = 16 * 1024 * 1024
# 子进程 JSON 响应头的额外预算，防止编码后的协议数据无限增长。
_MAX_IPC_HEADER_BYTES = 8 * 1024 * 1024
HTTP_MAX_ATTEMPTS = 3
HTTP_BACKOFF_SECONDS = (1.0, 2.0)
# 容量预检预留 1 GiB，降低文件系统元数据和并发写入导致空间不足的风险。
SPACE_RESERVE_BYTES = 1024**3
# token 与平台状态共同管理，不进入请求、计划或作业参数的数据模型。
CREDENTIAL_FILENAME = "hf_token"

type RepoType = Literal["dataset", "model"]


@dataclass(frozen=True)
class DownloadRequest:
    """用户选择；模式以 fnmatchcase 匹配仓库相对路径。

    Attributes:
        repo_type: dataset 或 model。
        repo_id: 命名空间/仓库名。
        revision: 非空分支、标签或 commit。
        storage_root: 已登记存储根名称。
        include: 包含模式，空元组表示全部。
        exclude: 排除模式，优先于包含模式。
        exclude_video: 是否排除全部视频，默认 False。
        exclude_cameras: 不要的视频相机键，默认空元组。
        target_subdir: 模型在所选存储根内的安全相对路径；None 使用默认路径，数据集必须为 None。
    """

    repo_type: RepoType
    repo_id: str
    revision: str
    storage_root: str
    include: tuple[str, ...] = ()
    exclude: tuple[str, ...] = ()
    exclude_video: bool = False
    exclude_cameras: tuple[str, ...] = ()
    target_subdir: str | None = None


@dataclass(frozen=True)
class RepositoryRevision:
    """已解析的提交和仓库访问状态。

    Attributes:
        commit: 完整 commit SHA。
        gated: 是否为受限仓库。
        private: 是否为私有仓库。
        disabled: 是否已禁用。
    """

    commit: str
    gated: bool
    private: bool
    disabled: bool


@dataclass(frozen=True)
class HubFile:
    """仓库文件校验信息。

    Attributes:
        path: 仓库内安全相对路径。
        size_bytes: 非负文件大小，单位字节。
        blob_sha1: git blob SHA-1。
        lfs_sha256: LFS SHA-256；非 LFS 文件为 None。
    """

    path: str
    size_bytes: int
    blob_sha1: str
    lfs_sha256: str | None


@dataclass(frozen=True)
class DatasetPreview:
    """meta/info.json 的数据集预览。

    Attributes:
        episodes: 非负 episode 数。
        frames: 非负帧数。
        fps: 正帧率，单位帧每秒。
        robot_type: 机器人类型；未知为 None。
        codebase_version: 数据集格式版本。
        cameras: 视频特征的相机键，保持元数据顺序。
    """

    episodes: int
    frames: int
    fps: float
    robot_type: str | None
    codebase_version: str
    cameras: tuple[str, ...]


@dataclass(frozen=True)
class Capacity:
    """本次只读容量观察，所有大小单位均为字节。

    Attributes:
        selected_bytes: 筛选后文件总大小。
        complete_bytes: 已完整文件大小之和。
        remaining_bytes: 筛选总量减已完整量。
        available_bytes: 存储根当时的可用空间。
        reserve_bytes: 留出的空间余量。
    """

    selected_bytes: int
    complete_bytes: int
    remaining_bytes: int
    available_bytes: int
    reserve_bytes: int


@dataclass(frozen=True)
class DownloadPlan:
    """可交给作业的快照；不含 token，空间观察不能保证后续仍可用。

    Attributes:
        request: 原始筛选和目标根选择。
        revision: 已固定的版本和访问状态。
        files: 筛选后的文件清单。
        preview: 数据集预览；模型为 None。
        staging_dir: 可复用的暂存路径。
        capacity: 容量观察。
    """

    request: DownloadRequest
    revision: RepositoryRevision
    files: tuple[HubFile, ...]
    preview: DatasetPreview | None
    staging_dir: Path
    capacity: Capacity


@dataclass(frozen=True)
class HttpResponse:
    """一次不跟随重定向的响应。

    Attributes:
        status: HTTP 状态码。
        headers: 响应头，保留 Link 和 Location。
        body: 响应体字节，不展示在 repr。
    """

    status: int
    headers: Mapping[str, str]
    body: bytes = field(repr=False)


class HttpTransport(Protocol):
    """不走代理、不自动重定向且支持超时的同步 HTTP 传输边界。"""

    def request(
        self, method: str, url: str, *, headers: Mapping[str, str], timeout_s: float
    ) -> HttpResponse:
        """发送一次 HTTP 请求并返回原始响应。

        Args:
            method: HEAD 或 GET。
            url: 镜像 HTTPS URL，不含凭据。
            headers: 请求头，可含敏感 Authorization，不得记录。
            timeout_s: 正的连接与读取等待上限，单位秒。

        Returns:
            原始状态、响应头和字节载荷，不自动跟随任何重定向。

        Raises:
            OSError: 连接或 TLS 失败；异常不得包含 token。
            ExternalError: 总耗时超过 HTTP_TOTAL_DEADLINE_S 或响应体超过 HTTP_MAX_BODY_BYTES。

        Side Effects:
            仅连接镜像，不读取代理环境变量，不写文件或日志。

        Time Semantics:
            连接及每次阻塞读取受 timeout_s 约束；总耗时不超过 HTTP_TOTAL_DEADLINE_S 秒，不自行重试。
        """
        raise NotImplementedError


class UrllibTransport:
    """使用标准库 urllib 的无代理、不跟随跳转的传输。"""

    def request(
        self, method: str, url: str, *, headers: Mapping[str, str], timeout_s: float
    ) -> HttpResponse:
        """发送一次不走代理、不跟随重定向的 HTTP 请求。

        Args:
            method: HEAD 或 GET。
            url: 镜像 HTTPS URL，不含凭据。
            headers: 请求头，可含 Authorization，禁止记录或回显。
            timeout_s: 正的连接与读取等待上限，单位秒。

        Returns:
            原始状态、响应头和响应体，包括非成功状态。

        Raises:
            OSError: 连接或 TLS 失败；不得泄漏敏感头部。
            ExternalError: 总耗时超过 HTTP_TOTAL_DEADLINE_S 或响应体超过 HTTP_MAX_BODY_BYTES。

        Side Effects:
            与镜像通信；不使用代理、不写文件或日志。
            启动并回收单次请求隔离子进程；超过总时长时终止子进程。

        Time Semantics:
            连接及每次阻塞读取受 timeout_s 约束；总耗时不超过 HTTP_TOTAL_DEADLINE_S 秒，不自行重试。
        """
        if method not in ("GET", "HEAD"):
            _raise_external("download.invalid_method", "镜像请求方法不是只读方法")
        parsed = urlsplit(url)
        if parsed.scheme != "https" or parsed.netloc != _MIRROR_NETLOC or parsed.fragment:
            _raise_external("download.invalid_url", "镜像请求地址不安全")
        # urllib 的逐次 socket 超时不能阻止服务器缓慢持续发送；隔离进程使总截止时可中断请求。
        return _bounded_request(method, url, headers, timeout_s)


def _child_command() -> list[str]:
    """隔离进程从标准输入接收敏感参数，命令行不携带凭据。"""
    return [sys.executable, "-m", "rdp.jobs.downloads._http_child"]


def _bounded_request(
    method: str, url: str, headers: Mapping[str, str], timeout_s: float
) -> HttpResponse:
    """通过安全启动的子进程隔离 urllib，并按单调时钟终止和回收。"""
    deadline = time.monotonic() + HTTP_TOTAL_DEADLINE_S
    message = json.dumps(
        {
            "method": method,
            "url": url,
            "headers": dict(headers),
            "timeout_s": timeout_s,
            "max_body_bytes": HTTP_MAX_BODY_BYTES,
        }
    ).encode("utf-8")
    try:
        # 命令只含当前解释器和固定代码；请求及凭据经标准输入，不参与命令构造。
        with subprocess.Popen(  # noqa: S603
            _child_command(),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        ) as child:
            try:
                payload, _ = child.communicate(
                    message, timeout=max(0.0, deadline - time.monotonic())
                )
            except BaseException:
                child.kill()
                child.communicate()
                raise
    except subprocess.TimeoutExpired:
        _raise_external("download.http_deadline", "镜像请求超过总时长")
    except OSError:
        raise OSError("镜像请求进程启动失败") from None
    # 即使输出看似完整，非零退出也不能证明子进程已正确完成请求。
    if child.returncode != 0:
        raise OSError("镜像请求进程异常退出")
    # Base64 最多膨胀到 4/3；另允许至多 8 MiB 响应头。
    limit = (HTTP_MAX_BODY_BYTES + 2) // 3 * 4 + _MAX_IPC_HEADER_BYTES
    if len(payload) > limit:
        _raise_external("download.http_body_limit", "镜像响应超过上限")
    if time.monotonic() > deadline:
        _raise_external("download.http_deadline", "镜像请求超过总时长")
    response = _decode_child_response(payload)
    if time.monotonic() > deadline:
        _raise_external("download.http_deadline", "镜像请求超过总时长")
    return response


def _decode_child_response(payload: bytes) -> HttpResponse:
    """解码子进程 JSON，拒绝不完整或超限结果。"""
    try:
        result: object = json.loads(payload)
        if not isinstance(result, dict):
            raise ValueError
        data = cast(dict[str, object], result)
        if data.get("error") == "oversize":
            _raise_external("download.http_body_limit", "镜像响应体超过上限")
        status, headers, body = data.get("status"), data.get("headers"), data.get("body")
        if type(status) is not int or not isinstance(headers, dict) or not isinstance(body, str):
            raise ValueError
        raw = base64.b64decode(body, validate=True)
        if len(raw) > HTTP_MAX_BODY_BYTES:
            _raise_external("download.http_body_limit", "镜像响应体超过上限")
        return HttpResponse(status=status, headers=cast(dict[str, str], headers), body=raw)
    except (ValueError, UnicodeError):
        raise OSError("镜像连接失败") from None


def read_token(config: PlatformConfig) -> str | None:
    """从状态目录读取镜像 token。

    Args:
        config: 已校验平台配置，其 state_dir 指定状态目录。

    Returns:
        token 文本；文件不存在返回 None，不暴露文件内容到日志。

    Raises:
        ExternalError: 文件不可读或权限不是 0600；诊断不得包含 token。
        InputError: 文件为空或内容不适合用作 HTTP 头。

    Side Effects:
        只读状态目录中的 CREDENTIAL_FILENAME，不创建或修改文件。

    Time Semantics:
        每次调用重新读取，不缓存凭据。
    """
    try:
        descriptor = os.open(
            config.state_dir / CREDENTIAL_FILENAME,
            # 非普通文件可能是 FIFO；非阻塞打开后用 fstat 拒绝，避免在校验前卡住。
            os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK,
        )
    except FileNotFoundError:
        return None
    except OSError:
        _raise_credential_error(external=True)
    try:
        with os.fdopen(descriptor, "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o600:
                _raise_credential_error(external=True)
            raw = stream.read()
    except OSError:
        _raise_credential_error(external=True)
    try:
        token = raw.decode("ascii").removesuffix("\n").removesuffix("\r")
    except UnicodeDecodeError:
        _raise_credential_error(external=False)
    if re.fullmatch(r"[!-~]+", token) is None:
        _raise_credential_error(external=False)
    return token


def _external_error(
    rule: str,
    actual: str,
    *,
    expected: str = "镜像服务正常可用",
    next_step: str = "检查镜像连接和仓库访问权限后重试",
) -> ExternalError:
    """构造不回显外部响应或凭据的外部失败诊断。"""
    return ExternalError(
        (
            Diagnostic(
                level=DiagnosticLevel.ERROR,
                category=DiagnosticCategory.EXTERNAL,
                stage="下载计划",
                source="平台",
                objects=(),
                rule=rule,
                actual=actual,
                expected=expected,
                consequence="未生成下载计划",
                next_step=next_step,
            ),
        )
    )


def _request(
    transport: HttpTransport,
    method: str,
    url: str,
    token: str | None,
    sleep: Callable[[float], None],
) -> HttpResponse:
    """对镜像发送请求，按有限预算重试连接及服务端临时故障。"""
    target = urlsplit(url)
    if target.scheme != "https" or target.netloc != _MIRROR_NETLOC or target.fragment:
        _raise_external("download.invalid_url", "镜像请求地址不安全")
    headers = {"Authorization": f"Bearer {token}"} if token is not None else {}
    last_reason = "镜像连接或服务失败，重试耗尽"
    for attempt in range(HTTP_MAX_ATTEMPTS):
        try:
            response = transport.request(method, url, headers=headers, timeout_s=HTTP_TIMEOUT_S)
        except ExternalError as error:
            # 只保留本模块稳定规则对应的固定文案，绝不回显替身或远端文本。
            code = error.diagnostics[0].rule
            last_reason = {
                "download.http_deadline": "镜像请求超过总时长，重试耗尽",
                "download.http_body_limit": "镜像响应超过上限，重试耗尽",
            }.get(code, "镜像连接或服务失败，重试耗尽")
            response = None
        except OSError:
            last_reason = "镜像连接失败，重试耗尽"
            response = None
        if response is not None:
            if response.status != 429 and not 500 <= response.status <= 599:
                return response
            last_reason = "镜像限流或服务不可用，重试耗尽"
        if attempt < HTTP_MAX_ATTEMPTS - 1:
            sleep(HTTP_BACKOFF_SECONDS[attempt])
    raise _external_error("download.request_failed", last_reason) from None


def _raise_external(
    rule: str, actual: str, *, next_step: str = "检查镜像连接和仓库访问权限后重试"
) -> NoReturn:
    """抛出不携带未过滤上游内容的外部诊断。"""
    raise _external_error(rule, actual, next_step=next_step) from None


def _json_object(response: HttpResponse) -> dict[str, object]:
    """校验成功响应的 JSON 对象，不回显响应内容。"""
    if response.status != 200:
        _raise_external("download.repository_unavailable", "仓库或镜像不可用")
    try:
        value: object = json.loads(response.body)
    except (ValueError, UnicodeError):
        _raise_external("download.invalid_response", "镜像返回无效 JSON")
    if not isinstance(value, dict) or not all(
        isinstance(key, str) for key in cast(dict[object, object], value)
    ):
        _raise_external("download.invalid_response", "镜像响应不是对象")
    return cast(dict[str, object], value)


def probe_mirror(transport: HttpTransport, *, sleep: Callable[[float], None]) -> None:
    """检查镜像首页和 API 是否重定向到官方站。

    Args:
        transport: 注入的无代理、不跟随跳转传输。
        sleep: 注入的同步退避函数，参数单位秒。

    Returns:
        无；两个探测均通过才返回。

    Raises:
        ExternalError: 任一请求的 3xx 指向官方站、请求失败或重试耗尽。

    Side Effects:
        对镜像发送 HEAD / 和 API GET，可调用 sleep；不跟随跳转。

    Time Semantics:
        每次请求总耗时不超过 HTTP_TOTAL_DEADLINE_S 秒，最多 HTTP_MAX_ATTEMPTS 次，
        间隔按 HTTP_BACKOFF_SECONDS；连接和阻塞读取超时 HTTP_TIMEOUT_S。
    """
    for method, url in (
        ("HEAD", f"{MIRROR_ENDPOINT}/"),
        ("GET", f"{MIRROR_ENDPOINT}/api/datasets/lerobot/pusht"),
    ):
        response = _request(transport, method, url, None, sleep)
        if 300 <= response.status < 400:
            _raise_external(
                "download.mirror_redirect",
                "镜像不生效，返回重定向",
                next_step="关闭 VPN，或让 hf-mirror.com 走直连后重试",
            )
        if not 200 <= response.status < 300:
            _raise_external("download.mirror_unavailable", "镜像探测失败")


def resolve_revision(
    request: DownloadRequest,
    transport: HttpTransport,
    *,
    token: str | None,
    sleep: Callable[[float], None],
) -> RepositoryRevision:
    """把数据集或模型版本解析为固定 commit 并检查访问状态。

    Args:
        request: 仓库类型、编号及分支、tag 或 commit。
        transport: 注入的镜像传输。
        token: 可选凭据，仅放在镜像请求头，不写入结果。
        sleep: 同步退避函数，参数单位秒。

    Returns:
        完整 commit 和 gated、private、disabled 状态。

    Raises:
        InputError: 仓库标识或版本非法。
        ExternalError: 仓库不可用、disabled、gated 未配置 token、响应无效或重试耗尽。

    Side Effects:
        向镜像发送版本查询并可能等待；不输出凭据或跟随重定向。

    Time Semantics:
        只解析一次可变版本；单次请求总耗时不超过 HTTP_TOTAL_DEADLINE_S 秒，
        按 HTTP_MAX_ATTEMPTS 和 HTTP_BACKOFF_SECONDS 有限重试。
    """
    parts = _repo_parts(request.repo_id)
    if (
        len(parts) != 2
        or request.repo_type not in ("dataset", "model")
        or not request.revision
        or any(ord(c) < 32 or ord(c) == 127 for c in request.revision)
    ):
        _raise_invalid_path()
    kind = "datasets" if request.repo_type == "dataset" else "models"
    url = f"{MIRROR_ENDPOINT}/api/{kind}/{parts[0]}/{parts[1]}/revision/{quote(request.revision, safe='')}"
    response = _request(transport, "GET", url, token, sleep)
    payload = _json_object(response)
    sha, gated = payload.get("sha"), payload.get("gated")
    private, disabled = payload.get("private"), payload.get("disabled")
    if (
        not isinstance(sha, str)
        or re.fullmatch(r"[0-9a-f]{40}", sha) is None
        or not (isinstance(gated, bool) or isinstance(gated, str) and gated in ("auto", "manual"))
        or not isinstance(private, bool)
        or not isinstance(disabled, bool)
    ):
        _raise_external("download.invalid_revision", "镜像返回无效仓库信息")
    if disabled:
        _raise_external("download.repository_disabled", "仓库已禁用")
    if gated and not token:
        _raise_external("download.token_required", "受限仓库需要 token，需要用户处理")
    return RepositoryRevision(commit=sha, gated=bool(gated), private=private, disabled=disabled)


def _parse_tree_entry(value: object) -> HubFile | None:
    """校验单条外部树记录，拒绝路径穿越和缺失的校验值。"""
    if not isinstance(value, dict):
        _raise_external("download.invalid_tree", "仓库清单条目无效")
    entry = cast(dict[str, object], value)
    if entry.get("type") == "directory":
        return None
    path, size, oid, lfs = entry.get("path"), entry.get("size"), entry.get("oid"), entry.get("lfs")
    if (
        entry.get("type") != "file"
        or not isinstance(path, str)
        or not isinstance(size, int)
        or isinstance(size, bool)
        or size < 0
        or not isinstance(oid, str)
        or re.fullmatch(r"[0-9a-f]{40}", oid) is None
    ):
        _raise_external("download.invalid_tree", "仓库文件条目无效")
    try:
        _file_parts(path)
    except InputError:
        _raise_external("download.invalid_tree", "仓库文件路径不安全")
    sha256: str | None = None
    if lfs is not None:
        if not isinstance(lfs, dict):
            _raise_external("download.invalid_tree", "LFS 校验值无效")
        item = cast(dict[str, object], lfs).get("oid")
        if not isinstance(item, str) or re.fullmatch(r"[0-9a-f]{64}", item) is None:
            _raise_external("download.invalid_tree", "LFS 校验值无效")
        sha256 = item
    return HubFile(path=path, size_bytes=size, blob_sha1=oid, lfs_sha256=sha256)


def _validate_page_url(url: str, path: str, seen: set[str]) -> None:
    """拒绝跨站、跨提交或循环的分页地址。"""
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.netloc != _MIRROR_NETLOC
        or parsed.path != path
        or parsed.fragment
        or url in seen
    ):
        _raise_external("download.invalid_pagination", "镜像分页地址不安全或重复")


def _next_page(response: HttpResponse, current: str) -> str | None:
    """从 Link 中提取下一页；拒绝歧义或格式损坏的地址。"""
    link = next((value for key, value in response.headers.items() if key.lower() == "link"), "")
    matches = re.findall(r'<([^>]+)>\s*;\s*rel="?next"?(?:\s*[,;]|\s*$)', link, re.IGNORECASE)
    if len(matches) > 1 or ("next" in link.lower() and not matches):
        _raise_external("download.invalid_pagination", "镜像分页格式无效")
    try:
        return urljoin(current, matches[0]) if matches else None
    except ValueError:
        _raise_external("download.invalid_pagination", "镜像分页地址格式无效")


def list_files(
    request: DownloadRequest,
    revision: RepositoryRevision,
    transport: HttpTransport,
    *,
    token: str | None,
    sleep: Callable[[float], None],
) -> tuple[HubFile, ...]:
    """递归列出固定 commit 的全部文件并跟随分页。

    Args:
        request: 仓库类型及编号。
        revision: 已固定的 commit，不再解析分支。
        transport: 注入的镜像传输。
        token: 可选凭据，只发送给镜像。
        sleep: 同步退避函数，参数单位秒。

    Returns:
        文件清单，含大小、git blob SHA-1 与可选 LFS SHA-256；不包含目录。

    Raises:
        ExternalError: 清单或分页无效、路径不安全或重复、下一页不属于镜像、请求失败或重试耗尽。

    Side Effects:
        只读请求镜像各页，不将 token 发送给其他主机或写入日志。

    Time Semantics:
        顺序跟随 Link 的 rel=next，所有页面绑定同一 commit；每页单次请求总耗时不超过 HTTP_TOTAL_DEADLINE_S 秒，各自有限重试。
    """
    parts = _repo_parts(request.repo_id)
    if (
        len(parts) != 2
        or request.repo_type not in ("dataset", "model")
        or re.fullmatch(r"[0-9a-f]{40}", revision.commit) is None
    ):
        _raise_external("download.invalid_tree", "仓库版本无效")
    kind = "datasets" if request.repo_type == "dataset" else "models"
    path = f"/api/{kind}/{parts[0]}/{parts[1]}/tree/{revision.commit}"
    url: str | None = f"{MIRROR_ENDPOINT}{path}?recursive=true&expand=false"
    seen_urls: set[str] = set()
    paths: set[str] = set()
    files: list[HubFile] = []
    while url is not None:
        _validate_page_url(url, path, seen_urls)
        seen_urls.add(url)
        response = _request(transport, "GET", url, token, sleep)
        if response.status != 200:
            _raise_external("download.tree_unavailable", "仓库清单不可用")
        try:
            entries: object = json.loads(response.body)
        except (ValueError, UnicodeError):
            _raise_external("download.invalid_tree", "仓库清单格式无效")
        if not isinstance(entries, list):
            _raise_external("download.invalid_tree", "仓库清单格式无效")
        for entry in cast(list[object], entries):
            item = _parse_tree_entry(entry)
            if item is not None:
                if item.path in paths:
                    _raise_external("download.invalid_tree", "仓库清单含重复路径")
                paths.add(item.path)
                files.append(item)
        url = _next_page(response, url)
    return tuple(files)


def _valid_fps(value: object) -> bool:
    """只接受可表示的有限正帧率，极大整数归为无效元数据。"""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return value > 0 and math.isfinite(value)
    except OverflowError:
        return False


def read_dataset_preview(
    request: DownloadRequest,
    revision: RepositoryRevision,
    transport: HttpTransport,
    *,
    token: str | None,
    sleep: Callable[[float], None],
) -> DatasetPreview:
    """从固定 commit 的 meta/info.json 读取数据集预览。

    Args:
        request: 数据集仓库请求；模型请求不适用。
        revision: 已解析的完整 commit。
        transport: 注入的镜像传输。
        token: 可选凭据，仅用于镜像请求头。
        sleep: 同步退避函数，参数单位秒。

    Returns:
        episode、帧数、FPS、机器人类型、版本和视频特征中的相机键。

    Raises:
        InputError: 请求不是数据集。
        ExternalError: 元数据缺失、格式无效、跳转或重试耗尽。

    Side Effects:
        只读请求镜像上的元数据，不保存载荷或凭据。

    Time Semantics:
        先于筛选读取，始终使用固定 commit；单次网络请求总耗时不超过 HTTP_TOTAL_DEADLINE_S 秒，且有限重试。
    """
    parts = _repo_parts(request.repo_id)
    if (
        request.repo_type != "dataset"
        or len(parts) != 2
        or re.fullmatch(r"[0-9a-f]{40}", revision.commit) is None
    ):
        _raise_invalid_path()
    url = (
        f"{MIRROR_ENDPOINT}/datasets/{parts[0]}/{parts[1]}/resolve/{revision.commit}/meta/info.json"
    )
    info = _json_object(_request(transport, "GET", url, token, sleep))
    episodes, frames, fps = info.get("total_episodes"), info.get("total_frames"), info.get("fps")
    robot, version, features = (
        info.get("robot_type"),
        info.get("codebase_version"),
        info.get("features"),
    )
    if (
        type(episodes) is not int
        or episodes < 0
        or type(frames) is not int
        or frames < 0
        or not _valid_fps(fps)
        or (robot is not None and not isinstance(robot, str))
        or not isinstance(version, str)
        or not version
        or not isinstance(features, dict)
    ):
        _raise_external("download.invalid_metadata", "数据集预览元数据无效")
    cameras: list[str] = []
    for key, value in cast(dict[object, object], features).items():
        if not isinstance(key, str) or not isinstance(value, dict):
            _raise_external("download.invalid_metadata", "数据集特征元数据无效")
        if cast(dict[str, object], value).get("dtype") == "video":
            cameras.append(key)
    return DatasetPreview(
        episodes, frames, float(cast(int | float, fps)), robot, version, tuple(cameras)
    )


def filter_files(
    files: tuple[HubFile, ...], request: DownloadRequest, preview: DatasetPreview | None
) -> tuple[HubFile, ...]:
    """按用户模式和视频、相机选择筛选文件。

    Args:
        files: 固定 commit 的文件元组。
        request: 包含、排除模式及便捷筛选；末尾斜杠补星号。
        preview: 数据集预览，指定排除相机时必填。

    Returns:
        保持清单顺序的文件元组；空包含模式表示全部，排除优先。

    Raises:
        InputError: 相机筛选缺少预览或相机键不在预览中。

    Side Effects:
        无；不读网络或文件系统。

    Time Semantics:
        只使用传入快照；匹配为区分大小写的 fnmatchcase，星号可跨斜杠。
    """
    if request.exclude_cameras and (
        preview is None or not set(request.exclude_cameras) <= set(preview.cameras)
    ):
        raise InputError(
            (
                Diagnostic(
                    level=DiagnosticLevel.ERROR,
                    category=DiagnosticCategory.INPUT,
                    stage="下载计划",
                    source="平台",
                    objects=(),
                    rule="download.invalid_camera",
                    actual="排除的相机不在数据集预览中",
                    expected="选择预览中列出的相机",
                    consequence="未生成筛选清单",
                    next_step="重新选择相机",
                ),
            )
        )
    include = tuple(
        pattern + "*" if pattern.endswith("/") else pattern for pattern in request.include
    )
    exclude = tuple(
        pattern + "*" if pattern.endswith("/") else pattern for pattern in request.exclude
    )
    return tuple(
        item
        for item in files
        if (not include or any(fnmatchcase(item.path, pattern) for pattern in include))
        and not any(fnmatchcase(item.path, pattern) for pattern in exclude)
        and not (request.exclude_video and item.path.startswith("videos/"))
        and not any(item.path.startswith(f"videos/{camera}/") for camera in request.exclude_cameras)
    )


def staging_path(
    root: StorageRootConfig, request: DownloadRequest, revision: RepositoryRevision
) -> Path:
    """构造可复用的下载暂存路径。

    Args:
        root: 已登记存储根；此函数不检查在线状态。
        request: 仓库类型和由恰好两个安全路径段组成的 repo_id。
        revision: 含完整 commit 的固定版本。

    Returns:
        根下 暂存/下载/类型/命名空间/仓库@commit前12位 的路径。

    Raises:
        InputError: repo_id 为绝对路径、含空段、点段、反斜线或其他不安全字符，或 commit 无效。

    Side Effects:
        无；不创建目录、不解析软链接。

    Time Semantics:
        相同根、类型、编号和 commit 始终得到同一路径。
    """
    parts = _repo_parts(request.repo_id)
    if (
        len(parts) != 2
        or request.repo_type not in ("dataset", "model")
        or re.fullmatch(r"[0-9a-f]{40}", revision.commit) is None
    ):
        _raise_invalid_path()
    return (
        root.path
        / "暂存"
        / "下载"
        / request.repo_type
        / parts[0]
        / f"{parts[1]}@{revision.commit[:12]}"
    )


def _raise_credential_error(*, external: bool) -> NoReturn:
    """只报告凭据的读取状态，不回显内容或底层异常。"""
    category = DiagnosticCategory.EXTERNAL if external else DiagnosticCategory.INPUT
    diagnostic = Diagnostic(
        level=DiagnosticLevel.ERROR,
        category=category,
        stage="下载计划",
        source="平台",
        objects=(),
        rule="download.credential_unavailable" if external else "download.credential_invalid",
        actual="凭据文件不可读或权限不正确" if external else "凭据内容不合法",
        expected="权限为 0600 的有效凭据文件",
        consequence="未生成下载计划",
        next_step="请管理员检查凭据设置",
    )
    if external:
        raise ExternalError((diagnostic,)) from None
    raise InputError((diagnostic,)) from None


def _raise_invalid_path() -> NoReturn:
    """以固定文本报告不安全输入，避免回显不可信内容。"""
    raise InputError(
        (
            Diagnostic(
                level=DiagnosticLevel.ERROR,
                category=DiagnosticCategory.INPUT,
                stage="下载计划",
                source="平台",
                objects=(),
                rule="download.invalid_path",
                actual="仓库或目标路径不合法",
                expected="安全的相对路径及完整提交编号",
                consequence="未生成下载路径",
                next_step="检查仓库编号、目标路径和提交编号",
            ),
        )
    )


def _repo_parts(value: str) -> tuple[str, ...]:
    """拒绝跨目录、控制字符和不受支持的路径段。"""
    if not isinstance(cast(object, value), str):
        _raise_invalid_path()
    parts = value.split("/")
    if any(
        part in {"", ".", ".."} or re.fullmatch(r"[A-Za-z0-9._-]+", part) is None for part in parts
    ):
        _raise_invalid_path()
    return tuple(parts)


def _target_parts(value: str) -> tuple[str, ...]:
    """按段拒绝控制字符、首尾空白和跨目录目标。"""
    if not isinstance(cast(object, value), str):
        _raise_invalid_path()
    parts = value.split("/")
    if any(
        not part
        or part in {".", ".."}
        or part != part.strip()
        or "\\" in part
        or any(unicodedata.category(char) == "Cc" for char in part)
        for part in parts
    ):
        _raise_invalid_path()
    return tuple(parts)


def _file_parts(value: str) -> tuple[str, ...]:
    """保留仓库文件名空白，同时拒绝跨目录和控制字符。"""
    parts = value.split("/")
    if any(
        not part
        or part in {".", ".."}
        or "\\" in part
        or any(unicodedata.category(char) == "Cc" for char in part)
        for part in parts
    ):
        _raise_invalid_path()
    return tuple(parts)


def model_weights_path(
    root: StorageRootConfig, request: DownloadRequest, revision: RepositoryRevision
) -> Path:
    """构造模型权重的最终落点，不操作导航层。

    Args:
        root: 已登记存储根，不在此检查在线或写许可。
        request: 模型请求，repo_id 为 ASCII；target_subdir 可含中文及段内空格。
        revision: 含完整 commit 的固定版本。

    Returns:
        根下 target_subdir；未指定时为根下 命名空间/仓库@commit前12位。

    Raises:
        InputError: 请求不是模型，repo_id 或 target_subdir 不安全，或 commit 无效。

    Side Effects:
        无；不创建路径、不写入权重或导航层。

    Time Semantics:
        相同输入得到相同路径，不读取当前时间。
    """
    parts = _repo_parts(request.repo_id)
    if (
        request.repo_type != "model"
        or len(parts) != 2
        or re.fullmatch(r"[0-9a-f]{40}", revision.commit) is None
    ):
        _raise_invalid_path()
    if request.target_subdir is not None:
        return root.path.joinpath(*_target_parts(request.target_subdir))
    return root.path / parts[0] / f"{parts[1]}@{revision.commit[:12]}"


def _complete_bytes(root: Path, stage: Path, files: tuple[HubFile, ...], abandoned: Event) -> int:
    """用 dir_fd 和 O_NOFOLLOW 逐段检查暂存文件大小，绝不打开文件内容。"""
    stage_parts = stage.relative_to(root).parts
    try:
        root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    except OSError:
        _raise_external("download.staging_unavailable", "无法检查暂存目录")
    total = 0
    try:
        for item in files:
            if abandoned.is_set():
                return total
            fd = os.dup(root_fd)
            try:
                parts = (*stage_parts, *_file_parts(item.path))
                for segment in parts[:-1]:
                    if abandoned.is_set():
                        return total
                    next_fd = os.open(
                        segment,
                        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                        dir_fd=fd,
                    )
                    os.close(fd)
                    fd = next_fd
                info = os.stat(parts[-1], dir_fd=fd, follow_symlinks=False)
                if stat.S_ISREG(info.st_mode) and info.st_size == item.size_bytes:
                    total += item.size_bytes
            except OSError as error:
                if error.errno not in (errno.ENOENT, errno.ENOTDIR, errno.ELOOP):
                    _raise_external("download.staging_unavailable", "无法检查暂存文件")
            finally:
                os.close(fd)
    finally:
        os.close(root_fd)
    return total


def _capacity_snapshot(
    root: StorageRootConfig,
    stage: Path,
    files: tuple[HubFile, ...],
    dependencies: "PlanDependencies",
) -> tuple[int, int]:
    """复用 worker 检查器的整体等待预算、取消机制和挂载身份检查。"""
    abandoned = Event()
    outcome: list[tuple[int, int]] = []

    def access(path: Path) -> None:
        dependencies.checker.access(path)
        if abandoned.is_set():
            return
        available = shutil.disk_usage(path).free
        if abandoned.is_set():
            return
        try:
            complete = _complete_bytes(path, stage, files, abandoned)
        except ExternalError:
            raise OSError("无法检查暂存文件") from None
        if not abandoned.is_set():
            outcome.append((available, complete))

    # 扩展已有 access 回调而不复制挂载与有界等待算法；迟到 I/O 返回后不再进入下一步。
    checker = replace(dependencies.checker, access=access)
    try:
        check_storage_before_job(
            (StorageUse(name=root.name, write=True),),
            checker=checker,
            checkpoint=dependencies.checkpoint,
        )
    finally:
        abandoned.set()
    if not outcome:
        raise DefectError()
    return outcome[0]


def _raise_insufficient_space(root: str, capacity: Capacity) -> NoReturn:
    """报告目标根所需字节、余量及可用字节。"""
    raise ExternalError(
        (
            Diagnostic(
                level=DiagnosticLevel.ERROR,
                category=DiagnosticCategory.EXTERNAL,
                stage="下载计划",
                source="平台",
                objects=(DiagnosticObject(key="storage_root", value=root),),
                rule="download.insufficient_space",
                actual=f"待下载 {capacity.remaining_bytes} 字节，预留 {capacity.reserve_bytes} 字节，可用 {capacity.available_bytes} 字节",
                expected="可用空间不少于待下载量与预留量之和",
                consequence="未生成下载计划",
                next_step="释放空间或选择其他可写存储根",
            ),
        )
    )


@dataclass(frozen=True)
class PlanDependencies:
    """生成计划所需的只读环境和可注入外部操作。

    Attributes:
        config: 平台配置。
        checker: worker 存储访问检查器。
        transport: 无代理、无自动跳转的 HTTP 传输。
        sleep: 同步退避回调，参数为秒。
        checkpoint: 检查等待时的取消或停止回调。
    """

    config: PlatformConfig
    checker: StorageAccessChecker
    transport: HttpTransport
    sleep: Callable[[float], None]
    checkpoint: Callable[[], None]


def build_plan(request: DownloadRequest, dependencies: PlanDependencies) -> DownloadPlan:
    """生成固定版本的下载清单、预览和容量预检。

    Args:
        request: 用户选择及已登记目标存储根名称。
        dependencies: 平台配置、worker 存储检查器、无代理 HTTP 传输、
            同步退避函数（参数单位秒）及取消或停止检查。

    Returns:
        不含 token 的计划；数据集预览非空，模型预览为 None。

    Raises:
        InputError: 仓库、版本、筛选或目标根输入不合法，或数据集填写 target_subdir。
        ExternalError: 镜像失效、仓库不可用、目标非可写或离线、空间不足或只读检查失败；
            空间不足诊断包含存储根、待下载字节数、余量和可用字节数。
        DefectError: 注入的检查器或配置不一致。
        Exception: checkpoint 的取消或停止异常原样传播。

    Side Effects:
        只读 token、暂存文件大小及存储根剩余空间，发送镜像请求；不创建目录、不下载文件。
        检查暂存文件时不跟随软链接，不访问暂存目录外的路径。

    Time Semantics:
        先探测再解析 commit，再列清单、读预览、筛选和预检；空间与在线状态仅是当时的观察。
        每个网络请求总耗时不超过 HTTP_TOTAL_DEADLINE_S 秒，且有限重试；存储检查使用 checker 的等待预算。
    """
    if request.repo_type == "dataset" and request.target_subdir is not None:
        _raise_invalid_path()
    roots = [
        root for root in dependencies.config.storage_roots if root.name == request.storage_root
    ]
    if len(roots) != 1:
        _raise_invalid_path()
    root = roots[0]
    if dependencies.checker.mounts.roots != dependencies.config.storage_roots:
        raise DefectError()
    token = read_token(dependencies.config)
    probe_mirror(dependencies.transport, sleep=dependencies.sleep)
    revision = resolve_revision(
        request, dependencies.transport, token=token, sleep=dependencies.sleep
    )
    files = list_files(
        request, revision, dependencies.transport, token=token, sleep=dependencies.sleep
    )
    preview = (
        read_dataset_preview(
            request, revision, dependencies.transport, token=token, sleep=dependencies.sleep
        )
        if request.repo_type == "dataset"
        else None
    )
    selected = filter_files(files, request, preview)
    stage = staging_path(root, request, revision)
    if request.repo_type == "model":
        model_weights_path(root, request, revision)
    available, complete = _capacity_snapshot(root, stage, selected, dependencies)
    total = sum(item.size_bytes for item in selected)
    capacity = Capacity(total, complete, total - complete, available, SPACE_RESERVE_BYTES)
    if available < capacity.remaining_bytes + capacity.reserve_bytes:
        _raise_insufficient_space(root.name, capacity)
    return DownloadPlan(request, revision, selected, preview, stage, capacity)
