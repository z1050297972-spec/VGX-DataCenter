"""下载作业契约；计划复用 plan，外部进程、RPC、校验和持久通道由执行入口注入。

本模块不实现 HTTP 或散列算法：分别复用既有计划和标准库；只定义可替换的边界。
"""

import ctypes
import errno
import json
import os
import stat
from collections.abc import Mapping
from contextlib import suppress
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Annotated, Literal, Protocol, cast
from urllib.parse import quote, urljoin, urlsplit

from pydantic import BaseModel, ConfigDict, Field

from rdp.infra.db.validation import invalid_field
from rdp.infra.diagnostics import (
    DefectError,
    Diagnostic,
    DiagnosticCategory,
    DiagnosticLevel,
    ExternalError,
    InputError,
)
from rdp.jobs.downloads._context import bind
from rdp.jobs.downloads.plan import (
    HTTP_TIMEOUT_S,
    MIRROR_ENDPOINT,
    DownloadPlan,
    DownloadRequest,
    HttpResponse,
    HubFile,
    PlanDependencies,
    build_plan,
    model_weights_path,
    probe_mirror,
    read_token,
)
from rdp.jobs.execution import ExecutionContext
from rdp.jobs.types import JobProgress

# aria2 的 K/M/G 以 1024 为基数，输入统一为字节，避免界面和执行端解释不一致。
MIB = 1024 * 1024
GIB = 1024 * MIB
# 远高于本机网卡，只为让值落在 SQLite INTEGER 内。
MAX_DOWNLOAD_LIMIT_BYTES_PER_S = 10 * GIB
# 五跳覆盖镜像到 CDN 的常见跳转，限制循环和不可信响应带来的请求预算。
MAX_REDIRECT_HOPS = 5
# 每分钟复探镜像，缩小代理或 VPN 状态变化后的暴露窗口。
MIRROR_RECHECK_INTERVAL_S = 60
DownloadLimit = (
    Annotated[int, Field(strict=True, ge=0, le=0)]
    | Annotated[int, Field(strict=True, ge=1024, le=MAX_DOWNLOAD_LIMIT_BYTES_PER_S)]
)


class DownloadParameters(BaseModel):
    """可持久化的下载请求与 aria2 参数；凭据不属于请求，也不能通过额外字段注入。

    Attributes:
        repo_type: dataset 或 model。
        repo_id: 命名空间/仓库名。
        revision: 非空版本，具体合法性由下载计划检查。
        storage_root: 已登记可写存储根名称。
        include: 包含模式，空表示全部。
        exclude: 排除模式，优先于 include。
        exclude_video: 排除全部视频。
        exclude_cameras: 排除的视频相机键。
        target_subdir: 模型目标相对路径；数据集必须为 None，由计划校验。
        max_concurrent_downloads: 同时下载文件数，1-16，默认 4。
        max_connection_per_server: 每服务器连接数，1-16，默认 4。
        split: 每文件分段数，1-16，默认 4。
        min_split_size_bytes: 最小分段大小，1 MiB-1 GiB，默认 20 MiB。
        max_overall_download_limit_bytes_per_s: 总速率，0 不限或 1024 至 10 GiB/s。
        max_tries: 最大尝试次数，1-20，默认 5。
        retry_wait_s: 重试间隔，0-600 秒，默认 10 秒。
    """

    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)
    repo_type: Literal["dataset", "model"]
    repo_id: str = Field(min_length=1)
    revision: str = Field(min_length=1)
    storage_root: str = Field(min_length=1)
    include: tuple[str, ...] = ()
    exclude: tuple[str, ...] = ()
    exclude_video: bool = Field(default=False, strict=True)
    exclude_cameras: tuple[str, ...] = ()
    target_subdir: str | None = None
    max_concurrent_downloads: int = Field(default=4, strict=True, ge=1, le=16)
    max_connection_per_server: int = Field(default=4, strict=True, ge=1, le=16)
    split: int = Field(default=4, strict=True, ge=1, le=16)
    min_split_size_bytes: int = Field(default=20 * MIB, strict=True, ge=MIB, le=GIB)
    max_overall_download_limit_bytes_per_s: DownloadLimit = 0
    max_tries: int = Field(default=5, strict=True, ge=1, le=20)
    retry_wait_s: int = Field(default=10, strict=True, ge=0, le=600)


class DownloadAdjustment(BaseModel):
    """运行中唯一允许调整的两项；None 表示保持，不接受凭据或其他选项。"""

    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)
    max_concurrent_downloads: int | None = Field(default=None, strict=True, ge=1, le=16)
    max_overall_download_limit_bytes_per_s: DownloadLimit | None = None


@dataclass(frozen=True)
class TransferStatus:
    """RPC 观察快照，不含服务器原始响应或凭据。

    Attributes:
        gid: aria2 文件标识。
        state: 标准化状态。
        completed_bytes: 已完成字节数。
        speed_bytes_per_s: 当前速度，bytes/s。
        http_status: 已知 HTTP 状态码，否则 None。
        aria2_error_code: aria2 错误码，不适用时为 None。
    """

    gid: str
    state: Literal["active", "waiting", "complete", "error", "removed"]
    completed_bytes: int
    speed_bytes_per_s: int
    http_status: int | None = None
    aria2_error_code: int | None = None


