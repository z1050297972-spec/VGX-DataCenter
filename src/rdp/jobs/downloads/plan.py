"""只读生成下载计划；HTTP、重试等待及存储检查由调用方注入。"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Protocol

from rdp.infra.config import PlatformConfig, StorageRootConfig
from rdp.infra.storage import StorageAccessChecker

# 调研 §5.2：所有请求使用镜像，不能透明退回官方站。
MIRROR_ENDPOINT = "https://hf-mirror.com"
# 请求等待和重试均有上限；这些数值是本计划的保守预算，单位分别为秒、次、秒。
HTTP_TIMEOUT_S = 10.0
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
    """

    repo_type: RepoType
    repo_id: str
    revision: str
    storage_root: str
    include: tuple[str, ...] = ()
    exclude: tuple[str, ...] = ()
    exclude_video: bool = False
    exclude_cameras: tuple[str, ...] = ()


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
            OSError: 连接、TLS 或超时失败；异常不得包含 token。

        Side Effects:
            仅连接镜像，不读取代理环境变量，不写文件或日志。

        Time Semantics:
            连接及每次阻塞读取受 timeout_s 约束；不限制整个响应的总时长，不自行重试。
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
            OSError: 连接、TLS 或等待失败；不得泄漏敏感头部。

        Side Effects:
            与镜像通信；不使用代理、不写文件或日志。

        Time Semantics:
            连接及每次阻塞读取受 timeout_s 约束；不限制整个响应的总时长，不自行重试。
        """
        raise NotImplementedError


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
    raise NotImplementedError


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
        每次请求最多 HTTP_MAX_ATTEMPTS 次，间隔按 HTTP_BACKOFF_SECONDS，连接及每次阻塞读取超时 HTTP_TIMEOUT_S；不保证整次请求总时长上限。
    """
    raise NotImplementedError


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
        只解析一次可变版本；请求按 HTTP_MAX_ATTEMPTS 和 HTTP_BACKOFF_SECONDS 有限重试。
    """
    raise NotImplementedError


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
        顺序跟随 Link 的 rel=next，所有页面绑定同一 commit；每页各自有限重试。
    """
    raise NotImplementedError


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
        先于筛选读取，始终使用固定 commit；网络请求有限重试。
    """
    raise NotImplementedError


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
    raise NotImplementedError


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
    raise NotImplementedError


def model_weights_path(
    root: StorageRootConfig, request: DownloadRequest, revision: RepositoryRevision
) -> Path:
    """构造模型权重的最终落点，不操作导航层。

    Args:
        root: 已登记存储根，不在此检查在线或写许可。
        request: 模型请求，其 repo_id 使用与暂存路径相同的安全段规则。
        revision: 含完整 commit 的固定版本。

    Returns:
        根下 权重/命名空间/仓库@commit前12位 的路径。

    Raises:
        InputError: 请求不是模型，repo_id 不安全或 commit 无效。

    Side Effects:
        无；不创建路径、不写入权重或导航层。

    Time Semantics:
        相同根、仓库和提交得到相同路径，不读取当前时间。
    """
    raise NotImplementedError


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
        InputError: 仓库、版本、筛选或目标根输入不合法。
        ExternalError: 镜像失效、仓库不可用、目标非可写或离线、空间不足或只读检查失败；
            空间不足诊断包含存储根、待下载字节数、余量和可用字节数。
        DefectError: 注入的检查器或配置不一致。
        Exception: checkpoint 的取消或停止异常原样传播。

    Side Effects:
        只读 token、暂存文件大小及存储根剩余空间，发送镜像请求；不创建目录、不下载文件。
        检查暂存文件时不跟随软链接，不访问暂存目录外的路径。

    Time Semantics:
        先探测再解析 commit，再列清单、读预览、筛选和预检；空间与在线状态仅是当时的观察。
        每个网络请求有超时和有限重试；存储检查使用 checker 的等待预算。
    """
    raise NotImplementedError