class MirrorRangeTransport(Protocol):
    """镜像首跳的单字节请求能力，与计划的完整响应传输隔离。"""

    def request(
        self, method: str, url: str, *, headers: Mapping[str, str], timeout_s: float
    ) -> HttpResponse:
        """发起一项镜像 Range 请求，最多读取首字节。

        Args:
            method: GET。
            url: 镜像 HTTPS resolve 地址。
            headers: Range 和可选镜像授权头。
            timeout_s: 连接和读取超时，正数秒。

        Returns:
            单次响应的状态、头和最多一个字节的响应体。

        Raises:
            ExternalError: 地址非法或请求失败。

        Side Effects:
            不走代理地访问镜像，不跟随跳转。

        Time Semantics:
            总截止沿用下载计划的传输预算。
        """
        raise NotImplementedError


class RedirectTransport(Protocol):
    """对已校验的非首跳地址执行一次不带凭据的 HTTPS 访问。"""

    def request(self, url: str, *, timeout_s: float) -> HttpResponse:
        """请求一个已经通过重定向策略检查的地址。

        Args:
            url: 不含用户信息的 HTTPS 地址，主机由调用方验证。
            timeout_s: 单次连接及读取等待的正数上限，单位秒。

        Returns:
            该次响应状态、响应头和有界载荷，不自动跟随跳转。

        Raises:
            ExternalError: 地址非法、网络失败、超时或响应体超过限制。

        Side Effects:
            以 GET 和 Range bytes=0-0 发送一次请求；不使用代理或令牌。

        Time Semantics:
            总时长不超过 HTTP_TOTAL_DEADLINE_S；不自行重试。
        """
        raise NotImplementedError


class Aria2Rpc(Protocol):
    """仅允许本地 RPC，RPC 密钥与文件凭据不得写入日志或作业记录。"""

    def add_file(self, url: str, target: Path, file: HubFile, token: str | None) -> str:
        """添加单文件并为 LFS 指定 sha256，令牌仅经请求头传递。

        Args:
            url: 逐跳预解析到 200/206 的 HTTPS 下载地址。
            target: 暂存目录内的文件路径。
            file: 文件大小及哈希元数据。
            token: 可选凭据，不进入参数、命令行或日志。

        Returns:
            aria2 的 GID。

        Raises:
            ExternalError: RPC 或下载地址不满足契约。

        Side Effects:
            调用 aria2.addUri，可能创建或续写暂存文件。

        Time Semantics:
            单次有界 RPC；不自行重试。
        """
        raise NotImplementedError

    def status(self, gid: str) -> TransferStatus:
        """读取指定文件的进度快照。

        Args:
            gid: add_file 返回的非空标识。

        Returns:
            当前状态及 bytes、bytes/s。

        Raises:
            ExternalError: RPC 失败或响应不合法。

        Side Effects:
            向本地 aria2 发送只读 RPC。

        Time Semantics:
            只代表本次观察，不保证后续状态不变。
        """
        raise NotImplementedError

    def change_global_options(self, adjustment: DownloadAdjustment) -> None:
        """调用 changeGlobalOption 应用允许的选项。

        Args:
            adjustment: 非空修改项，速率单位 bytes/s。

        Returns:
            无；RPC 确认后才能记录生效值。

        Raises:
            ExternalError: RPC 拒绝或不可达。

        Side Effects:
            改变当前 aria2 全局选项。

        Time Semantics:
            以 RPC 成功响应为生效时刻。
        """
        raise NotImplementedError

    def stop(self, gids: tuple[str, ...]) -> None:
        """依次 forceRemove 未完成项并 shutdown，不删除暂存目录。

        Args:
            gids: 本次执行的未完成文件标识。

        Returns:
            无。

        Raises:
            ExternalError: RPC 停止失败；调用方仍须终止进程组。

        Side Effects:
            停止 aria2 文件及服务。

        Time Semantics:
            RPC 有界等待，先移除再关闭。
        """
        raise NotImplementedError


class Aria2Process(Protocol):
    """由已有进程组设施实现的 aria2 生命周期边界。"""

    def start(self, parameters: DownloadParameters) -> Aria2Rpc:
        """启动仅监听回环的 aria2 RPC 进程。

        Args:
            parameters: 已验证选项，不含凭据。

        Returns:
            连接该进程的 RPC 客户端。

        Raises:
            ExternalError: 可执行文件不可用或启动超时。

        Side Effects:
            创建进程组；生成随机 RPC secret，仅监听 127.0.0.1，禁用代理，
            启用续传、关闭自动重命名和预分配；凭据不放进程命令行。

        Time Semantics:
            进程就绪后返回，随机 RPC 密钥不得进入日志。
        """
        raise NotImplementedError

    def terminate(self) -> None:
        """通过现有进程组策略 TERM 后 KILL。

        Args:
            无。

        Returns:
            无。

        Raises:
            ExternalError: 进程无法终止。

        Side Effects:
            终止进程组；不删除暂存文件。

        Time Semantics:
            TERM 与 KILL 顺序和期限由 M0 进程设施控制。
        """
        raise NotImplementedError


class CurlFallback(Protocol):
    """可替换的单文件 curl 兜底边界。"""

    def download(
        self, url: str, target: Path, token: str | None, parameters: DownloadParameters
    ) -> None:
        """对单文件续传，逐跳验证地址并沿用限速与重试。

        Args:
            url: 初始镜像地址。
            target: 暂存文件路径。
            token: 可选凭据，不进入命令行或日志。
            parameters: 限速 bytes/s 与最大尝试次数。

        Returns:
            无；返回不代表文件校验通过。

        Raises:
            ExternalError: 下载失败、重定向违规或次数耗尽。

        Side Effects:
            调用 curl 并续写暂存文件；不跟随官方站。

        Time Semantics:
            最多指定次数，等待可被作业取消打断。
        """
        raise NotImplementedError


class FileVerifier(Protocol):
    """文件大小与 Git blob SHA-1 或 LFS SHA-256 校验边界。"""

    def verify(self, path: Path, file: HubFile) -> bool:
        """校验文件大小与清单指定的散列。

        Args:
            path: 暂存目录内的文件。
            file: 期望大小及散列。

        Returns:
            大小和散列均匹配为 True，否则 False。

        Raises:
            ExternalError: 无法读取文件。

        Side Effects:
            只读文件，不改变内容。

        Time Semantics:
            校验观察期间文件须不被其他写入者修改。
        """
        raise NotImplementedError


@dataclass(frozen=True)
class DownloadStatus:
    """下载详情增量快照；其余通用进度仍由 M0 作业接口提供。

    Attributes:
        requested_version: 最近提交版本，非负。
        applied_version: 最近应用版本，非负且不超过请求版本。
        requested: 用户要求的完整并发和限速。
        effective: 当前实际并发和限速。
        speed_bytes_per_s: 传输速度，非负 bytes/s。
        total_files: 清单文件总数，非负。
        completed_files: 成功下载且校验的文件数，非负，不含跳过。
        failed_files: 失败文件数，非负。
        skipped_files: 已校验跳过文件数，非负。
    """

    requested_version: int
    applied_version: int
    requested: DownloadAdjustment
    effective: DownloadAdjustment
    speed_bytes_per_s: int
    total_files: int
    completed_files: int
    failed_files: int
    skipped_files: int


class AdjustmentChannel(Protocol):
    """版本化调参通道；旧应答不能覆盖更新的请求。"""

    def initialize(self, job_id: int, initial: DownloadAdjustment) -> None:
        """只在通道不存在时保存初始并发和速率。

        Args:
            job_id: 下载作业正整数编号。
            initial: 两项均非空，速率单位 bytes/s。

        Returns:
            无；已有调参记录不覆盖。

        Raises:
            InputError: 作业类型、编号或初值非法。
            ExternalError: 数据库写入失败。

        Side Effects:
            在受管数据库中按需新建一行。

        Time Semantics:
            应在启动 aria2 前完成；恢复时保留已有版本。
        """
        raise NotImplementedError

    def submit(self, job_id: int, adjustment: DownloadAdjustment) -> int:
        """原子合并新调整并增加请求版本。

        Args:
            job_id: 正整数下载作业编号，必须仍在运行。
            adjustment: 至少一项非空；速率单位 bytes/s。

        Returns:
            新的正整数版本号。

        Raises:
            InputError: 参数无效或作业不是下载类型。
            ConflictError: 作业不在运行或并发更新冲突。
            ExternalError: 数据库不可用。

        Side Effects:
            同事务更新请求完整目标，不发送 RPC。

        Time Semantics:
            版本在事务提交时生效，不能覆盖并发提交的另一字段。
        """
        raise NotImplementedError

    def read(self, job_id: int) -> DownloadStatus:
        """读取调参与进度的单事务快照。

        Args:
            job_id: 正整数下载作业编号。

        Returns:
            已提交、已应用选项和文件进度快照。

        Raises:
            InputError: 作业不存在或不是下载类型。
            ExternalError: 数据库读取失败。

        Side Effects:
            只读数据库。

        Time Semantics:
            数据截至最近一次 worker 上报，并非实时网络速率。
        """
        raise NotImplementedError

    def report(self, job_id: int, status: DownloadStatus) -> None:
        """发布下载速度和文件计数，不覆盖并发提交的请求。

        Args:
            job_id: 正整数下载作业编号。
            status: 当前完整快照，速度为 bytes/s；只写进度字段。

        Returns:
            无。

        Raises:
            ExternalError: 数据库写入失败。
            DefectError: 计数为负、相互矛盾或超出总文件数。

        Side Effects:
            同事务写入速度及文件计数，不写请求或生效版本。

        Time Semantics:
            由单调时钟限频每秒最多一次，最终快照可强制保存。
        """
        raise NotImplementedError

    def pending(self, job_id: int) -> tuple[int, DownloadAdjustment] | None:
        """读取待生效调整的版本和完整目标值。

        Args:
            job_id: 正整数作业编号。

        Returns:
            待生效版本和目标值；无待处理时为 None。

        Raises:
            ExternalError: 数据库读取失败。

        Side Effects:
            只读数据库。

        Time Semantics:
            返回读取时的快照；版本单调递增。
        """
        raise NotImplementedError

    def acknowledge(self, job_id: int, version: int, effective: DownloadAdjustment) -> None:
        """RPC 成功后按版本确认生效值，不覆盖较新的待处理请求。

        Args:
            job_id: 正整数作业编号。
            version: 已应用的正整数请求版本。
            effective: 实际生效的完整选项，速率为 bytes/s。

        Returns:
            无。

        Raises:
            ExternalError: 数据库写入失败。

        Side Effects:
            事务更新生效版本及生效值。

        Time Semantics:
            必须在 RPC 成功后写入；与并发提交使用版本比较。
        """
        raise NotImplementedError


@dataclass(frozen=True)
class DownloadDependencies:
    """worker 注入的外部边界；计划和存储检查沿用 M0、01 的依赖。

    Attributes:
        plan: 现有计划使用的配置、存储检查和 HTTP 边界。
        mirror_range: 镜像首跳的单字节传输。
        redirects: 后续跳转的无凭据单跳 HTTPS 传输。
        process: 受控 aria2 进程及 RPC 客户端工厂。
        curl: 逐文件 curl 兜底。
        verifier: 文件大小与哈希校验。
        adjustments: 持久化运行中调整通道。
    """

    plan: PlanDependencies
    mirror_range: MirrorRangeTransport
    redirects: RedirectTransport
    process: Aria2Process
    curl: CurlFallback
    verifier: FileVerifier
    adjustments: AdjustmentChannel


def request_from_parameters(parameters: DownloadParameters) -> DownloadRequest:
    """将持久参数转换为已批准的下载计划请求，不携带 token。

    Args:
        parameters: 已校验的下载作业参数。

    Returns:
        与参数选择一致的 DownloadRequest。

    Raises:
        DefectError: 参数类型不符合内部契约。

    Side Effects:
        无。

    Time Semantics:
        同步转换，不读取配置或时间。
    """
    if not isinstance(cast(object, parameters), DownloadParameters):
        raise DefectError()
    return DownloadRequest(
        repo_type=parameters.repo_type,
        repo_id=parameters.repo_id,
        revision=parameters.revision,
        storage_root=parameters.storage_root,
        include=parameters.include,
        exclude=parameters.exclude,
        exclude_video=parameters.exclude_video,
        exclude_cameras=parameters.exclude_cameras,
        target_subdir=parameters.target_subdir,
    )


@dataclass(frozen=True)
class DownloadExecutor:
    """作业类型绑定的执行器，Web 可登记无执行能力的实例。

    Attributes:
        dependencies: worker 的执行依赖；Web 只校验参数时为 None。
    """

    dependencies: DownloadDependencies | None

    def execute(self, context: ExecutionContext) -> None:
        """执行探测、计划、下载和校验，最终使用 M0 计数计算结果。

        Args:
            context: fresh 或 resume 的下载作业上下文，参数为 DownloadParameters。

        Returns:
            无；数据集保留暂存，模型全部成功后同文件系统不覆盖改名。

        Raises:
            InputError: 镜像不生效、目标已存在或存储根不可写。
            ExternalError: 计划、进程、数据库或存储发生不可恢复故障。
            JobCancelledError: 收到取消，先 RPC 停止再终止进程组。
            WorkerStoppingError: worker 停止，保留暂存及续跑状态。
            DefectError: worker 未注入依赖或内部契约被破坏。

        Side Effects:
            仅在登记为可写的存储根创建暂存产物，报告进度、条目及诊断；不输出凭据。

        Time Semantics:
            每次执行重新生成计划；续跑以上次进度为计数基线，累计计数不得回退；
            单调时间限频至每秒最多一次，等待可取消。
        """
        if self.dependencies is None or not isinstance(context.parameters, DownloadParameters):
            raise DefectError()
        context.reporter.check_cancelled()
        plan_dependencies = replace(
            self.dependencies.plan,
            sleep=context.reporter.wait,
            checkpoint=context.reporter.check_cancelled,
        )
        dependencies = replace(self.dependencies, plan=plan_dependencies)
        plan = build_plan(request_from_parameters(context.parameters), plan_dependencies)
        run_download(context, plan, dependencies)


def run_download(
    context: ExecutionContext, plan: DownloadPlan, dependencies: DownloadDependencies
) -> None:
    """使用注入边界执行已预检的下载计划。

    Args:
        context: 作业上下文；报告、取消和等待沿用 M0。
        plan: 固定 commit 的下载计划，存储根已经预检。
        dependencies: aria2、curl、校验及调参替身或生产适配器。

    Returns:
        无；每个文件计一个条目，包括校验通过而跳过的文件。

    Raises:
        ExternalError: 无法继续执行或持久化。
        JobCancelledError: 取消后保留暂存。
        WorkerStoppingError: 中断后保留暂存以供恢复。

    Side Effects:
        在可写暂存区下载、校验并记录结果；不写已入库数据。
        成功校验后在同目录原子替换 .rdp-verified-v1.json；失败不写通过记录，
        不跟随缓存或目标文件的软链接。

    Time Semantics:
        先校验已完成文件，再续传；每次执行重新读取计划，调参确认在 RPC 成功后。
        每个文件先逐跳预解析；预解析与实际传输之间有竞态，期间每 60 秒复探镜像。
        同一作业恢复时按持久检查点识别已计数文件，避免重复累计；重新提交按新作业独立计数。
    """
    parameters = context.parameters
    if not isinstance(parameters, DownloadParameters):
        failure = DefectError()
        raise failure
    # 固定实际下载的版本和完整筛选清单；入库不重新解析可能已移动的远端分支。
    from rdp.infra.state import state_paths
    from rdp.jobs.downloads._ingest_receipt import save_receipt

    save_receipt(state_paths(dependencies.plan.config, ()), context.job_id, plan, parameters)
    state = _DownloadRun(context, plan, dependencies, parameters)
    with bind(context, state.check_mirror, state.curl_adjustment):
        state.run()


def _safe_directory(root: Path, directory: Path) -> None:
    """逐层在已登记根内建目录，不跟随任何目录软链接。"""
    try:
        parts = directory.relative_to(root).parts
        if any(part in ("", ".", "..") for part in parts):
            raise ValueError("unsafe component")
        descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            for part in parts:
                with suppress(FileExistsError):
                    os.mkdir(part, dir_fd=descriptor)
                child = os.open(
                    part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor
                )
                os.close(descriptor)
                descriptor = child
        finally:
            os.close(descriptor)
    except (OSError, ValueError) as error:
        problem = invalid_field("storage_root", "位于可写存储根内且不经过软链接")
        raise problem from error


def _rename_noreplace(source: Path, target: Path) -> None:
    """Linux 原子不覆盖改名，避免检查与改名之间的竞争。"""
    libc = ctypes.CDLL(None, use_errno=True)
    rename = libc.renameat2
    rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    rename.restype = ctypes.c_int
    # Linux RENAME_NOREPLACE=1，AT_FDCWD=-100；目标存在时内核拒绝替换。
    result = rename(-100, os.fsencode(source), -100, os.fsencode(target), 1)
    if result != 0:
        number = ctypes.get_errno()
        if number == errno.EEXIST:
            failure = invalid_field("target", "不存在的模型目标目录")
            raise failure
        raise OSError(number, os.strerror(number))


class _MirrorUnavailableError(ExternalError):
    """周期复探失败必须中止整个作业，不能降级为单文件失败。"""


class _DownloadRun:
    """隔离单次作业的内存计数和外部调用顺序。"""

    def __init__(
        self,
        context: ExecutionContext,
        plan: DownloadPlan,
        dependencies: DownloadDependencies,
        parameters: DownloadParameters,
    ) -> None:
        """保存作业上下文与本轮传输状态。"""
        self.context = context
        self.plan = plan
        self.dependencies = dependencies
        self.parameters = parameters
        self.token = read_token(dependencies.plan.config)
        self.active: list[str] = []
        self.queued: list[tuple[HubFile, Path, str, str]] = []
        self.fallback: list[tuple[HubFile, Path, str]] = []
        self.done = self.completed = self.failed = self.skipped = 0
        self.total = sum(item.size_bytes for item in plan.files)
        self.rpc: Aria2Rpc | None = None
        self.last_probe = context.clock.monotonic()
        self.last_report_at: float | None = None
        self.last_curl_adjust_at: float | None = None
        self.last_progress = context.previous_progress
        roots = [
            root
            for root in dependencies.plan.config.storage_roots
            if root.name == plan.request.storage_root and root.writable
        ]
        if len(roots) != 1:
            failure = invalid_field("storage_root", "已登记的可写存储根")
            raise failure
        self.root = roots[0]
        try:
            plan.staging_dir.relative_to(self.root.path)
        except ValueError as error:
            failure = invalid_field("staging_dir", "位于已登记的可写存储根内")
            raise failure from error
        self.model_target = (
            model_weights_path(self.root, plan.request, plan.revision)
            if plan.request.repo_type == "model"
            else None
        )

    def report(self, active_bytes: int = 0, speed: int = 0, *, final: bool = False) -> None:
        """限频上报当前活动字节和累计文件计数。"""
        now = self.context.clock.monotonic()
        if self.last_report_at is not None and now - self.last_report_at < 1.0:
            if not final:
                return
            self.context.reporter.wait(max(0.0, 1.0 - (now - self.last_report_at)))
            now = self.context.clock.monotonic()
        done = min(self.total, self.done + active_bytes)
        previous = self.last_progress
        completed, failed, skipped = self.completed, self.failed, self.skipped
        stage_index, stage_name, warnings = 5, "下载", 0
        if previous is not None:
            warnings = previous.warning_count
            if not final and (completed < previous.total_items or failed < previous.failed_items):
                return
            if final:
                # 恢复沿用已经上报的累计失败；不能让进度回退而被 M0 拒绝。
                completed = max(completed, previous.total_items)
                failed = max(failed, previous.failed_items)
                skipped = min(skipped, completed - failed)
            if previous.stage_index > 5 or (previous.stage_index == 5 and done < previous.done):
                if not final:
                    return
                # 已报告的在途字节可能随失败消失；切换到校验阶段而不是倒退下载进度。
                stage_index = max(6, previous.stage_index)
                stage_name = previous.stage_name if previous.stage_index > 5 else "校验"
                if previous.stage_index == stage_index:
                    done = max(done, previous.done)
        self.last_report_at = now
        snapshot = self.dependencies.adjustments.read(self.context.job_id)
        self.dependencies.adjustments.report(
            self.context.job_id,
            DownloadStatus(
                requested_version=snapshot.requested_version,
                applied_version=snapshot.applied_version,
                requested=snapshot.requested,
                effective=snapshot.effective,
                speed_bytes_per_s=speed,
                total_files=len(self.plan.files),
                completed_files=completed - failed - skipped,
                failed_files=failed,
                skipped_files=skipped,
            ),
        )
        progress = JobProgress(
            stage_index=stage_index,
            stage_count=7,
            stage_name=stage_name,
            done=done,
            total=max(self.total, done),
            unit="字节",
            total_items=completed,
            failed_items=failed,
            warning_count=warnings,
        )
        self.context.reporter.report(progress)
        self.last_progress = progress

    def check_mirror(self) -> None:
        """到达 60 秒预算时重新探测，失败立即中止整项下载。"""
        now = self.context.clock.monotonic()
        if now - self.last_probe >= MIRROR_RECHECK_INTERVAL_S:
            try:
                probe_mirror(self.dependencies.plan.transport, sleep=self.context.reporter.wait)
            except ExternalError as error:
                raise _MirrorUnavailableError(error.diagnostics) from error
            self.last_probe = now

    def queue(self, rpc: Aria2Rpc) -> None:
        """提交本轮 aria2 并标记已校验文件。"""
        for file in self.plan.files:
            self.context.reporter.check_cancelled()
            self.check_mirror()
            target = self.plan.staging_dir / file.path
            _safe_directory(self.root.path, target.parent)
            control = target.with_name(target.name + ".aria2")
            # aria2 会写入同名控制文件，目标和控制文件都不能指向存储根外。
            if target.is_symlink() or control.is_symlink():
                failure = invalid_field("target", "目标和续传控制文件不能是软链接")
                raise failure
            if (
                target.is_file()
                and not target.is_symlink()
                and target.stat().st_size == file.size_bytes
                and self.dependencies.verifier.verify(target, file)
            ):
                self.done += file.size_bytes
                self.completed += 1
                self.skipped += 1
                self.report()
                continue
            prefix = "datasets/" if self.plan.request.repo_type == "dataset" else ""
            initial = f"{MIRROR_ENDPOINT}/{prefix}{quote(self.plan.request.repo_id, safe='/')}/resolve/{self.plan.revision.commit}/{quote(file.path, safe='/')}"
            try:
                url = resolve_download_url(
                    initial,
                    self.token,
                    self.dependencies.mirror_range,
                    self.dependencies.redirects,
                )
            except InputError:
                self.context.reporter.diagnostic(
                    Diagnostic(
                        level=DiagnosticLevel.ERROR,
                        category=DiagnosticCategory.INPUT,
                        stage="下载",
                        source="平台",
                        objects=(),
                        rule="download.mirror_redirect",
                        actual="镜像不生效，重定向到不允许的地址",
                        expected="只访问允许的镜像或 CDN",
                        consequence="该文件失败",
                        next_step="关闭 VPN 或修正镜像连接后重试",
                    )
                )
                self.failed += 1
                self.completed += 1
                self.report()
                continue
            token = (
                self.token if urlsplit(url).hostname == urlsplit(MIRROR_ENDPOINT).hostname else None
            )
            gid = rpc.add_file(url, target, file, token)
            self.active.append(gid)
            self.queued.append((file, target, initial, gid))

    def apply_adjustment(self, rpc: Aria2Rpc) -> None:
        """仅在 RPC 确认后持久化当前实际调整。"""
        pending = self.dependencies.adjustments.pending(self.context.job_id)
        if pending is None:
            return
        version, adjustment = pending
        rpc.change_global_options(adjustment)
        self.dependencies.adjustments.acknowledge(self.context.job_id, version, adjustment)
        self.parameters = DownloadParameters.model_validate(
            {
                **self.parameters.model_dump(),
                "max_concurrent_downloads": adjustment.max_concurrent_downloads,
                "max_overall_download_limit_bytes_per_s": adjustment.max_overall_download_limit_bytes_per_s,
            }
        )

    def curl_adjustment(self) -> DownloadParameters | None:
        """Curl 运行期间仍应用 RPC 选项；速率变化时要求续传重启。"""
        if self.rpc is None:
            return None
        now = self.context.clock.monotonic()
        if self.last_curl_adjust_at is not None and now - self.last_curl_adjust_at < 1.0:
            return None
        self.last_curl_adjust_at = now
        old = self.parameters.max_overall_download_limit_bytes_per_s
        self.apply_adjustment(self.rpc)
        if self.parameters.max_overall_download_limit_bytes_per_s != old:
            return self.parameters
        return None

    def collect(self, rpc: Aria2Rpc) -> None:
        """逐项采集本轮结果，并收集需要 curl 的文件。"""
        for file, target, initial, gid in self.queued:
            refreshed = False
            while True:
                self.context.reporter.check_cancelled()
                self.check_mirror()
                self.apply_adjustment(rpc)
                status = rpc.status(gid)
                if (
                    status.state == "error"
                    and not refreshed
                    and (status.http_status in (403, 410) or status.aria2_error_code == 3)
                ):
                    refreshed = True
                    self.active.remove(gid)
                    url = resolve_download_url(
                        initial,
                        self.token,
                        self.dependencies.mirror_range,
                        self.dependencies.redirects,
                    )
                    token = (
                        self.token
                        if urlsplit(url).hostname == urlsplit(MIRROR_ENDPOINT).hostname
                        else None
                    )
                    gid = rpc.add_file(url, target, file, token)
                    self.active.append(gid)
                    continue
                if status.state in ("complete", "error", "removed"):
                    break
                self.report(status.completed_bytes, status.speed_bytes_per_s)
                self.context.reporter.wait(1.0)
            self.active.remove(gid)
            if status.state != "complete":
                self.fallback.append((file, target, initial))
                continue
            # LFS 的 aria2 任务已传入 SHA-256，完整状态表示工具已完成校验；避免再次读取大型文件。
            if file.lfs_sha256 is not None:
                info = target.stat(follow_symlinks=False)
                verified = stat.S_ISREG(info.st_mode) and info.st_size == file.size_bytes
            else:
                verified = self.dependencies.verifier.verify(target, file)
            if verified:
                self.done += file.size_bytes
            else:
                self.failed += 1
            self.completed += 1
            self.report()

    def run_fallback(self) -> None:
        """aria2 传输全部结束后串行使用 curl，RPC 保持可调。"""
        for file, target, initial in self.fallback:
            self.context.reporter.check_cancelled()
            try:
                self.dependencies.curl.download(initial, target, self.token, self.parameters)
                if self.dependencies.verifier.verify(target, file):
                    self.done += file.size_bytes
                else:
                    self.failed += 1
            except _MirrorUnavailableError:
                raise
            except (ExternalError, InputError) as error:
                self.failed += 1
                for diagnostic in error.diagnostics:
                    self.context.reporter.diagnostic(diagnostic)
            self.completed += 1
            self.report()

    def run(self) -> None:
        """依次运行 aria2 轮次和 curl 轮次。"""
        if self.model_target is not None and os.path.lexists(self.model_target):
            failure = invalid_field("target", "不存在的模型目标目录")
            raise failure
        initial = DownloadAdjustment(
            max_concurrent_downloads=self.parameters.max_concurrent_downloads,
            max_overall_download_limit_bytes_per_s=self.parameters.max_overall_download_limit_bytes_per_s,
        )
        self.dependencies.adjustments.initialize(self.context.job_id, initial)
        snapshot = self.dependencies.adjustments.read(self.context.job_id)
        self.parameters = DownloadParameters.model_validate(
            {
                **self.parameters.model_dump(),
                "max_concurrent_downloads": snapshot.effective.max_concurrent_downloads,
                "max_overall_download_limit_bytes_per_s": snapshot.effective.max_overall_download_limit_bytes_per_s,
            }
        )
        _safe_directory(self.root.path, self.plan.staging_dir)
        rpc = self.dependencies.process.start(self.parameters)
        self.rpc = rpc
        try:
            self.queue(rpc)
            self.collect(rpc)
            self.apply_adjustment(rpc)
            self.run_fallback()
        finally:
            self.rpc = None
            try:
                rpc.stop(tuple(self.active))
            finally:
                self.dependencies.process.terminate()
        self.report(final=True)
        if self.model_target is not None and self.failed == 0:
            _safe_directory(self.root.path, self.model_target.parent)
            _rename_noreplace(self.plan.staging_dir, self.model_target)


def validate_download_redirect(current_url: str, location: str) -> str:
    """逐跳解析下载重定向并拒绝官方站与非 HTTPS 地址。

    Args:
        current_url: 当前 HTTPS 地址，不包含用户信息。
        location: 服务端返回的相对或绝对 Location，不含凭据。

    Returns:
        解析归一化后的下一跳 HTTPS URL，不保证该 URL 的后续跳转安全。

    Raises:
        InputError: 格式非法、目标是 huggingface.co 或其子域、含用户信息或非 HTTPS。

    Side Effects:
        无；不解析 DNS 或发出网络请求。

    Time Semantics:
        每个真实响应均须调用，预检不能代替传输时逐跳检查。
    """
    # URL 解析会容忍控制字符；先拒绝原始输入，避免校验与实际请求解释不一致。
    if not location or any(ord(char) < 32 or ord(char) == 127 for char in location):
        failure = invalid_field("redirect", "安全的 HTTPS 下载地址")
        raise failure
    try:
        target = urljoin(current_url, location)
        parsed = urlsplit(target)
        host = (parsed.hostname or "").lower().rstrip(".")
        port = parsed.port
        if (
            parsed.scheme != "https"
            or not host
            or "%" in host
            or parsed.username is not None
            or parsed.password is not None
            or parsed.fragment
            or port == 0
            or host == "huggingface.co"
            or host.endswith(".huggingface.co")
        ):
            failure = invalid_field("redirect", "非官方站且无凭据的 HTTPS 地址")
            raise failure
    except ValueError as error:
        failure = invalid_field("redirect", "非官方站且无凭据的 HTTPS 地址")
        raise failure from error
    return target


def cached_file_is_valid(path: Path, file: HubFile, manifest: Path) -> bool:
    """仅在缓存身份与当前文件和清单均匹配时复用校验结果。

    Args:
        path: 暂存文件的安全路径。
        file: 本次清单的相对路径、大小与期望哈希。
        manifest: 同一暂存目录下 .rdp-verified-v1.json；JSON 顶层含 version=1 和 entries，
            entries 以相对路径为键，每项记录期望算法、散列、大小和设备号、inode、mtime_ns、ctime_ns。

    Returns:
        完整身份匹配返回 True；缓存缺失、损坏或身份变化返回 False。

    Raises:
        ExternalError: 无法安全读取文件或缓存。

    Side Effects:
        只读文件元信息和缓存，不计算哈希、不修改文件。

    Time Semantics:
        身份包含设备号、inode、大小、mtime_ns、ctime_ns 和期望哈希；缓存是优化而非抗恶意篡改证明。
    """
    try:
        # O_NOFOLLOW 确保缓存文件本身不是指向存储根外的软链接。
        descriptor = os.open(manifest, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(descriptor, "rb") as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                return False
            raw = stream.read(16 * MIB + 1)
        if len(raw) > 16 * MIB:
            return False
        payload = json.loads(raw)
        info = path.stat(follow_symlinks=False)
    except FileNotFoundError:
        return False
    except (json.JSONDecodeError, UnicodeDecodeError, TypeError):
        return False
    except OSError as error:
        raise ExternalError(
            (
                Diagnostic(
                    level=DiagnosticLevel.ERROR,
                    category=DiagnosticCategory.EXTERNAL,
                    stage="校验",
                    source="平台",
                    objects=(),
                    rule="download.cache_read",
                    actual="暂存文件或校验缓存无法安全读取",
                    expected="文件及缓存可安全读取",
                    consequence="未复用缓存，作业无法继续",
                    next_step="检查暂存目录权限并重试",
                ),
            )
        ) from error
    if not stat.S_ISREG(info.st_mode) or not isinstance(payload, dict):
        return False
    payload_map = cast(dict[str, object], payload)
    entries = payload_map.get("entries")
    if payload_map.get("version") != 1 or not isinstance(entries, dict):
        return False
    entry_map = cast(dict[str, object], entries)
    expected = {
        "algorithm": "sha256" if file.lfs_sha256 is not None else "git-blob-sha1",
        "digest": file.lfs_sha256 if file.lfs_sha256 is not None else file.blob_sha1,
        "size": file.size_bytes,
        "dev": info.st_dev,
        "ino": info.st_ino,
        "mtime_ns": info.st_mtime_ns,
        "ctime_ns": info.st_ctime_ns,
    }
    return info.st_size == file.size_bytes and entry_map.get(file.path) == expected


def resolve_download_url(
    url: str, token: str | None, mirror: MirrorRangeTransport, redirects: RedirectTransport
) -> str:
    """逐跳预解析文件地址，首跳只向镜像发送令牌。

    Args:
        url: 镜像 HTTPS resolve 地址，不含用户信息。
        token: 可选令牌；只在首跳发送，不记录。
        mirror: 仅连接镜像的单字节 Range 传输。
        redirects: 不携带凭据的后续单跳传输。

    Returns:
        返回 200 或 206 的最终 HTTPS 地址。

    Raises:
        InputError: 跳转不安全或指向官方站。
        ExternalError: 网络故障、非预期状态、缺少 Location 或超过五跳。
        OSError: 首跳传输 I/O 故障。
        DefectError: 内部重定向循环违反不变量。

    Side Effects:
        依次发送 GET 和 Range bytes=0-0；只向镜像发送 token。

    Time Semantics:
        至多五次重定向；每次传输受其有限超时约束。
    """
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.netloc != urlsplit(MIRROR_ENDPOINT).netloc
        or parsed.fragment
    ):
        failure = invalid_field("url", "不含凭据的镜像 HTTPS 地址")
        raise failure
    headers = {"Range": "bytes=0-0"}
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    response = mirror.request("GET", url, headers=headers, timeout_s=HTTP_TIMEOUT_S)
    current = url
    for hop in range(MAX_REDIRECT_HOPS + 1):
        if response.status in (200, 206):
            return current
        location = next(
            (value for key, value in response.headers.items() if key.lower() == "location"), None
        )
        if not 300 <= response.status < 400 or location is None or hop == MAX_REDIRECT_HOPS:
            raise ExternalError(
                (
                    Diagnostic(
                        level=DiagnosticLevel.ERROR,
                        category=DiagnosticCategory.EXTERNAL,
                        stage="下载",
                        source="平台",
                        objects=(),
                        rule="download.redirect",
                        actual="镜像响应无法解析或跳转次数耗尽",
                        expected="镜像返回可下载地址",
                        consequence="该文件下载失败",
                        next_step="检查镜像连接后重试",
                    ),
                )
            )
        current = validate_download_redirect(current, location)
        response = redirects.request(current, timeout_s=HTTP_TIMEOUT_S)
    raise DefectError()
